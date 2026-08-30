# News Operations

This repository deliberately separates raw-news collection from AI analysis.
The old `news_signals.json` / 20%-sentiment description is retired.

## 1. GitHub Actions: raw-news collector

`.github/workflows/news.yml` starts at `:05` every hour on weekdays. Its
session guard permits work from 09:00–15:30 PKT Monday–Thursday and
09:00–16:30 PKT Friday.

It fetches the previous 24 hours of approved publisher news and commits
`news_raw_24h.json`.

If GitHub has an `ANTHROPIC_API_KEY` secret, the workflow also extracts article
bodies and runs `news_claude.py`. If the secret is absent, that is intentional:
the raw-news collection remains green and Claude Routine 2 owns the later
article-reading and rating stages.

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
neutral. Company news can adjust the technical base by up to 8 points; sector
news by up to 4 points.

## 3. PSX engine loop

`.github/workflows/engine.yml` runs market analysis every 15 minutes during the
PSX session. It reads valid current-session ratings but does not fetch or rate
news itself. It commits `psx_engine.db`, which drives the dashboard, reports,
and portfolio view.

## Operational rule

Use one AI-rating owner per run:

- With no GitHub `ANTHROPIC_API_KEY`, Claude Routine 2 owns ratings.
- If that secret is deliberately added, disable Claude Routine 2 first; GitHub
  can then own collection, body extraction, and ratings in one runner.
