"""macro_news_analyzer.py — Computes the 40% macro / industry / fundamentals
/ news score and builds the written explanation per stock.

Inputs:
  * Macro anchors from config (policy rate, CPI, USD/PKR, reserves) — manually
    maintained with as-of dates; stale or empty anchors lower confidence.
  * Public news headlines (macro, sector, company) scored by keyword/polarity.
  * A per-sector driver map so the explanation is sector-aware.

The module NEVER invents fundamentals. Where audited financials are not
wired in, it says so and relies on news + macro context, flagging the gap.
"""

import logging
from datetime import datetime

import config
import database as db
from sentiment_analyzer import _polarity  # reuse polarity engine

log = logging.getLogger("macro")

MACRO_KEYWORDS = {
    "rates": ["policy rate", "interest rate", "monetary policy", "sbp", "mpc"],
    "inflation": ["inflation", "cpi"],
    "fx": ["rupee", "usd", "exchange rate", "pkr"],
    "reserves": ["reserves", "foreign exchange reserves"],
    "imf": ["imf", "bailout", "programme review", "tranche"],
    "policy": ["budget", "tax", "subsidy", "tariff", "psdp", "circular debt"],
}

SECTOR_DRIVERS = {
    "Oil Marketing": ["oil price", "petroleum levy", "circular debt", "fuel demand", "margins"],
    "Islamic Banking": ["policy rate", "deposit growth", "advances", "adr", "islamic banking"],
    "Technology/IT Exports": ["it exports", "remote work", "dollar revenue", "rupee depreciation"],
    "Technology/Telecom Devices": ["smartphone", "import duty", "assembly", "lc restrictions"],
    "Cement/Conglomerate": ["cement dispatches", "construction", "coal price", "psdp"],
    "Fertilizer": ["urea", "gas price", "offtake", "subsidy", "agriculture"],
    "Oil & Gas Exploration": ["oil price", "gas price", "wellhead", "exploration", "circular debt"],
    "Diversified/Consumer": ["consumer demand", "raw material", "margins"],
}


def _anchor_status():
    notes, stale = [], 0
    for k, v in config.MACRO_ANCHORS.items():
        if v["value"] is None:
            notes.append(f"Macro anchor '{k}' not set — update config.MACRO_ANCHORS "
                         f"from {v['source']}.")
            stale += 1
        elif v["as_of"]:
            try:
                age = (datetime.now() - datetime.fromisoformat(v["as_of"])).days
                if age > config.MACRO_STALE_DAYS:
                    notes.append(f"Macro anchor '{k}' is {age} days old — refresh it.")
                    stale += 1
            except Exception:
                pass
    return notes, stale


def analyze(symbol, news_items):
    """Returns dict: score (0-100), explanation, components, notes."""
    sector = config.SECTORS.get(symbol, "Unknown")
    notes, components = [], {}

    anchor_notes, stale_count = _anchor_status()
    notes += anchor_notes

    all_titles = [n["title"] for n in news_items] + \
                 [n["title"] for n in db.recent_news(72)]
    all_titles = list(dict.fromkeys(all_titles))

    # ---- 1) Macro environment score (0-100) from macro headlines
    macro_hits, macro_pol = [], []
    for t in all_titles:
        low = t.lower()
        for theme, kws in MACRO_KEYWORDS.items():
            if any(k in low for k in kws):
                macro_hits.append((theme, t))
                macro_pol.append(_polarity(t))
                break
    macro_score = 50 + (sum(macro_pol) / len(macro_pol)) * 40 if macro_pol else 50
    components["macro_environment"] = round(macro_score, 1)
    if not macro_pol:
        notes.append("No macro headlines captured this run — macro component "
                     "neutral with low confidence.")

    # ---- 2) Sector score from sector-driver headlines
    drivers = SECTOR_DRIVERS.get(sector, [])
    sector_pol = [_polarity(t) for t in all_titles
                  if any(d in t.lower() for d in drivers)]
    sector_score = 50 + (sum(sector_pol) / len(sector_pol)) * 40 if sector_pol else 50
    components["sector"] = round(sector_score, 1)

    # ---- 3) Company news score
    comp_titles = [n["title"] for n in db.recent_news(96, symbol)]
    comp_pol = [_polarity(t) for t in comp_titles]
    comp_score = 50 + (sum(comp_pol) / len(comp_pol)) * 45 if comp_pol else 50
    components["company_news"] = round(comp_score, 1)
    if not comp_titles:
        notes.append(f"No company-specific headlines for {symbol} in the last "
                     "96h — company component neutral.")

    # ---- 4) Fundamentals placeholder honesty
    notes.append("Audited fundamentals (revenue/profit growth, margins, debt, "
                 "cash flow, dividends) are not auto-ingested in this version. "
                 "Review the latest quarterly report on PSX before any Buy. "
                 "Score relies on macro + sector + news components.")

    # Weighted blend: macro 35%, sector 30%, company news 35%
    score = round(0.35 * macro_score + 0.30 * sector_score + 0.35 * comp_score, 1)

    bad_news = [t for t in comp_titles if _polarity(t) < -0.4]
    explanation = _explain(symbol, sector, components, macro_hits[:5],
                           comp_titles[:5], bad_news)

    return {"symbol": symbol, "score": score, "components": components,
            "explanation": explanation, "notes": notes,
            "bad_news_flag": bool(bad_news), "bad_news": bad_news[:3],
            "low_confidence": stale_count >= 3 or (not macro_pol and not comp_titles),
            "sources": "Public RSS feeds (Business Recorder, Dawn, Profit, "
                       "Mettis) + config macro anchors"}


def _explain(symbol, sector, comp, macro_hits, comp_titles, bad_news):
    lines = [f"{symbol} ({sector}): macro environment component "
             f"{comp['macro_environment']}/100, sector component "
             f"{comp['sector']}/100, company news component "
             f"{comp['company_news']}/100."]
    if macro_hits:
        themes = ", ".join(sorted({t for t, _ in macro_hits}))
        lines.append(f"Macro themes in play: {themes}.")
    if comp_titles:
        lines.append("Recent company headlines: " +
                     " | ".join(t[:90] for t in comp_titles[:3]))
    if bad_news:
        lines.append("⚠ Negative company news detected — treated as a risk "
                     "override candidate.")
    if not macro_hits and not comp_titles:
        lines.append("Limited news flow this run; assessment is neutral by "
                     "construction, not by conviction.")
    return " ".join(lines)
