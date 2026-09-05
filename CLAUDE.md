# PSX engine operating constraints

- Never fabricate prices, bars, news, eligibility, actions, outcomes or probabilities.
- Use public permitted sources; no protection bypass.
- This is experimental decision support. No automatic orders or live trading.
- Pure technical decisions and replay share decision_engine.decide and a completed session cutoff.
- Do not weaken data guards to recover signal coverage. Reconcile source data first.
- Preserve the tracked baseline database and actual portfolio during development. Test on isolated copies.
- Preserve immutable opportunities, frozen execution assumptions and legacy label definitions.
- Do not merge or deploy audit work automatically. Runtime migration needs a durable destination and verified restore.
- Run unittest discovery, compilation and git diff checks before proposing changes.

See README.md and docs/AUDIT_IMPLEMENTATION.md for current behavior and unfinished acceptance gates.
Dated historical research, preferences and rationales are preserved verbatim in docs/history/CLAUDE-2026-09-05.md. They are historical evidence, not validated strategy performance.
