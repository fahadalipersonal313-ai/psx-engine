# Kickoff, publication and momentum review

## Verified findings

- Morning kickoff ran at 09:32 PKT, then failed on the next cycle at 09:48 after another writer changed news_raw_24h.json. Evidence: GitHub job 103858099951 logs, fetched through github_fetch_workflow_job_logs; main commits b933e56 and 88d03fc (`git log --oneline`). This was a publication conflict, not failure to launch.
- The same job logged a Gmail 535 authentication error. It did not stop signal generation. Credentials were not read or changed.
- Claude's 8a4f505 dashboard change distinguishes engine heartbeat from completed-session age. Retained: `git show 8a4f505 --stat` and reviewed dashboard diff. Earlier prices during a live session remain the daily strategy contract.
- Old momentum.detect used daily_ohlc only, and main banked completed bars only. Thus its earlier-session date was truthful but could not answer what is moving now (`rg -n 'burst|market_watch|intraday' main.py momentum.py dashboard.py`).
- news.yml still used a side-selecting rebase and could finish successfully after failed pushes. Replaced with the shared checked publisher (`rg -n 'push|pull|concurrency|cron' .github/workflows`).
- Signal publication digest omitted price, rule identity and decision session; the unchanged-signal path could indefinitely withhold newly graded database outcomes. Added digest fields and hourly checkpoints.

## Changes

1. runtime_publish.py: normal push then plain rebase; only raw-news conflicts are automatically merged. Headline union uses URL+symbol, newest duplicate and newest window. Database, code and ratings conflicts remain visible errors. Engine, news and evening workflows use it; Claude should use it too.
2. intraday_momentum.py: separate current-session Watch panel and small JSON snapshot. Reads official timestamped trades, keeps prior verified bars read-only, rejects previous-day/future/stale trades and thin liquidity. No live volume extrapolation or historical success-rate claim. Updates with engine cycles, approximately every 15 minutes. Old momentum is labelled completed-session momentum.
3. engine_watchdog.py + watchdog.yml: checks on worker completion and at UTC minutes 07/27/47 between 03:00 and 11:59 weekdays. Starts only a missing worker during the calendar window; suppresses duplicate workers and caps repeated starts. Existing morning backup kicks remain.
4. Engine starts from current main, bounds network/engine steps and publishes the database hourly even if labels do not change. Raw news stays independent of Claude ratings. Timing offsets alone cannot prevent variable-duration jobs overlapping; content-aware conflict handling addresses the observed race.

## Validation and limits

- Official source probe: PSO /timeseries/int returned HTTP 200, 1,896 rows; newest observed timestamp 2026-09-14 10:48:38 UTC. Certificate verification retained using the Windows trust store. Collector probe reached 60/60 symbols without request failures and returned zero qualifying candidates.
- test_runtime_recovery.py tests stale/future/previous-session data, bad history, ineligible stocks, volume, watchdog bounds, headline union, and an actual two-clone Git race. The raw-news race merges; database conflict aborts without losing either writer's committed data.
- Full unittest discovery: 109 tests passed. Python/YAML syntax, git diff checks, unchanged historical database/portfolio, and isolated Streamlit momentum panel rendering passed. Fixed an existing news ingestion test whose hard-coded dates had fallen outside its 72-hour query window.
- No strategy thresholds or completed-session execution rules changed; no backtest measurements recomputed. Software checks do not establish trading profitability.
- Not verified: future GitHub scheduling punctuality, external Claude scheduler reliability, repaired SMTP credentials, or intraday predictive performance. No claim that every future kickoff is guaranteed. Missing/stale current-session captures are shown explicitly.

Sources: [failed worker](https://github.com/fahadalipersonal313-ai/psx-engine/actions/runs/34806072491), [PSX market watch](https://dps.psx.com.pk/market-watch), [PSX trading hours](https://www.psx.com.pk/psx/exchange/general/trading-hours).
