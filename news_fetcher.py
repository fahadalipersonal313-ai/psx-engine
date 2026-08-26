"""news_fetcher.py — Fetch raw last-24h headlines for every symbol in
config.STOCKS plus the macro Pakistan-press feeds. Writes news_raw_24h.json.

Triggered by the daily 'Run the repo news' workflow (.github/workflows/news.yml).
This module ONLY collects raw headlines — it does NOT judge them. Claude reads
the raw JSON, applies the news_routine.md rules, and writes news_signals.json
(the file the engine actually consumes via news_feed.py).

Split exists because the sandbox where Claude runs can't reach Pakistani news
hosts (403 host_not_allowed); GitHub Actions can. So fetch runs in CI, judgment
runs in the session.
"""

import json
from collections import Counter
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import requests

import config
import mettis_scraper

log = logging.getLogger("news_fetcher")

# Default daily window is 24h (the routine's standing spec). Override via env
# NEWS_WINDOW_HOURS for one-off backfills (e.g. 96 for a 4-day rebuild).
WINDOW_HOURS = int(os.environ.get("NEWS_WINDOW_HOURS") or "24")  # "" (cron) → 24
TIMEOUT = 15
UA = {"User-Agent": "Mozilla/5.0 (psx-engine news-routine; +github)"}

# Macro feeds — used to surface market-wide stories not tied to a single stock.
# Sector and policy stories arrive here, not through the per-symbol queries:
# COMPANY_NEWS_ANCHORS deliberately requires a distinctive company name, so a
# "refining margin policy" story matches no symbol at all. sector_headlines()
# scans this macro pool, so a desk missing from this list is a desk whose
# sector news can only reach a score by luck, via a Google News redirect.
# Mettis and ProPakistani were in NEWS_SOURCE_ALLOWLIST but not here — added
# 2026-08-26 to close that gap.
MACRO_FEEDS = [
    ("Business Recorder", "https://www.brecorder.com/feeds/latest-news"),
    ("Dawn Business",     "https://www.dawn.com/feeds/business"),
    ("Profit Pakistan Today", "https://profit.pakistantoday.com.pk/feed/"),
    # Mettis Global is NOT here on purpose. It is in NEWS_SOURCE_ALLOWLIST, so
    # its stories still arrive via Google News redirects, but four candidate
    # feed paths (/feed/, /rss, www./feed/, /feed/rss/) all failed a live probe
    # on 2026-08-26 and the host is egress-blocked from the dev sandbox, so the
    # real path could not be found. A permanently-failing entry is worse than
    # an absent one: it would arm the macro-failure branch of run()'s
    # regression guard on every fetch and could block a genuinely quiet day.
    # Add it back only with a URL confirmed to return items.
    # Mettis Global and Investify are deliberately NOT direct feeds. Eight
    # candidate RSS paths were probed live on 2026-08-26 and every one failed:
    #   mettisglobal.news  /feed/  /rss  www./feed/  /feed/rss/  /latest/feed/  ?feed=rss2
    #   investify.pk       /feed/  ?feed=rss2
    # The URLs the user supplied (mettisglobal.news/latest, www.investify.pk/)
    # are HTML listing pages, and this parser consumes RSS XML only. Both hosts
    # ARE in NEWS_SOURCE_ALLOWLIST, so their stories still arrive whenever
    # Google News surfaces one under a per-symbol query — they just are not
    # polled directly. Add either here only with a URL confirmed to return XML;
    # a permanently-failing entry would arm the macro-failure branch of run()'s
    # regression guard on every fetch.
    ("ProPakistani",      "https://propakistani.pk/feed/"),
]


def _parse_pub(s):
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _allowed(url):
    return any(host in (url or "") for host in config.NEWS_SOURCE_ALLOWLIST)


def _fetch_rss(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return ET.fromstring(r.content)


def _items_from_rss(root, cutoff):
    """Yield (title, link, published_iso, summary) for items newer than cutoff."""
    for item in root.iter("item"):
        title = _strip_html(item.findtext("title", ""))
        link = (item.findtext("link", "") or "").strip()
        pub = _parse_pub(item.findtext("pubDate", ""))
        if not title or not link or not pub:
            continue
        if pub < cutoff:
            continue
        summary = _strip_html(item.findtext("description", ""))[:400]
        yield title, link, pub.isoformat(), summary


def fetch_for_symbol(symbol, cutoff):
    """Google News RSS query, allowlist-filtered, last-24h."""
    query = config.COMPANY_NEWS_QUERY.get(symbol, f"{symbol} PSX Pakistan")
    url = config.GOOGLE_NEWS_RSS.format(query=quote_plus(query))
    out = []
    try:
        root = _fetch_rss(url)
    except Exception as e:
        log.warning("Google News RSS failed for %s: %s", symbol, e)
        return out
    for title, link, pub_iso, summary in _items_from_rss(root, cutoff):
        if not config.headline_matches_company(symbol, title, summary):
            # Google News token-matches the query loosely (a "National Foods"
            # story matches the "National Refinery" query); require the headline
            # to actually name this company before attributing it to the symbol.
            continue
        if not _allowed(link) and not _allowed(summary):
            # Google News wraps the source URL inside the description; if neither
            # the link nor the description names an allowlisted host, skip.
            continue
        out.append({"symbol": symbol, "title": title, "url": link,
                    "published": pub_iso, "summary": summary,
                    "source": "google_news_rss"})
    return out


def fetch_macro(cutoff, failures=None):
    out = []
    for name, url in MACRO_FEEDS:
        try:
            root = _fetch_rss(url)
        except Exception as e:
            log.warning("macro feed %s failed: %s", name, e)
            if failures is not None:
                failures.append(name)
            continue
        for title, link, pub_iso, summary in _items_from_rss(root, cutoff):
            out.append({"symbol": "_macro", "title": title, "url": link,
                        "published": pub_iso, "summary": summary,
                        "source": name})
    return out


def _known_mettis(path):
    """url -> published, from the previous file. Lets a story that was dated once
    keep that timestamp when it later shows up in an undated list."""
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f).get("items") or []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return {i["url"]: i["published"] for i in items
            if i.get("source") == "Mettis Global" and i.get("url")
            and i.get("published")}


def _existing_sources(path):
    """source -> item count in the file currently on disk. Empty if unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            return Counter(i.get("source") for i in (json.load(f).get("items") or []))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return Counter()


def _existing_count(path):
    try:
        with open(path, encoding="utf-8") as f:
            return int(json.load(f).get("count") or 0)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0


def run(output_path="news_raw_24h.json"):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    items = []
    macro_failures = []
    for sym in config.STOCKS:
        items.extend(fetch_for_symbol(sym, cutoff))
    items.extend(fetch_macro(cutoff, macro_failures))

    # Mettis publishes no RSS but carries most PSX-relevant coverage, so it is
    # read from its public pages instead (see mettis_scraper). Wrapped: a
    # scraper is inherently more fragile than a feed, and a layout change must
    # cost this one source, never the whole fetch.
    try:
        m_items, m_failures = mettis_scraper.fetch(
            cutoff, _known_mettis(output_path))
        items.extend(m_items)
        macro_failures.extend(f"mettis:{f}" for f in m_failures)
    except Exception as e:
        log.warning("mettis scraper failed: %s", e)
        macro_failures.append("mettis")

    # Regression guard (2026-08-26). A blocked host makes the fetch return a
    # SMALL result, not an empty one, so "did it write anything" is not a
    # sufficient check: a run where every macro feed 403'd still wrote 5
    # Google-News items and committed them over a good 46-item file, silently
    # dropping every macro story (and with it all sector-news coverage).
    # Refuse to overwrite when feeds failed AND the result is much thinner than
    # what is already on disk. Exit non-zero so the caller sees it.
    # Per-source regression (2026-08-26). The aggregate 50% rule above is too
    # coarse to catch ONE blocked publisher: the Claude routine's environment
    # allows fewer hosts than GitHub Actions, so its fetch lost Mettis and
    # ProPakistani entirely — 50 items down to 40, a 20% drop that sailed past
    # the aggregate check and committed over the good file. A desk that was
    # contributing and now contributes NOTHING, on a run that also had fetch
    # failures, is a network problem, not a quiet news day.
    prev_by_source = _existing_sources(output_path)
    now_by_source = Counter(i.get("source") for i in items)
    vanished = [src for src, n in prev_by_source.items()
                if n >= 3 and not now_by_source.get(src)]
    if macro_failures and vanished:
        log.error("REFUSING to overwrite %s: source(s) %s contributed nothing "
                  "this run but had %s items before, and these fetches failed: "
                  "%s. Fix the host allowlist rather than committing a "
                  "degraded fetch.", output_path, ", ".join(vanished),
                  [prev_by_source[v] for v in vanished], ", ".join(macro_failures))
        return None

    prev = _existing_count(output_path)
    if macro_failures and prev and len(items) < prev * 0.5:
        log.error("REFUSING to overwrite %s: %d items now vs %d before, and "
                  "these feeds failed: %s. Likely a network allowlist problem "
                  "— fix the host list rather than committing a degraded fetch.",
                  output_path, len(items), prev, ", ".join(macro_failures))
        return None
    # A story can arrive from both Google News and the Mettis scraper. Dedupe
    # on cleaned title so it is not counted, displayed or rated twice.
    seen_titles, deduped = set(), []
    for it in items:
        key = re.sub(r"\s+", " ", (it.get("title") or "")).strip().lower()
        key = key.rsplit(" - ", 1)[0] if " - " in key else key
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(it)
    items = deduped
    items.sort(key=lambda x: x["published"], reverse=True)
    payload = {"fetched_at": now.isoformat(),
               "window_hours": WINDOW_HOURS,
               "cutoff": cutoff.isoformat(),
               "universe": config.STOCKS,
               "allowlist": config.NEWS_SOURCE_ALLOWLIST,
               "count": len(items),
               "items": items}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    log.info("Wrote %s with %d items (%d macro feeds failed)",
             output_path, len(items), len(macro_failures))
    if macro_failures:
        log.warning("macro feeds unreachable: %s", ", ".join(macro_failures))
    return payload


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(0 if run() is not None else 1)
