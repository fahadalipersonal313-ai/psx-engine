"""hl_probe.py — READ-ONLY reconnaissance for a daily High/Low source.

PSX DPS end-of-day returns [timestamp, close, volume, open] and no High or Low,
so ATR, ADX and a true CMF cannot be computed from the backfilled history. The
only real H/L the engine has is what the intraday poller banks into daily_ohlc,
which grows one day per day and currently reaches back ~50 sessions.

This script does NOT write to the database and does NOT parse anything into the
engine. It reports what each candidate source actually returns, so the decision
is made on observed markup rather than inference. That distinction is the whole
point: on 2026-08-26 a Mettis date parser was written from assumed markup, bound
articles to the wrong dates, printed a FUTURE publication date, and had to be
reverted. Do not skip this step and write a scraper from a guess.

Run it where PSX is reachable — a GitHub runner. This sandbox cannot reach any
of these hosts (every probe returns a connection failure), and a sandbox refusal
is evidence about the sandbox, not about the portal.

    python hl_probe.py            # probe every candidate
    python hl_probe.py NRL        # probe with a specific symbol
"""

import sys
import re
import json
import logging

import requests

import config
import ssl_compat

log = logging.getLogger("hl_probe")
TIMEOUT = 25
SNIPPET = 700


def _looks_like_ohlc(text):
    """Report which of the five fields are even mentioned, case-insensitively.
    A source that never says 'high' or 'low' cannot be the answer."""
    t = text.lower()
    return {k: (k in t) for k in ("open", "high", "low", "close", "volume")}


def _probe(name, method, url, **kw):
    print(f"\n=== {name} ===\n{method} {url}")
    try:
        r = (requests.post(url, timeout=TIMEOUT, **kw) if method == "POST"
             else requests.get(url, timeout=TIMEOUT, **kw))
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        return None
    ctype = r.headers.get("Content-Type", "?")
    print(f"  HTTP {r.status_code} | {ctype} | {len(r.content)} bytes")
    for h in ("Server", "Retry-After", "CF-Ray"):
        if r.headers.get(h):
            print(f"  {h}: {r.headers[h]}")
    if r.status_code != 200:
        print(f"  body: {r.text[:200]!r}")
        return r
    print(f"  field mentions: {_looks_like_ohlc(r.text)}")
    # Count table rows/cells — the shape that decides whether a parser is viable.
    rows = len(re.findall(r"<tr\b", r.text, re.I))
    if rows:
        print(f"  <tr> rows: {rows}")
    try:
        j = r.json()
        print(f"  JSON keys: {list(j)[:12] if isinstance(j, dict) else type(j).__name__}")
        print(f"  sample: {json.dumps(j)[:SNIPPET]}")
    except Exception:
        print(f"  snippet: {r.text[:SNIPPET]!r}")
    return r


def main():
    ssl_compat.enable()
    logging.basicConfig(level=logging.WARNING)
    sym = (sys.argv[1] if len(sys.argv) > 1 else "NRL").upper()
    hdrs = dict(config.REQUEST_HEADERS)
    browser = dict(hdrs, **{
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/128.0 Safari/537.36"),
        "Referer": "https://dps.psx.com.pk/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    print(f"Probing daily High/Low sources (symbol: {sym}).")
    print("Nothing is written to the database.")

    # 1. The strongest candidate. PSX's own Historical / Market Summary view is
    #    keyed by DATE, not symbol, so ONE request returns every listed company's
    #    OHLCV for that session — ~250 requests covers a year for all 50 names,
    #    versus 50 requests per symbol. Same public portal the engine already
    #    uses, so it introduces no new source and no protection bypass.
    #    The request shape below is a GUESS and is exactly what needs confirming.
    _probe("DPS historical (POST date)", "POST",
           "https://dps.psx.com.pk/historical",
           data={"date": "2026-08-29"}, headers=browser)
    _probe("DPS historical (GET)", "GET",
           "https://dps.psx.com.pk/historical", headers=browser)

    # 2. Baseline: the endpoint the engine already relies on. Confirms the host
    #    is reachable at all, so a failure above is about the path, not the site.
    _probe("DPS EOD (known-good baseline)", "GET",
           config.PSX_EOD_URL.format(symbol=sym), headers=hdrs)

    # 3. The company page — may carry a day range even without full history.
    _probe("DPS company page", "GET",
           f"https://dps.psx.com.pk/company/{sym}", headers=browser)

    # 4. Third-party aggregators. Only worth pursuing if PSX itself has no H/L
    #    route: each adds a dependency whose terms and accuracy are unverified,
    #    and this engine's rule is that data must be real and attributable.
    _probe("Sarmaaya", "GET",
           f"https://sarmaaya.pk/psx/company/{sym}", headers=browser)
    _probe("SCSTrade historical", "GET",
           f"https://www.scstrade.com/stockscreening/SS_CompanySnapShot.aspx?symbol={sym}",
           headers=browser)

    print("\n---\nWhat to look for:")
    print("  * a 200 whose 'field mentions' shows BOTH high and low True;")
    print("  * for the historical view, many <tr> rows (one per listed company);")
    print("  * paste the winning snippet back before any parser is written —")
    print("    markup written from assumption is what produced the Mettis")
    print("    date bug, and a wrong High/Low silently corrupts every ATR.")


if __name__ == "__main__":
    main()
