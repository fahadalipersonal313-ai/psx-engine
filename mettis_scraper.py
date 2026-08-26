"""mettis_scraper.py — Collect Mettis Global headlines from their public pages.

Mettis publishes no RSS (confirmed 2026-08-26: zero application/rss+xml link
tags, and eight candidate feed paths all 404'd), but it carries the bulk of
PSX-relevant Pakistani market news, so the user directed that it be scraped.
This widens the project's standing "public RSS only" source rule to include
this one publisher's public, unauthenticated pages.

What is and is NOT done here:
  - Only pages Mettis serves to any anonymous visitor are read. No login, no
    paywall, no token, nothing behind mettisglobal.net.
  - Their internal JSON endpoints are deliberately NOT touched. The homepage
    fills #company-analysis-container, #technical-analysis-container and
    #analyst-briefing-container from JavaScript, and reverse-engineering those
    calls would be going after the data path they sell as "MG - APIs".
    Consequence: this scraper CANNOT see the MG Research analysis sections.
    Only the server-rendered news headlines are reachable.
  - Requests are paced and capped so a run is a handful of page loads.

Accuracy rules, since these feed a score:
  - A story's publish time comes from the article's own data-time attribute.
    An item whose timestamp cannot be read is DROPPED, never stamped with the
    fetch time — a synthesized timestamp would silently place old news inside
    the current session window.
  - Attribution reuses config.headline_matches_company, the same anchor gate
    the Google News path uses. A headline naming exactly one universe company
    is filed under that symbol; anything else is filed as _macro, where
    sector_headlines can still pick it up. A headline matching two or more
    companies is filed as _macro rather than guessed at.
"""

import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

import config

log = logging.getLogger("mettis_scraper")

BASE = "https://mettisglobal.news/"
# Listing pages worth reading. Kept short on purpose: each is one request, and
# the sections chosen are the ones that actually move PSX names.
LISTING_PAGES = [
    "",                    # homepage — lead story + latest list + must-reads
    "latest",
    "Equity",
    "Economy",
    "Commodities",
    "PSXRoundup",
    "MorningBreeze",
]
# An article URL is <slug>-<numeric id>; that id is what makes them matchable.
ARTICLE_RE = re.compile(r"https://mettisglobal\.news/([A-Za-z0-9%\-]+?-(\d{4,}))(?:[/?#]|$)")
TIME_RE = re.compile(r'data-time="([^"]+)"')
TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
OG_TITLE_RE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', re.I)

UA = {"User-Agent": "Mozilla/5.0 (psx-engine news-routine; +github)"}
TIMEOUT = 20
MAX_ARTICLES = int(getattr(config, "METTIS_MAX_ARTICLES", 40))
PAUSE_SECONDS = 0.4


def _get(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def _clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    for ent, ch in (("&#x27;", "'"), ("&#x2019;", "’"), ("&amp;", "&"),
                    ("&quot;", '"'), ("&nbsp;", " "), ("&#x2013;", "–")):
        text = text.replace(ent, ch)
    return re.sub(r"\s+", " ", text).strip()


def _parse_time(raw):
    """Mettis stamps ISO-8601 with 7 fractional digits, which datetime rejects.
    Trim to 6. Returns an aware datetime or None — never a guess."""
    if not raw:
        return None
    s = raw.strip().replace("Z", "+00:00")
    s = re.sub(r"\.(\d{6})\d+", r".\1", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def discover_article_urls():
    """Article URLs found across the listing pages, de-duplicated."""
    urls, failures = [], []
    seen = set()
    for page in LISTING_PAGES:
        url = urljoin(BASE, page)
        try:
            html = _get(url)
        except Exception as e:
            log.warning("listing %s failed: %s", url or "/", e)
            failures.append(page or "/")
            continue
        for m in ARTICLE_RE.finditer(html):
            full = f"https://mettisglobal.news/{m.group(1)}"
            if full not in seen:
                seen.add(full)
                urls.append(full)
        time.sleep(PAUSE_SECONDS)
    return urls, failures


def _attribute(title, summary=""):
    """Symbol for this headline, or '_macro'. Reuses the SAME anchor gate as the
    Google News path, so the anti-mis-attribution guarantee is identical. A
    headline naming two companies is left as _macro rather than guessed."""
    hits = [s for s in config.STOCKS
            if config.headline_matches_company(s, title, summary)]
    return hits[0] if len(hits) == 1 else "_macro"


def fetch(cutoff, known=None):
    """Return (items, failures).

    `known` maps url -> published_iso from a previous run, so an article is
    only fetched once. Items older than `cutoff`, or with an unreadable
    timestamp, are dropped.
    """
    known = known or {}
    urls, failures = discover_article_urls()
    if not urls:
        return [], failures or ["mettis: no article links found"]

    items, fetched, no_timestamp = [], 0, 0
    for url in urls:
        pub_iso = known.get(url)
        title = None
        if pub_iso is None:
            if fetched >= MAX_ARTICLES:
                break
            try:
                html = _get(url)
            except Exception as e:
                log.debug("article %s failed: %s", url, e)
                continue
            fetched += 1
            time.sleep(PAUSE_SECONDS)
            tm = TIME_RE.search(html)
            dt = _parse_time(tm.group(1) if tm else None)
            if dt is None:
                no_timestamp += 1
                continue
            pub_iso = dt.isoformat()
            m = TITLE_RE.search(html) or OG_TITLE_RE.search(html)
            title = _clean(m.group(1)) if m else None

        dt = _parse_time(pub_iso)
        if dt is None or dt < cutoff:
            continue
        if not title:
            # Recover a readable title from the slug when reusing a cached URL.
            slug = url.rsplit("/", 1)[-1]
            title = _clean(re.sub(r"-\d{4,}$", "", slug).replace("-", " "))
        if not title:
            continue
        items.append({"symbol": _attribute(title), "title": title, "url": url,
                      "published": dt.isoformat(), "summary": "",
                      "source": "Mettis Global"})

    if no_timestamp:
        log.warning("mettis: dropped %d article(s) with no readable timestamp",
                    no_timestamp)
    log.info("mettis: %d listing pages, %d urls, %d articles fetched, %d items",
             len(LISTING_PAGES) - len(failures), len(urls), fetched, len(items))
    return items, failures


if __name__ == "__main__":
    from datetime import timedelta
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    got, fails = fetch(datetime.now(timezone.utc) - timedelta(hours=24))
    print(f"\n{len(got)} items, failures={fails}")
    for it in got[:15]:
        print(f"  [{it['symbol']:7}] {it['published'][:16]}  {it['title'][:70]}")
