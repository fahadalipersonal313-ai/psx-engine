# Engine simplified to technical analysis + news review (2026-10-07)

Requested by the owner (relayed from their other Claude session): "technical
analysis only and news engine only; news for review only, rated positive,
negative, neutral"; keep Codex ratings, Past results and the Watchlist.

Everything removed is recoverable from git: the last commit before this change
is `2bb65e1a` (`git show 2bb65e1a:<path>`).

## What runs now

- **Engine loop** (`engine.yml`, every 15 minutes in session): official daily
  bars (`psx_mkt_summary`), KSE100 benchmark (`psx_index_pdf`), the unchanged
  42-session `decision_engine.decide` (strategy v8), outcome grading, news fetch,
  dashboard snapshot. Plain sleep between cycles.
- **News** (`news.yml` hourly + the loop): headlines; Claude and Codex rate them
  Very positive / Positive / Neutral / Negative / Very negative with a reason and
  source. News weight in the score stays 0: review only.
- **Safety nets**: watchdog, hourly recovery cycle, evening grading, weekly
  archive, code sync, tests.

## Dashboard (5 tabs)

Trading desk (today's news + Buy/Exit cards with each stock's headlines),
Watchlist (last close, support, resistance, stop, targets, buy zone, score,
risk, news rating; rising-trend list), Past results, Stock detail (chart,
levels, Claude/Codex news review), News.

## Retired

- 3-4 Oct research layer: `research_*.py`, `intraday_capture.py`,
  `psx_company_quotes.py`, the 15-stock quote/checkpoint steps and the
  five-minute sampler in the loop, research outputs from the snapshot.
  Its data files on `runtime-state` and the `research-state` branch are left
  untouched (records are never deleted); nothing writes them from this repo.
- Short-horizon research (`short_horizon*.py`, Reports tab panel).
- Dashboard: intraday momentum/observation panels (the feed stopped on
  2026-10-02), order-depth upload, History and Reports tabs.
- Workflows: db/decision audit and prune one-shots, restore-main-db,
  depth/hl/mw probes, hl-backfill, and the one-off index/source probes.

Kept as data: `research_calendar.py`'s PSX closure dates moved unchanged to
`exchange_closures.py` (verified identical calendar Jul 2026-Jan 2027).

Not changed: decision rules, contract, strategy version, data guards, stored
decisions and outcomes. CLAUDE.md still describes some retired features; it
was left for the owner to update.
