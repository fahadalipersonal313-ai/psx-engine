# Combined research contract v1

The original versioned technical strategy remains separate. New research is experimental decision support, not a probability, order service, calibrated prediction, or demonstrated edge.

## Runtime and deployment

- Live user-facing app: `https://psx-engine.streamlit.app`, repository `fahadalipersonal313-ai/psx-dashboard`, branch `main`, `dashboard.py`.
- The separate `psx-engine` repository owns source on `main`, data on `runtime-state`, and model context on `research-state`.
- Approved research universe: PRL, MEBL, SYS, PSO, GAL, EFERT, ATRL, NRL, ASL, FCL, FCEPL, CNERGY, THCCL, FABL, OGDC. Existing 60-stock technical strategy is unchanged.
- One authorized model-context writer updates only `research-state:research_context.json`, using its current blob SHA and refusing a race rather than overwriting another writer.
- Validate before writing: `python research_contract.py research_context.json`. Read back and revalidate after publication.
- Source updates must not write SQLite. Engine/recovery/evening writers share `psx-engine` concurrency and publish data only to `runtime-state`, through the conflict-refusing publication helper.
- The existing engine loop targets 15-minute start-to-start snapshots. Model research targets 30-minute scheduled reviews. Neither GitHub nor assistant scheduling guarantees exact latency; the UI fails closed at read time.

## JSON shape

Top-level: `schema_version: 1`, `generated_at`, `as_of`, `expires_at` (aware ISO timestamps), `universe` (exact 15 symbols), `sources`, `market_context`, `stocks`.

Source: `id`, `title`, `url` (public HTTP/S, no credentials), `kind`, `published_at` (aware ISO or null if genuinely unknown), `verified_at` (aware ISO). All references resolve to source IDs; unknown publication time must never be presented as fresh publication. A fetched date does not revise an old event's date.

Evidence object: `status` (`available`, `unavailable`, or `no_material_news`), `summary`, `bias` (`supportive`, `mixed`, `adverse`, `unknown`), `source_ids`. Available evidence requires a source verified within one hour of the declared research as-of. Fundamentals instead reference sources verified around their preserved monthly reviewed_at (24-hour allowance), so a fresh news review does not force a new financial-report review. A no-material-news conclusion is permitted only for news, requires a checked coverage source, and cannot carry supportive bias. Missing evidence is not neutral evidence.

Market context: evidence objects plus `category` (`macro`, `geopolitical`, `sector`). Global vetoes apply only to macro/geopolitical observations; stock sector context is scoped to each stock.

Stock: `symbol`, `thesis`, `countercase`, evidence objects `news`, `sector`, `fundamentals`, `public_sentiment`, and `horizons` (`intraday`, `swing`, `investment`). Horizon: `stance` (`watch`, `supportive`, `cautious`, `avoid`, `unavailable`), `rationale`, `source_ids`.

Fundamentals additionally require `report_period`, `reviewed_at`, `next_review_at`, `event_review_required` (boolean), `event_triggers` (list). Available fundamentals require a report period and next review within 31 days. Refresh at least monthly and after sourced results, distributions, corporate actions, financing changes, material guidance, material regulations or similar issuer/sector events. Explain event impact and label inference. Do not treat an old ratio retrieval date as a current audited financial period.

Optional `fundamentals.events` contains sourced `{kind, date, known_at, source_ids}`; kind is earnings/agm/dividend/corporate_action, date is YYYY-MM-DD, known_at is an aware ISO timestamp. Known earnings within five calendar days and corporate actions within one day block new combined entries. Unknown event dates are not invented.

A review can remain displayed after expiry, but cannot enable an entry. Context expires within at most 72 hours; intraday review must additionally be at most 60 minutes old. The weekend baseline must be reviewed again before Monday intraday use. Public sentiment needs independent attributable public evidence and sample/duplication caveats; news headlines alone are not an independent social signal.

## Market observations and gates

Public PSX company pages are a delayed REG snapshot fallback while legacy tick endpoints return 404. The source quote-update timestamp is preserved as `source_as_of`, separate from `fetched_at`. DPS declares a nominal five-minute delay, not a guaranteed maximum lag. FUT/CSF/ODL rows are excluded. Regular-session cumulative volume must never be treated as per-tick volume.

Snapshots start warming up, require distinct increasing source timestamps, and compare only the same trading segment. Friday lunch is a boundary. No tick tape or intraday OHLC is synthesized. The snapshot watch uses an explicitly experimental 10,000-share cumulative-volume increment, not fabricated PKR turnover or a same-time volume baseline. Reference swing levels require latest completed-session official history, a versioned input hash, a current source/action/session audit, correct level ordering, and acceptable research risk. Known unresolved actions and market-wide session coverage holes withhold new research levels. An independent dated Aug-Dec2026 exchange calendar cross-checks the market-wide banked manifest and catches jointly missing stock/index sessions. It uses the revised Aug26 EidMilad closure, not the obsolete provisional Aug25 entry. Dates outside the covered feature-window range fail closed; later exceptional closure notices must still update the manifest.

During trading hours, the quote must be current-session, at most 20 minutes old, not future-dated, within the validated entry zone, above the stop and below target, with gross target-1 reward/risk at least 2 using the observed quote. Costs, gap/circuit limits, spread and order availability remain unverified; these are plans for review, not executable guarantees. Long-term numeric valuation targets are withheld because no separately validated valuation model exists.

## Prospective records

`python research_runtime.py --quotes-only` refreshes quotes/history. `python research_runtime.py` writes `research_status.json` and immutable `research_decisions/YYYY-MM-DD/HHMMSS-id.json` checkpoints, with full input evidence and SHA256 digests, exact statuses and frozen levels. The original technical backtest cohort is not pooled with combined research.

The initial implementation records observations/candidates only. It does not assume a position was entered. Outcomes stay pending execution evidence, costs are unspecified, and same-bar stop/target conflicts are unresolved without sequencing evidence. No success rate is calculated. A separately verified forward evaluator and explicit cost/execution assumptions are required before performance claims.

No credentials are created, account access expanded, app audience changed, or orders placed. Preserve data-source licensing restrictions and do not assume publicly readable quotes authorize wider redistribution.

## Calendar and artifact maintenance

Review the 2027 exchange calendar by 2026-12-01. The current manifest ends 2026-12-31, and uncovered feature windows fail closed rather than inventing January session coverage. `research_status.json` surfaces this maintenance date. Reconcile new official exceptional-closure notices promptly. Keep each model artifact under 256 KB by removing unreferenced old news sources; retain sources needed by still-current financial reviews. Do not duplicate headlines by alternate URLs or count syndicated copies as independent evidence.
