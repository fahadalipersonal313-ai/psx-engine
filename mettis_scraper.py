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
# Terminator is a LOOKAHEAD, not `$`: in real markup the URL is followed by the
# closing quote of href=, and `$` only matches end-of-string, so an earlier
# version matched bare URLs in tests and nothing at all on the live page.
# Both absolute and root-relative forms appear, so the origin is optional.
ARTICLE_RE = re.compile(
    r"""(?:https://mettisglobal\.news)?/([A-Za-z0-9%\-]+?-(\d{4,}))(?=["'\s<>?#]|$)""")
TIME_RE = re.compile(r'data-time="([^"]+)"')
# The listing carries almost no dates — measured 2026-08-30 on /latest: 8 dates
# for ~58 article links, and zero data-time / <time> / "x hours ago". Parsing
# them by proximity bound dates to the WRONG articles (it stamped a June story
# as today, and one story with a future date), which is why that was reverted.
# The article pages, however, carry authoritative JSON-LD:
#     "datePublished": "2026-08-29T17:19:58Z"
# present on every article sampled. An earlier attempt looked only for
# data-time on those pages and wrongly concluded they had no timestamp.
LD_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
OG_TITLE_RE = re.compile(r'<meta[^>]*property="og:title"[^>]*>', re.I)
CONTENT_RE = re.compile(r'content="([^"]*)"', re.I)
# Only the lead story on each listing carries data-time; every other item shows
# its date as TEXT. Parsing that text was tried on 2026-08-26 and REVERTED: the
# per-article block boundaries below do not match the page's real structure, so
# a date near an article bound to the wrong one. It stamped article 61496
# ("PSX in June") and 62554 as published today, and one story with a date in the
# FUTURE. A stale story wearing today's date is worse than a missing story, so
# only the article's own data-time is trusted. The census logged below records
# how much this costs on each run.
HEADLINE_RE = re.compile(
    r'<h[1-4][^>]*class="[^"]*HeadlineStyle[^"]*"[^>]*>(?:\s*<a[^>]*>)?(.*?)</',
    re.S | re.I)
ANCHOR_TEXT_RE = re.compile(r">([^<>]{15,200})<", re.S)

# Counted per run and logged: which date-bearing markup a listing actually
# carries. Mettis renders most of its lists client-side, so the mix changes.
MARKUP_PROBES = {
    "data-time": re.compile(r'data-time="[^"]*"'),
    "datetime": re.compile(r'datetime="[^"]*"'),
    "time-tag": re.compile(r"<time[^>]*>"),
    "ago": re.compile(r"\b\d{1,2}\s+(?:hours?|minutes?|days?)\s+ago\b", re.I),
    "date-text": re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d\d\b"),
    "iso": re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"),
}

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


def _blocks(html):
    """Yield (url, block_html) for each article link, where the block runs to
    the next article link. Mettis puts an item's timestamp in a reading-time
    div AFTER its anchor, so the timestamp for an item lives in its block."""
    marks = [(m.start(), f"https://mettisglobal.news/{m.group(1)}")
             for m in ARTICLE_RE.finditer(html)]
    for i, (pos, url) in enumerate(marks):
        nxt = marks[i + 1][0] if i + 1 < len(marks) else min(pos + 2000, len(html))
        yield url, html[pos:nxt]


def _title_from(block, url):
    """Headline text for this block, else a title recovered from the slug."""
    m = HEADLINE_RE.search(block) or ANCHOR_TEXT_RE.search(block)
    title = _clean(m.group(1)) if m else ""
    if not title:
        slug = url.rsplit("/", 1)[-1]
        title = _clean(re.sub(r"-\d{4,}$", "", slug).replace("-", " "))
    return title


def _attribute(title, summary=""):
    """Symbol for this headline, or '_macro'. Reuses the SAME anchor gate as the
    Google News path, so the anti-mis-attribution guarantee is identical. A
    headline naming two companies is left as _macro rather than guessed."""
    hits = [s for s in config.STOCKS
            if config.headline_matches_company(s, title, summary)]
    return hits[0] if len(hits) == 1 else "_macro"


def _article_meta(url):
    """(published_dt, title) read from the article's own page, or (None, None).

    Authoritative: the date is the publisher's own JSON-LD datePublished, and
    the title is its og:title — so neither is inferred from a neighbouring
    element on a listing, which is what previously mis-dated and mis-titled
    stories.
    """
    try:
        html = _get(url)
    except Exception as e:
        log.debug("article fetch failed %s: %s", url, e)
        return None, None
    m = LD_DATE_RE.search(html)
    dt = _parse_time(m.group(1)) if m else None
    if dt is None:
        tm = TIME_RE.search(html)
        dt = _parse_time(tm.group(1)) if tm else None
    title = ""
    om = OG_TITLE_RE.search(html)
    if om:
        cm = CONTENT_RE.search(om.group(0))
        if cm:
            title = _clean(cm.group(1))
    return dt, title


def fetch(cutoff, known=None):
    """Return (items, failures).

    Two stages: discover article URLs from the listing pages, then read each
    article's OWN date and title from its page. The second stage is what makes
    this source usable — the listings do not carry per-item dates, so anything
    derived from them is a guess.

    `known` (url -> (published_iso, title)) skips the article fetch for stories
    already seen, so a steady state costs only the day's new ones. The cached
    TITLE matters as much as the date: without it the slug fallback would turn
    "Rs1.2tr" into "Rs12tr".
    """
    known = known or {}
    urls, failures = [], []
    seen = set()

    for page in LISTING_PAGES:
        try:
            html = _get(urljoin(BASE, page))
        except Exception as e:
            log.warning("listing %s failed: %s", page or "/", e)
            failures.append(page or "/")
            continue
        for m in ARTICLE_RE.finditer(html):
            u = f"https://mettisglobal.news/{m.group(1)}"
            if u not in seen:
                seen.add(u)
                urls.append(u)
        time.sleep(PAUSE_SECONDS)

    items, no_ts, fetched = [], 0, 0
    for url in urls[:MAX_ARTICLES]:
        prev = known.get(url)
        prev_dt, prev_title = prev if isinstance(prev, tuple) else (prev, "")
        cached = _parse_time(prev_dt)
        if cached is not None:
            dt, title = cached, prev_title
        else:
            dt, title = _article_meta(url)
            fetched += 1
            time.sleep(PAUSE_SECONDS)
        if dt is None:
            no_ts += 1
            continue
        if dt < cutoff:
            continue
        if not title:
            slug = url.rsplit("/", 1)[-1]
            title = _clean(re.sub(r"-\d{4,}$", "", slug).replace("-", " "))
        items.append({"symbol": _attribute(title), "title": title,
                      "url": url, "published": dt.isoformat(),
                      "summary": "", "source": "Mettis Global"})

    log.info("mettis: %d/%d listings ok, %d urls found, %d pages fetched, "
             "%d in window, %d undated",
             len(LISTING_PAGES) - len(failures), len(LISTING_PAGES),
             len(urls), fetched, len(items), no_ts)
    if not items and not failures:
        failures.append("no dated items")
    return items, failures


if __name__ == "__main__":
    from datetime import timedelta
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    got, fails = fetch(datetime.now(timezone.utc) - timedelta(hours=24))
    print(f"\n{len(got)} items, failures={fails}")
    for it in got[:15]:
        print(f"  [{it['symbol']:7}] {it['published'][:16]}  {it['title'][:70]}")
