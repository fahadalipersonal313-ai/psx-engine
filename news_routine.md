# Daily Authentic-News Routine

Produces `news_signals.json` — the authentic, LLM-judged news layer the PSX
engine reads (via `news_feed.py`) for the `sentiment` (news) component and the
bad-news veto. Runs nightly (~midnight) as a local Claude routine, and can be run
manually ("run the news routine").

## Goal
For each of the 30 stocks in `config.STOCKS`, find genuine news from the last
~24–48h, judge its direction and materiality, and write a verdict **with source
URLs**. Authenticity over coverage — a missing stock is safely treated as
NEUTRAL by the engine (VADER keyword scoring is disabled).

## Authentic sources ONLY — exactly THREE (`config.NEWS_SOURCE_ALLOWLIST`)
- `mettisglobal.news` (Mettis Global)
- `brecorder.com` (Business Recorder)
- `dawn.com` (Dawn Business)

**Never** use any other site — no PSX portal, no social media, forums, or rumor
sites. If a claim appears only off these three, treat it as unverified.

## EXCLUDE routine financial results & dividends (important)
The engine ALREADY auto-fetches fundamentals (P/E, EPS growth, ROE, debt/equity,
dividend yield) — see [fundamentals layer]. So news that merely re-reports
quarterly/annual **results, profit %, EPS, revenue, or dividend declarations is
DOUBLE-COUNTING and must be SKIPPED.** This news layer is for EVENT signal that
fundamentals cannot capture:
- corporate actions: M&A, acquisitions, public offers, stake sales, spin-offs
- discoveries / new wells / new plants / capacity expansion / major contracts
- regulatory & policy: tariff/gas-price/duty changes, OGRA/SBP/SECP actions,
  circular-debt or subsidy decisions affecting the company
- index changes (e.g. KMI/MII30/JSMFI inclusion or removal)
- management/governance shocks, litigation, default/restructuring, plant outages
If a stock's only news is "profit up X%, dividend Rs Y" → OMIT it (engine treats
it as neutral). If an article mixes an event WITH results, keep ONLY the event in
the summary and drop the financial figures.

## Steps
1. Read `config.STOCKS` for the current universe (30 symbols).
2. For each symbol: ONE `WebSearch` with `allowed_domains` set to the three
   allowlist sources (e.g. `"<Company> PSX news <month year>"` — do NOT add
   "results"/"dividend" to the query). Token-frugal: rely on the search snippet;
   only `WebFetch` an article when an EVENT looks real but the snippet is too
   thin to judge. If the search shows nothing but routine results/dividends,
   SKIP the stock immediately (no fetch) — the engine treats it as neutral.
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
   - OPTIONAL `earnings_date`: if a source reports an upcoming board-meeting /
     result-announcement date for the stock, add `"earnings_date": "YYYY-MM-DD"`.
     The engine then holds fresh Buys at Watch within ~5 days of it (event risk).
     Omit if unknown — never guess a date.
4. Only include a symbol when there is real, sourced news. Omit the rest —
   `news_feed.py` treats them as neutral. Do not invent neutral filler.
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
    "OGDC": {
      "score": 62,
      "direction": "positive",
      "materiality": "normal",
      "confidence": "high",
      "summary": "Bobi Deep-1 oil & gas discovery in Sindh (2,000 bpd + 1.1 MMSCFD) — fresh reserve-add catalyst.",
      "headlines": ["Bobi Deep-1 in Sindh: OGDC makes significant oil and gas discovery"],
      "sources": ["https://www.brecorder.com/news/40423877/bobi-deep-1-..."]
    }
  }
}
```

## Notes
- The engine's 15-min loop only READS this file; it never fetches news. So this
  routine is the single source of authentic news truth.
- Freshness: the engine ignores the file if older than 36h
  (`NEWS_SIGNALS_MAX_AGE_HOURS`). Scheduled for 00:00 (midnight) PKT weekdays —
  run on the home laptop near midnight so the day's authentic news is committed
  and ready before the 09:15 session. Stays fresh through that trading day.
- PSX market days are Mon–Fri. If a night is missed, the engine simply uses
  authentic-or-NEUTRAL news that day (VADER is disabled) — never RSS noise.
