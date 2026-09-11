# Astra re-audit — 2026-09-11

## Implementation follow-up (user authorized fixes)
- The findings below describe baseline `ff0cac5`; their line references are baseline references. Fixes are now local on `codex/audit-astra-recheck`, with no production data migration or main-branch write.
- Finding 1: corrected ten-session metric and added a separately named full-horizon metric (`swing_evaluation.metrics`).
- Finding 2: version/contract-separated cohort query (`database.cohort_summary`, used by `main`).
- Finding 3: v6 freezes suggested quantity and prior volume; order capacity no longer depends on the entry day's final volume. Locked-day fills remain unavailable. Old frozen policies keep legacy behavior (`swing_evaluation.opportunity/resolve`). Daily-bar simulation still cannot prove broker queue fills.
- Finding 4: median 20-session traded PKR is supplied by the core decision and required by risk/shortlist; absent evidence fails closed (`decision_engine`, `risk_manager`, `upward_candidates`).
- Finding 5: date-bounded, validated, action-adjusted target-time history (`target_timing.verified_history`); dashboard supplies decision date or withholds estimate.
- Finding 6: before the documented 2026-09-09 current-universe selection, database replay withholds membership and reports unknown stock-days (`swing_evaluation.backtest`, `history_view`). Earlier dated membership is still missing, not manufactured.
- Finding 7: displays actual duration and frozen planned horizon rather than a ten-day literal (`history_view`).
- Finding 8: older shortlist rows explicitly show analysis date and an older-data warning (`upward_candidates`).
- Finding 9: explicitly closes the archive read connection (`archive`); archive regression errors resolved.
- Drift: removed unused BACKTEST configuration, centralized replay window, and restricted contract hashing to decision inputs. Tests isolate engine-state writes.
- New regression coverage is in `test_astra_fixes.py`; existing execution/shortlist fixtures now supply required v6 evidence. Final `python -m unittest discover -q`: 97 tests passed in 30.637s. All 59 root Python modules compiled; `git diff --check` passed. No profitability measurements were rerun.

## Scope and corrections
- Audited fetched GitHub revision `ff0cac5`, on `codex/audit-astra-recheck`; query: `git log -1 origin/main --format="%h %ci %s"` returned `ff0cac5 2026-09-11 14:24:41 +0000 Add the Codex Astra operating brief`.
- The previous audit examined `a41252a` (September 5), not this revision. Its conclusions about current GitHub were too broad. This report supersedes them.
- Current version is v5, holding period 30 sessions (`config.py:933`, `config.py:956`); executed `print(len(config.STOCKS))` returned 60.
- Token Economy and Pakistan Stock Market Specialist instructions applied from the supplied operating brief. No §5 performance measurements were recalculated or rejected.
- Audit only: no application code, tracked database or portfolio edits; no commit or push.
- Correction: PKR turnover is not wholly unused. Repository-wide `rg -n 'MIN_TURNOVER_PKR' -g '*.py' .` finds event-library and momentum usage (`event_library.py:153`, `momentum.py:52-53,130-134`). It remains absent from core risk and top-ten qualification.
- Correction: CLI accuracy explicitly says legacy (`main.py`, search `Legacy benchmark-relative`); current historical results also exist in `history_view.py:43-73`. The earlier claim that current evaluation is absent was overstated.
- Correction: ranking qualifying stocks by score is not a demonstrated defect (`upward_candidates.py:44-45`). No measurement here proves a replacement ranking better.

## Ranked defects — severity and confidence

### 1. High / high: 10-session target metric counts later targets
- Evidence: `swing_evaluation.py:87-88` records separate time flags, but `swing_evaluation.py:101` uses all target outcomes for `target_by_10_pct`.
- Scenario: a target first reached on day 20 contributes to the supposed ten-day success rate under v5's 30-session horizon.
- Executed probe: `swing_evaluation.metrics([dict(status='target',net_return_pct=1,target_by_5=False,target_by_10=False)])` returned `target_by_10_pct: 100.0`.
- Smallest fix: aggregate the stored `target_by_10` flag; distinguish horizon-wide target success; add a late-target regression case. This changes reporting, not frozen trades.

### 2. High / high: cohort report combines different strategy versions
- Evidence: `main.py:543` groups all `cohort_outcomes` only by status; it does not join the candidate's version or contract.
- Executed read-only SQL: `select k.version,x.status,count(*) from cohort_candidates k join cohort_outcomes x on x.candidate_id=k.id group by k.version,x.status`.
- Result: v3 includes 12 stops; v4 includes 54 stops and 1 target; v5 includes 3 stops and 22 pending. Other v3/v4 statuses also exist.
- Scenario: the command presents a combined status count even though the brief prohibits pooling v4 and v5.
- Smallest fix: join candidates, group by version and config hash, and print separate cohorts. Preserve all stored outcomes.

### 3. High / high: execution at the open depends on end-of-day information
- Evidence: `swing_evaluation.py:62-70` uses that session's full high, low and volume to accept/reject an opening fill; `swing_evaluation.py:20` fixes quantity at one share.
- Scenario: an opening order is accepted or rejected using volume that was not known at that opening. This is execution-model hindsight, although it does not leak future prices into signal features.
- Executed v4 probe, on resolver logic unchanged in v5 except the horizon cap: with identical OHLC and 1% participation, volume 99 yielded `unfilled`; volume 100 yielded `target` for a one-share order. `git diff a41252a HEAD -- swing_evaluation.py` confirms the entry logic is unchanged.
- Smallest fix: base opening-order size eligibility on prior completed-session liquidity and actual intended quantity. If intraday fill evidence is unavailable, label the fill uncertain rather than claiming it was known at the opening. Any execution-policy change requires a new version.
- Limit: daily volume can be a retrospective capacity approximation; this probe does not measure the direction or size of its performance bias and does not invalidate every §5 number by itself.

### 4. High / high: PKR liquidity gate does not protect the core shortlist
- Evidence: `risk_manager.py:68-73` and `upward_candidates.py:18` use share volume. Their unchanged code has no PKR turnover gate; momentum has one (`momentum.py:130-134`).
- Scenario: a low-price stock with enough shares traded but insufficient traded money can qualify for the core shortlist.
- Smallest fix: apply one shared median-20-session PKR turnover gate to entry and actionable shortlist paths; leave low-liquidity research rows visibly labelled. Freeze the changed rule under a new contract.
- The one-share opportunity size also means the evaluator does not validate practical position capacity (`swing_evaluation.py:20,68`).

### 5. High / high: time-to-target bypasses validated price history
- Evidence: `target_timing.py:60-66` reads raw history directly; `database.py:652-660` returns raw OHLC without validity or action adjustment. `_atr` and target-touch calculations operate on those rows (`target_timing.py:38-54,75-84`).
- Executed read-only SQL: `select count(*) from daily_ohlc where close<low or close>high` returned 7.
- Scenario: invalid historical bars or unadjusted share actions can influence displayed hit rates/timeframes although core decisions reject or adjust those inputs (`decision_engine.py:60-66,106-110`).
- Smallest fix: use a shared verified, action-aware history view with an explicit cutoff; report unavailable estimates when required evidence is missing.
- Additional timing limit: `estimate` has no decision-date argument and reads latest bars (`target_timing.py:88-109`); the card passes only symbol, price and target (`dashboard.py:785`). A carried older decision can therefore display an estimate incorporating later data. This is a presentation timing risk, not demonstrated signal-price leakage.
- No affected symbol's estimate was recalculated; the numerical impact is not verified.

### 6. Medium / high: historical universe is selected with hindsight
- Evidence: current eligibility is passed once across replay (`swing_evaluation.py:151-158`), and portfolio replay uses current `config.STOCKS` (`swing_evaluation.py:161-162`).
- `config.py:109-119` documents additions chosen after backfill using history availability, liquidity and ranking; `CLAUDE.md:20` confirms the dated selection.
- Scenario: old results for this selected universe are treated as an unbiased test of what the engine could have selected then.
- Smallest fix: retain the current-universe warning and use dated eligibility/universe membership for point-in-time claims; assess the frozen cohort prospectively. Do not invent historical membership.
- No claim that the supplied §5 measurements were computed incorrectly; their selection bias is not quantified here.

### 7. Medium / high: historical screen still describes a ten-day exit
- Evidence: `history_view.py:5` labels expiry as "Sold after 10 trading days"; line 60 repeats the ten-day limit despite `config.py:956` selecting 30.
- Scenario: a v5 expiry is explained as a ten-day sale.
- Smallest fix: render the trade's frozen horizon/actual duration; separate descriptions when contracts differ.

### 8. Medium / high: shortlist can silently fall back to arbitrarily old decisions
- Evidence: `upward_candidates.py:35-40` falls back to `MAX(session)` with no freshness limit; returned fields omit that session (`upward_candidates.py:46-50`).
- Scenario: an ingestion failure is treated like a closure and an old shortlist appears current.
- Smallest fix: return/display the analysis date and explicitly mark stale fallback; distinguish verified exchange closures from missing ingestion.

### 9. Medium / high: archive read connection is not closed explicitly
- Evidence: `archive.py:168-169` opens an anonymous SQLite connection and discards it without closing it.
- Repeated 85-test run: zero assertion failures, three errors in `ArchiveDurability.test_a_snapshot_still_referenced_is_never_purged`, `test_export_verify_purge_restore_round_trip`, and `test_unreferenced_snapshots_are_archived_not_stranded`; all were `WinError 32` removing temporary `a.db` files.
- Smallest fix: explicitly close that connection in a `finally` block, then rerun archive tests. The exact attribution of every locked handle requires that follow-up; no archive data loss was demonstrated.

## Signal integrity and execution limits
- PSO path: `main.analyze_stock` supplies completed bars to `decision_engine.decide`; symbol-independent validation trims future dates (`decision_engine.py:41-69`), requires aligned stock/index sessions (`98-105`), adjusts known actions (`106-107`; `corporate_actions.py:123-133`), then calculates indicators, risk and signals (`120-131`). These four core modules are unchanged between audited revisions (executed `git diff a41252a HEAD -- decision_engine.py risk_manager.py corporate_actions.py signal_generator.py`, empty output).
- Missing/bad inputs become explicit `No data` through the exception path (`decision_engine.py:84-89,133-135`); this is not a valid Buy with guessed prices.
- No direct future-price feature leakage found in this core path. This limited conclusion does not clear execution hindsight or auxiliary presentation timing described above.
- Next-session entry, stop-first ambiguity and adverse opening gaps are implemented (`swing_evaluation.py:42,66-86`). Flat-range/zero-volume bars are rejected or left unresolved (`63-64`).
- A non-flat daily candle does not establish that an order could fill at a circuit boundary: the resolver uses OHLC, not order queues (`swing_evaluation.py:62-86`). Actual circuit-day fillability remains unverified.
- Frozen execution policy comes from the decision snapshot (`swing_evaluation.py:19`). The cohort-report pooling defect is reporting, not evidence that stored horizons are overwritten.

## Configuration drift
- `BACKTEST` documents 250-day and out-of-sample settings (`config.py`, search `BACKTEST =`), while active replay defaults to 21 (`swing_evaluation.py:108,151-158`). Treat this as stale configuration/documentation, not proof that a one-month default is wrong.
- `decision_engine.contract` hashes serializable uppercase config broadly (`decision_engine.py:23-38`), including unrelated settings. `upward_candidates.py:27-28,41-42` requires an exact hash: changing unrelated hashed settings can hide prior decisions. Smallest fix: explicit versioned contract inputs, preserving historical hashes.
- No complete dead-function inventory was performed; absence from a small search is not proof of dead code.

## Validation and not verified
- Original v4 checkout: `python -m unittest discover -q` passed 46 tests. This does not validate v5.
- Latest v5 checkout: same command ran 85 tests and failed with 3 errors; concise rerun confirmed the three archive cleanup errors listed above. Tests also changed `.engine-state.json` in this isolated checkout; that test-generated change was restored to HEAD.
- Compilation: compiled each root Python source in memory with `compile(...)`; all 58 passed.
- §5 profitability, horizon grids, time-to-target tables and backfill measurements were not rerun.
- No exhaustive security audit, live PSX source verification, broker fill test, or restored-backup drill was performed.
- Findings apply to pinned `ff0cac5`; later engine pushes are outside this snapshot.
