"""One-off discovery probe. Runs in GitHub Actions (open internet) because the
dev sandbox is egress-blocked for these hosts.

For each target page: dump the RSS/Atom <link> tags, any feed-looking href, and
the site's section links, so the real feed path and the "analysis" sections can
be identified instead of guessed. Writes probe_result.txt. Delete after use.
"""

import re
import sys
from urllib.parse import urljoin

import requests

UA = {"User-Agent": "Mozilla/5.0 (psx-engine source-probe; +github)"}
TARGETS = [
    "https://mettisglobal.news/",
    "https://mettisglobal.news/latest",
    "https://www.investify.pk/",
]

out = []


def w(line=""):
    out.append(line)
    print(line)


for url in TARGETS:
    w("=" * 72)
    w(f"TARGET: {url}")
    try:
        r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
        html = r.text
        w(f"  HTTP {r.status_code}  final={r.url}  bytes={len(html)}")
    except Exception as e:
        w(f"  FAILED: {type(e).__name__}: {e}")
        continue

    # 1. Declared feeds
    feeds = re.findall(
        r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>',
        html, re.I)
    w(f"  -- declared feed <link> tags: {len(feeds)}")
    for f in feeds[:10]:
        href = re.search(r'href=["\']([^"\']+)["\']', f, re.I)
        title = re.search(r'title=["\']([^"\']*)["\']', f, re.I)
        if href:
            w(f"     FEED: {urljoin(r.url, href.group(1))}"
              f"   ({title.group(1) if title else 'no title'})")

    # 2. Any feed-ish href at all
    hrefs = set(re.findall(r'href=["\']([^"\']+)["\']', html, re.I))
    feedish = sorted({h for h in hrefs
                      if re.search(r'(feed|rss|atom|\.xml)', h, re.I)})
    w(f"  -- feed-looking hrefs: {len(feedish)}")
    for h in feedish[:15]:
        w(f"     {urljoin(r.url, h)}")

    # 3. Section links — to spot analysis/research areas worth evaluating
    paths = {}
    for h in hrefs:
        full = urljoin(r.url, h)
        m = re.match(r'https?://[^/]+/([^/?#]+)', full)
        if m and full.startswith(r.url.split('/')[0] + '//' + r.url.split('/')[2]):
            paths[m.group(1)] = paths.get(m.group(1), 0) + 1
    top = sorted(paths.items(), key=lambda x: -x[1])[:25]
    w(f"  -- top site sections (path segment, link count):")
    for seg, n in top:
        w(f"     /{seg}  ({n})")
    w()

with open("probe_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"\nwrote probe_result.txt ({len(out)} lines)")
sys.exit(0)
