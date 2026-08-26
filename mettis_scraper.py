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
from datetime import datetime, timedelta, timezone
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
# Only the lead story on each listing carries data-time; every other item shows
# its date as TEXT ("Aug 26, 2026", sometimes with a clock time). Measured
# 2026-08-26 across the seven listings: 1 data-time vs 56 date texts, against 64
# distinct stories — so the attribute path alone can never see this source.
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_TEXT_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(\d{1,2}),?\s+(20\d\d)"
    r"(?:[\s,|@·–-]{1,4}(\d{1,2}):(\d{2})\s*([APap][Mm])?)?")
PKT = timezone(timedelta(hours=5))
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


def _parse_date_text(block):
    """(datetime, precision) from a listing item's visible date, else (None, None).

    Mettis renders these in PKT. When the text carries no clock time the result
    is DAY precision: it is anchored at 00:00 PKT so the day is preserved, and
    flagged so consumers that need a real instant (session scoring) can reject
    it rather than treat midnight as a fact.
    """
    m = DATE_TEXT_RE.search(block)
    if not m:
        return None, None
    mon, day, year, hh, mm, ampm = m.groups()
    try:
        base = datetime(int(year), MONTHS[mon.lower()[:3]], int(day), tzinfo=PKT)
    except ValueError:
        return None, None
    if hh is None:
        return base, "day"
    hour = int(hh) % 12 if ampm else int(hh)
    if ampm and ampm.lower() == "pm":
        hour += 12
    if hour > 23 or int(mm) > 59:
        return base, "day"
    return base.replace(hour=hour, minute=int(mm)), "minute"


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


def fetch(cutoff, known=None):
    """Return (items, failures).

    Reads only the listing pages — seven requests per run, no per-article
    fetching. An earlier version fetched each article looking for its
    timestamp; the articles do not carry one, so 40 requests produced 0 usable
    items. The timestamp is in the listing, beside the link.

    `known` (url -> published_iso) supplies a timestamp for an item whose
    listing block has none, so a story already dated on a previous run is not
    lost when it later appears in an undated list.
    """
    known = known or {}
    items, failures, no_ts = {}, [], 0
    undated_urls, markup, samples = set(), {}, []

    for page in LISTING_PAGES:
        url = urljoin(BASE, page)
        try:
            html = _get(url)
        except Exception as e:
            log.warning("listing %s failed: %s", page or "/", e)
            failures.append(page or "/")
            continue
        for pat, rx in MARKUP_PROBES.items():
            markup[pat] = markup.get(pat, 0) + len(rx.findall(html))
        for art_url, block in _blocks(html):
            tm = TIME_RE.search(block)
            dt = _parse_time(tm.group(1) if tm else known.get(art_url))
            precision = "minute" if dt else None
            if dt is None:
                dt, precision = _parse_date_text(block)
                if dt is not None and len(samples) < 3:
                    samples.append(DATE_TEXT_RE.search(block).group(0))
            if dt is None:
                no_ts += 1
                undated_urls.add(art_url)
                continue
            # A day-precision item is kept only if its DAY can still fall inside
            # the window; comparing its 00:00 anchor to the cutoff would drop
            # every story published earlier today.
            if (dt + timedelta(days=1) if precision == "day" else dt) < cutoff:
                continue
            title = _title_from(block, art_url)
            if not title:
                continue
            prev = items.get(art_url)
            # Keep the richer title if the same story appears on several lists.
            if prev and len(prev["title"]) >= len(title):
                continue
            items[art_url] = {"symbol": _attribute(title), "title": title,
                              "url": art_url, "published": dt.isoformat(),
                              "published_precision": precision,
                              "summary": "", "source": "Mettis Global"}
        time.sleep(PAUSE_SECONDS)

    out = list(items.values())
    log.info("mettis: %d/%d listings ok, %d dated items, %d blocks undated, "
             "%d distinct undated urls; date markup seen: %s",
             len(LISTING_PAGES) - len(failures), len(LISTING_PAGES),
             len(out), no_ts, len(undated_urls),
             {k: v for k, v in markup.items() if v})
    log.info("mettis: precision %s; date-text samples %s",
             {p: sum(1 for i in out if i["published_precision"] == p)
              for p in ("minute", "day")}, samples)
    if not out and not failures:
        failures.append("no dated items")
    return out, failures


if __name__ == "__main__":
    from datetime import timedelta
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    got, fails = fetch(datetime.now(timezone.utc) - timedelta(hours=24))
    print(f"\n{len(got)} items, failures={fails}")
    for it in got[:15]:
        print(f"  [{it['symbol']:7}] {it['published'][:16]}  {it['title'][:70]}")
