# Audit implementation status

This branch is a correctness and evidence repair for the audit of commit
`3007b29fe83f672578d7cd7a957b4b832f78c24b`. It does not claim profitable or
accurate future signals.

## Implemented

- A pure, versioned completed-session decision function is shared by live runs
  and historical replay. It archives the configuration and complete source
  snapshot needed to reproduce each decision.
- Technical mode is invariant to news and sentiment. Missing benchmark, CMF,
  true OHLC indicators, synchronized sessions, eligibility, or final official
  bars prevents entry.
- Wilder RSI handles rising, falling, flat, and warmup inputs. Structure and
  volume baselines exclude the decision bar. Duplicate MACD scoring is removed.
- Stop and target values must be finite and correctly ordered. Target 2 is
  absent when no valid higher target exists.
- Strong Buy confirmation uses raw qualification on distinct consecutive
  exchange sessions, with repeated polls in one session remaining idempotent.
- Source precedence is deterministic. Invalid bars enter quarantine. Detected
  price gaps never create inferred adjustment factors. Only sourced, verified
  actions with explicit price and volume factors can affect adjusted views.
- Opportunities and outcome observations are immutable and version isolated.
  Evaluation uses next-session opening entry, costs, participation, adverse gap
  fills, conservative stop-first daily-bar ordering, ten-session expiry, and
  explicit unfilled, unavailable, pending, invalid, target, stop, and expired
  states. Unavailable exposure remains visible.
- Account admission uses one sizing service with cash, marked holdings, actual
  stops, pending positions, duplication, sector exposure, total risk, fees, and
  volume participation. A technical opportunity and account eligibility are
  separate results.
- Core batches publish atomically. A complete batch requires unique expected
  symbol coverage and at least one usable result. A health command checks the
  latest batch and completed-session freshness.
- Dashboard authentication uses a one-hour server session, requires a configured
  password, and removes reusable URL credentials. The dashboard and exports call
  scores heuristic quality rather than probability and no longer present the
  old compounded backtest or legacy focus advice as versioned output.
- PSX regular trading hours use Asia/Karachi and the verified Friday split
  session. Workflows run core regression tests on Python 3.10 and 3.12, pin the
  existing GitHub actions to immutable revisions, fail on core errors, and no
  longer resolve SQLite publication races by silently keeping one writer.
- Runtime backup, data reconciliation, verified-action import, experiment
  registration, purged training selection, and calibration-evaluation utilities
  are included.

## Verification evidence

- 38 unit and integration tests pass under Python 3.12 with dependencies from
  `requirements-ci.txt`.
- Root modules compile and parse. `git diff --check` passes.
- A mocked two-symbol full run writes one complete atomic batch, renders a report,
  excludes news and live quotes from the technical decision, and does not send a
  notification.
- A Streamlit application smoke test renders with no exceptions against an
  isolated database copy.
- The committed database passes SQLite `integrity_check`. A read-only scan
  reproduces 42 invalid OHLC rows: 19 inconsistent OHLC rows and 23 rows with
  missing or invalid OHLC fields under the strict validator.
- A verified runtime backup was created without changing the tracked database.
  The read-only reconciliation inventory found 2,732 non-final or invalid bars
  across 93 dates. The PSX historical endpoint timed out during the attempted
  repair, so no replacements were fabricated or applied.

## Remaining gates

- Reconcile the runtime database from the dated official historical endpoint.
  Strict decisions currently fail closed for all 50 symbols because their
  required history contains invalid or intraday-derived rows. This is expected
  until the official replacement workflow succeeds.
- Populate holidays, Ramadan hours, and other dated session overrides from PSX
  notices. The regular schedule is verified; special schedules are not.
- Provision durable, private, single-writer runtime storage and point the worker
  and dashboard to it with `PSX_DB_PATH`. The tracked SQLite database remains in
  place because its current hosting dependency has not been migrated.
- Verify live source volume semantics, spreads, tick sizes, quantity-dependent
  fills, locked-circuit exit delays, and action handling during open positions
  with source-specific evidence.
- Reconstruct historical universe membership where available. Current replay
  retains survivorship bias and is descriptive research only.
- Register and run limited chronological baseline-versus-feature ablations after
  data reconciliation. Keep a final untouched period. Do not display calibrated
  target probabilities until independently resolved versioned opportunities are
  sufficient for temporal evaluation.
- Implement a chronological, cash-constrained marked portfolio simulator before
  reporting portfolio return or drawdown. Aggregated opportunity statistics are
  deliberately not labeled portfolio performance.
- Pin all Python packages through a reviewed lock/update process and demonstrate
  a runtime backup restore after durable storage is available.
- Run a prospective frozen-version paper evaluation for long enough to mature
  independent ten-session opportunities. Any material strategy change starts a
  new cohort.

## Deployment position

This branch is reviewable but must remain a draft. It should not be merged into
the current production workflow until data reconciliation and runtime storage
migration are complete. Deploying it now would correctly publish unavailable
decisions for the existing mixed-provenance history rather than silently issuing
signals from unverified inputs.
