"""Publish PSX's official full-market daily bars for the paper-trading test.

The paper trader (orphan branch `paper-trading`, run by a cloud routine) needs
the OFFICIAL close for ~280 symbols plus the KSE-100. Its own price feed is a
live scanner that cannot be relied on for the official close (PSX's close is
the VWAP of the last 30 minutes, published after the session) and is not
reachable from every environment. The engine already downloads the official
market-summary file every run and banks the KSE-100 from the closing-rates
PDF, so it writes both here, in one small file on runtime-state:

    market_eod.json = {"source": ..., "sessions": {
        "2026-10-19": {"kse100": 165966.09,
                       "stocks": {"PRL": [open, high, low, close, volume, ldcp], ...}}}}

Only completed sessions are written (the run's cutoff), only symbols that
traded that day (psx_mkt_summary drops O=H=L=0 rows), and only the newest
KEEP sessions, so a consumer that misses a few days can catch up. `kse100` is
null until the index close for that session is banked; consumers must wait for
it rather than substitute anything. The content is deterministic (no run
timestamps), so two runs that publish the same session write identical bytes.

This is a record for the paper test, not a decision input: nothing in the
engine reads it back, and it never touches daily_ohlc.
"""
import json
import os

import config
import database as db

PATH = os.environ.get("PSX_MARKET_EOD_PATH", os.path.join(config.BASE_DIR, "market_eod.json"))
KEEP = 10
SOURCE = ("PSX mkt_summary download (stocks) + PSX closing-rates PDF (KSE100); "
          "fields open, high, low, close, volume, ldcp; close is PSX's official close")


def _index_close(day):
    import psx_index_pdf
    with db.conn() as c:
        row = c.execute("SELECT close FROM daily_eod WHERE symbol=? AND date=?",
                        (psx_index_pdf.SYMBOL, day)).fetchone()
    return row[0] if row and row[0] else None


def publish(cutoff, bars, path=None, keep=KEEP, index_close=None):
    """Add `cutoff`'s official bars to the file. Returns a short summary, or
    None when there is nothing to write (no bars for the session)."""
    if not bars:
        return None
    path = path or PATH
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    sessions = data.get("sessions") or {}
    stocks = {}
    for b in bars:
        stocks[b["symbol"]] = [b["open"], b["high"], b["low"], b["close"],
                               b["volume"], b.get("ldcp")]
    kse = index_close(cutoff) if index_close else _index_close(cutoff)
    sessions[cutoff] = {"kse100": kse, "stocks": dict(sorted(stocks.items()))}
    kept = dict(sorted(sessions.items())[-keep:])
    out = {"source": SOURCE, "sessions": kept}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"), sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    return {"session": cutoff, "symbols": len(stocks), "kse100": kse, "sessions_kept": len(kept)}
