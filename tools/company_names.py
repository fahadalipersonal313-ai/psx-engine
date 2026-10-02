"""Print PSX's official company names for symbols lacking news anchors. Read-only."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
import config, psx_mkt_summary as ms

missing = [s for s in config.STOCKS if s not in config.COMPANY_NEWS_ANCHORS]
d = date.today()
for _ in range(10):
    d -= timedelta(days=1)
    if d.weekday() >= 5:
        continue
    import requests
    r = ms.get_with_retry(requests, ms.URL.format(day=d.isoformat()), headers=config.REQUEST_HEADERS, timeout=30)
    if r.status_code != 200:
        continue
    text = ms._body(r.content).decode("latin-1", "ignore")
    for line in text.splitlines():
        f = [x.strip() for x in line.split("|")]
        if len(f) > 3 and f[1].upper() in missing:
            print(f"{f[1]}|{f[3]}")
    break
