"""Find a PERMITTED replacement for PSX's data paths.

Since 2026-09-25 PSX's dps.psx.com.pk data paths refuse non-browser requests
(403 /historical, 404 /timeseries, /market-watch) while its pages load. Our
rule is public permitted sources and no protection bypass, so this does NOT try
to look like a browser. It asks each candidate source ONCE, honestly identified,
and reports whether it returns a real, plausible end-of-day price.

"Plausible" is checked against our own last banked close (2026-09-23): a price
within +-25% of it for a well-known symbol. A source that answers but returns
nothing recognisable is reported as such, never guessed at.
"""
import io
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

UA = {"User-Agent": "PSX-Research-Engine/1.0 (personal research tool)"}
REF = {"OGDC": 319.53, "PSO": 352.54, "HUBC": 205.56, "LUCK": 424.34, "MEBL": 555.51}
DAY = os.environ.get("PROBE_DAY", "2026-09-29")
Y, M, D = DAY.split("-")


def plausible(sym, value):
    try:
        v = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return False
    return abs(v / REF[sym] - 1) <= 0.25


def fetch(url, **kw):
    try:
        return requests.get(url, headers=UA, timeout=30, allow_redirects=True, **kw)
    except requests.RequestException as exc:
        return exc


def show(name, url, r):
    if isinstance(r, Exception):
        print(f"[{name}] {url}\n    ERROR {type(r).__name__}: {str(r)[:120]}")
        return None
    ct = r.headers.get("content-type", "")
    print(f"[{name}] {url}\n    {r.status_code} | {ct[:40]} | {len(r.content)} bytes")
    return r


def text_prices(text, syms=REF):
    """Find 'SYMBOL ... number' pairs in a text or HTML body."""
    found = {}
    for s in syms:
        m = re.search(rf"\b{s}\b[^0-9\n]{{0,80}}?([0-9][0-9,]*\.[0-9]{{1,2}})", text)
        if m:
            found[s] = m.group(1)
    return found


def verdict(found):
    ok = {s: v for s, v in found.items() if plausible(s, v)}
    print(f"    prices found: {found or 'none'}")
    print(f"    PLAUSIBLE: {len(ok)}/{len(REF)} {ok if ok else ''}")
    return len(ok)


def main():
    score = {}

    # 1. PSX's own published daily files (official bulk download route).
    for name, url in [
        ("psx closing_rates pdf", f"https://dps.psx.com.pk/download/closing_rates/{DAY}.pdf"),
        ("psx mkt_summary Z",     f"https://dps.psx.com.pk/download/mkt_summary/{DAY}.Z"),
        ("psx closing_rates zip", f"https://dps.psx.com.pk/download/closing_rates/{DAY}.zip"),
        ("psx md txt",            f"https://dps.psx.com.pk/download/md/{DAY}.Z"),
    ]:
        r = show(name, url, fetch(url))
        if r is not None and r.status_code == 200 and len(r.content) > 500:
            body = r.content
            if body[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(body)) as z:
                    body = b"".join(z.read(n) for n in z.namelist())
            head = body[:200]
            print(f"    head: {head!r}")
            score[name] = verdict(text_prices(body.decode("latin-1", "ignore")))

    # 2. Yahoo Finance chart API (.KA = Karachi).
    for sym in ("OGDC", "PSO"):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.KA?range=1mo&interval=1d"
        r = show(f"yahoo {sym}", url, fetch(url))
        if r is not None and r.status_code == 200:
            try:
                res = r.json()["chart"]["result"][0]
                ts, q = res["timestamp"], res["indicators"]["quote"][0]
                last = [c for c in q["close"] if c is not None][-1]
                print(f"    bars: {len(ts)} | last close: {last} | plausible: {plausible(sym, last)}")
                score[f"yahoo {sym}"] = int(plausible(sym, last))
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                print(f"    unparseable: {exc}")

    # 3. Stooq CSV.
    for code in ("ogdc.pk", "ogdc"):
        url = f"https://stooq.com/q/d/l/?s={code}&i=d"
        r = show(f"stooq {code}", url, fetch(url))
        if r is not None and r.status_code == 200:
            print(f"    head: {r.text[:160]!r}")

    # 4. Pakistani market-data sites (public pages, one request each).
    for name, url in [
        ("scstrade",   "https://www.scstrade.com/MarketStatistics/MS_MarketSummary.aspx"),
        ("sarmaaya",   "https://sarmaaya.pk/psx/market/"),
        ("brecorder",  "https://www.brecorder.com/markets/stocks"),
        ("mettis",     "https://mettisglobal.news/market-data/"),
        ("ksestocks",  "https://www.ksestocks.com/Rates"),
        ("psx mobile", "https://www.psx.com.pk/market-summary/"),
        ("google fin", "https://www.google.com/finance/quote/OGDC:KAR"),
    ]:
        r = show(name, url, fetch(url))
        if r is not None and r.status_code == 200:
            score[name] = verdict(text_prices(r.text))

    print("\n=== SUMMARY (plausible prices per source)")
    for k, v in sorted(score.items(), key=lambda x: -x[1]):
        print(f"   {v}  {k}")


if __name__ == "__main__":
    main()
