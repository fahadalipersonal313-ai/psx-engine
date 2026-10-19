# Paper-trading forward test (Turn-Confirmation Theory)

A separate experiment, not part of the engine's signals. It lives on the orphan branch `paper-trading`
(never merged into `main`) and is run by a cloud routine on weekdays. Paper only: no real orders.

## What the engine provides: `market_eod.json` (runtime-state)

`market_eod.py` is called from `main.full_run` after the cutoff session's official bars are fetched and the KSE-100
close is banked. It writes the newest 10 completed sessions:

    {"source": "...", "sessions": {"2026-10-19": {"kse100": 165966.09,
                                                  "stocks": {"PRL": [open, high, low, close, volume, ldcp], ...}}}}

* Stocks: every symbol in PSX's mkt_summary download that traded that day (the same file and guards the engine banks
  from). `ldcp` is PSX's previous close, which lets the consumer detect a bonus/split/rights ex-date.
* `kse100`: the official close from the closing-rates PDF (`daily_eod`); null until banked. Consumers must wait.
* Deterministic content (no run timestamps), staged by engine.yml, evening.yml and recovery-last-close.yml.
* A record only: the engine never reads it back and it never touches `daily_ohlc` or any decision input.

## What the paper trader does with it

See `README.md` on the `paper-trading` branch. In short, each session is finalised once from the official bars:
price-adjustment guard, fills at the official open, stops/time stop/trail on the official bar, then gates, scan and
next-open orders. It writes `state/status.json`, which the dashboard's Trading desk shows as a separate, zero-weight
"Market turn check (paper test)" panel.

Measured on 2026-10-19: the TradingView history the test was seeded from matches PSX's official bars to 0.01 for
7,538 of 7,660 overlapping bars (60 engine symbols since July); the 122 that differ are four stocks (CLOV, STL,
FPRM, ITANZ) whose bonus/rights issues TradingView back-adjusts. Cash dividends are not adjusted by either source.
