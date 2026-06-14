# Daily Authentic-News Routine

Produces `news_signals.json` — the authentic, LLM-judged news layer the PSX
engine reads (via `news_feed.py`) for the `sentiment` (news) component and the
bad-news veto. Runs every morning as a Claude routine, and can be run manually
("run the news routine").

## Goal
For each of the 30 stocks in `config.STOCKS`, find genuine news from the last
~24–48h, judge its direction and materiality, and write a verdict **with source
URLs**. Authenticity over coverage — a missing stock safely falls back to VADER.

## Authentic sources ONLY (the allowlist — `config.NEWS_SOURCE_ALLOWLIST`)
- PSX official: `dps.psx.com.pk`, `psx.com.pk` (announcements, result filings)
- State Bank: `sbp.org.pk`
- Reputable desks: `brecorder.com` (Business Recorder), `dawn.com` (Dawn
  Business), `profit.pakistantoday.com.pk` (Profit), `mettisglobal.news`
  (Mettis Global), `thenews.com.pk` (The News)

**Never** use social media, forums, Telegram/WhatsApp tips, or rumor sites.
If a claim appears only on a non-allowlist site, treat it as unverified.

## Steps
1. Read `config.STOCKS` for the current universe (30 symbols).
2. For each symbol: `WebSearch` with `allowed_domains` set to the allowlist
   (e.g. `"<Company> <TICKER> PSX news <month year> results dividend"`).
   `WebFetch` the most relevant article(s) when the snippet is thin.
3. Judge each stock:
   - `score` 0–100 (50 = neutral; weigh results/dividends/discoveries/ratings
     vs. losses/defaults/regulatory hits). Keep it sober — a normal dividend is
     mildly positive, not euphoric.
   - `direction`: positive | negative | neutral
   - `materiality`: `material_negative` (default risk, big loss, fraud, license
     loss, sharp guidance cut) | `material_positive` (transformational) |
     `normal`. **material_negative triggers the Buy→Watch veto** — use it only
     for genuinely serious news.
   - `confidence`: high (official filing / clear result) | medium | low (thin
     or indirect). Use `low` rather than guessing.
   - `summary`: one plain-English line.
   - `headlines`: 1–3 real headlines. `sources`: their URLs (allowlist only).
4. Only include a symbol when there is real, sourced news. Omit the rest —
   `news_feed.py` falls them back to VADER. Do not invent neutral filler.
5. Write `news_signals.json` (schema below), set `as_of` to now (PKT, ISO-8601
   with timezone). Validate it parses.
6. Commit + push:
   ```
   git add news_signals.json
   git commit -m "News routine $(date -u +'%Y-%m-%dT%H:%MZ')"
   git pull --rebase -X theirs --autostash origin main || git rebase --abort
   git push
   ```
   (Same conflict-proof pattern as the engine workflow.)

## Schema
```json
{
  "as_of": "2026-06-14T09:00:00+05:00",
  "generated_by": "claude-news-routine",
  "source_allowlist": ["dps.psx.com.pk", "..."],
  "signals": {
    "FFC": {
      "score": 70,
      "direction": "positive",
      "materiality": "normal",
      "confidence": "high",
      "summary": "Q1 2026 profit +31.6% YoY; Rs8.50 dividend; urea share 58%.",
      "headlines": ["FFC posts 32% profit growth, Rs8.50 dividend declared"],
      "sources": ["https://mettisglobal.news/FFC-posts-32-profit-growth-..."]
    }
  }
}
```

## Notes
- The engine's 15-min loop only READS this file; it never fetches news. So this
  routine is the single source of authentic news truth.
- Freshness: the engine ignores the file if older than 36h
  (`NEWS_SIGNALS_MAX_AGE_HOURS`) → run it at least every weekday morning.
- PSX market days are Mon–Fri; a weekend-stale file simply falls back to VADER.
