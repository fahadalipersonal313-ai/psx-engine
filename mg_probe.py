"""Throwaway diagnostic: what date markup does a Mettis listing actually carry?

Run from Actions (the sandbox cannot reach mettisglobal.news). Delete after use.
"""
import re, sys
import requests

UA = {"User-Agent": "Mozilla/5.0 (psx-engine news-routine; +github)"}
ART = re.compile(r"""(?:https://mettisglobal\.news)?/([A-Za-z0-9%\-]+?-(\d{4,}))(?=["'\s<>?#]|$)""")

for page in ("latest", "Equity"):
    url = "https://mettisglobal.news/" + page
    html = requests.get(url, headers=UA, timeout=25).text
    marks = [(m.start(), m.group(1)) for m in ART.finditer(html)]
    uniq = {u for _, u in marks}
    print(f"\n===== /{page}  bytes={len(html)}  link-matches={len(marks)}  distinct={len(uniq)}")
    for pat in (r'data-time="[^"]*"', r'datetime="[^"]*"',
                r'<time[^>]*>', r'property="article:published_time"[^>]*',
                r'\b\d{1,2}\s+(?:hours?|minutes?|days?)\s+ago\b',
                r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d\d\b',
                r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}'):
        hits = re.findall(pat, html)
        print(f"  {pat[:52]:55} {len(hits):4}  {hits[:3]}")
    # raw window around the 3rd distinct link, to see the surrounding item markup
    seen, shown = set(), 0
    for pos, u in marks:
        if u in seen:
            continue
        seen.add(u)
        if len(seen) < 3 or shown >= 2:
            continue
        print(f"\n  --- window around {u[:60]} ---")
        print(re.sub(r"\s+", " ", html[max(0, pos - 700):pos + 700]))
        shown += 1
