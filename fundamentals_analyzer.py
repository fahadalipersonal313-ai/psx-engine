"""fundamentals_analyzer.py — Scores a stock's audited fundamentals to 0-100.

Reads ratios from config.FUNDAMENTALS (a manually maintained table — same honest
pattern as MACRO_ANCHORS). The engine NEVER invents fundamentals: any symbol with
no entry scores a neutral 50 and is flagged low_confidence so the weight-aware
confidence penalty kicks in. Fill the table from the latest quarterly/annual
report to activate this layer.

Per-symbol dict keys (all optional): pe, eps_growth (%), roe (%),
de (debt/equity ratio), div_yield (%).
"""

import json
import os

import config

log_neutral = 50.0

# Auto-fetched ratios cache (written by fundamentals_fetcher.py). Manual entries
# in config.FUNDAMENTALS override anything here.
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "fundamentals.json")


def _load_cache():
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"data": {}, "as_of": None}


_CACHE = _load_cache()


def _lin(x, lo, hi, lo_score, hi_score):
    """Linear map x in [lo,hi] -> [lo_score,hi_score], clamped."""
    if x is None:
        return None
    if hi == lo:
        return hi_score
    t = (x - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    return lo_score + t * (hi_score - lo_score)


def analyze(symbol):
    # Merge auto-fetched cache with manual config overrides (config wins).
    data = dict(_CACHE.get("data", {}).get(symbol, {}))
    data.update((getattr(config, "FUNDAMENTALS", {}) or {}).get(symbol, {}))
    as_of = (getattr(config, "FUNDAMENTALS_AS_OF", "") or _CACHE.get("as_of")
             or "n/a")
    if not data:
        return {"symbol": symbol, "score": log_neutral, "low_confidence": True,
                "as_of": as_of, "have": [],
                "notes": ["No fundamentals data — neutral 50. Run "
                          "`python fundamentals_fetcher.py` or add "
                          f"config.FUNDAMENTALS['{symbol}']."]}

    parts, have, notes = [], [], []
    pe = data.get("pe")
    if pe is not None and pe > 0:                 # lower P/E better
        parts.append(_lin(pe, 5, 25, 100, 20)); have.append(f"P/E {pe}")
    g = data.get("eps_growth")
    if g is not None:                             # higher EPS growth better
        parts.append(_lin(g, -10, 25, 10, 100)); have.append(f"EPSg {g}%")
    roe = data.get("roe")
    if roe is not None:                           # higher ROE better
        parts.append(_lin(roe, 5, 25, 20, 100)); have.append(f"ROE {roe}%")
    de = data.get("de")
    if de is not None:                            # lower debt/equity better
        parts.append(_lin(de, 0.3, 2.0, 100, 20)); have.append(f"D/E {de}")
    dy = data.get("div_yield")
    if dy is not None:                            # higher yield better
        parts.append(_lin(dy, 0, 8, 40, 100)); have.append(f"DY {dy}%")

    parts = [p for p in parts if p is not None]
    if not parts:
        return {"symbol": symbol, "score": log_neutral, "low_confidence": True,
                "as_of": as_of, "have": [],
                "notes": ["Fundamentals entry present but no usable ratios — "
                          "neutral 50."]}

    score = round(sum(parts) / len(parts), 1)
    thin = len(parts) < 2                         # 1 ratio = thin, low confidence
    notes.append(f"Fundamentals ({as_of}): " + ", ".join(have)
                 + ". Verify against the latest quarterly before acting.")
    return {"symbol": symbol, "score": score, "low_confidence": thin,
            "as_of": as_of, "have": have, "notes": notes}
