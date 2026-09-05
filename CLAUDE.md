# PSX engine operating constraints

- Never fabricate prices, bars, news, eligibility, actions, outcomes or probabilities.
- Use public permitted sources; no protection bypass.
- This is experimental decision support. No automatic orders or live trading.
- Pure technical decisions and replay share decision_engine.decide and a completed session cutoff.
- Do not weaken data guards to recover signal coverage. Reconcile source data first.
- Preserve the tracked baseline database and actual portfolio during development. Test on isolated copies.
- Preserve immutable opportunities, frozen execution assumptions and legacy label definitions.
- Audit reliability implementation was authorized for `main` on 2026-09-05. Runtime data migration still needs a durable destination, official-bar reconciliation, and a verified restore before production signals can resume.
- Run unittest discovery, compilation and git diff checks before proposing changes.

See README.md and docs/AUDIT_IMPLEMENTATION.md for current behavior and unfinished acceptance gates.
Dated historical research, preferences and rationales are preserved verbatim in docs/history/CLAUDE-2026-09-05.md. They are historical evidence, not validated strategy performance.

## Current implementation state

- Commit `678edd9` introduced versioned completed-session decisions, immutable opportunity outcomes, target-before-stop evaluation, atomic batches, source-quality gates, shared sizing, exchange-session handling, and regression CI.
- The existing database is deliberately unchanged. Its mixed provenance and 42 invalid bars cause the strict strategy to fail closed until `tools/reconcile_data.py` obtains verified official replacements.
- A passing test suite validates software behavior, not forecast accuracy or profitability. Keep probabilities uncalibrated until a frozen prospective cohort has enough independently resolved opportunities.
