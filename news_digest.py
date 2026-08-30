"""news_digest.py — Build the analysis bundle the news Routine rates.

Why this exists
---------------
The Routine used to assemble its input with a long inline `python -c`, which
could only ever pass HEADLINES to the rater. Now that article_text.py fetches
real bodies, the input needs assembling properly: matched to companies and
sectors, carrying the article text, and honest about which items have text and
which do not.

The asymmetry that shapes this module (measured 2026-08-30 on a 66-item file):

  company-attributed items   13   ALL from google_news_rss -> NO body available
  _macro pool                53   ALL direct publishers    -> body available

Google News serves a JavaScript app shell, not an article (HTTP 200, 593 KB of
`window.WIZ_global_data`, identical under a browser UA), so those 13 are
headline-only and cannot be fixed by fetching harder.

The win is the other direction: the 53 direct-publisher articles carry real
prose, so a company named in the BODY of a macro story can now be surfaced —
coverage that the headline-only gate could never see. A refining-policy piece
that names National Refinery in paragraph three was previously invisible to NRL.

Guard against the obvious way that could go wrong: body matching is restricted
to the LEDE (first LEDE_CHARS), not the whole article. A company mentioned in
passing near the end of a piece is not what that piece is about, and attributing
it there would manufacture news for that symbol.
"""

import json
import logging
import os
import sys

import config

log = logging.getLogger("news_digest")

RAW_PATH = os.path.join(config.BASE_DIR, "news_raw_24h.json")
BODIES_PATH = os.path.join(config.BASE_DIR, "news_bodies.json")

LEDE_CHARS = 600         # body window used for ATTRIBUTION (not for rating)
TEXT_CHARS = 3000        # body text handed to the rater per item
MAX_PER_KEY = 6          # items per company / per sector


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def build(raw_path=RAW_PATH, bodies_path=BODIES_PATH):
    raw = _load(raw_path, {})
    items = raw.get("items") or []
    bodies = (_load(bodies_path, {}) or {}).get("bodies") or {}

    companies, sectors = {}, {}
    read_urls, with_text = [], 0

    for it in items:
        url = it.get("url") or ""
        title = it.get("title") or ""
        body = bodies.get(url)
        summary = it.get("summary") or ""
        # Rating text: the real article when we have it, else the RSS stub.
        # depth is recorded so a thin call is never mistaken for a deep one.
        if body:
            text, depth = body[:TEXT_CHARS], "full"
            with_text += 1
            read_urls.append(url)
        else:
            text, depth = summary, "headline"
        lede = (body or summary)[:LEDE_CHARS]

        entry = {"title": title, "url": url, "source": it.get("source"),
                 "published": it.get("published"), "depth": depth, "text": text}

        # --- company attribution
        # 1. what the fetcher already decided (per-symbol RSS query)
        sym = (it.get("symbol") or "").upper()
        hits = set()
        if sym and sym != "_MACRO":
            hits.add(sym)
        # 2. NEW: a company named in the title or the lede of a macro article.
        for s in config.STOCKS:
            if config.headline_matches_company(s, title, lede):
                hits.add(s)
        for s in hits:
            companies.setdefault(s, [])
            if len(companies[s]) < MAX_PER_KEY:
                companies[s].append(entry)

        # --- sector attribution (same phrases the engine already uses)
        hay = f"{title} {lede}".lower()
        for sector, phrases in config.SECTOR_NEWS_ANCHORS.items():
            if any(p.lower() in hay for p in phrases):
                sectors.setdefault(sector, [])
                if len(sectors[sector]) < MAX_PER_KEY:
                    sectors[sector].append(entry)

    return {"fetched_at": raw.get("fetched_at"),
            "items_total": len(items),
            "articles_with_text": with_text,
            "read_urls": sorted(set(read_urls)),
            "company": companies,
            "sector": sectors}


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    d = build()
    if "--summary" in sys.argv:
        print(f"items {d['items_total']}, with full text {d['articles_with_text']}, "
              f"companies {len(d['company'])}, sectors {len(d['sector'])}")
        for s, v in sorted(d["company"].items()):
            deep = sum(1 for e in v if e["depth"] == "full")
            print(f"  {s:8} {len(v)} item(s), {deep} with full text")
        for s, v in sorted(d["sector"].items()):
            deep = sum(1 for e in v if e["depth"] == "full")
            print(f"  [S] {s:24} {len(v)} item(s), {deep} with full text")
    else:
        print(json.dumps(d, ensure_ascii=False))
