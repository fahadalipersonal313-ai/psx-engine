"""KSE100 daily close from PSX's official closing-rates PDF -- the v8 benchmark.

PSX's index EOD path (/timeseries/eod) answers 404 to automated requests since
2026-09-25, and its /indices page shows only the latest session. KMI30 appears
in no dated official file, which left 2026-09-24..28 permanently unrecoverable
for it. PSX's dated closing-rates PDF DOES carry KSE100 on page one, so on
2026-09-30 the user chose to move the benchmark to KSE100 (strategy v8):

    https://dps.psx.com.pk/download/closing_rates/<YYYY-MM-DD>.pdf

    ... | Tuesday September 29,2026 | ...
    P. Vol.: 421015660 P.KSE100 Ind: 170425.62 P.KSE30 Ind: 50717.83 Plus: 154
    C. Vol.: 568040396 C.KSE100 Ind: 169600.41 C.KSE30 Ind: 50456.98 Minus: 305

C. = current session, P. = previous session. The file gives no index open, so
open is stored as NULL; decide() reads only the close. C. Vol. is whole-market
share volume, stored as the row's volume.

Each file states the previous session's close, so every banked day is checked
against the one before it: a mismatch means a mislabelled or revised file, and
the row is refused rather than stored.
"""
import io
import logging
import re
import time
from datetime import date, datetime, timedelta

import requests

import config

log = logging.getLogger("psx_index_pdf")

URL = "https://dps.psx.com.pk/download/closing_rates/{day}.pdf"
SOURCE = "PSX closing_rates PDF (official download)"
SYMBOL = "KSE100"
TIMEOUT = 30
PAUSE = 0.3
TOLERANCE = 0.011   # the PDF prints two decimals

_NUM = r"([0-9][0-9,]*\.?[0-9]*)"


def _num(text):
    return float(text.replace(",", ""))


def parse(text, day):
    """-> {date, close, prev_close, volume} for `day` from page-one text.

    Raises ValueError if the header date differs from `day` or the KSE100
    lines are missing: a changed layout must fail loudly, never guess.
    """
    want = datetime.strptime(day, "%Y-%m-%d").date()
    flat = re.sub(r"\s+", " ", text)
    # PSX pads single-digit days on some files ("May 04,2026"), not others.
    found = re.search(r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day ([A-Za-z]+) (\d{1,2}),(\d{4})", flat)
    try:
        stated = datetime.strptime(" ".join(found.groups()), "%B %d %Y").date() if found else None
    except ValueError:
        stated = None
    if stated != want:
        raise ValueError(f"closing_rates for {day} is dated "
                         f"{stated or 'unknown'}, not {want}")
    cur = re.search(r"C\.\s*KSE100 Ind:\s*" + _NUM, flat)
    prev = re.search(r"P\.\s*KSE100 Ind:\s*" + _NUM, flat)
    vol = re.search(r"C\.\s*Vol\.:\s*" + _NUM, flat)
    if not cur or not prev:
        raise ValueError(f"closing_rates for {day}: KSE100 lines not found -- layout changed")
    close = _num(cur.group(1))
    if close <= 0:
        raise ValueError(f"closing_rates for {day}: KSE100 close {close} is not a price")
    return {"date": day, "close": close, "prev_close": _num(prev.group(1)),
            "volume": _num(vol.group(1)) if vol else None}


def _page_one_text(pdf_bytes):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return reader.pages[0].extract_text() or ""


def fetch_day(day, session=None):
    """KSE100 row for `day`, or None when PSX publishes no file (holiday or
    not yet published). Any other failure raises."""
    s = session or requests
    from psx_mkt_summary import get_with_retry
    r = get_with_retry(s, URL.format(day=day), headers=config.REQUEST_HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        # PSX answers some missing days with an HTML page instead of a 404.
        return None
    return parse(_page_one_text(r.content), day)


def check_chain(prev_row, row):
    """True when `row`'s stated previous close equals the banked prior close."""
    if prev_row is None or prev_row.get("close") is None:
        return True
    return abs(row["prev_close"] - prev_row["close"]) <= TOLERANCE


def backfill(start, end, fetch=fetch_day, save=None, last=None, pause=PAUSE):
    """Bank KSE100 for every published session in [start, end].

    `last` is the banked row immediately before `start` (for the chain check).
    Stops at the first chain break, so nothing after an unverified row is kept.
    """
    import database as db
    save = save or (lambda row: db.save_eod_history(
        SYMBOL, [(row["date"], None, row["close"], row["volume"])], source=SOURCE))
    d, stop = date.fromisoformat(start), date.fromisoformat(end)
    banked, no_file = [], []
    while d <= stop:
        day = d.isoformat()
        if d.weekday() < 5:
            t0 = time.monotonic()
            row = fetch(day)
            log.info("KSE100 %s: %s (%.1fs)", day,
                     "no file" if row is None else row["close"], time.monotonic() - t0)
            if row is None:
                no_file.append(day)
            else:
                if not check_chain(last, row):
                    raise ValueError(
                        f"KSE100 {day}: file states previous close {row['prev_close']}, "
                        f"banked {last['date']} close is {last['close']} -- refusing")
                save(row)
                banked.append(day)
                last = row
            if pause:
                time.sleep(pause)
        d += timedelta(days=1)
    log.info("KSE100 backfill %s..%s: banked %d, no file %s", start, end, len(banked), no_file)
    return {"banked": banked, "no_file": no_file}


if __name__ == "__main__":
    import sys
    import database as db
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 3:
        sys.exit("usage: python psx_index_pdf.py START END   (YYYY-MM-DD)")
    db.init_db()
    prior = [r for r in db.get_eod_history(SYMBOL, limit=100000) if r["date"] < sys.argv[1]]
    print(backfill(sys.argv[1], sys.argv[2], last=prior[-1] if prior else None))
