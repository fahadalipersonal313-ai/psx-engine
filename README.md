# PSX technical swing research engine

The audit branch implements an experimental technical strategy evaluated by target 1 before stop within ten exchange sessions. Signals are opportunities for review. Heuristic quality is not a probability, and the code does not establish a profitable edge.

## Decision and execution contract

`decision_engine.decide` is the pure function used by the live orchestrator and historical replay. It consumes finalized official OHLC, a synchronized benchmark, an explicit completed-session cutoff, eligibility and previous-session state. It requires 200 sessions, retains up to 1,500 sessions consistently, and rejects missing, malformed, duplicate, stale or unresolved action-affected inputs. News cannot change the technical result.

Price structure excludes the decision bar. RSI uses Wilder smoothing. True OHLC ATR/ADX and CMF are required. Stops and targets must satisfy `stop < entry < target1 < target2` when target 2 exists. Strong Buy needs raw qualification on distinct consecutive sessions. Settings, source bars, benchmark, actions and previous state are archived with each usable decision.

Orders are simulated at the next benchmark session opening with the saved entry-gap bound, costs and volume-participation assumption. Same-bar ambiguity is stop-first; opening gaps through stops fill at the worse open. The initial stop and target remain fixed. Outcomes include target, stop, ten-session expiry, unfilled, pending, invalid and unavailable. Unavailable positions retain unresolved exposure. Corporate actions during a holding period require reconciliation rather than fabricated P/L. No compounded portfolio return or drawdown is manufactured from overlapping trades.

## Run and test

Python 3.10 and 3.12 are the CI targets. Install `requirements-ci.txt` for the engine, or `requirements.txt` for the dashboard. Dependencies are not yet fully locked.

```sh
python -m unittest discover -v
python -m compileall -q .
python main.py run
python main.py backtest PSO
python main.py metrics
python tools/health.py
```

`PSX_DB_PATH` selects runtime storage. Before running against real data, create a separate verified database copy:

```sh
python tools/migrate_runtime.py psx_engine.db /durable/runtime.db
python tools/reconcile_data.py --database /durable/runtime.db
python tools/reconcile_data.py --database /durable/runtime.db --apply --max-dates 10
```

The reconciliation tool preserves replaced observations and accepts only valid dated official replacements. It does not guess missing bars. Use `tools/import_actions.py` for sourced, verified actions with explicit price and volume factors and a known-at date.

## Operations and data limits

Regular PSX times use Asia/Karachi, including Friday breaks. The regular schedule was verified against https://www.psx.com.pk/psx/exchange/general/trading-hours on 2026-09-05. Holidays and special/Ramadan overrides must still be populated from dated official notices. The 30-minute publication allowance is an operational assumption, not an exchange SLA. Historical benchmark dates provide the evaluator's session sequence; completeness of that dataset remains a requirement.

Atomic batches prevent partial core results from publishing. The health command reports latest-batch failure or stale session coverage. Account admission includes available cash, pending reservations, existing marked holdings and actual stops. Technical opportunities remain distinct from account eligibility; legacy advisor promotion is disabled for versioned results.

Dashboard login uses an expiring server session and requires `DASHBOARD_PASSWORD`; credentials are not carried in query parameters. Existing public Git history cannot be protected by dashboard login.

The tracked database remains a baseline and the current hosting dependency. Mutable production state has NOT migrated out of Git. Workflow publication now fails on a race rather than resolving a binary database conflict by discarding a writer. Provision durable single-writer storage and migrate worker plus dashboard together before retiring the Git transport.

See docs/AUDIT_IMPLEMENTATION.md for acceptance evidence, outstanding work and deployment blockers. Historical notes are in docs/history. Research utilities do not constitute a completed experiment, calibrated probability model or prospective paper evaluation.
