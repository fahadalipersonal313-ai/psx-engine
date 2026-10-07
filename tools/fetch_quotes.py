"""Read-only: latest delayed REG quotes from PSX company pages.

    python tools/fetch_quotes.py PSO SYS ...

For each symbol, one GET of https://dps.psx.com.pk/company/<SYM> (one retry on
a dropped connection, 2 s spacing). Reads only:
  * .quote__close  -> displayed price
  * .quote__date   -> exchange/source "As of" time (Asia/Karachi)
  * #statsTab .tabs__panel[data-name='REG'] -> Open, High, Low, Volume, LDCP
Source time and retrieval time are separate fields. Quotes are DELAYED
(PSX says ~5 minutes; can be longer). A quote whose source date is not today's
Karachi date is marked prior_session and must not be used for intraday
activation. Missing fields stay empty; nothing is inferred. Writes nothing:
prints CSV + JSON (and the raw REG panel text for audit) to stdout.
"""
import csv
import html
import json
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
import config  # noqa: E402
from psx_mkt_summary import get_with_retry  # noqa: E402

PKT = ZoneInfo("Asia/Karachi")
URL = "https://dps.psx.com.pk/company/{sym}"
FIELDS = ("Open", "High", "Low", "Volume", "LDCP")


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _first_class(page, cls):
    m = re.search(r'<[^>]*class="[^"]*\b%s\b[^"]*"[^>]*>(.*?)</' % re.escape(cls), page, re.S)
    return _text(m.group(1)) if m else None


def _reg_panel(page):
    tab = page.find('id="statsTab"')
    if tab < 0:
        return None
    m = re.search(r'<div[^>]*class="[^"]*tabs__panel[^"]*"[^>]*data-name="REG"[^>]*>', page[tab:])
    if not m:
        m = re.search(r'<div[^>]*data-name="REG"[^>]*class="[^"]*tabs__panel[^"]*"[^>]*>', page[tab:])
    if not m:
        return None
    start = tab + m.end()
    nxt = re.search(r'<div[^>]*class="[^"]*tabs__panel', page[start:])
    return page[start:start + nxt.start()] if nxt else page[start:start + 20000]


def _num(s):
    """The single number in a displayed value ("Rs.355.86", "1,234,567"); None if absent."""
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def parse(page, sym, retrieved):
    row = {"symbol": sym, "url": URL.format(sym=sym), "retrieved_at_pkt": retrieved.isoformat(timespec="seconds")}
    row["price"] = _num(_first_class(page, "quote__close") or "")
    raw_date = _first_class(page, "quote__date")
    row["source_time_text"] = raw_date
    src = None
    if raw_date:
        m = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M)?", raw_date)
        if m:
            fmt = "%b %d, %Y %I:%M:%S %p" if m.group(2) and m.group(2).count(":") == 2 else "%b %d, %Y %I:%M %p"
            try:
                src = (datetime.strptime(f"{m.group(1)} {m.group(2)}", fmt) if m.group(2)
                       else datetime.strptime(m.group(1), "%b %d, %Y")).replace(tzinfo=PKT)
            except ValueError:
                src = None
    row["source_time_pkt"] = src.isoformat(timespec="seconds") if src else None
    panel = _reg_panel(page)
    row["reg_panel_found"] = panel is not None
    tokens = [t for t in re.split(r"\s{2,}|\n", _text(panel).replace(" ", "  ")) if t] if panel else []
    flat = _text(panel) if panel else ""
    for f in FIELDS:
        m = re.search(r"\b%s\b\s*([\d,]+(?:\.\d+)?)" % f, flat)
        row[f.lower()] = _num(m.group(1)) if m else None
    row["reg_panel_text"] = flat[:400]
    today = retrieved.date()
    row["delayed"] = True
    row["session_status"] = ("unknown_source_time" if not src else
                             "current_session" if src.date() == today else "prior_session")
    issues = []
    p, o, h, l, v = row["price"], row["open"], row["high"], row["low"], row["volume"]
    if p is None or p <= 0:
        issues.append("no positive price")
    if v is not None and v < 0:
        issues.append("negative volume")
    if None not in (h, l) and not (l <= h):
        issues.append("low > high")
    if None not in (p, h, l) and not (l <= p <= h) and row["session_status"] == "current_session":
        issues.append("price outside REG high/low")
    row["issues"] = "; ".join(issues)
    return row


def main(symbols):
    rows = []
    for i, sym in enumerate(symbols):
        if i:
            time.sleep(2.0)
        retrieved = datetime.now(PKT)
        try:
            r = get_with_retry(requests, URL.format(sym=sym), headers=config.REQUEST_HEADERS, timeout=30)
            status = r.status_code
            page = r.text if status == 200 else ""
        except Exception as exc:  # recorded, never substituted
            status, page = f"error: {type(exc).__name__}: {exc}", ""
        row = parse(page, sym, retrieved) if page else {
            "symbol": sym, "url": URL.format(sym=sym), "retrieved_at_pkt": retrieved.isoformat(timespec="seconds"),
            "session_status": "not_retrieved"}
        row["http_status"] = status
        rows.append(row)
    cols = ["symbol", "price", "open", "high", "low", "volume", "ldcp", "source_time_pkt", "source_time_text",
            "retrieved_at_pkt", "session_status", "delayed", "http_status", "reg_panel_found", "issues", "url"]
    print("===CSV===")
    w = csv.DictWriter(sys.stdout, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    print("===JSON===")
    print(json.dumps(rows, indent=1, default=str))


if __name__ == "__main__":
    main([s.upper() for s in sys.argv[1:]] or ["PSO"])
