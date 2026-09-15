# Re-measuring the regime gate at the 30-session horizon (2026-09-15)

Reproduce with `python tools/measure_regime_gate.py`.

## Why this was re-run

The gate was audited on 2026-09-05 (`dfba5ee`) and kept. That audit measured a
**10-session** horizon, which was the v4 execution contract at the time. v5
moved the contract to **30 sessions**, and the horizon grid had already shown
that expectancy changes a great deal with the exit rule. v7 then disabled the
gate on the user's instruction. So the only evidence about the gate was taken
under an execution contract the engine no longer uses.

## Method

Deliberately identical to the 2026-09-05 audit, so the two are comparable. Only
the horizon differs.

- **Absolute returns**, not the same-day cross-sectional excess used everywhere
  else in this repo. A market-wide rule is differenced away exactly by a
  same-day benchmark.
- **Regime proxy**: equal-weight index of our own names (KMI30 is not stored
  historically), compounded from the **mean** daily return, versus its
  `REGIME_EMA_SPAN` (40) EMA. Compounding the *median* was the bug that produced
  the first, wrong answer in September.
- **Entry rule**: EMA10>20>40 with EMA40 rising, positive 10-session momentum,
  `CMF >= BUY_MIN_CMF` (-0.15), and the v6 liquidity floor
  (`median 20-day PKR turnover >= MIN_TURNOVER_PKR`). This approximates the
  technical core the gate sits in front of; it is **not** the full `decide()`.
- Reported at both **trade level** and **session level**, because the session is
  the independent unit but collapsing to one number per session weights a quiet
  3-candidate day equally with a busy 40-candidate day — which is precisely what
  reversed the original result.

Panel: 59 symbols x 1,249 sessions, 2021-09-01 to 2026-09-14.
752 risk-on sessions, 457 risk-off, 40 unknown (insufficient EMA history).

## The 10-session result reproduces the September audit

| regime | trades | mean % | median % | p90 % | win % |
|---|---|---|---|---|---|
| risk-on | 13,925 | **1.78** | 0.28 | 14.37 | 51.5 |
| risk-off | 1,795 | **0.48** | -0.35 | 10.15 | 48.0 |

The September audit reported p90 of +14.14% risk-on against +10.15% risk-off.
This run gives 14.37 and **10.15** — the risk-off figure matches exactly. The
means differ slightly (1.78/0.48 here against 1.45/0.64 then), which is expected:
the universe and the banked history both changed with the 2026-09-08 backfill,
and this entry rule is an approximation. Direction and magnitude reproduce, so
the method is sound.

**At 10 sessions the gate is justified**: risk-on earns 3.7x the mean with 7.8x
the opportunities.

## At 30 sessions the picture changes

| regime | trades | sessions | mean % | median % | p90 % | win % | session-mean % |
|---|---|---|---|---|---|---|---|
| risk-on | 13,536 | 727 | **4.60** | 0.92 | 28.52 | 52.4 | 4.47 |
| risk-off | 1,797 | 396 | **2.84** | -0.25 | 19.66 | 48.8 | 3.50 |

Risk-on still leads on the pooled mean (+1.76pp), but the relationship is much
weaker than at 10 sessions:

- Risk-off captures **62%** of risk-on's mean at 30 sessions, against **27%** at
  10. The longer horizon lifts risk-off disproportionately (0.48 -> 2.84, a 5.9x
  increase, against risk-on's 1.78 -> 4.60, 2.6x).
- At the **session** level — the independent unit — the gap is only **0.97pp**.
- Risk-off expectancy is solidly **positive**: +2.84% per trade over 30 sessions.

## Risk-off is also the safer side, not just the quieter one

| horizon | regime | p10 % | p25 % | worst % | share < -10% |
|---|---|---|---|---|---|
| 30 | risk-on | -15.08 | -7.98 | -88.35 | 20.1 |
| 30 | risk-off | **-12.94** | **-6.97** | -79.18 | **16.0** |

The September audit called this "a genuine trade-off ... risk-off is marginally
safer on drawdown; risk-on is more than twice as profitable". At 30 sessions the
safety advantage survives while the profitability advantage shrinks to 1.76pp
pooled and 0.97pp per session.

## The per-year split is the real finding

30-session mean, trades in brackets:

| year | risk-on | risk-off |
|---|---|---|
| 2021 | -9.67 (20) | -5.29 (96) |
| 2022 | -8.34 (768) | -2.39 (665) |
| 2023 | +7.60 (2,767) | +5.27 (465) |
| 2024 | +9.82 (3,932) | **+15.60 (170)** |
| 2025 | +3.20 (4,112) | **+6.16 (236)** |
| 2026 | **-2.05 (1,937)** | **+3.86 (165)** |

**Risk-off beats risk-on in each of the last three years.** In 2026 — the
Iran-US war year that dominates recent data — risk-on is *negative* (-2.05%)
while risk-off is *positive* (+3.86%). The pooled five-year advantage for
risk-on is carried entirely by 2022 and 2023.

## Conclusion

The 2026-09-05 decision to keep the gate was correct **for the contract it was
measured under**. At the 30-session horizon the engine actually runs, the
evidence no longer supports vetoing Buys in a falling market:

1. Risk-off expectancy is positive and substantial (+2.84% per trade).
2. Risk-off has lower downside on every percentile measured.
3. Risk-off has outperformed risk-on for three consecutive years.

So **v7 (`REGIME_GATE_ENABLED = False`) is supported by this measurement**, and
the gate was withholding positive-expectancy trades — in the last three years,
the better half of them.

## What this does NOT establish

- **Not demonstrated profitability.** These are absolute returns including
  market drift, with no costs, slippage or queue availability. The v7 contract
  still has no prospectively resolved cohort.
- **Overlapping windows.** 30-session forward returns from consecutive sessions
  are heavily autocorrelated, so the effective sample is far smaller than the
  trade counts suggest. Treat the per-year risk-off rows especially carefully:
  170, 236 and 165 trades, drawn from 396 sessions in total.
- **Approximate entry rule**, not the real `decide()`. It reproduces the
  September numbers well enough to trust the comparison, not well enough to
  quote as engine performance.
- **The median is still negative in risk-off** (-0.25%). As with the horizon
  study, the gain is tail-driven: most risk-off trades still lose slightly and
  the mean is carried by winners. Do not read +2.84% as a typical trade.
