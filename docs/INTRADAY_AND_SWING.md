# Separate intraday and swing analysis

The dashboard now groups live checks under **Intraday momentum** and daily calls under **Swing opportunities**. Completed-session burst information remains in a separate, labelled expander; it is never presented as today's intraday movement. The existing news desk, stock detail, history, portfolio and expanded trade cards remain accessible.

Compact view is on by default for new sessions. Its cards show the signal's time horizon, price or entry references, a short reason, entry condition, main risk, both news reviewers and data date. Full explanations, additional levels and news sources are expandable. Existing users can turn Compact view on in the sidebar. News schedules, review prompts, scoring weights and swing decisions are unchanged.

## Every-run recording

The existing collector updates every successful cycle, approximately 15 minutes apart. It now writes `intraday_observations.db` separately from the swing database, plus the existing `intraday_momentum.json` dashboard output. The existing workflow publishes the intraday archive every successful cycle, even if swing signals are unchanged. No external job is added.

- `runs`: exact capture time, rule settings and the news-review files available in that run.
- `observations`: one row per stock/run, including unchanged signals and missing-feed states.
- `sessions`: the latest observation for each stock/session; this does not replace earlier observations.
- `changes`: meaningful state transitions.
- `episodes`: distinct research setups, with immutable first qualifying observation and observed end time.

A retry with the same run timestamp/session/settings returns the saved run rather than duplicating it. A later run is retained. Out-of-order writes cannot replace a newer session summary. Records are committed transactionally, then the dashboard JSON is replaced atomically. Connections close explicitly on Windows. Collection failure prevents publication of a new success capture; the previous capture ages visibly.

## Intraday calculation

`intraday_tracking.RULES` contains versioned, experimental thresholds. The current defaults require a rise of at least 1% from the validated previous close, price above a verified opening price, at least 0.15% improvement over a fixed 15-minute window, and PKR1m traded value in that window. None of these thresholds is claimed to be profitable or optimized.

The 15-minute anchor must be no more than two minutes before the target time. Windows cannot cross Friday's break or the opening boundary. Future trades are ignored; the last trade must be at most 20 minutes old. This is a periodic observation system, not tick-by-tick execution.

The opening price comes from the existing market-watch provider and must agree within 0.1% with a current-day trade captured within two minutes of regular opening. Because that page is undated, an uncorroborated opening price stays unavailable; the first trade seen later in the day is not substituted for the official open. This strict check may leave many stocks unavailable until provider completeness is verified.

The previous close must belong to the expected previous completed session. Existing compliance checks remain applicable. A beyond-limit unexplained price change is withheld. Tick volume is interpreted using the existing intraday provider's per-observation-volume convention; a provider-schema change requires revalidation. Same-time historical volume comparisons are explicitly unavailable until enough reliable observations exist.

After two qualifying observations 10–20 minutes apart, with a genuinely newer trade in the same uninterrupted session segment, the state becomes **Momentum confirmed · watch**. A repeated update preserves the episode ID. Weakening, missing data, rule-version change, an excessive gap or a session break ends the continuing episode. Re-entry needs two new qualifying observations. A prior-day episode expires when a later session is observed. End times are observation times, not claimed trade exits.

The existing daily-volume burst can appear as an extra tag within this section; it compares volume so far with the full-day historical average and is not an estimate of normal same-time volume.

## What this does not claim

Intraday states are research watches, not new validated Buy/Strong Buy recommendations. Swing Buy/Strong Buy logic is unchanged. Fifteen-minute high/low references are observation levels, not guaranteed stop or target fills. No broker orders, account positions or hypothetical profits are created. Prices, news and observations are retained for later evaluation, but return grading, fees, slippage, executable fills and portfolio backtests are not implemented by this change. Do not count episode endings as trade exits or repeated observations as independent trades.

## Preview and checks

`python tools/build_dashboard_preview.py` generates `docs/dashboard-preview.html` using the same card renderer as the dashboard. It is an illustrative card/layout preview with fictional examples, not current PSX calls or a replica of every existing dashboard section.

Run `python -m unittest test_intraday_tracking test_intraday_review -v` for timing, opening-price, stale/future-feed, Friday-break, duplicate-run, continuation, re-entry and HTML-escaping checks. The full suite is `python -m unittest discover -q`.

The implementation remains on the isolated development branch until published. New-format intraday cards and the archive start with the first successful collector run after deployment; older JSON captures retain their explicitly labelled legacy display.
