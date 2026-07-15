# PSX Shariah Engine — Working Memory

A Shariah-compliant PSX (Pakistan Stock Exchange) equity analysis engine. KMI-30
focus, with a broader KMI All-Share universe.

## Hard rules (NEVER violate)
- **Never fabricate data.** Shariah status, news, earnings dates, prices, OHLC,
  benchmark moves — all sourced from real data or explicitly labelled
  unavailable. Missing data stays NULL, never a synthesized value.
- **No protection bypass.** Public PSX DPS endpoints + public RSS only.
- **No backwards-compat shims, no dead code, minimal comments.** Comment only
  the non-obvious WHY.
- **Manual confirmation required before any trade** — this is decision support,
  not auto-trading.

## News: auto-fetched, UNSCORED window (2026-07-15)

News carries **0% score weight**. The `news.yml` workflow now runs on a
**weekday-morning cron** (09:05 / 09:35 / 11:05 PKT, staggered) — no manual
prompt needed — and commits `news_raw_24h.json`. The dashboard reads that raw
file via `news_feed.raw_headlines(sym)` and shows the last-24h headlines per
stock as an **unscored window for manual cross-verification** (Watchlist "Full
detail" expander + Stock detail tab). `news_feed.raw_headlines` filters to
credible desks by publisher NAME (`config.NEWS_DISPLAY_PUBLISHERS`) because the
fetch-time host allowlist is bypassed by Google News redirect links (every link
is `news.google.com`, so off-desk publishers leak into the raw file). The
LLM-judged `news_signals.json` routine below is now OPTIONAL — only relevant if
news weights are ever restored.

## GLM second opinion (2026-07-15, unweighted)

`news_glm.py` runs after the news fetch in `news.yml` (needs `GLM_API_KEY`
secret set in the repo — ZhipuAI free tier, `glm-4.5-flash`). One batched
request rates every symbol that has fresh credible headlines as
`highly_positive | positive | neutral | negative | highly_negative` and writes
`news_glm_ratings.json`. `news_feed.glm_rating(sym)` reads it. The dashboard
shows a `🤖 GLM` pill next to `📰` on each actionable-card, plus the GLM
reason, so the user can cross-check whether the LLM agrees with the engine's
Buy/Avoid. **Zero score weight** — informational only. Missing key / stale
file → pill shows `GLM: —` and nothing else changes.

## Dashboard: regime what-if toggle (2026-07-15)

Sidebar radio `🔀 Regime what-if` — `Actual | Assume risk-on | Assume
risk-off`. On each Buy/Strong Buy card it prints a one-line note of what the
signal WOULD be under the assumed regime (risk-off → soft-downgrade to Watch
via the regime gate; risk-on → holds, chase guard loosens). Approximation, not
a re-run — the stored score/vetoes drive it. Never mutates stored signals.

## "Run the repo news" — optional LLM-judged routine (only if weights restored)

User says **"Run the repo news"** any morning after 09:00 PKT → Claude:
1. Triggers `.github/workflows/news.yml` (workflow_dispatch on `main`) via
   `mcp__github__actions_run_trigger`. CI runs `python news_fetcher.py` which
   fetches last-24h headlines from Google News RSS per symbol (filtered to the
   allowlist) + Business Recorder / Dawn Business / Profit Pakistan Today /
   Mettis macro feeds, and commits `news_raw_24h.json`.
2. Pulls `news_raw_24h.json`, applies `news_routine.md` rules (exclude routine
   results/dividends; score 0–100; direction/materiality/confidence; sources
   from allowlist only), writes `news_signals.json`, commits + pushes.
3. Triggers `engine.yml` so the dashboard reflects fresh news-weighted signals.

**News weight is ZERO as of 2026-07-15** — the user turned news off because the
headline-driven score swings were noise (a single live-blog headline could flip
a symbol run-to-run). `config.WEIGHTS` is now **technical 1.0**, fundamentals
0.0, macro_news 0.0, sentiment 0.0 — `final_score == technical score`. The news
routine, `news_signals.json`, macro and sentiment sections are all STILL
computed and shown, and still drive the `bad_news` / `manipulation_risk` SAFETY
vetoes in `risk_manager` (those only downgrade a Buy→Watch, never fabricate),
but news no longer MOVES the score. To re-enable, restore e.g. technical 0.55 /
macro_news 0.20 / sentiment 0.25. Fundamentals was zeroed earlier (2026-06-19):
confirmed manually. `NEWS_SIGNALS_MAX_AGE_HOURS = 24` still gates stale files.

## Architecture (top-down)

`main.py` orchestrates one run:
1. Fetch market news, per-company news, benchmark index (KMI30).
2. `market_regime.assess_regime()` → risk-on/risk-off + `pct_above` (% the
   index sits above its 50-EMA).
3. For each stock: shariah check → quote/EOD → technical → sentiment →
   macro/news → fundamentals → relative strength → `scoring_engine.compute()` →
   `risk_manager.assess()` (now regime-aware) → `signal_generator.generate()`.
4. Save to SQLite (`psx_engine.db`); `backtester.update_outcomes()` fills
   forward prices and grades old runs (learning loop).

## Signal pipeline (signal_generator.generate)

Order of operations:
1. **No-data guard**: missing price → `"No data"` signal.
2. **Hard overrides** (always beat the score): shariah issue → `Avoid`;
   technical breakdown below support → `Exit` (if held) / `Avoid`.
3. **Score → base band**: `≥80 Strong Buy`, `≥70 Buy`, `≥60 Watch`,
   `≥50 Hold`, else `Avoid`. Strong Buy needs technicals confirming.
4. **Hysteresis dead-band** (`HYSTERESIS_BAND=2`): one-notch transitions
   require crossing threshold by 2pts. Stops Buy↔Watch flapping when raw
   score grazes 70. Symmetric (downgrades AND upgrades).
5. **Strong Buy confirmation gate**: a fresh Strong Buy is held at Buy until
   the very next run still scores Strong Buy. No numeric streak/conviction
   count is tracked or shown anywhere (removed — see below).
6. **Confluence gate** (4 dims, each independent): trend (price>50-EMA),
   momentum (RSI 40-74 AND MACD hist>0), volume (OBV up), structure
   (price>support AND no breakdown). Strong Buy needs ≥3/4, Buy needs ≥2/4.
7. **Chase guard** (regime-aware + rally-strength-scaled): if `ext_pct >
   max_extension_pct × multiplier` OR `momentum_20d > max_extension_momentum_pct
   × multiplier`, step down. Multiplier ramps from 1.0 (neutral) up to
   `extension_riskon_multiplier=1.8` as `regime_pct_above` reaches
   `extension_riskon_full_pct=8.0`.
8. **Soft downgrades** (Buy/Strong Buy → Watch): earnings blackout (≤5d),
   risk-off regime, `poor_rr` veto, `manipulation_risk`, `bad_news`, High risk,
   confidence<45.
9. **Pullback-entry upgrade** (Watch/Hold → Buy): when price has retraced to
   the 20-EMA buy-zone with confluence ≥2 and no vetoes — AND (2026-07-15
   audit) `final_score ≥ PULLBACK_MIN_SCORE (60)` and `RS ≥ PULLBACK_MIN_RS
   (55)`. Ungated pullback Buys won 21%; quality-gated won 42%.
10. **RS laggard veto** (soft downgrade, 2026-07-15): Buy/Strong Buy with
    `relative_strength < RS_LAGGARD_VETO (45)` → Watch. Laggard Buys won 19%
    vs 35% for the rest. RS=None never vetoes (missing data can't block).

## Confidence honesty (2026-07-15)

`scoring_engine.historical_confidence_adjust` counts ONLY strictly-graded
signals (Buy/Strong Buy/Avoid/Exit). Watch/Hold outcomes use the loose
"didn't lose >3%" rule (80-90% survival rates, not edge) and were inflating
every symbol's confidence toward the +15 cap.

## Conviction streak — removed

The dashboard used to show a "🔥 N-run/N-day streak" badge per stock. Removed
entirely: even day-bucketed, it kept giving a false sense of independent
confirmation. `db.signal_streak()` is gone; `conviction_streak` stays in the
`runs` schema (old rows only) but nothing writes to it anymore. The Strong Buy
confirmation gate (above) achieves the same "don't chase a one-run spike"
goal without surfacing a number that looks like a track record.

## Risk vetoes (risk_manager.assess)

- `breakdown` — price below support
- `poor_rr` — real headroom_rr below `min_headroom_rr` (1.5 baseline).
  **Regime-aware:** in risk-on, threshold ramps DOWN to floor 1.1 by
  `headroom_rr_riskon_full_pct=8.0` (% the benchmark sits above its EMA).
- `bad_news`, `manipulation_risk` — content-driven

## Learning loop (backtester)

- `update_outcomes()` fills `price_1d/3d/7d` from real EOD; grades once 3-day
  price exists; credits/blames sub-indicators in `indicator_accuracy`.
- `_signal_worked()` grading rules:
  - **Buy/Strong Buy**: price rose >1% in 3 days without stop hit
  - **Avoid/Exit**: stock underperformed the **REAL KMI30 benchmark**
    forward move (3-day). Falls back to **cohort median** (engine's own
    universe) when the index isn't reachable. Final fallback: "did not rise"
    (chg<0). Three honest fallbacks, never fabricated.
  - **Watch/Hold**: loose grade — didn't lose >3%
- `regrade_all()` (`python main.py regrade`) wipes indicator_accuracy and
  re-grades EVERY completed run under current rules. Run this whenever
  grading rules change.

## Accuracy stats

`db.signal_accuracy_summary()` returns rows with `n_confidence`
(`high`/`medium`/`low`) — small-N win rates are flagged as NOISE, not edge.
CLI `python main.py accuracy` shows this with explicit warnings.

## Dashboard staleness

- `DATA_FRESHNESS_AMBER_HOURS=4` → tile turns amber, banner warns
- `DATA_FRESHNESS_RED_HOURS=24` → tile turns red, error banner

## Dashboard trade-plan cards

Each Buy-signal card has an inline "📋 Full detail" expander (no extra data
fetch — uses fields already on the row: full reason, main risk, shariah
status, regime, support/resistance, buy-zone). Chart + per-stock backtest
still live only in the 📈 Stock detail tab to avoid an EOD fetch per card.

## Key files

- `config.py` — all knobs (thresholds, weights, risk caps, stocks).
- `signal_generator.py` — signal decision logic (the heart).
- `risk_manager.py` — veto layer + position sizing.
- `market_regime.py` — KMI30-driven regime + relative strength.
- `technical_analyzer.py` — TA score + flags (ext_pct, momentum_20d,
  headroom_rr, confluence inputs, accumulation candidates).
- `scoring_engine.py` — weighted final_score + confidence.
- `backtester.py` — learning loop + historical replay (in-sample/OOS/walk-forward).
- `database.py` — SQLite (tracked binary `psx_engine.db`).
- `dashboard.py` — Streamlit UI.
- `main.py` — CLI entry: `run / schedule / morning / evening / backtest SYMBOL /
  metrics / portfolio / accuracy / regrade / accumulating / history SYMBOL /
  fundamentals`.

## Environment notes

- PSX DPS (`dps.psx.com.pk`) returns **403 Forbidden** from this sandbox.
  All live analysis uses stored data via `db.last_run()` / `db.run_history()`.
- The cloud GitHub Action runs the engine automatically and commits
  `psx_engine.db` frequently → expect binary rebase conflicts. Resolve via
  `git checkout --theirs psx_engine.db`, then re-run any maintenance commands
  (e.g., `python main.py regrade`) and re-push.

## Universe (KMI-30 verified + KMI All-Share)

See `KMI30_VERIFIED`, `KMIALLSHR_VERIFIED`, `OTHER_COMPLIANT` in config.py.
Re-verify each semi-annual recomposition (KMI30 effective 2026-05-25;
KMI All-Share effective 2026-06-05).

## Open / parked ideas

- Per-symbol-type backtest split (training vs evaluation window) — currently
  the in-sample/OOS split exists in `backtester.backtest()` but live signal
  accuracy stats are all in-sample.
- Earnings dates remain manual (`EARNINGS_DATES = {}` in config + optional
  `earnings_date` field in `news_signals.json`).

## Cross-account handoff — "continue where other account stopped"

This section is the resume point for any Claude account. It is committed to
`main`, so a fresh session sees it via git. **When the user says "continue where
other account stopped," read this section first, then `git pull origin main` to
get the latest state.** Keep this section current at the end of each work
session (edit the dates/state, commit, push).

**Last updated:** 2026-07-15 (engine live and pushing continuously; deep
signal-quality audit shipped — pullback quality gate, RS laggard veto,
strict-history confidence).

### Current working context
- All recent work is committed directly to `main` (news-only + analysis + config
  commits follow this pattern). Designated dev branch is
  `claude/determined-ptolemy-8m2o5o` for code-change PRs if/when needed.
- News routine is fully operational and has been run daily (latest: commit
  `3f382f5`, "News routine 2026-06-24"). Follow the two-stage pipeline in the
  "Run the repo news" section above, and ALWAYS run the URL-verification script
  (below) before committing `news_signals.json`.
- Live PSX DPS is 403 in-sandbox → all live analysis uses stored data via
  `db.last_run()` / `db.run_history()`, and independent analysis is qualitative
  (never fabricate live prices/valuations).

### News URL-verification script (MANDATORY before every news commit)
```python
import json
d = json.load(open('news_signals.json'))
raw = json.load(open('news_raw_24h.json'))
raw_urls = set(it['url'] for it in raw['items'])
bad = [(s, u) for s, v in d['signals'].items() for u in v['sources'] if u not in raw_urls]
print('Unverified URLs:', bad)   # MUST be []
```
Common trap: copying URLs from a truncated `[:80]`-sliced exploration print.
Fix by patching each source from the raw fetch programmatically, never retyping.

### In-flight / recent analysis threads
- **PSO** (user's portfolio is ~83% PSO, avg ~363.8, in loss): covered backtest
  mechanics, relative-strength calc, and a 6-month averaging strategy. Key take:
  concentration is the real risk, not PSO itself; tranche around the 344.54 stop,
  diversify into PRL. Engine last had PSO at "Avoid" (score 45, news-driven).
- **KMI-30 independent top picks (2026-06-24):** MARI (top conviction — Shams-1
  gas catalyst, cleanest E&P balance sheet), MEBL (rate-cycle Islamic bank),
  OGDC (Sahito-1 catalyst but oil-price hedged), a fertilizer name (EFERT/FFC,
  defensive income). Avoid pure oil-beta (PPL) and PSO into falling oil.
- **MARI deep-dive → `analysis/MARI_verification_checklist.md`** (committed). Six
  numbers to verify (Shams-1 volume, valuation multiple, dividend, RRR, net cash,
  % market-linked output) with a buy/wait/pass decision rule. This is the current
  active deliverable — next step is filling those six numbers from PSX/financials.

### Parked (only resume if user asks)
- Item #5 from an earlier "start with 2, then 3 and then 5" instruction: a PSO
  confluence-dimension breakdown (trend/momentum/volume/structure) — never done.
