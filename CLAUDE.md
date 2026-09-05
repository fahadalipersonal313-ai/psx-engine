# PSX Shariah Engine — Working Memory

A Shariah-compliant PSX (Pakistan Stock Exchange) equity analysis engine. KMI-30
focus, with a broader KMI All-Share universe.

## Hard rules (NEVER violate)
- **Never fabricate data.** Shariah status, news, earnings dates, prices, OHLC,
  benchmark moves — all sourced from real data or explicitly labelled
  unavailable. Missing data stays NULL, never a synthesized value.
- **No protection bypass.** Public PSX DPS endpoints + public RSS only.
- **No backwards-compat shims, no dead code, minimal comments.** Comment only
  the non-obvious WHY.
- **Manual confirmation required before any trade** — this is decision support,
  not auto-trading.

## News: auto-fetched, UNSCORED window (2026-07-15)

News carries **0% score weight**. The `news.yml` workflow now runs on a
**weekday-morning cron** (09:05 / 09:35 / 11:05 PKT, staggered) — no manual
prompt needed — and commits `news_raw_24h.json`. The dashboard reads that raw
file via `news_feed.raw_headlines(sym)` and shows the last-24h headlines per
stock as an **unscored window for manual cross-verification** (Watchlist "Full
detail" expander + Stock detail tab). `news_feed.raw_headlines` filters to
credible desks by publisher NAME (`config.NEWS_DISPLAY_PUBLISHERS`) because the
fetch-time host allowlist is bypassed by Google News redirect links (every link
is `news.google.com`, so off-desk publishers leak into the raw file). The
LLM-judged `news_signals.json` routine below is now OPTIONAL — only relevant if
news weights are ever restored.

**Relevance-anchor gate (2026-07-15):** Google News RSS token-matches the
company query loosely, so a *"National Foods expands in UAE"* headline matched
NRL's *"National Refinery"* query and got attributed to (and GLM-rated as) NRL
— a cross-company mis-attribution. `config.COMPANY_NEWS_ANCHORS` now holds a
distinctive name phrase per symbol and `config.headline_matches_company()`
(word-boundary matched, flexible whitespace) gates every headline. Applied at
BOTH fetch time (`news_fetcher.fetch_for_symbol`) AND read time
(`news_feed.raw_headlines`, which GLM consumes) so already-committed raw files
are cleaned without a re-fetch. Ambiguous bare tickers are omitted on purpose
(NRL is also National Rugby League). Trade-off: a few ticker-only legit
headlines are missed (conservative) — correct for an UNWEIGHTED feed where
mis-attribution is the real harm. Result: raw feed went from ~209
loosely-matched items to ~8 correctly-attributed ones.

**All 5 previously-unnamed symbols now have curated anchors (2026-08-13):**
SLM `service long march`, SLGL `secure logistics`, THCCL `thatta cement`,
GHNI `ghandhara industries`, GAL `ghandhara automobiles`.
- SLGL's registered name is HYPHENATED ("Secure Logistics-Trax Group Ltd.") and
  `headline_matches_company` joins tokens with `\s+`, so a 3-word
  "secure logistics trax" anchor would NEVER match the real name. Two words
  match both the hyphenated and spaced forms.
- GHNI/GAL use TWO-word anchors because both companies share the surname
  "Ghandhara": a bare "Ghandhara" headline deliberately matches NEITHER rather
  than both. Verified across reversed pairs and an all-caps form.

**Open discrepancy — do not fix as a side effect:** `SECTORS` still maps GHNI to
"Glass/Holding" and GAL to "Textile/Synthetic Fibre", but both are automotive
assemblers. Those labels drive the sector-exposure cap in `portfolio_risk`, so
re-bucketing two symbols changes book-level risk limits and needs a deliberate
decision.

## Who rates the news (updated 2026-08-26)

The **Claude Routine** is now the primary rater, not GLM. A scheduled Routine
(`trig_01JM5xvBrJjEaDYNJSZjCNqT`, cron `0 4-10 * * 1-5`) runs in the CLOUD — not
in Actions — collects via `news_fetcher.py`, rates every symbol and sector that
has a session-window headline, and commits `news_ai_ratings.json`.
`news_feed._RATING_FILES` reads that file FIRST and falls back to
`news_glm_ratings.json`. Because it runs in the cloud it survives GitHub cron
outages: on 2026-08-27 every Actions trigger missed and the Routine still fired.

Two gotchas that cost real time:
- Its environment has its own allowed-domain list, SEPARATE from Actions.
  `mettisglobal.news` and `propakistani.pk` are still BLOCKED there, so the
  Routine's own fetch silently loses those desks (40 items vs 50 from Actions).
- `as_of` must be a real current UTC timestamp. `_load_rating_file` silently
  returns `{}` when stale, and a MISSING/malformed `as_of` bypasses the gate
  entirely and reads as fresh.

## GLM second opinion (2026-07-15, now the FALLBACK rater)

`news_glm.py` runs after the news fetch in `news.yml` (needs `GLM_API_KEY`
secret set in the repo — ZhipuAI free tier, `glm-4.5-flash`). One batched
request rates every symbol that has fresh credible headlines as
`highly_positive | positive | neutral | negative | highly_negative` and writes
`news_glm_ratings.json`. `news_feed.glm_rating(sym)` reads it. The dashboard
shows a `🤖 GLM` pill next to `📰` on each actionable-card, plus the GLM
reason, so the user can cross-check whether the LLM agrees with the engine's
Buy/Avoid. **Zero score weight** — informational only. Missing key / stale
file → pill shows `GLM: —` and nothing else changes.

**Timeout fix (2026-07-15):** `open.bigmodel.cn` is a mainland-China endpoint;
from GitHub's US runners the batched call regularly overran the old 60s read
timeout and `news_glm_ratings.json` never got written (the step is wrapped in
`|| true`, so it looked "green" while silently failing — check the step LOG,
not just its conclusion). `GLM_TIMEOUT` is now 120s (env-overridable) with ONE
retry on `Timeout`/`ConnectionError` only — an HTTP error like a 401 from a bad
key still fails fast, never retried. Confirmed live: run wrote 19 ratings.
Diagnosing key issues: a bad key = instant ~1s **401**; a slow-endpoint problem
= ~60s+ **read timeout**. Different symptoms, different fixes.

**GLM ratings live in TWO places (2026-07-15):** the per-card `🤖 GLM` pill
(actionable Buy/Exit cards only) AND a **`🤖 GLM news read` panel** on the main
page (`dashboard.py`, after the staleness banner, a **collapsed-by-default**
expander) that lists EVERY rated symbol with pill + reason, sorted
positive→negative, via `news_feed.load_glm_ratings()`. The panel exists because
actionable cards are empty in a risk-off market, which hid the second opinion
entirely — the panel always surfaces it. Still zero score weight.

## Dashboard: regime what-if toggle (2026-07-15)

**On the MAIN page (2026-07-15):** `🔀 Regime what-if` is a horizontal
`st.radio` sitting right above the Market-regime tile (moved OUT of the sidebar,
where it was buried on mobile) — `Actual | Assume risk-on | Assume risk-off`.
On each Buy/Strong Buy card it prints a one-line note of what the
signal WOULD be under the assumed regime (risk-off → soft-downgrade to Watch
via the regime gate; risk-on → holds, chase guard loosens). Approximation, not
a re-run — the stored score/vetoes drive it. Never mutates stored signals.

**Risk-on surfaces regime-gated Buys (2026-07-15):** selecting `Assume risk-on`
while the market is really risk-off now REVERSES the risk-off regime gate for
display: a `Watch` whose stored `main_reason` contains the exact phrase
`"market regime risk-off"` resurfaces as a `Buy` (never Strong Buy — the
pre-gate tier is unknown, so take the conservative one). Driven by a new
`display_signal` column that feeds the Actionable tile, Top pick, Action-today
cards + compact table; every promoted card/section is loudly labelled
what-if/verify-manually. The phrase match is exact, so confluence/chase/
earnings/rr/score-band Watches are NEVER promoted (tested). **Stored `signal`
is untouched; Portfolio heat still uses the real signals.** Caveat: the regime
gate is first in the soft-downgrade `elif` chain, so a promoted Buy may still
carry a secondary veto (poor_rr/RS) the engine never evaluated — hence the
verify-manually labels. `_display_signal()` in `dashboard.py`.

## "Run the repo news" — optional LLM-judged routine (only if weights restored)

User says **"Run the repo news"** any morning after 09:00 PKT → Claude:
1. Triggers `.github/workflows/news.yml` (workflow_dispatch on `main`) via
   `mcp__github__actions_run_trigger`. CI runs `python news_fetcher.py` which
   fetches last-24h headlines from Google News RSS per symbol (filtered to the
   allowlist) + Business Recorder / Dawn Business / Profit Pakistan Today /
   Mettis macro feeds, and commits `news_raw_24h.json`.
2. Pulls `news_raw_24h.json`, applies `news_routine.md` rules (exclude routine
   results/dividends; score 0–100; direction/materiality/confidence; sources
   from allowlist only), writes `news_signals.json`, commits + pushes.
3. Triggers `engine.yml` so the dashboard reflects fresh news-weighted signals.

**SUPERSEDED 2026-08-26 — news now MOVES the score, as bounded modifiers.**
`config.WEIGHTS` is still technical 1.0 (news is NOT blended into the weighted
sum, which would mute every Buy — measured: macro_news 0.30 dropped a technical
78 with no news to 69.6, below the 75 Buy band). Instead `scoring_engine`
applies two capped adjustments on top of the technical score:
`NEWS_SCORE_ADJUST_MAX = 8.0` (company) and `SECTOR_NEWS_SCORE_ADJUST_MAX = 4.0`
(sector), so news can move a score at most +-12 and a symbol with NO news moves
exactly 0.0 — never penalised for silence.
Damping is `50 + (base-50) x causality_mult x confidence`, causality being
causal 1.0 / correlated 0.35 / noise 0.0, so pure noise cannot move a score at
all however confident the rater was. Verified live 2026-08-26: PRL +3.0
(company+sector), NRL/ATRL +1.0 (sector only), HUBC -1.2, MARI 0.0.
**Both modifiers are UNMEASURED** against the standing rule below — run
`python main.py measure` once a few weeks of graded history exists.

The historical note below is kept for context:

**News weight WAS ZERO from 2026-07-15 to 2026-08-26** — the user turned news off because the
headline-driven score swings were noise (a single live-blog headline could flip
a symbol run-to-run). `config.WEIGHTS` is now **technical 1.0**, fundamentals
0.0, macro_news 0.0, sentiment 0.0 — `final_score == technical score`. The news
routine, `news_signals.json`, macro and sentiment sections are all STILL
computed and shown, and still drive the `bad_news` / `manipulation_risk` SAFETY
vetoes in `risk_manager` (those only downgrade a Buy→Watch, never fabricate),
but news no longer MOVES the score. To re-enable, restore e.g. technical 0.55 /
macro_news 0.20 / sentiment 0.25. Fundamentals was zeroed earlier (2026-06-19):
confirmed manually. `NEWS_SIGNALS_MAX_AGE_HOURS = 24` still gates stale files.

## Architecture (top-down)

`main.py` orchestrates one run:
1. Fetch market news, per-company news, benchmark index (KMI30).
2. `market_regime.assess_regime()` → risk-on/risk-off + `pct_above` (% the
   index sits above its 50-EMA).
3. For each stock: shariah check → quote/EOD → technical → sentiment →
   macro/news → fundamentals → relative strength → `scoring_engine.compute()` →
   `risk_manager.assess()` (now regime-aware) → `signal_generator.generate()`.
4. Save to SQLite (`psx_engine.db`); `backtester.update_outcomes()` fills
   forward prices and grades old runs (learning loop).

## Signal pipeline (signal_generator.generate)

Order of operations:
1. **No-data guard**: missing price → `"No data"` signal.
2. **Hard overrides** (always beat the score): shariah issue → `Avoid`;
   technical breakdown below support → `Exit` (if held) / `Avoid`.
3. **Score → base band**: `≥80 Strong Buy`, `≥75 Buy`, `≥60 Watch`,
   `≥50 Hold`, else `Avoid`. Strong Buy needs technicals confirming.
4. **Hysteresis dead-band** (`HYSTERESIS_BAND=2`): the band sits ENTIRELY
   ABOVE the threshold — enter at `threshold+2`, exit at `threshold`. It used
   to straddle (exit at `threshold-2`), which let a stale Buy persist at 73-74
   after the threshold moved to 75 — exactly the 30%-win band the raise was
   meant to exclude. Anti-flap is preserved by the upgrade side.
5. **Strong Buy confirmation gate**: a fresh Strong Buy is held at Buy until
   the very next run still scores Strong Buy. No numeric streak/conviction
   count is tracked or shown anywhere (removed — see below).
6. **Confluence — MEASURED, NOT A GATE (2026-08-12).** 4 dims: trend
   (price>50-EMA), momentum (RSI 40-74 AND MACD hist>0), volume (OBV up),
   structure (price>support AND no breakdown). The gate is REMOVED: graded
   outcomes were flat across it (2/4 won 17%, 3/4 26%, 4/4 25%) because the
   dims are not independent (trend and structure are near-collinear). Still
   computed, stored and shown per card.
7. **Chase guard — DISABLED 2026-08-12** (`CHASE_GUARD_ENABLED = False`). The
   extension is still computed and printed on the card as a `chase guard OFF`
   note, but it no longer steps a signal down. The regime-aware multiplier logic
   is retained behind the flag; flip the flag to restore it.
8. **Soft downgrades** (Buy/Strong Buy → Watch, first match wins): earnings
   blackout (≤5d), risk-off regime, `concentrated`, `poor_rr`, confidence<45,
   RS laggard. `bad_news` / `manipulation_risk` no longer fire (PURE_TECHNICAL).
   The `risk_level == "High"` branch was REMOVED — any veto forces High and
   every veto has its own branch above it, so it could never fire.
9. **Pullback-entry upgrade — REMOVED 2026-08-12.** The Buys it created
   (score below the Buy band) won 9% (n=57) vs a 38% market base rate. The
   SETUP (`pullback_ready` + buy-zone) is still computed and displayed as
   manual context; the engine no longer acts on it.
10. **Money-flow confirmation (`BUY_MIN_CMF`, moved 0.0 -> -0.15 on
    2026-09-04)**: a Buy whose CMF is at or below the threshold -> Watch.
    Re-audited against the CANDIDATE POOL over 5 years of adjusted, tradeable
    history, and the cut at zero did not survive: it rejected **50.1% of
    candidate-days to capture -0.07pp** at 5 days, the worst
    rejection-to-benefit ratio of anything measured here. The sweep is
    monotonic — a tighter cut rejects fewer AND captures more:

    | threshold | rejects | % of pool | 5d diff | 10d diff |
    |---|---|---|---|---|
    | 0.00 (old) | 12,824 | 50.1% | -0.07pp | -0.16pp |
    | -0.10 | 6,655 | 26.0% | -0.17pp | -0.32pp |
    | **-0.15** | 4,276 | **16.7%** | **-0.30pp** | **-0.46pp** |
    | -0.20 | 2,704 | 10.6% | -0.37pp | -0.57pp |

    All the information sits BELOW -0.15; the four buckets between -0.15 and
    +0.15 measured 5d medians of 0.00%, i.e. noise. Independence at -0.15:
    n=4,276, 49 symbols, 25 sectors, top symbol 4%. Year split 2024 -0.29pp,
    2025 -0.56pp, **2026 -0.32pp** — the recent years agree and the LIVE regime
    points the right way, which is precisely what the 15-40% extension zone
    failed. Caveat kept: 2022 (+0.06pp) and 2023 (-0.01pp) show nothing, so this
    may be regime-dependent; re-run the year split before tightening further.
    CMF=None never vetoes.

    **This SUPERSEDES the 2026-08-13 claim that CMF>0 lifted the beat rate
    70% -> 83% (n=56).** That test compared the filtered subset against a
    baseline instead of asking whether the REJECTED days were worse than the
    KEPT ones — the one question that catches a veto rejecting a better subset,
    which is how `poor_rr` and the chase guard both got through.

11. **RS laggard veto**: Buy/Strong Buy with `relative_strength <
    RS_LAGGARD_VETO (55, raised from 45 on 2026-08-12)` → Watch. RS<55 won 21%,
    RS 70+ won 36%; a 70 cut adds no accuracy once score≥75 applies but halves
    trade count. RS=None never vetoes (missing data can't block).

## Pure technicals + 50-EMA reference (2026-08-12)

User-directed risk-up. Three knobs in `config.py`:

- **`PURE_TECHNICAL = True`** — signals now come from price/volume ONLY. The
  score was already 100% technical (`WEIGHTS` technical 1.0), but news and
  sentiment could still MOVE a signal through the `bad_news` /
  `manipulation_risk` vetoes in `risk_manager`. Those are now emitted as
  WARNINGS only (still shown in the dashboard for manual cross-check) and are
  excluded from the `hard` count that sets `risk_level` — otherwise a bad
  headline would have kept downgrading Buys via the "High risk" branch.
  Structural gates are UNTOUCHED: shariah, breakdown, `poor_rr`, earnings
  blackout, regime, RS laggard.
- **`CHASE_GUARD_ENABLED = False`** — the engine no longer refuses to buy
  strength (see pipeline step 7).
- **`PULLBACK_EMA_SPAN = 50`** (was 20) — the reference EMA for BOTH the
  extension measure (`ext_pct`) and the pullback buy-zone (`ref_ema × 0.96` to
  `× 1.03`, floored at support). A deeper retracement = a wider, riskier zone.
  Because price inside a 50-EMA zone can sit slightly BELOW the 50-EMA, the old
  `price > ema50` trend test in `pullback_ready` would contradict the zone; it
  is replaced by "reference EMA rising over the last 10 sessions" plus the
  200-EMA test. The pullback RSI window widened 40-62 → 35-65 to match.

`technical['buy_zone_ema_span']` carries the span through to the dashboard/
signal reasons, so labels follow the config instead of being hardcoded.
`reports.py`'s "Entry zone" column now prints the real buy-zone (it was showing
support–EMA20, which was never the actual zone).

**Not changed:** `WEIGHTS` (already technical 1.0), the confluence gate,
hysteresis, Strong Buy confirmation, RS laggard veto, pullback quality gates
(`PULLBACK_MIN_SCORE`/`MIN_RS`) — those are technical/statistical, not news.

## Signal quality audit (2026-08-12) — the veto layer was inverting the edge

Measured on 43,470 stored rows, **day-deduped** (15-min polling inflates raw
counts ~20x — always dedupe to one row per symbol per day before believing any
win rate). Graded 3-day forward, compared to the SAME-DAY cohort median so the
market regime is controlled for (50% = no skill):

| cohort | n | beat market | median excess |
|---|---|---|---|
| signals actually emitted as Buy (old rules) | 97 | 36% | −0.63% |
| raw candidates score ≥70 | 198 | 56% | +0.37% |
| raw candidates score ≥75 | 81 | 63% | +0.85% |
| **new stack: score ≥75 AND RS ≥55** | 71 | **66%** | **+1.18%** |

**The raw technical score always had edge; the veto/gate layer was selecting the
worst subset of it.** Emitted Buys underperformed a coin flip while the
candidate pool they came from beat the market. That is the single most important
fact in this file — before adding any new gate, measure the emitted cohort
against the candidate pool, not against nothing.

Score band is the strongest discriminator (day-deduped, 3-day win): 70-75 → 30%
(n=66), 75-80 → 68% (n=28), 80+ → 86% (n=7). Two-thirds of Buys were coming
from the worst band, hence the 70 → 75 threshold move.

## Measurement independence — a win rate alone is not evidence (2026-08-17)

Day-deduping and cohort-median comparison were never enough. A cohort can look
spectacular while being **one event counted many times**. Live example from this
session: candidates (score ≥75, RS ≥55) split by the RSI flag showed the
*stretched* bucket beating the market **94% (3d) and 100% (7d)**, median excess
+8.71%/+10.52%. It looked like a discovery. It was 17 rows from **two symbols**
(PRL, NRL), **one sector** (Refinery), over 13 overlapping days of the Brownfield
refining-policy rally — the same trade, replayed, with overlapping forward
windows so the rows were not even independent of each other.

`measure.py` exists so this cannot happen again. `cohort()` NEVER returns a bare
win rate: every result carries distinct symbols, distinct sectors, top
symbol/sector share and date span, and prints **NOT TRUSTWORTHY** with reasons
when the sample is too concentrated (thresholds: ≥20 rows, ≥5 symbols,
≥3 sectors, no symbol >40%, no sector >60%). `python main.py measure` runs the
standing candidate-pool-vs-emitted-Buys comparison.

**Before believing any new finding, run it through `measure.render()`.** The
2026-08-12 audit above is the "measure against the candidate pool" rule; this is
the "and check the pool is more than one bet" rule. Both are needed.

## poor_rr veto DISABLED (2026-08-17) — it rejected the better subset

`POOR_RR_VETO_ENABLED = False` in config (mirrors `CHASE_GUARD_ENABLED`).
Measured with independence checks, pool = score ≥75:

| cohort | n | symbols | sectors | 3d beat | median excess |
|---|---|---|---|---|---|
| blocked by `poor_rr` | 47 | 17 | 11 | **68.1%** | +1.73% |
| blocked by `poor_rr`, RS ≥55 | 31 | 14 | 10 | **77.4%** | +2.12% |
| emitted Buys | 21 | 11 | 8 | **52.4%** | +0.41% |

7-day agrees (blocked 65.5%, +1.60%). All cohorts pass the independence checks,
so this is NOT the refinery rally. `poor_rr` was the most active veto in the
system — 48 of 98 candidates — and the names it blocked beat the names it passed
by 16 points (25 with RS ≥55).

**Cause:** headroom is measured to overhead *resistance*, and a leader printing
new highs has none by construction — the same penalise-strength flaw already
documented for the chase guard.

**Gated in `risk_manager`, not at the downgrade branch**, because
`risk_level = "High" if hard >= 2 or vetoes` — a disabled-but-present veto would
keep mislabelling cards the engine no longer blocks. `headroom_rr` is still
computed and still emitted as a warning.

Effect at the time of the change: PPL (78.8) and IMAGE (77.8) joined NRL and
GHNI as Buys. **Watch PPL — its RS is 41, below `RS_LAGGARD_VETO` (55).** It
only cleared because `poor_rr` was earlier in the soft-downgrade `elif` chain,
so the RS branch never evaluated. If PPL persists as a Buy, that ordering needs
fixing. Re-run `python main.py measure` in a few weeks: emitted Buys should move
from 52% toward the pool's 71%, else flip the flag back.

## The outage that froze signals for 4 days (2026-08-13 → 08-17)

`backtester.update_outcomes()` wrote the 7-day grade via
`db.update_outcome(id, "outcome_7d", ...)`, but `update_outcome`'s field
whitelist never gained `"outcome_7d"` when the early-warning tier added the
column (`681df04`). The assert fired on the first row whose `price_7d` filled,
killing `full_run()` at `main.py:150` — before the regime, before any save.

**Why nobody noticed:** the news fetch runs at lines 146-149, BEFORE the crash.
Every cycle still modified the DB, so `git commit` succeeded, the push went
through, and the workflow reported success while `runs` had not grown since
08-13. The dashboard silently showed Thursday's signals for four days.

Lessons now encoded:
- `engine.yml` captures the traceback instead of `|| echo "Run failed"`, and
  commits `engine_last_error.log` (force-added — `*.log` is gitignored, and a
  plain `git add` of an ignored path exits non-zero and kills the step).
- **A step's shell script is baked in when the job starts.** The loop's
  `git reset --hard origin/main` updates repo FILES (so Python changes apply
  next cycle) but NOT the already-running bash. To change loop behaviour you
  must cancel the job and start a new one.
- GitHub only releases a job's logs when it ENDS. A 6-hour loop hides its own
  traceback all session — cancel it if you need to read the failure.
- Anything added to `full_run` goes LAST and wrapped in try/except (see
  `_save_focus_brief`), so a fault costs one feature, never the signals.

## Focus brief — position-aware 360° read (2026-08-17)

`focus_brief.py` + `focus_brief` table + `config.FOCUS_SYMBOL` (currently NRL).
Resolves signal, score, regime, RS, confluence, CMF, levels, buy-zone, shariah,
the real book position, unscored company AND sector news, GLM, and the symbol's
graded record into **one action**. Rendered as the 🔬 panel above "Action today"
and via `python main.py brief`.

It never invents a score — it re-reads the engine's own signal. The gap it
closes: *a Buy you already hold 52% of is a different decision from a Buy you
hold none of*, and per-trade sizing is blind to that.

`exit_plan()` builds a **scaled exit ladder** for an over-cap holding: de-risk /
reach-the-cap / runner, with per-tranche P&L and what a stop-out costs. Tranches
rather than one exit because already-extended score≥75 names kept beating the
market here. **Cost-aware:** below breakeven the first tranche WAITS for
breakeven rather than banking a loss to fix a sizing problem.

`sector_crowding()` shows peer signals and warns when a large share of the
board's Buys are one sector — per-symbol scoring cannot see that its
"independent" Buys are one bet. **Informational, never a veto** (see the audit).

## Sector news routing (2026-08-17)

`config.SECTOR_NEWS_ANCHORS` + `news_feed.sector_headlines()`.
`COMPANY_NEWS_ANCHORS` requires a distinctive company name to stop cross-company
mis-attribution — but that also meant SECTOR news reached nobody. The Brownfield
refining policy (approved 2026-07-28), which drove every refinery name through
August, matched only PRL's anchor and was **invisible in NRL's own news window**
while being the single biggest driver of NRL's price. Sector phrases now route a
headline to every peer, returned SEPARATELY and labelled sector news, so the
company-level guarantee is untouched.

## Momentum burst — the one new signal that measured (2026-08-17)

`momentum.py` + a ⚡ panel at the TOP of the dashboard (user's placement).
A burst is one session breaking out of a stock's own norm, computed from
`daily_ohlc` — no fetch, and **no write path in `full_run`**, so it cannot take
the signals down with it.

Measured BEFORE building, then re-measured when the thresholds were loosened
(day-deduped, vs same-day cohort median, independence-checked):

| trigger | 3d | 7d |
|---|---|---|
| ≥3.0% & 1.5× vol | n=42, beat 83.3%, +2.54% | n=35, beat 71.4%, +1.92% |
| **≥2.0% & 1.3× vol (shipped)** | n=66, beat **80.3%**, +2.14% | n=53, beat **71.7%**, +2.13% |

The looser trigger (user's request, to enter earlier) costs ~3 points at 3 days
but is IDENTICAL at 7 days with a better median excess, on 57% more signals.
All four cohorts pass independence on both horizons — rare on this data, where
score velocity (45%), OBV divergence (negative) and the accumulation heuristics
all failed.

Thresholds live in `config.MOMENTUM_BURST` so they can be re-measured and moved
without editing code. **The dashboard caption quotes the measurement for the
CURRENT thresholds** — if you change them, re-measure and update that text, or
the panel advertises accuracy it no longer has.

A stricter variant also requiring a 20-day closing high scored 91.3% at 3 days,
but its 7-day sample is 16 rows / 69% one sector, so `at_high` ships as a TAG,
not part of the trigger. **It is a watch tier, never a Buy** — see the audit.

## Dashboard: what was deleted as measured noise (2026-08-17)

Removed because this repo's own graded history condemns them, not for taste:

- **Accumulation watch** (section + 🧲 pill). Its own caption admitted 47% beat
  at 3d / 53% at 7d and a NEGATIVE OBV-divergence component, and pointed the
  reader to Early watch instead.
- **Confluence dots** on cards and in the brief. Outcomes were flat across it
  (2/4 17%, 3/4 26%, 4/4 25%) — the gate was removed in August for exactly this
  reason and the display outlived the evidence.
- **Old "Momentum-burst watchlist"** (`db.momentum_bursts`, ≥5% movers, in the
  Watchlist tab). Superseded by the measured ⚡ panel AND contradicting it — the
  old caption said the engine "deliberately does NOT chase these". Two burst
  lists disagreeing is worse than neither.

**Kept on purpose** (zero score weight ≠ zero value): the unscored news window,
the GLM panel, the regime what-if, and Early watch (CMF — the one lead
indicator that measured; labelled unproven). Stored DB columns were NOT dropped,
so the data keeps accruing for future measurement.

## Morning timing — when signals actually land (2026-08-17)

User wants fresh signals by **09:35 PKT**. What was wrong and what changed:

- `MARKET_OPEN` was **09:15**, but PSX pre-open is 09:15-09:30 and REGULAR
  trading starts **09:32**. The first cycle of every day was therefore scoring
  yesterday's closes and presenting them as today's signals. Now `09:32`.
- The pre-open poll slept **300s**, so the loop could idle until ~09:37 before
  noticing the open. Now **60s**.

The FIRST cycle runs `python main.py run --fast`: no news fetch, no
`update_outcomes()`. Measured cost of what it skips: macro feeds ~2s + company
news 0.51s x 50 = **~27s**. Safe because news weight is 0.0 (and PURE_TECHNICAL
already demotes its vetoes to warnings) and outcome grading judges PAST runs —
it still runs on every later cycle and in the evening job. Everything feeding a
signal is untouched. `engine.yml` sets `first_cycle=1` and clears it after the
first pass.

Realistic timeline: loop kicked off by the 09:10 cron waits, first cycle starts
~09:32, a fast 50-symbol run takes ~4.5 min, so **fresh signals commit ~09:36**.
Signals reflecting real trading CANNOT exist before 09:32 — that is the market,
not the engine. Do not promise 09:35 exactly.

**The remaining cost is 50 symbols x 2 sequential PSX DPS calls** (intraday +
EOD), roughly 4.5 of the 5 minutes. Parallelising them (~8 at a time) would cut
the cycle to 1-2 min and clear 09:35 comfortably — proposed 2026-08-17 and the
user declined ("not needed"). Do not do it unasked: it raises concurrent load on
DPS, which already 403s from some hosts.

**GitHub cron is best-effort** (fires late, skips under load), which is why
`engine.yml` carries six staggered kickoffs. The external **cron-job.org
pinger** (outside this repo, user-managed) is the only trigger that holds a
precise time — point it at the `workflow_dispatch` endpoint.

Also: `concurrency: cancel-in-progress: false` means every trigger arriving
while a loop is alive shows as **cancelled** in the Actions list. That is by
design, not a fault.

## Early warning / lead time (2026-08-13)

User asked for signals "well ahead of time, not when the price has already
hiked". Before building anything, every leading indicator the engine already
computes was measured on graded history (7-day forward vs SAME-DAY cohort
median, day-deduped; 50% = no skill):

| candidate | 3d beat | 7d beat | verdict |
|---|---|---|---|
| CMF > 0.10 | 58% | **61%** (+2.07%) | the ONLY one with edge |
| CMF > 0.10 inside score 60-75 | — | **75%** (+2.70%, n=16) | small but consistent |
| accumulation_candidate | 47% | 53% | no edge |
| OBV bullish divergence | 44% | 45% | NEGATIVE |
| OBV up while price flat | 40% | 37% | NEGATIVE |
| score velocity (3d rise >5) | — | 45% | NEGATIVE |

**Score velocity does not work** — a fast-rising score predicts nothing. Neither
do the OBV-based accumulation heuristics, which the dashboard had been showing
as bullish tags; the Accumulation-watch caption now says so explicitly.

`signal_generator.early_watch()` implements the one thing that measured: CMF >
`EARLY_WATCH_MIN_CMF` inside `EARLY_WATCH_SCORE_BAND` (55-75, below the Buy
band), structure intact (no breakdown, price > support), RS ≥ 45. It returns
`(bool, reason)` and is stored per run (`early_watch`, `early_reason`) and shown
in a `🔭 Early watch` dashboard section. **It is NOT a signal and never becomes
a Buy** — it is a monitoring tier that buys lead time and deliberately leaves
the validated Buy stack untouched.

**7-day grading added** (`outcome_7d`, `backtester._beat_market_7d`,
`db.cohort_forward_move(..., days=7)`): a lead signal needs room to play out, so
3 days cannot judge it. Stored SEPARATELY from `outcome` so the Buy/Avoid stats
keep their 3-day definition. In a few weeks this gives real evidence on whether
the early tier works — until then it is labelled unproven in the UI.

**Note the counter-evidence on "buy before the hike":** score≥75 candidates that
had ALREADY run >8% in the prior 5 sessions beat the market 92% with +8.77%
median excess (n=13, small), while Buys taken on 5-day dips lost (-1.30%, n=35).
On this sample momentum PERSISTED and buying early/cheap was worse. That is the
opposite of the intuition behind the request — worth re-testing as data grows
before acting on it either way.

## Confidence honesty (2026-07-15)

`scoring_engine.historical_confidence_adjust` counts ONLY strictly-graded
signals (Buy/Strong Buy/Avoid/Exit). Watch/Hold outcomes use the loose
"didn't lose >3%" rule (80-90% survival rates, not edge) and were inflating
every symbol's confidence toward the +15 cap.

## Conviction streak — removed

The dashboard used to show a "🔥 N-run/N-day streak" badge per stock. Removed
entirely: even day-bucketed, it kept giving a false sense of independent
confirmation. `db.signal_streak()` is gone; `conviction_streak` stays in the
`runs` schema (old rows only) but nothing writes to it anymore. The Strong Buy
confirmation gate (above) achieves the same "don't chase a one-run spike"
goal without surfacing a number that looks like a track record.

## Risk vetoes (risk_manager.assess)

- `breakdown` — price below support
- `poor_rr` — **DISABLED 2026-08-17** (`POOR_RR_VETO_ENABLED = False`); it
  rejected a better subset than it passed — see its section above. Still
  computed and emitted as a warning; the veto is not appended, so it no longer
  forces `risk_level` High either. When enabled: headroom_rr below
  `min_headroom_rr` (1.5 baseline), **regime-aware** — in risk-on the threshold
  ramps DOWN to floor 1.1 by `headroom_rr_riskon_full_pct=8.0`.
- `bad_news`, `manipulation_risk` — content-driven (warnings only under
  PURE_TECHNICAL)
- `concentrated` — **DISABLED 2026-08-24** (`CONCENTRATION_VETO_ENABLED = False`,
  user-directed: they did not want portfolio-driven analysis). Gated in
  `risk_manager` the same way `poor_rr` is, so it cannot mislabel `risk_level`.
  When enabled it worked as follows: this symbol is already above
  `RISK["max_existing_concentration_pct"]` (25%) of the REAL book read from
  `portfolio.json`. Per-trade sizing is blind to existing holdings, so an
  80%-of-account position kept producing clean Buys. Blocks ADDING only;
  no portfolio file / no position → never fires.

## Data resilience: the day every ticker read "No data" (2026-08-27)

All 50 symbols returned `No data`, price `None`. The engine had not crashed — it
simply could not price anything, while holding a cached quote AND ~48 real
banked daily bars per symbol.

**Cause:** `data_fetcher.fetch_eod` had NO fallback. It returned `None` on any
failure, and `technical_analyzer` withholds the entire read when `eod is None`,
so `price` came back `None` and the no-data guard fired. `latest_quote`, ten
lines above it, had always degraded to the cached price; `fetch_eod` never did.

`fetch_eod` now falls back to `db.get_daily_ohlc` (>=30 bars) — REAL prices
captured from earlier intraday polls, the same bars the ATR/ADX path trusts.
**The staleness is made loud**, which is the part that matters: a cached
fallback still yields a full technical read, so a row stamped with today's
`run_time` would otherwise show `data_quality: good` over days-old prices —
exactly how the 2026-08-13 outage hid four stale days.
`main.analyze_stock` writes `STALE prices (<date>)` into `data_quality`, which
surfaces in the Watchlist Data column and the good-count tile.

**Why DPS actually failed — and every wrong theory, so they are not re-run.**
A runner probe (`dps_probe.py`, since deleted) proved PSX DPS was **healthy**:
HTTP 200 on both endpoints, bot UA and browser UA alike, TLS fine, no WAF
headers, and a 20-symbol rapid burst all 200. Then the engine's EXACT path —
full `requirements-ci.txt`, `ssl_compat.enable()`, `config.REQUEST_HEADERS` —
also returned `rows=1239 live=True` in a fresh job. So it was NOT an IP block,
NOT the bot User-Agent, NOT the ~2,400 requests/day volume, and NOT truststore.
**It was state local to the long-running loop job**: every cycle of the job
started at 09:45 failed on all 50 symbols, while a fresh job succeeded in the
same minute. Cancelling and restarting the loop restored live prices instantly.
If it recurs, restart the job — do not go hunting in the fetch code again.
(A job's logs are only released when it ENDS, so cancelling is also the only
way to read a running loop's failure.)

**Do not read a sandbox 403 as evidence about PSX.** This sandbox cannot reach
`dps.psx.com.pk` at all — `$HTTPS_PROXY/__agentproxy/status` shows
`connect_rejected`, i.e. the request never leaves the container. That is the
environment's egress policy and says nothing about the portal.

## Tracked DB size — pruned and self-maintaining (2026-08-27)

The whole DB is committed every 15-minute cycle, so its size is a per-push cost.
It reached **54 MB**, past GitHub's 50 MB warning and heading for the 100 MB
hard limit. Almost all of it was rows nothing reads:

| table | before | after | why the surplus was dead |
|---|---|---|---|
| `prices` | 41,938 | 50 | `latest_quote` reads only the LAST row per symbol |
| `news` | 20,799 | 1,858 | `recent_news()` only ever queries a 48h window |
| `runs` | 52,020 | 7,580 | 18.7x duplicated by 15-minute polling |

**54 MB -> 6.9 MB.** `runs` keeps FULL fidelity for the last 7 days (the
backtester grades 7 days forward and needs every row); older days keep one row
per symbol per day — the same dedupe every analysis here already applies.
`daily_ohlc` is untouched: it is now load-bearing for the EOD fallback above.

**Expect the accuracy n to be ~19x smaller** — that is the day-deduped truth,
not a regression. Buy reads n=140 at 47.1% where the inflated count implied far
more evidence than existed.

`db.prune()` runs nightly from the evening job (last, wrapped), so it cannot
creep back; `python main.py prune` runs it by hand. **Cancel the engine loop and
confirm it is dead before any manual prune** — the loop's DB wins every rebase
conflict (see the regrade it ate on 2026-08-13).

## Learning loop (backtester)

- `update_outcomes()` fills `price_1d/3d/7d` from real EOD; grades once 3-day
  price exists; credits/blames sub-indicators in `indicator_accuracy`.
- `_signal_worked()` grading rules:
  - **Buy/Strong Buy**: BEAT the real KMI30 3-day forward move without a stop
    hit (same benchmark → cohort-median → fallback chain as Avoid). Changed
    2026-08-12 from an absolute ">1% in 3 days", which mostly measured the
    market: it scored Buys at 22% against a 38% base rate for "any symbol rose
    >1%", so Buy and Avoid were not comparable. Re-graded: Buy win 22% → 39%.
  - **Avoid/Exit**: stock underperformed the **REAL KMI30 benchmark**
    forward move (3-day). Falls back to **cohort median** (engine's own
    universe) when the index isn't reachable. Final fallback: "did not rise"
    (chg<0). Three honest fallbacks, never fabricated.
  - **Watch/Hold**: loose grade — didn't lose >3%
- `regrade_all()` (`python main.py regrade`) wipes indicator_accuracy and
  re-grades EVERY completed run under current rules. Run this whenever
  grading rules change.

## Accuracy stats

`db.signal_accuracy_summary()` returns rows with `n_confidence`
(`high`/`medium`/`low`) — small-N win rates are flagged as NOISE, not edge.
CLI `python main.py accuracy` shows this with explicit warnings.

## Dashboard staleness

- `DATA_FRESHNESS_AMBER_HOURS=4` → tile turns amber, banner warns
- `DATA_FRESHNESS_RED_HOURS=24` → tile turns red, error banner

**Password-safe auto-refresh (2026-07-15):** on Streamlit Cloud the running
server serves the git snapshot from its last deploy; an open tab needs a full
reload to reconnect after a redeploy and re-read the committed DB. `_auto_refresh`
reloads every `DASHBOARD_REFRESH_SECONDS` (300). It USED to be disabled whenever
`DASHBOARD_PASSWORD` was set (a reload forced re-login) → the user had to reboot
manually. Now login stamps a non-reversible hashed token (`_auth_token`) into the
URL query string (`?k=…`); `window.location.reload()` preserves it, so the tab
re-authenticates itself across both the timed reload and Streamlit Cloud
redeploys (which drop server sessions). Trade-off: the token is a bearer
credential in the URL — fine for a single-user personal dashboard, noted in-code.
If the user rejects the URL-token approach, the fallback is host-independent:
pull latest run rows from a small committed JSON via GitHub raw with a short TTL.

## Dashboard trade-plan cards

Each Buy-signal card has an inline "📋 Full detail" expander (no extra data
fetch — uses fields already on the row: full reason, main risk, shariah
status, regime, support/resistance, buy-zone). Chart + per-stock backtest
still live only in the 📈 Stock detail tab to avoid an EOD fetch per card.

## Sector news reached almost nobody (fixed 2026-09-01)

The reason news never moved a score was NOT the rater. Only **7 of 26 sectors
had anchors at all**, and the anchored ones lacked the two drivers that actually
move this board: there was no crude anchor and no petrol/diesel anchor. On
2026-09-01 the digest offered the rater Fertilizer, Power Generation and Islamic
Banking — which genuinely had no story, so it correctly rated them
`neutral`/`noise`, i.e. exactly 0.0 movement — while *"Oil climbs above $91.5 as
US-Iran conflict raises supply fears"* sat in the same file routed to nothing.
NRL/PRL/ATRL are refiners and never saw it.

24 sectors now have anchors. Measured on that day's file: **3 sectors -> 12**,
**~6 -> 25 of 50 symbols** covered, and `sector_headlines('NRL')` returns the
oil story as its top item.

Two matching bugs fixed with it:
- Sector matching was **plain substring**, so `"ipp"` routed *"Shipping volumes
  rise at Port Qasim"* and *"Philippines trade deal"* to Power Generation, and a
  bare `"sbp"` sent every FX release to Islamic Banking. Sectors now use the same
  word-boundary matcher as companies (`config.headline_matches_sector`).
- `SECTOR_NEWS_EXCLUDE` is checked FIRST, so *"Palm oil prices ease"* cannot
  reach the refiners through the `oil prices` anchor.

Broader anchors mean some routes will be wrong. The cost is bounded on purpose:
`neutral`/`noise` moves a score by exactly 0.0 and the sector cap is +-4.

## Vetoes are COLLECTED, not first-match-wins (2026-09-01)

The soft-downgrade chain was `elif`, so the first veto masked every later one —
a Buy blocked by `poor_rr` was never RS-tested, and disabling `poor_rr` silently
exposed candidates a later veto should have caught (PPL at RS 41). Downgrades
are now collected into one reason string joined by `"; also "`.

**The emitted signal is unchanged** — any match still means Watch. What changes
is that a card names EVERY reason it failed, so a disabled veto can no longer
hide an active one. Consequence to remember: `dashboard._display_signal` now
promotes a regime-gated Watch under "Assume risk-on" ONLY when `"; also "` is
absent, i.e. the regime gate is the sole veto. Without that guard the collected
string would have made the what-if invent Buys carrying a second live veto.

## Real daily High/Low — PSX's historical view (2026-09-01)

DPS end-of-day returns `[ts, close, volume, open]` and **no High or Low**, so ATR,
ADX and a true CMF were limited to the ~50 bars the intraday poller had banked —
and CMF is the one lead indicator that measured here.

`POST https://dps.psx.com.pk/historical` with `date=YYYY-MM-DD` returns EVERY
listed company's OHLCV for that session. **Keyed by date, not symbol**, so one
request covers the whole universe: ~1,305 weekday sessions for 5 years instead
of 12,500 per-symbol calls. Confirmed on a runner (`hl_probe`), markup observed
not assumed:

    <table id="historicalTable"><thead><tr><th data-name="symbol">…
    row: ['<strong>786</strong>','23.27','23.30','23.30','23.00','23.05',
          '<i …></i> -0.22','<i …></i> -0.95%','47,039']
    => SYMBOL | LDCP | OPEN | HIGH | LOW | CLOSE | CHANGE | CHANGE% | VOLUME

Gotchas that cost real time, so they are not re-learned:
- **A non-trading day returns the SAME HTTP 200 with an empty tbody.** The first
  probe used 2026-08-29, a Saturday, got 903 bytes, and read as a dead endpoint.
  Empty means "no session", and is a free holiday guard — no calendar needed.
- Cells carry markup (`<strong>`, direction `<i>`) and volume is comma-grouped.
- `psx_historical.parse` keys columns off the header's `data-name` attributes and
  **raises** if one is missing, rather than mis-mapping High into Low. A wrong
  High/Low corrupts every derived ATR and looks perfectly normal on a chart.
- **~2.8s per request** (the response is the whole market, ~500 rows), so with
  1s pacing a 5-year run takes ~80 minutes, not the ~22 the pacing alone implies.
- Older sessions return ~44 of our 50 symbols, not 50 — names that had not listed
  yet. A flat 50 every session would be the suspicious result.

`save_hl_bar` defaults to **INSERT OR IGNORE**, keeping intraday-banked bars.
Note the trade-off: the portal's figure is the exchange's OFFICIAL one, while an
intraday-derived high/low is reconstructed from 15-minute polls and must
UNDERSTATE the true range whenever an extreme printed between polls. So for the
~50 overlapping days the LESS accurate value wins by default;
`--prefer-official` replaces them.

`hl-backfill.yml` is manual-only and **refuses to start while `engine.yml` is
running** — the loop rebases with `-X theirs`, so its DB wins every conflict and
would silently discard the whole backfill (that is what ate the 2026-08-13
regrade). It pushes with a PLAIN rebase so a mid-job collision fails loudly.

## daily_eod — the EOD history that was being thrown away (2026-09-01)

`fetch_eod` downloaded ~1,200 daily bars per symbol on every one of the ~24
cycles a day and discarded all of them; `daily_ohlc` only ever held what the
INTRADAY path banked (~50 days). `_bank_eod_history` now persists them, guarded
on `(rows, latest_date)` so a symbol writes once per day rather than 24 times,
and wrapped so banking can never fail a price fetch. Only the LIVE path banks —
the banked-bars fallback cannot feed itself.

**`daily_eod` is a SEPARATE table on purpose.** DPS EOD has no High/Low, and
`save_daily_ohlc` uses `INSERT OR REPLACE`, so writing null-H/L rows into
`daily_ohlc` would have destroyed the real intraday-derived highs and lows the
ATR/ADX/momentum paths read. Never merge the two.

## Confluence axes — continuous, and wired into NOTHING (2026-09-01)

The old 4-dim `_confluence` is binary and near-collinear (trend is
`price>EMA50`, structure is `price>support`; in an uptrend the second is implied
by the first), which is why outcomes were flat across it (2/4 17%, 3/4 26%,
4/4 25%). `confluence_axes.py` keeps the idea and fixes the shape: six
CONTINUOUS 0..1 axes chosen for different mechanisms — EMA50 slope, relative
strength (the only cross-sectional one), inverted realised-vol percentile,
volume vs the symbol's own median, headroom above support in SIGMA not percent,
and consecutive sessions above the 50-EMA (the only temporal one).

All six are computable from close/open/volume, so the banked history scores them
over years. Money flow is deliberately absent — a true CMF needs High/Low.

A missing input yields `None` and is EXCLUDED from the composite rather than
defaulted to 0.5, which would invent agreement. Results carry `coverage`, `bars`
and `trustworthy`. Computed LAST and wrapped in `analyze_stock`.

**EVERY AXIS IS UNMEASURED and none touches signal generation.** The 2026-08-12
audit is the reason: emitted Buys beat the market 36% while the candidate pool
they came from beat it 63%, so a new gate on unmeasured inputs is the single
change most likely to destroy edge. Grade each axis with `measure.render()`
first, and prefer RANKING or POSITION SIZING over a veto — every veto measured
here (`poor_rr`, chase guard, the confluence gate, the pullback upgrade)
rejected a better subset than it passed. `python main.py axes` prints them.

## market-watch — the whole market's live OHLC in one request (2026-09-04)

`dps.psx.com.pk/market-watch` returns every listed company's current session row.
`psx_market_watch.fetch()` is called ONCE per cycle in `full_run`, before the
per-symbol loop, and banks the exchange's **official intraday High/Low** into
`daily_ohlc` with `overwrite=True`.

That overwrite is deliberate and reverses the backfill's default: an
intraday-derived high/low is reconstructed from 15-minute polls and MUST
understate the true range whenever an extreme prints between them, so where the
official figure is available it wins. ATR, ADX and CMF all read that table.

Verified on a runner before wiring (`mw-probe.yml`): **49 of 50 symbols**, real
OHLC, ~2s. The `current` column was confirmed to be the LIVE price and not a
silent fallback to `ldcp` — from the data, not the header: all eight sampled
symbols had `current` strictly inside their own day's low-high, and FFC's band
was only 0.5% wide, so eight for eight is not chance. `to_bars()` RAISES on a
missing column rather than mis-mapping High into Low, and drops O=H=L=0.00 bars
(the JVDC/BNL no-trade case). `fetch()` never raises.

**NOT done yet, and it is the real prize:** replacing `fetch_eod` +
`latest_quote` with this feed would cut **100 requests per cycle to 1** — the
load reduction that parallelising was declined for. That changes the price path
itself, so it needs its own pass and its own verification.

## market-watch invented a Saturday session (fixed 2026-09-05)

`psx_market_watch.fetch()` has NO session date in its payload — once the market
shuts it simply keeps serving the LAST session's row. `_bank_official_hl` stamped
that with `datetime.now()`, so an out-of-hours dispatch on Saturday 2026-09-05
banked **49 bars dated 2026-09-05**, byte-identical to Thursday's for 45 of them.

A duplicated bar is worse than a missing one: every window that counts SESSIONS
rather than reading the latest price — ATR, true range, momentum, the range
features, forward returns — treats it as a real flat day. The signals in that run
were unaffected (they read the latest bar, which was the right price).

Two guards now, because the clock alone cannot see a public holiday:
- `_is_live_session()` — weekday AND inside `MARKET_OPEN..MARKET_CLOSE`. The
  workflow sets `TZ=Asia/Karachi`, so `datetime.now()` is already Pakistan time.
- a bar identical to the symbol's PREVIOUS stored bar (on an earlier date) is
  skipped as the feed repeating itself. This is the holiday case. It does NOT
  fire when the latest stored bar is today's — intraday overwrite still works,
  which is the whole point of `overwrite=True`.

The 49 phantom rows were deleted, scoped to that exact `source`. Verified after:
**zero weekend bars anywhere in `daily_ohlc`**, so this was the first and only
occurrence.

## market-watch invented a Saturday session (fixed 2026-09-05)

`psx_market_watch.fetch()` has NO session date in its payload — once the market
shuts it simply keeps serving the LAST session's row. `_bank_official_hl` stamped
that with `datetime.now()`, so an out-of-hours dispatch on Saturday 2026-09-05
banked **49 bars dated 2026-09-05**, byte-identical to Thursday's for 45 of them.

A duplicated bar is worse than a missing one: every window that counts SESSIONS
rather than reading the latest price — ATR, true range, momentum, the range
features, forward returns — treats it as a real flat day. The signals in that run
were unaffected (they read the latest bar, which was the right price).

Two guards now, because the clock alone cannot see a public holiday:
- `_is_live_session()` — weekday AND inside `MARKET_OPEN..MARKET_CLOSE`. The
  workflow sets `TZ=Asia/Karachi`, so `datetime.now()` is already Pakistan time.
- a bar identical to the symbol's PREVIOUS stored bar (on an earlier date) is
  skipped as the feed repeating itself. This is the holiday case. It does NOT
  fire when the latest stored bar is today's — intraday overwrite still works,
  which is the whole point of `overwrite=True`.

The 49 phantom rows were deleted, scoped to that exact `source`. Verified after:
**zero weekend bars anywhere in `daily_ohlc`**, so this was the first and only
occurrence.

## PSX does NOT publish an order book (settled 2026-09-04)

`depth_probe.py` tried `/orderbook/`, `/depth/`, `/market-depth/`,
`/timeseries/depth/`, `/quote/`, `/marketwatch/` — all **404**. The company page
mentions bid/ask but its only table is the board of directors.

The telling find is in `market-watch`, whose HTML carries **commented-out**
headers: `<!-- th TOTAL BUY ORDERS -->` and `<!-- th TOTAL SELL ORDERS -->`.
The exchange built those columns and disabled them. This is not an endpoint that
was missed; depth is off by design. Do not go looking again.

## Order book — a measurement dataset, fed by hand (2026-09-04)

Investify's quote page shows **L1 only** (best bid/ask + their volumes), not full
depth. `tools/investify_l1.js` pasted into Chrome's DevTools console reads it off
the rendered page — nothing to install, transmits nothing, never touches request
headers. CSVs dropped into `orderbook/` are ingested by `orderbook.ingest()` on
every run into the `order_book` table.

**Nothing reads it into a signal, and that is the design.** One symbol at a time,
captured by hand in bursts, stale within minutes against a 15-minute cycle, and
UNMEASURED — and every unmeasured input this repo trusted on appearance alone
(OBV divergence, score velocity, the confluence gate) went on to measure flat or
negative. It accumulates so `imbalance` can be graded with `measure.py`; if it
earns a place it is a ranker or sizer, never a veto.

Three things learned the hard way, all worth keeping:
- **Consecutive identical states are collapsed.** The first live capture was 37
  rows containing **5 distinct states** (7.4x): the broker page repaints when
  something CHANGES, not on the sampler's clock. Storing every sample would
  inflate any future n ~7x and defeat the independence checks outright. Sample
  at 45-60s, not 5s.
- **The browser writes the CAPTURER'S clock (PKT); the engine runs in UTC.**
  Stored naive, an 11:15 snapshot read as 90 minutes in the FUTURE, and a future
  timestamp trivially passes "younger than N minutes". Timestamps normalise to
  UTC on ingest (`ORDERBOOK_TZ_OFFSET`, default +5) and `order_book_latest`
  REJECTS a negative age — the same silent-bypass shape as a missing `as_of`.
- The CSV carries only a clock time, so the DATE is recovered from an ISO date
  or epoch-ms in the filename, else mtime. Name files `NRL_YYYY-MM-DD.csv`.

Measured nothing yet: L1 imbalance swung 0.17 -> 10.71 -> 0.17 within four
minutes on the only session captured, median 1.01. That is noise until proven
otherwise, and it is the most spoofable number in the market.

## This sandbox has NO general egress and NO display (2026-09-04)

Established by direct test, so it is not re-litigated. Chromium 141 is installed
and runs, but **every** outbound connection is `connect_rejected` at the proxy —
`example.com` and `google.com` included, not just PSX — and `DISPLAY` is unset
with no X11 socket, so it is headless-only with no window anyone could see or
type into. There is therefore no way to open a browser for the user to log into,
and no route from this container to any browser on their device.

What DOES work: headless Chromium against **localhost** (the Streamlit dashboard
was rendered and screenshotted this way, after `pip install streamlit` — pypi
bypasses the proxy), and the `WebSearch`/`WebFetch` tools, which route through
Anthropic's service rather than this container. Those are **anonymous, one-shot
and cookie-less**, so they can never act as a logged-in session.

## Chase guard re-measured and REJECTED again (2026-09-04)

Re-tested against the candidate pool on 5 years of adjusted, tradeable history
after the event library made a proper test possible. **Keep `CHASE_GUARD_ENABLED
= False`.**

As configured (`ext > 11%` or `mom20 > 22%`) it would reject **28.7% of
candidate-days** for **-0.16pp at 5 days**, decaying to -0.01pp at 10 and
**exactly 0.00pp at 20**. Nearly a third of the opportunity set for nothing.

Extension is NOT the enemy, and the relationship is not monotonic:

| ext above 50-EMA | n | 5d med | 20d med |
|---|---|---|---|
| 0-5% | 10,873 | -0.01% | +0.00% |
| 5-10% | 6,659 | +0.13% | +0.27% |
| 10-15% | 3,711 | +0.00% | **+0.39%** |
| 15-25% | 2,779 | **-0.50%** | -0.30% |
| 25-40% | 1,081 | -0.38% | -0.36% |
| 40%+ | 370 | +1.16% | +0.14% |

The 11% trigger rejects the 10-15% band, which is one of the BEST.

**A targeted 15-40% veto was tested and also rejected**, and the reason is worth
keeping: it looks strong (-0.48%, 46% positive, n=3,860, 49 symbols, 25 sectors,
top symbol 5% — passes every independence check) but the sign **FLIPPED POSITIVE
in 2026** (+0.62%, 54%, n=314) after four negative years. Deploying a rule whose
sign inverted in the live regime is the classic backtest-to-blowup path. Do not
resurrect it without re-running the year split.

## Shock-up entry deferral — the one rule that earned deployment (2026-09-04)

`SHOCK_UP_DEFER_ENABLED`. A day carrying a >=2.5 sigma, >=3% up-move DEFERS a
fresh Buy to Watch for that single run; the stock is free to become a Buy the
next day. It rejects the TIMING, not the name.

Measured the only way that catches this repo's recurring failure — inside the
candidate pool (uptrend + positive RS), asking whether the rejected days are
worse than the kept ones. They are: **-0.41% median excess at 5d vs 0.00%, 45%
positive vs 49%, n=1,169 across 49 symbols**, negative at every horizon
(3d -0.47, 5d -0.41, 10d -0.60, 20d -0.13pp). Fires on only 4.3% of
candidate-days.

The contrast with the chase guard is the lesson: **a one-day event with a stable
effect is deployable; a persistent state with a regime-dependent effect is not.**

Caveat kept on purpose: the engine's own graded Buys disagree (n=7, 57% vs 50%).
That is far too small to mean anything, but it is the only LIVE evidence and it
points the other way. Re-run `python main.py measure` once more Buys have graded.

## Hysteresis and the confidence floor audited (2026-09-05)

The last two gates between the candidate pool and emitted Buys. Neither is
removed; both were misunderstood.

**Hysteresis: the downgrade half was UNREACHABLE, and is now deleted.** The
branch held a one-notch downgrade when `final_score >= the previous tier's
threshold` — but clearing that threshold is precisely what keeps the score IN
that tier, so it contradicted the band assignment that produced the downgrade.
Dead in all four notches. Confirmed against stored history: the downgrade
message appears in **0** rows, the upgrade message in **437**.

**The upgrade delay MEASURED NEUTRAL, so it stays.** Deferring a fresh candidate
entry by one session over 5 years of banked bars (18,113 candidate-days, 49
symbols): 5-day median 0.00% -> 0.00%, mean +0.88% -> +0.87%, positive 49.7% ->
49.9%; flat at 10 and 20 days. It buys anti-flap for nothing. Live rows point
the same way but cannot carry the verdict — fresh pool entries scoring 75-77
(the band the gate defers) beat those scoring 77+ at every horizon (5d +5.86%
vs +2.33%), and the edge survives dropping Refinery and matching the date
window, but only on n=11-16. **Under-powered, not evidence.** Re-run once more
history exists; if it holds, the gate is costing entries rather than saving them.

Also fixed: the retained message read `base` AFTER reassigning it, so all 437
firings named the previous tier twice instead of the one being withheld.

**The confidence floor (`confidence < 45` -> Watch) has never fired and cannot.**
Across 3,130 day-deduped rows, 157 score below 45 confidence and **every one has
`final_score <= 70`** — below the Buy band, so the downgrade has nothing to
downgrade. It is not independent: low confidence is driven by `data_quality`
(136 of 157 are `weak: technical`), and a weak technical read depresses the
score itself. Harmless, so it stays as a backstop, but do not count it as an
active filter — it explains none of the pool-vs-emitted gap.

**Gate audit closed.** poor_rr, chase guard, concentration, confluence and the
pullback upgrade were removed or disabled on evidence; CMF was loosened; the
regime gate and shock-up deferral were kept on evidence; hysteresis and the
confidence floor are inert. No remaining gate accounts for emitted Buys trailing
the candidate pool — the next place to look is the score itself, not the vetoes.

## Chart features measured — standalone only, NOT wired to signals (2026-09-05)

`chart_analysis.py` reproduces the discretionary read (swing pivots, HH/HL
structure, anchored trendlines, tested zones, EMA stack, candle patterns,
volume). Before connecting any of it, every feature was graded on the candidate
pool over 5 years of adjusted history (pool = uptrend + positive RS; benchmark =
same-day cross-sectional median; pool baseline 5d 0.00%/49.7%):

| feature | n | 5d med | 10d med | 10d pos |
|---|---|---|---|---|
| MA stack 20>50>200 | 13,688 | +0.08% | +0.29% | 51.9% |
| close > 55-day high | 1,649 | +0.14% | +0.32% | 51.4% |
| breakout + volume expansion | 1,810 | +0.09% | +0.13% | 50.7% |
| bullish engulfing | 709 | +0.02% | -0.02% | 48.5% |
| doji | 1,974 | 0.00% | 0.00% | 49.7% |
| long lower wick | 467 | +0.06% | +0.09% | 50.3% |
| volume > 1.5x 20d median | 6,301 | **-0.08%** | -0.01% | 48.9% |
| pullback within 2% of EMA50 | 2,038 | **-0.10%** | **-0.19%** | 47.0% |

**Candle patterns are noise here** — engulfing, doji and long-wick bars all sit
inside the pool baseline. So is volume confirmation, which is mildly NEGATIVE:
buying the volume-expansion day underperforms the pool. Buying the pullback to
the 50-EMA is the worst of the set, agreeing with the pullback upgrade that was
removed in August.

**The one promising feature failed the live regime.** A 10-day range under 5%
(volatility contraction / coiling) measured 10d +0.89%, 56.9% positive, n=504
across 29 symbols and 16 sectors — it passes every independence check. But the
year split inverts: 2022 +1.79%, 2024 +1.90%, then **2026 -0.40% with only 30%
positive**, and the inversion holds at every threshold tested (<5%, <7%, <9%).
That is the same shape that killed the 15-40% extension veto — a rule whose sign
flipped in the live regime. Re-run the year split before reconsidering.

**Conclusion: chart_analysis stays read-only.** Nothing in it earns a place in
signal generation on this evidence. When something eventually does, it enters as
a RANKER or POSITION SIZER, never a veto — every veto measured in this repo
rejected a better subset than it passed.

## Buying up-shocks loses in EVERY category (2026-09-04)

On adjusted, tradeable events (1,020 up-shocks): sector-driven **-1.93%, 39%
positive**; market-driven **-0.31%, 47%**; company-specific **-0.08%, 48%**.
Not one category is profitable. The only positive cohort in the library is the
company-specific SELLOFF: +1.02%, 58%, n=204 across 45 symbols and 22 sectors.

Realistic testing of that selloff trade (enter next OPEN, hold 10d, target +5%,
stop 6%) gives median +1.14%, 59% win, **+0.74% net of 0.4% costs, against a
median MAE of -3.95%**. Real but thin — risking ~4% of drawdown for ~0.75%. Size
it small if used at all, and note that TIGHTER stops made it WORSE (4% stop ->
+0.39%): these trades need room.

## Regime gate audited and KEPT (2026-09-04) — and the trap that nearly reversed it

`REGIME_GATE_ENABLED` stays True. The audit is recorded mainly for its
METHOD, because the first result pointed the other way and was wrong.

Two things make a market-wide rule different from a per-stock one, and getting
either wrong inverts the answer:
- **The benchmark must be ABSOLUTE, not cross-sectional excess.** Every other
  audit here measures excess against the same-day universe median. A rule that
  fires on the whole market at once is differenced away exactly by that
  benchmark and will always measure zero.
- **The independent unit is the SESSION, not the stock-day.** 25,000 stock-days
  across 1,240 sessions is ~1,240 observations.

Day-clustered on absolute returns, risk-off looked BETTER at every horizon
(5d +0.64pp, 10d +0.75pp, and 2026 +1.62pp), with a sound-sounding mechanism:
in risk-off, a name still clearing trend + RS + CMF is genuinely exceptional,
while in risk-on nearly everything clears it.

**That was an artifact.** Collapsing each session to one median gives a quiet
risk-off day with 3 candidates the same weight as a busy risk-on day with 40.
On the full stock-day sample the MEAN — which is what compounds — says the
opposite:

| over 10d | risk-on | risk-off |
|---|---|---|
| median MAE | -4.91% | -4.24% |
| **mean return** | **+1.45%** | **+0.64%** |
| p90 | +14.14% | +10.15% |
| candidate-days | 18,166 | 2,968 |

Risk-off is marginally safer; risk-on is more than twice as profitable and
offers 6x the opportunities. Unlike the CMF threshold — better on both axes at
once — this is a real trade-off, and it favours the gate.

**A regime proxy was used, not KMI30**: the equal-weight index of our own 50
names (mean of daily returns, compounded) against its 50-EMA, giving risk-off on
38% of sessions. Note the construction: compounding the MEDIAN daily return
instead drifts persistently downward and reported risk-off on 84% of sessions,
which is what exposed the bug. An index is a portfolio, so it takes the mean.

## Key files

- `config.py` — all knobs (thresholds, weights, risk caps, stocks).
- `signal_generator.py` — signal decision logic (the heart).
- `risk_manager.py` — veto layer + position sizing.
- `market_regime.py` — KMI30-driven regime + relative strength.
- `technical_analyzer.py` — TA score + flags (ext_pct, momentum_20d,
  headroom_rr, confluence inputs, accumulation candidates).
- `scoring_engine.py` — weighted final_score + confidence.
- `backtester.py` — learning loop + historical replay (in-sample/OOS/walk-forward).
- `database.py` — SQLite (tracked binary `psx_engine.db`).
- `dashboard.py` — Streamlit UI.
- `measure.py` — cohort stats WITH independence checks; never returns a bare
  win rate. Run every finding through it before believing it.
- `focus_brief.py` — position-aware 360° brief + scaled exit ladder + sector
  crowding for `config.FOCUS_SYMBOL`.
- `momentum.py` — momentum-burst detector (config.MOMENTUM_BURST). Reads
  `daily_ohlc` only; no write path in `full_run`.
- `confluence_axes.py` — six CONTINUOUS setup dimensions (2026-09-01). Stored
  per run (`confluence_axes` JSON + `confluence_composite`), wired into NOTHING.
- `psx_historical.py` — daily High/Low backfill from PSX's historical view.
- `psx_market_watch.py` — whole-market live OHLC in ONE request (2026-09-04).
- `orderbook.py` — ingests hand-captured L1 CSVs from `orderbook/`. Stored only.
- `tools/investify_l1.js` — DevTools console snippet that captures the L1 book.
- `hl_probe.py` / `depth_probe.py` — read-only source reconnaissance (runner only).
- `main.py` — CLI entry: `run / schedule / morning / evening / backtest SYMBOL /
  metrics / portfolio / accuracy / regrade / accumulating / history SYMBOL /
  fundamentals / measure / brief / prune / backfill / axes`.

## Environment notes

- PSX DPS (`dps.psx.com.pk`) returns **403 Forbidden** from this sandbox.
  All live analysis uses stored data via `db.last_run()` / `db.run_history()`.
- The cloud GitHub Action runs the engine automatically and commits
  `psx_engine.db` frequently → expect binary rebase conflicts. Resolve via
  `git checkout --theirs psx_engine.db`, then re-run any maintenance commands
  (e.g., `python main.py regrade`) and re-push.

### NEVER run a DB maintenance command while the engine loop is live
`engine.yml` loops every 15 min doing run → commit → `git pull --rebase -X
theirs` → push. In a rebase `theirs` is the commit being replayed — the LOOP's
own DB — so **the loop's copy wins every conflict and silently discards any DB
you pushed**. This ate a full `regrade` on 2026-08-13: the code change was in
`main`, but all 38,310 re-graded outcomes reverted to the old rule, and the only
symptom was the Buy win rate reading 22% again instead of 39%.

Safe procedure for `regrade` (or anything else that rewrites the DB):
1. Cancel the in-progress `engine.yml` run and WAIT for status `completed`.
2. `git pull origin main` to get the loop's final DB.
3. Run the maintenance command, commit, push.
4. Re-dispatch `engine.yml` — the fresh checkout starts from your DB.

Schema migrations self-heal (the next run's `init_db` re-adds missing columns),
but row DATA does not. After any regrade, VERIFY it stuck by re-reading the
win rate — do not assume the push held.

## Universe (KMI-30 verified + KMI All-Share)

See `KMI30_VERIFIED`, `KMIALLSHR_VERIFIED`, `OTHER_COMPLIANT` in config.py.
Re-verify each semi-annual recomposition (KMI30 effective 2026-05-25;
KMI All-Share effective 2026-06-05).

## Open / parked ideas

- Per-symbol-type backtest split (training vs evaluation window) — currently
  the in-sample/OOS split exists in `backtester.backtest()` but live signal
  accuracy stats are all in-sample.
- Earnings dates remain manual (`EARNINGS_DATES = {}` in config + optional
  `earnings_date` field in `news_signals.json`). **The blackout veto has
  therefore never fired once.** NRL's FY ends 30 June, so FY26 annual results
  land ~Sept–Oct 2026 — with 52% of the book in NRL that is a live, avoidable
  exposure. Ask the user for the board-meeting date and populate it.
- **Veto ordering bug (suspected, 2026-08-17):** the soft-downgrade `elif`
  chain is first-match-wins, so disabling `poor_rr` can expose candidates that
  a LATER veto should have caught. PPL surfaced as a Buy at RS 41, below
  `RS_LAGGARD_VETO` (55). Verify on the next run; if it persists, the chain
  needs reordering or converting to collect-all-vetoes.
- Which OTHER vetoes leak edge — `regime risk-off` blocked losers (41.2%,
  −0.80%) which suggests it works, but n=17 fails `measure.py`'s threshold.
  Re-run `python main.py measure` as history accumulates.
- Fundamentals: PSX DPS publishes a P/E per company (NRL 4.91 TTM on
  2026-08-17) and NRL posted 9MFY26 net profit PKR 9.07bn vs a 14.49bn loss.
  `fundamentals.json` has only 3 symbols and `WEIGHTS` fundamentals is 0.0 —
  do NOT re-enable without a data audit + explicit OK (user's standing call).

## Cross-account handoff — "continue where other account stopped"

This section is the resume point for any Claude account. It is committed to
`main`, so a fresh session sees it via git. **When the user says "continue where
other account stopped," read this section first, then `git pull origin main` to
get the latest state.** Keep this section current at the end of each work
session (edit the dates/state, commit, push).

**Last updated:** 2026-09-04. Today, all merged to `main`: `market-watch` banks
the exchange's OFFICIAL intraday High/Low every cycle (49/50 symbols, one ~2s
request, verified on a runner first); order-book ingestion added as a
measurement dataset with the timezone and dedupe traps documented above; PSX
confirmed NOT to publish depth (the columns exist but are commented out); and
the sandbox's lack of egress and display established by test. `main.py` gained
`orderbook`. Engine ran clean at 07:56 PKT (50 symbols, 49 `good`); by 14:56 the
regime had flipped risk-off and all Buys were gated — NRL fell 3.5% the day
after the $6bn refinery signing was due, which is the sell-the-news risk flagged
in that morning's independent read.

Previously 2026-09-01: sector-news routing
fixed (7 -> 24 anchored sectors; the substring `ipp`/`sbp` mis-routes killed;
`SECTOR_NEWS_EXCLUDE` added) — this was why news never moved a score, NOT the
rater; soft downgrades now COLLECT instead of first-match-wins (signal
unchanged, every reason surfaced, and the risk-on what-if now needs the regime
gate to be the SOLE veto); `daily_eod` banks the EOD history `fetch_eod` was
discarding 24x a day; `confluence_axes.py` added, UNMEASURED and wired into
nothing; and **5 years of real daily High/Low backfilled** from PSX's historical
view.

Backfill result (run 33558311387, ~86 min, 0 request errors): **56,140 official
bars, 2021-09-01 .. 2026-07-31, all 50 symbols**, median 1,239 bars each. DB
6.9 -> 15.9 MB. Verified rather than assumed: `low > high` is **0** (High/Low
are not swapped), and the official close matched the engine's own recorded price
**10/10 exactly** for 2026-06-11 — two independent PSX endpoints agreeing to the
paisa. 10 bars where PSX reports O=H=L=0.00 (a session with no trades, JVDC and
BNL) were deleted and the parser now rejects them: a zero is not a price and
would collapse every ATR touching it. 29 bars (0.05%) keep a close outside the
traded range — a genuine PSX quirk on illiquid no-trade sessions, which true
range handles by design. SLM has only 53 bars because it listed 2026-06-15.

Previously 2026-08-27: `fetch_eod` fallback to banked bars ended a
total "No data" blackout, with `STALE prices (<date>)` surfacing the staleness;
DPS diagnosed (healthy — the fault was long-running-job state, restart fixes it);
tracked DB pruned 54 MB -> 6.9 MB with a nightly `db.prune()`; the routine's
`FORCE_RUN_TEST_2608` overrides removed. 2026-08-26: news now MOVES the score as
bounded +-8 / +-4 modifiers with causality damping (both UNMEASURED — run
`python main.py measure`); the Claude Routine became the primary rater and GLM
the fallback; the news read shows on EVERY signal card, falling back to the
sector rating (labelled) so a score that moved never shows a blank; Mettis
scraper added, then its date-text parser REVERTED for binding dates to the wrong
articles (~1 item/run now — raising it needs the listing's real per-item markup).
2026-08-24: concentration veto disabled; NRL close corrected to 526.29.

**Live operational cautions for the next session:**
- `mettisglobal.news` and `propakistani.pk` are still blocked in the ROUTINE's
  environment (Actions is fine) — the user must add them.
- GitHub cron missed EVERY trigger on 2026-08-27; the pre-open crons and the
  cron-job.org pinger all failed and the loop had to be dispatched by hand.
  Check the pinger is alive before relying on the 09:32 start.
- Do NOT dispatch a workflow in the same breath as pushing a change to it —
  indexing lags a push by minutes and the run is orphaned in `queued` forever.
  Two such zombies from 2026-08-26 could not be cancelled via the API (403).
  ~45s is enough; three dispatches on 2026-09-01 all started cleanly after that.
- **A running job's logs are unreadable via the API** (`get_job_logs` -> 404)
  but the WEB UI streams them live. The CLAUDE.md rule about cancelling a job to
  read its logs applies to the API path only — ask the user to read the browser.
- `confluence_axes` reports `trustworthy: False` until ~70 bars are available.
  Before the backfill every symbol failed that and `trend_quality` was None;
  with 1,239 bars banked both now resolve.
- **Streamlit Cloud serves the git snapshot from its last deploy.** After a
  session with code changes, the dashboard may need Manage app -> Reboot app.

Previously 2026-08-17 (end of session). Momentum-burst panel added and
measured; dashboard stripped of measured-noise sections; morning timing fixed
(MARKET_OPEN 09:15 → 09:32). Earlier the same day: four-day signal outage found and fixed
(`outcome_7d` missing from `update_outcome`'s whitelist — see "The outage that
froze signals"); `measure.py` independence checks; `poor_rr` veto DISABLED on
measured evidence; focus brief + exit ladder for NRL; sector news routing;
Streamlit pinned. Previously 2026-08-13 (early-warning tier + 7-day grading — see
"Early warning / lead time"). Previously 2026-08-12b (SIGNAL-QUALITY AUDIT — see "Signal quality audit"
below: Buy threshold 70→75, confluence gate removed, pullback upgrade removed,
RS veto 45→55, dead High-risk branch removed, concentration veto added, Buy
grading made benchmark-relative). Earlier same day (pure-technical mode: news/sentiment vetoes
downgraded to warnings; chase guard off; pullback/extension reference EMA
20 → 50). Previously: 2026-07-15 (news relevance-anchor gate stops cross-company
mis-attribution; regime what-if moved to main page; password-safe auto-refresh.
Earlier same-day: GLM free-tier key live + timeout fix, GLM-news-read panel,
risk-on what-if surfaces regime-gated Buys; deep signal-quality audit — pullback
quality gate, RS laggard veto, strict-history confidence).

### Current working context
- All recent work is committed directly to `main`. 2026-08-17 commits:
  `f57d769` pin streamlit==1.61.1, `387f016` trade-card prices as markdown,
  `96ae2ab` engine loop surfaces tracebacks + 09:35 cron, `57ee524` the
  `outcome_7d` fix that ended the outage, `1d816f5` focus brief, `ecfdce1` exit
  ladder + null-P&L guards, `254a926` cost-aware ladder, `10dc641` evening
  refreshes the brief, `5380740` measure.py + sector news + crowding,
  `8a2b65f` poor_rr veto disabled.
- **Real book (`portfolio.json`) re-synced 2026-08-21 10:15 PKT** from the
  KTrade custody screen — five positions, cash (Long Limit Avl) PKR 871,036:
  NRL 2,139 @ 491.55, PIBTL 5,000 @ 17.17, FABL 66 @ 97.09, PSO 4 @ 381.80,
  PRL 1 @ 36.29. Every per-line P&L reconciles exactly against the terminal's
  own "Total gain/loss" column, so the read is verified, not inferred.
  **The NRL cost basis moved 535.26 → 491.55** (the terminal also showed 1,192
  bought / 1,000 sold that session, so the user has been actively averaging).
  At 492.98 the position is **+PKR 3,059, marginally IN profit** — the previous
  note that it was under water no longer holds, and the cost-aware exit ladder
  now prices all three tranches as gains rather than making tranche 1 wait for
  breakeven. Concentration is UNCHANGED as the live problem: NRL is **52.3% of
  equity** (92.2% of holdings ex-cash), still far above the 25% single-name cap,
  though the `concentrated` veto is DISABLED as of 2026-08-24 and no longer
  fires at all. Averaging down cut the loss, not the
  risk. GHNI (300) and FCEPL (1,000) are GONE from the book; PIBTL halved
  10,000 → 5,000; PSO cut 1,041 → 4 and FCEPL's exit means the 08-18 sync is
  stale wherever it is quoted.
- **Dashboard was never rebooted on 08-17**, so the user saw a pre-deploy
  snapshot ("08-13, 92.2h old") all day. Streamlit Cloud serves the git
  snapshot from its last deploy — Manage app → Reboot app is required before
  any of this is visible.
- **`st.metric` is fragile on mobile.** It ships in a lazily-imported JS chunk;
  a cached page shell from an earlier Cloud build 404s it and renders
  "TypeError: Importing a module script failed" in the widget's slot. Trade
  cards now use `price_row()` markdown instead. **18 other `st.metric` call
  sites remain** (Portfolio heat tiles, Edge metrics, Stock detail header) —
  convert them the same way if they break. `plotly` is still unpinned and has
  the same failure mode.
- **Reviewed but NOT changed (user's call):** #4 "is it 360°?" — the technical
  analyzer IS multi-indicator (RSI/MACD/EMA20-50-200/Bollinger/OBV/ADX/ATR/CMF/
  S-R/momentum/volume/candles/4-dim confluence), but `config.WEIGHTS` is
  technical 1.0 / fundamentals 0.0 / macro 0.0 / sentiment 0.0, so final_score
  is 100% technical — NO fundamental/valuation input. User chose to KEEP it
  100% technical (do not re-enable fundamentals without a data audit + explicit
  OK). As of 2026-08-12 the engine is PURELY technical end-to-end — see the
  "Pure technicals + 50-EMA reference" section; the reference EMA for the
  pullback zone / extension is now the 50-EMA and the chase guard is off.
- **GLM free-tier second opinion is LIVE.** `GLM_API_KEY` secret is set and
  valid; `news_glm_ratings.json` is written each news run (19 symbols last run).
  If it goes dark again, read the `news.yml` GLM step LOG (it's `|| true`, so the
  step conclusion lies): 401 = bad key, 60s+ timeout = slow China endpoint.
- News routine is fully operational and has been run daily (latest: commit
  `3f382f5`, "News routine 2026-06-24"). Follow the two-stage pipeline in the
  "Run the repo news" section above, and ALWAYS run the URL-verification script
  (below) before committing `news_signals.json`.
- Live PSX DPS is 403 in-sandbox → all live analysis uses stored data via
  `db.last_run()` / `db.run_history()`, and independent analysis is qualitative
  (never fabricate live prices/valuations).

### News URL-verification script (MANDATORY before every news commit)
```python
import json
d = json.load(open('news_signals.json'))
raw = json.load(open('news_raw_24h.json'))
raw_urls = set(it['url'] for it in raw['items'])
bad = [(s, u) for s, v in d['signals'].items() for u in v['sources'] if u not in raw_urls]
print('Unverified URLs:', bad)   # MUST be []
```
Common trap: copying URLs from a truncated `[:80]`-sliced exploration print.
Fix by patching each source from the raw fetch programmatically, never retyping.

### In-flight / recent analysis threads
- **PSO** (user's portfolio is ~83% PSO, avg ~363.8, in loss): covered backtest
  mechanics, relative-strength calc, and a 6-month averaging strategy. Key take:
  concentration is the real risk, not PSO itself; tranche around the 344.54 stop,
  diversify into PRL. Engine last had PSO at "Avoid" (score 45, news-driven).
- **KMI-30 independent top picks (2026-06-24):** MARI (top conviction — Shams-1
  gas catalyst, cleanest E&P balance sheet), MEBL (rate-cycle Islamic bank),
  OGDC (Sahito-1 catalyst but oil-price hedged), a fertilizer name (EFERT/FFC,
  defensive income). Avoid pure oil-beta (PPL) and PSO into falling oil.
- **MARI deep-dive → `analysis/MARI_verification_checklist.md`** (committed). Six
  numbers to verify (Shams-1 volume, valuation multiple, dividend, RRR, net cash,
  % market-linked output) with a buy/wait/pass decision rule. This is the current
  active deliverable — next step is filling those six numbers from PSX/financials.

### Parked (only resume if user asks)
- Item #5 from an earlier "start with 2, then 3 and then 5" instruction: a PSO
  confluence-dimension breakdown (trend/momentum/volume/structure) — never done.
