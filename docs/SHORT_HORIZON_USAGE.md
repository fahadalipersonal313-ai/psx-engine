# Refresh the 1–5-day research view

This adds a research panel to the existing engine. It does not change Buy/Strong Buy scoring or execute orders. The method is experimental, not backtested or a profit forecast.

## Refresh and reproduce

From the repository root:

```
python short_horizon_refresh.py
python tools/compare_short_horizon.py
python short_horizon_refresh.py --replay short_horizon_inputs.json
python -m unittest test_short_horizon -v
```

Normal `python main.py run` refreshes after the existing engine. `--fast` skips this addition to protect opening-run speed. The existing workflow stages its inputs, report and status files. These changes are local until reviewed and published; no extra scheduler is needed or created.

Inputs include the exact settings, completed session, official universe observation, bars, adjustment records and news evidence. Their SHA-256 identifies a reproducible calculation. Replay requires no network and writes to `reports_out/short_horizon_replay.json`. Core rows reproduce exactly; changes against a previous report depend on that previous report. Normal refresh also saves input/report pairs by hash under `reports_out/short_horizon_snapshots`; Git retains published versions. Do not overwrite the preserved baseline archive.

`short_horizon_latest.json` contains the selected rows, every eligible row, exclusions and previous-snapshot changes. `short_horizon_status.json` records refresh failure separately so old output cannot silently appear fresh. CSV is available in the panel and `reports_out/short_horizon.csv`; the committed sample is `analysis/short_horizon_sample.csv`.

## Settings

Edit `short_horizon_config.json`; change its method version for a material rule change. Default: 42 completed sessions, up to 50 displayed names, PKR5 minimum price, PKR1bn company value, 100,000 average shares, 25,000 latest shares, PKR5m median daily trading value. Trend strength must reach 20; RSI above 75 or price more than two daily-range units above its average is extended. Settings are assumptions, not optimized thresholds.

Scores comprise trend 30, momentum 30, participation 25 and trend strength 15. Labels additionally require valid data, liquidity, risk checks and reviewed direct news/event evidence. A high score can still be a reversal or overextended watch. Data/illiquidity failures sort last. No bullish quota is filled.

Prices are PKR/share; volume is shares; market capitalization/turnover are PKR; percentage values are percentage points. P/E is the official displayed value with an unconfirmed denominator period. Financial context from the supplied snapshot is dated, separate and unweighted.

## Evidence maintenance

The two existing news-review files feed supporting context automatically. Their source/publication gaps remain visible. They do not automatically certify full primary-document review. Add reviewed items to `short_horizon_evidence.json`, for example:

```json
{
  "symbol": "EXACT_TICKER",
  "assessment": "positive",
  "linkage": "direct",
  "quality": "primary-full",
  "source": "https://dps.psx.com.pk/download/document/REVIEWED_DOCUMENT.pdf",
  "published_at": "2026-09-21T10:00:00+05:00",
  "known_at": "2026-09-21T10:30:00+05:00",
  "expires_at": "2026-09-22T15:30:00+05:00",
  "event_date": "2026-09-21",
  "event_risk": "resolved",
  "rationale": "What the original document establishes, attributable economics, limits and what would require another review."
}
```

This is a schema example, not actual evidence. Use primary-full only after reading the original. Never backdate known_at. Unknown event timing/outcomes stay pending/unresolved. New adverse evidence or changed terms require reassessment before expiry. A date-only publication is conservative: usable only after the day ends. News expires at the earlier of explicit expiry and the configured maximum age. Manual analyst exclusions require a reason/source, known_at and review_by; overdue exclusions remain blocked until explicitly reviewed. CPHL's precaution is separate from official membership and exchange NC status.

## Failure behaviour

Official universe is cached six hours, usable for at most 24; a failed attempted refresh blocks recommendations even with cached rows. Daily whole-market requests are shared across stocks, paced one second apart and bounded by a 150-second refresh budget plus an in-flight request. Published inputs seed later runners. Missing history stays missing; no fabricated bars or substitutions from old exports. An initial partial run can gain coverage on the next existing cycle. The production database is never modified by this module.

The dashboard checks current completed-session date, snapshot age and last-attempt status. It marks old output historical and reports zero current candidates on failure. Calendar gaps, invalid corporate-action terms and unexplained jumps require investigation, not guessed adjustments.

Remaining work before claiming trading performance: verified point-in-time membership and announcement history, reconciled financial periods, explicit execution/cost/slippage assumptions and chronological out-of-sample evaluation. The preserved 50-stock workbook is not such an evaluation.
