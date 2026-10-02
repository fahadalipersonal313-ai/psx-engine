"""PSX's official daily market-summary download -- the permitted daily-bar source.

Since 2026-09-25 PSX's interactive data paths refuse automated requests:
/historical answers 403 even with the browser-style headers psx_historical
already sent, and /timeseries and /market-watch answer 404. Our rule is public
permitted sources and no protection bypass, so imitating a browser harder is
not the fix.

PSX publishes the same session data as a plain download for exactly this use:

    https://dps.psx.com.pk/download/mkt_summary/<YYYY-MM-DD>.Z

One pipe-delimited line per listed security, full market, every trading day:

    29SEP2026|OGDC|0823|Oil & Gas Development Co.|321.0|323.9|317.5|318.69|..|319.53|||
    date     |sym |sect|name                      |open |high |low  |close |vol|prev close

It answers our honest research User-Agent with 200 (probe, 2026-09-29), so no
disguise is involved. Same return contract as psx_historical.fetch_day: a list
of {symbol, open, high, low, close, volume}, [] for a day with no file.
"""
import gzip
import io
import logging
import time
import zipfile
from datetime import date, datetime, timedelta

import requests

import config

log = logging.getLogger("psx_mkt_summary")

URL = "https://dps.psx.com.pk/download/mkt_summary/{day}.Z"
# 'historical' + 'psx' gives data_quality.source_priority 3: an official
# end-of-day bar, the same trust level as the old /historical view.
SOURCE = "PSX mkt_summary historical (official download)"
TIMEOUT = 30
PAUSE = 1.0
MIN_FIELDS = 9
RETRY_WAIT = 5.0


def get_with_retry(s, url, **kw):
    """GET with ONE retry on a dropped connection or timeout.

    On 2026-10-01 a cycle was lost to a single "Remote end closed connection"
    from PSX. Only transport failures are retried: an HTTP refusal (403 and
    the like) is a real answer and still fails at once, and one retry is
    the limit so a sustained outage is never hammered.
    """
    try:
        return s.get(url, **kw)
    except (requests.ConnectionError, requests.Timeout) as exc:
        log.warning("PSX request failed (%s); retrying once in %.0fs", exc, RETRY_WAIT)
        time.sleep(RETRY_WAIT)
        return s.get(url, **kw)


def _num(text):
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _body(raw):
    # Despite the .Z name, PSX serves a ZIP archive holding one text member
    # (closing11.lis). Confirmed by dumping the live bytes on 2026-09-29.
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return b"".join(z.read(n) for n in z.namelist())
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if raw[:2] == b"\x1f\x9d":
        # Unix `compress` (LZW). Python has no decoder for it; say so plainly
        # rather than return garbage parsed as prices.
        raise ValueError("mkt_summary arrived LZW-compressed (.Z); decoder not available")
    return raw


def parse(text, day):
    """-> list of bars for `day` (YYYY-MM-DD).

    Raises ValueError when lines are present but none parse, or when the file
    is for a different date: a changed format or a mislabelled file must
    surface as a failure, never as silently wrong prices.
    """
    stamp = datetime.strptime(day, "%Y-%m-%d").strftime("%d%b%Y").upper()
    lines = [l for l in text.replace("\r", "").split("\n") if l.strip()]
    out, dated_elsewhere = [], 0
    for line in lines:
        f = [x.strip() for x in line.split("|")]
        if len(f) < MIN_FIELDS:
            continue
        if f[0].upper() != stamp:
            dated_elsewhere += 1
            continue
        sym = f[1].upper().split()[0] if f[1] else ""
        if not sym:
            continue
        row = {"symbol": sym, "open": _num(f[4]), "high": _num(f[5]),
               "low": _num(f[6]), "close": _num(f[7]), "volume": _num(f[8])}
        # Identical guards to psx_historical.parse: a bar with no high/low, or
        # O=H=L=0 (a session in which the name did not trade), is not a price.
        if row["high"] is None or row["low"] is None or row["close"] is None:
            continue
        if row["high"] <= 0 or row["low"] <= 0:
            continue
        out.append(row)
    if lines and not out:
        if dated_elsewhere:
            raise ValueError(f"mkt_summary for {day} carries a different date "
                             f"({dated_elsewhere} lines not stamped {stamp})")
        raise ValueError(f"mkt_summary for {day}: {len(lines)} lines, none parsed "
                         f"-- the file format has changed")
    return out


def fetch_day(date_str, session=None):
    """One session's full-market OHLCV. [] when PSX publishes no file for the
    day (a holiday, or not yet published). Any other failure raises."""
    s = session or requests
    r = get_with_retry(s, URL.format(day=date_str), headers=config.REQUEST_HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return parse(_body(r.content).decode("latin-1", "ignore"), date_str)


def backfill(start, end, symbols=None, save=None, pause=PAUSE):
    """Bank every published session in [start, end] for `symbols`.

    Used to close a gap left by an outage: the 42-session contract reads a
    CONTIGUOUS window, so a missing session would silently distort every EMA
    that spans it. Weekends are skipped without a request; a weekday with no
    file is treated as a holiday and recorded as such, never invented.
    """
    import database as db
    save = save or db.save_hl_bar
    wanted = set(symbols or config.STOCKS)
    d, stop = date.fromisoformat(start), date.fromisoformat(end)
    banked, empty = {}, []
    while d <= stop:
        day = d.isoformat()
        if d.weekday() < 5:
            bars = fetch_day(day)
            rows = [b for b in bars if b["symbol"] in wanted]
            for b in rows:
                save(b["symbol"], day, b["open"], b["high"], b["low"], b["close"],
                     b["volume"], SOURCE, overwrite=True)
            if rows:
                banked[day] = len(rows)
            else:
                empty.append(day)
            time.sleep(pause)
        d += timedelta(days=1)
    log.info("mkt_summary backfill %s..%s: banked %s, no file %s", start, end, banked, empty)
    return {"banked": banked, "no_file": empty}
