# PSX engine operating constraints

- Never fabricate prices, bars, news, eligibility, actions, outcomes or probabilities.
- Use public permitted sources; no protection bypass.
- This is experimental decision support. No automatic orders or live trading.
- Pure technical decisions and replay share decision_engine.decide and a completed session cutoff.
- Do not weaken data guards to recover signal coverage. Reconcile source data first.
- Preserve the tracked baseline database and actual portfolio during development. Test on isolated copies.
- Preserve immutable opportunities, frozen execution assumptions and legacy label definitions.
- Audit reliability and the 42-session v3 strategy were authorized for `main` on 2026-09-05. Runtime data still needs a durable destination and a verified restore; keep rolling official reconciliation current.
- Run unittest discovery, compilation and git diff checks before proposing changes.

See README.md and docs/AUDIT_IMPLEMENTATION.md for current behavior and unfinished acceptance gates.
Dated historical research, preferences and rationales are preserved verbatim in docs/history/CLAUDE-2026-09-05.md. They are historical evidence, not validated strategy performance.

## Current implementation state

- User requests: use plain language throughout the dashboard; test past signals for all tracked stocks; include verified KMI All Share stocks below PKR 50. Do not confuse the user's Codex usage reset with a change to that price limit.
- v4 fixes the obsolete 60-session weak-data flag: the complete 42-session contract must not automatically block all Buys. Each historical decision still uses only its preceding 42 sessions. Default evaluation is the latest 21 sessions, backed by 64 official sessions where available.
- The universe now includes 168 distinct symbols. The dated PSX membership and price evidence is in data_lower_price_stocks.json. PSX label suffixes such as XD and NC are not part of the trading symbol.
- Top-ten candidates must have rising 10/20/40-session trends, positive momentum and buying flow, adequate volume, valid trade levels, and verified eligibility. Show fewer than ten when fewer qualify; never fill the list with weak names.

- Commit `678edd9` introduced versioned completed-session decisions, immutable opportunity outcomes, target-before-stop evaluation, atomic batches, source-quality gates, shared sizing, exchange-session handling, and regression CI.
- `technical_swing_short_v3` uses exactly 42 sessions, 10/20/40-session EMAs, and 10/21/41-session relative strength. Older bars cannot affect its decision.
- The latest 42-session decision window, 2026-07-07 through 2026-09-04, is reconciled to 2,100 official bars for all 50 symbols. Its initial smoke result was 29 Avoid, 18 Watch, 3 Hold, and zero Buy; do not weaken thresholds to manufacture candidates.
- A passing test suite validates software behavior, not forecast accuracy or profitability. Keep probabilities uncalibrated until a frozen prospective cohort has enough independently resolved opportunities.
