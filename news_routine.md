# News Operations

This repository deliberately separates raw-news collection from AI analysis.
The old `news_signals.json` / 20%-sentiment description is retired.

## 1. GitHub Actions: raw-news collector

`.github/workflows/news.yml` starts at `:05` every hour on weekdays. Its
session guard permits work from 09:00–15:30 PKT Monday–Thursday and
09:00–16:30 PKT Friday.

It fetches the previous 24 hours of approved publisher news and commits
`news_raw_24h.json`.

GitHub performs no AI call and does not read article bodies. Claude Routine 2
is the sole owner of article reading and ratings.

## 2. Claude Routine 2: article reader and AI rater

Schedule it at:

```
35 4-10 * * 1-5
```

This is 09:35 through 15:35 PKT, Monday–Friday, where the scheduler uses UTC.
It runs 30 minutes after GitHub's `:05` collector start, so the two do not race.

Routine 2 must:

1. Pull and read the newest committed `news_raw_24h.json`.
2. Stop without writing if it is stale, malformed, or empty.
3. Fetch/read every linked approved-publisher article where available.
4. Treat an unavailable body as headline-only evidence, never invented text.
5. Match company evidence only through the real company anchors, and sector
   evidence only through configured sector anchors.
6. Write **only** `news_ai_ratings.json`.
7. Commit/push only that ratings file after schema validation.

Routine 2 must not run `news_fetcher.py`, modify `news_raw_24h.json`, dispatch
`news.yml`, or alter `.engine-kick`.

## Rating contract

Every rating must include a permitted rating, `causality`, numeric confidence
from 0.0–1.0, a permitted horizon, concise evidence-bound reason, source URLs,
and source publication timestamps. The engine accepts ratings only when they
are fresh, valid, sourced, and published in the current session. Noise is
neutral.

**News carries 0% score weight.** `config.WEIGHTS` sets `macro_news` and
`sentiment` to 0.0, so no rating moves a signal. Ratings are displayed for
manual cross-verification and are graded after the fact; they are not an input.

## 2b. News memory — reading a story, not a headline

A story is rarely one event: a merger clears one regulator, then another, then
completes or collapses. `news_ai_ratings.json` is **overwritten every run**, so
`news_memory.py` banks each read permanently in the `news_memory` table before
the next one lands. `main.py full_run` calls `remember()` then `grade()` on
every cycle; both are wrapped, because a record must never cost a run.

Routine 2 must, between steps 4 and 5:

  4b. Run `python main.py newsmem` (or `newsmem <SYMBOL>`) and read the prior
      reads for every symbol it is about to rate. Analyse the fresh item **in
      line with that history**: is this a new story, the next stage of a running
      one, or a restatement of something already rated and already priced?
  4c. Say so in `reason` when a read continues an earlier one, and set
      `thread_key` to a short stable slug (e.g. `ftmm-treet-merger`) shared with
      the earlier reads on that story.

Nothing infers threading from text. Clustering headlines on shared words invents
links that are not there, and a wrong link is worse than none — so `thread_key`
is written **only** by the rater, which can actually judge relatedness, and an
empty history is reported as empty rather than padded.

Grading is descriptive: `outcome_1d/3d/5d/10d/20d` are excess returns over the
same-day cross-sectional median of `config.STOCKS`, so a positive call during a
market-wide rally is not counted as a correct one. `python main.py newsmem grade`
prints the current accuracy buckets. These figures are evidence for later
calibration, not a score input, and stay uncalibrated until a frozen prospective
cohort has enough independently resolved reads.

## 3. PSX engine loop

`.github/workflows/engine.yml` runs market analysis every 15 minutes during the
PSX session. It reads valid current-session ratings but does not fetch or rate
news itself. It commits `psx_engine.db`, which drives the dashboard, reports,
and portfolio view.

## Operational rule

Claude Routine 2 is the only AI-rating owner. Do not add or use API secrets in
this workflow.
