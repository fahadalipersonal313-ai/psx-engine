"""Find a permitted daily source for the KMI30 benchmark. Read-only, one request each."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests, config, psx_mkt_summary as ms

UA = config.REQUEST_HEADERS
DAY = "2026-09-29"
r = requests.get(ms.URL.format(day=DAY), headers=UA, timeout=30)
text = ms._body(r.content).decode("latin-1", "ignore")
lines = [l for l in text.replace("\r", "").split("\n") if l.strip()]
print(f"mkt_summary {DAY}: {len(lines)} lines")
idx = [l for l in lines if re.search(r"KMI|KSE|ALLSHR|INDEX|IDX", l, re.I)]
print(f"index-like lines: {len(idx)}")
for l in idx[:15]:
    print("   ", l[:160])
print("sector codes seen:", sorted({l.split('|')[2] for l in lines if l.count('|') > 3})[:40])

for name, url in [
    ("indices page",      "https://dps.psx.com.pk/indices"),
    ("indices KMI30",     "https://dps.psx.com.pk/indices/KMI30"),
    ("idx download a",    f"https://dps.psx.com.pk/download/indices/{DAY}.Z"),
    ("idx download b",    f"https://dps.psx.com.pk/download/index_summary/{DAY}.Z"),
    ("idx download c",    f"https://dps.psx.com.pk/download/indhist/{DAY}.Z"),
    ("yahoo ^KSE",        "https://query1.finance.yahoo.com/v8/finance/chart/%5EKSE?range=1mo&interval=1d"),
    ("yahoo KMI30",       "https://query1.finance.yahoo.com/v8/finance/chart/%5EKMI30?range=1mo&interval=1d"),
]:
    try:
        x = requests.get(url, headers=UA, timeout=30)
        body = x.content
        kind = "zip" if body[:2] == b"PK" else x.headers.get("content-type", "")[:30]
        print(f"[{name}] {x.status_code} {kind} {len(body)}b")
        if x.status_code == 200 and "yahoo" in name:
            res = x.json()["chart"]["result"][0]
            print(f"    symbol={res['meta'].get('symbol')} last={res['meta'].get('regularMarketPrice')} bars={len(res.get('timestamp') or [])}")
        elif x.status_code == 200 and body[:2] == b"PK":
            t = ms._body(body).decode("latin-1", "ignore")
            print("    head:", t[:300].replace("\r", " | "))
        elif x.status_code == 200:
            m = re.findall(r"KMI[- ]?30[^<]{0,120}", x.text)
            print("    KMI30 mentions:", [s[:100] for s in m[:3]])
    except Exception as e:
        print(f"[{name}] ERROR {type(e).__name__}: {str(e)[:100]}")
