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
5. **Conviction streak gate**: a fresh Strong Buy is held at Buy until
   confirmed on the next CALENDAR DAY (not next 15-min run — see below).
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
   the 20-EMA buy-zone with confluence ≥2 and no vetoes.

## Conviction streak (day-based, not run-based)

`conviction_streak` / `db.signal_streak()` count consecutive TRADING DAYS the
signal has held — one vote per day (that day's last run), restricted to runs
at/after `config.STREAK_PRODUCTION_START` (2026-06-15, when steady automated
15-min cadence began; earlier rows are dev/testing noise and excluded).
Raw rows are not used directly: the engine polls every 15 min, so a naive
row-count streak could hit double digits within a single session without any
real day-over-day confirmation. `signal_generator.generate()` only bumps the
streak when `prev_run_date` differs from today's date — repeat runs within
the same day hold the streak steady rather than inflating it.

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
