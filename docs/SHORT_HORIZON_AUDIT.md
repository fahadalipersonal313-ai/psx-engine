# Audit and integration — 20 September 2026

## Evidence and scope

The supplied analysis is preserved byte-for-byte in `analysis/baselines/2026-09-18/original.zip`; its manifest records individual SHA-256 hashes. Source citations below refer to files inside that archive. The preservation/audit command actually run was:

`python tools/audit_short_horizon.py C:/Users/hp/Documents/Codex/2026-09-20/oi analysis/baselines/2026-09-18`

It read the supplied JSON datasets and workbook cell XML, and preserved the scripts, inspection output, CSV and previews. Results: 50 unique tickers; no price-outside-range failures; 4,984 workbook cells; 550 formulas; zero cached error cells; seven annual/TTM direction conflicts. This is not independent spreadsheet recalculation. See the manifest and `tools/audit_short_horizon.py:18`.

## What was sound

- The original was conditional research: 2 momentum, 30 confirmation, 17 reversal and 1 overextended. MFL and NETSOL were the momentum names, both with ADX below 20. Reproduced from `work/final-data.json` by the audit command; results saved in the manifest.
- The workbook disclosed the September 18 price session, approximate displayed units, imperfect announcement coverage and non-guaranteed reference levels. It warned that annual and trailing financial periods differ (`work/build.mjs:39`, `work/build.mjs:49`).
- CPHL was an analyst precaution, not a proven official Shariah exclusion. The new settings preserve that distinction (`short_horizon_evidence.json:6`).

## Material weaknesses and corrections

|Finding|Evidence|Correction|
|---|---|---|
|Selection preceded final news/risk enrichment; the final order was not a uniform assessment of all 113 eligible names.|`work/screen.mjs:9`; `work/prepare.mjs:60`|Calculate the same features for the full refreshed eligible universe, then select the display rows (`short_horizon.py:177`). News coverage remains explicitly staged and incomplete.|
|Summary technical ratings were scored alongside their underlying trend/momentum indicators.|`work/screen.mjs:8`|Four disclosed technical dimensions, no provider Buy/Sell rating points (`short_horizon.py:138`). Indicators remain correlated; weights are not validated.|
|JavaScript comparisons can treat null as zero; missing inputs could influence scoring or penalties.|`work/screen.mjs:8`; `work/prepare.mjs:62`|Explicit missing/finite checks; incomplete required indicators block a candidate (`short_horizon.py:18`, `short_horizon.py:138`). No affected historical row is asserted without a row-level proof.|
|Momentum classification did not require adequate ADX.|`work/prepare.mjs:61`; manifest weak_trend_candidates|Trend-strength gate; MFL and NETSOL now need confirmation. See generated comparison.|
|Slow annual and trailing growth were mixed into short-horizon points.|`work/screen.mjs:8`; `work/prepare.mjs:60`|Separate labelled financial context, no earnings points (`short_horizon.py:77`). Seven conflicts: MFL, NETSOL, MWMP, HTL, FABL, QTECH, GGGL (manifest).|
|Fixed company-specific news bonuses could outlive their event or overstate attributable economics.|`work/prepare.mjs:1` through its 50-entry assessment object; final newsPoints fields|Dated evidence with publication, known-at, expiry, exact symbol, source, quality and event status (`short_horizon.py:89`; `short_horizon_refresh.py:62`). No fixed news points.|
|Original reference combined a one-session high and moving averages, with zero substitution for missing averages.|`work/prepare.mjs:64`|Actual five-session high/low, labelled observation references, no claimed support/target/guaranteed stop (`short_horizon.py:116`).|
|Rounded display numbers could change threshold decisions; index separators were removed by the existing generic parser.|`psx_market_watch.py:52`; live screener adapter test|Read PSX machine numbers and preserve index separators, retaining exact share-class symbols (`short_horizon_refresh.py:42`; `test_short_horizon.py`).|

## News conclusions: distinguish captures from new verification

All 50 original assessments were reviewed in `work/prepare.mjs` and preserved in `work/final-data.json`. They are historical research statements, not newly verified facts. In particular, signing versus closing (EPCL), pending restructuring terms (THCCL), gross versus attributable gas (MARI/OGDC), unquantified distribution revenue (MTL), parent versus subsidiary identity (NETSOL), ordinary versus preference shares (ASL/ASLPS), and warnings/resignations versus operating catalysts (POWER/ECOP) must remain distinct. None earns a new automatic catalyst bonus.

CNERGY's September 24 meeting, EFERT's planned maintenance/restart, HTL's unresolved outcome, GCIL's rights terms and CPHL's business-scope resolution still require original-document/event-outcome review. Old notices are not treated as cleared risks. Primary PDFs were not fully verified in this implementation; the user requested a faster finish. Existing news desk ratings remain dated supporting context, not certified direct evidence.

## Temporal integrity

The new pure builder rejects future/incomplete market sessions, filters future bars, checks membership observation age/effective date, and accepts news only after publication **and** reviewer-known time. Date-only publication becomes usable at the end of that Pakistan day. Verified corporate-action terms must be known by the cutoff. Tests exercise future bars, future reviews, date-only publication, expiry and unresolved adjustments (`test_short_horizon.py`).

This is a present-time review using the latest completed daily session. September 20 membership or news must not be presented as something a September 18 trading decision knew. Frozen inputs retain both clocks. Historical membership effective dates and complete point-in-time news archives are unavailable, so this method is explicitly **unvalidated**, with no retrospective return claims. Existing §5 engine measurements were not recomputed or reinterpreted.

## Actual refreshed sample

Command run: `python short_horizon_refresh.py`. Official source: https://dps.psx.com.pk/screener/; existing whole-market PSX historical provider; production database opened read-only. Exact timestamps, source hashes, fetched/cached dates and source-qualified bars are in `short_horizon_inputs.json`. Prices end September 18; review is September 20, not live intraday trading.

137 stocks pass the initial index/price/size/average-volume gates. All receive the same technical assessment before choosing 50 displayed rows. The 50 contain 11 confirmation, 38 reversal and 1 overextended; no momentum candidates. Across the full 137, 23 fail current liquidity requirements and four are blocked: NNAR/SOYASUP missing history; SRVI/STL unexplained price jumps. These counts were queried from `short_horizon_latest.json`; regenerate with `python tools/compare_short_horizon.py`.

See `SHORT_HORIZON_COMPARISON.md` for all 50 original names and the generated CSV under `analysis/short_horizon_sample.csv`. The wider universe, different data definitions and new gates explain rank changes; this is not evidence of higher returns.

## Integration and limits

The existing full engine run calls this research refresh; its fast opening run skips it (`main.py:323`). The existing workflow publishes its separate text snapshots (`.github/workflows/engine.yml:195`). The dashboard adds a collapsible plain-language view (`dashboard.py:638`). Existing swing scoring and portfolio execution are unchanged. No external job was created, no trade placed and no public deployment performed.

The model uses 42 sessions, so EMA/RSI/ADX values can differ from a provider with longer initialization. Daily money flow is a closing-price/volume proxy, not proof of institutional accumulation. No current spread, order-book depth, intraday entry or executable fill is verified. Financial statements and P/E denominator periods are not newly reconciled; unavailable periods remain unknown. The exchange calendar depends on existing configured holidays and benchmark history.

Validation: `python -m unittest discover -q` passed 133 tests, including 14 new research tests; focused tests passed after numeric-parsing correction. Compilation and whitespace checks are run separately. Production database/portfolio diffs were empty. UI browser appearance and hosted deployment were not checked in this local task.
