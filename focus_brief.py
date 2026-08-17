"""focus_brief.py — One deep, position-aware morning brief for a single symbol.

Aggregates EVERYTHING the engine already knows about `config.FOCUS_SYMBOL` into
one stored verdict: the technical read, the market regime, relative strength,
money flow, the structural levels, the real book position, the unscored news
window, and the symbol's own graded track record.

It does NOT invent a new score or a new signal. The action is derived from the
engine's own validated signal plus the position you actually hold — a Buy you
already own 43% of is a different decision from a Buy you own none of, and that
is the gap this module closes.

Honest gaps are reported, never papered over: fundamentals are absent for most
of the universe (config.WEIGHTS is technical 1.0), and news carries zero weight.
"""

import json
import logging

import config
import database as db
import news_feed

log = logging.getLogger("focus_brief")

FLAG_LABEL = {
    "trend": "Price above 50-EMA",
    "rsi": "RSI in healthy range",
    "macd": "MACD histogram positive",
    "obv": "OBV rising (volume confirms)",
    "momentum": "20-day momentum positive",
    "bb": "Bollinger position constructive",
    "rs": "Outperforming KMI30",
    "accumulation": "Accumulation footprint",
}


def _pct(a, b):
    """Percent move from a to b; None when either side is missing."""
    if a in (None, 0) or b is None:
        return None
    return (b - a) / a * 100


def _position(symbol, advice):
    """This symbol's slice of the real book, or None if not held."""
    for h in (advice or {}).get("holdings", []):
        if h.get("symbol") == symbol:
            return h
    return None


def _track_record(symbol):
    """The symbol's OWN graded history. Small samples are labelled noise rather
    than presented as edge."""
    try:
        rows = db.signal_accuracy_summary(symbol=symbol) or []
    except Exception:
        return []
    out = []
    for r in rows:
        r = dict(r)
        r["is_noise"] = (r.get("n_confidence") != "high")
        out.append(r)
    return out


def _levels(row):
    price = row.get("price")
    stop, t1 = row.get("stop_loss"), row.get("target1")
    sup, res = row.get("support"), row.get("resistance")
    risk_pct = _pct(price, stop)
    reward_pct = _pct(price, t1)
    rr = None
    if price and stop and t1 and price > stop:
        rr = (t1 - price) / (price - stop)
    return {"price": price, "stop": stop, "target1": t1, "target2": row.get("target2"),
            "support": sup, "resistance": res,
            "risk_pct": risk_pct, "reward_pct": reward_pct, "rr": rr,
            "to_support_pct": _pct(price, sup), "to_resistance_pct": _pct(price, res),
            "buy_zone_low": row.get("buy_zone_low"),
            "buy_zone_high": row.get("buy_zone_high")}


def _add_size(price, stop, cash, equity, current_value):
    """Shares an ADD could take, bounded by per-trade risk, the position cap and
    cash. Mirrors risk_manager's rules so the brief cannot suggest a size the
    engine would refuse."""
    if not price or price <= 0 or not cash or cash <= 0:
        return 0, 0.0
    risk_budget = (equity or 0) * config.RISK["max_risk_per_trade_pct"] / 100
    per_share_risk = (price - stop) if (stop and price > stop) else None
    by_risk = (risk_budget / per_share_risk) if per_share_risk else 0
    cap_value = (equity or 0) * config.RISK["max_position_pct"] / 100
    room = max(cap_value - (current_value or 0), 0)
    by_cap = room / price
    by_cash = cash / price
    shares = int(max(min(by_risk, by_cap, by_cash), 0))
    return shares, shares * price


def exit_plan(qty, price, stop, target1, equity, cap_pct):
    """Scaled exit ladder for an oversized winner. Sells in tranches rather than
    all at once: on this engine's own graded history, score>=75 names that had
    already run >8% in the prior 5 sessions went ON to beat the market 92% of
    the time (n=13, small), so a full exit into strength has been the worse
    trade. The ladder banks the concentration risk while leaving a runner.

    Returns [] when the position is not oversized — nothing to unwind."""
    if not (qty and price and equity):
        return []
    cap_shares = cap_pct / 100 * equity / price
    excess = qty - cap_shares
    if excess <= 0:
        return []
    first = int(excess // 2)
    second = int(excess) - first
    runner = int(qty - first - second)
    plan = []
    if first:
        plan.append({"tranche": "1 — de-risk now", "shares": first,
                     "trigger": f"at market (~{price:,.2f})",
                     "proceeds": first * price,
                     "why": "Removes the single-name risk that no stop protects: "
                            "a gap through your stop takes the whole book with it."})
    if second:
        plan.append({"tranche": "2 — reach the cap", "shares": second,
                     "trigger": f"on strength above {price * 1.03:,.2f} "
                                f"(+3%), or at market if momentum stalls",
                     "proceeds": second * price * 1.03,
                     "why": f"Brings the position to the {cap_pct:.0f}% cap while "
                            "selling into demand rather than into a fall."})
    if runner > 0:
        plan.append({"tranche": "3 — runner", "shares": runner,
                     "trigger": f"trail below {stop:,.2f}; take profit at "
                                f"{target1:,.2f}" if stop and target1 else "trail the stop",
                     "proceeds": runner * (target1 or price),
                     "why": "Keeps the upside the engine's Buy signal is pointing "
                            "at, sized so a stop-out is survivable."})
    return plan


def build(symbol=None, advice=None):
    """Return the brief dict, or None when there is no stored run to build on."""
    symbol = (symbol or config.FOCUS_SYMBOL).upper()
    row = db.last_run(symbol)
    if not row:
        return None
    row = dict(row)

    try:
        flags = json.loads(row.get("tech_flags") or "{}")
    except (json.JSONDecodeError, TypeError):
        flags = {}

    pos = _position(symbol, advice)
    totals = (advice or {}).get("totals") or {}
    equity = totals.get("equity")
    cash = totals.get("cash") or 0
    lv = _levels(row)
    pos_pct = (pos or {}).get("pos_pct")
    held_value = (pos or {}).get("qty", 0) * (lv["price"] or 0) if pos else 0

    cap = config.RISK["max_existing_concentration_pct"]
    over_cap = pos_pct is not None and pos_pct > cap
    signal = row.get("signal")
    in_zone = (lv["buy_zone_low"] is not None and lv["buy_zone_high"] is not None
               and lv["price"] is not None
               and lv["buy_zone_low"] <= lv["price"] <= lv["buy_zone_high"])
    breakdown = (lv["price"] is not None and lv["support"] is not None
                 and lv["price"] < lv["support"])

    add_shares, add_value = (0, 0.0)
    if not over_cap and signal in ("Buy", "Strong Buy") and in_zone:
        add_shares, add_value = _add_size(lv["price"], lv["stop"], cash, equity,
                                          held_value)

    # Action ladder — first match wins, mirroring the engine's own precedence:
    # structure first, then concentration, then the signal, then the entry zone.
    if breakdown or signal == "Exit":
        action, why = "REDUCE / EXIT", (
            "Price is below support — the structural stop case, not a dip to buy.")
    elif not pos:
        if signal in ("Buy", "Strong Buy") and in_zone:
            action, why = "OPEN (in buy-zone)", "Engine Buy and price sits inside the buy-zone."
        elif signal in ("Buy", "Strong Buy"):
            action, why = "WAIT FOR ZONE", "Engine Buy, but price is outside the buy-zone."
        else:
            action, why = "NO ACTION", f"Engine signal is {signal} — not an entry."
    elif over_cap:
        action, why = "HOLD — DO NOT ADD", (
            f"This position is {pos_pct:.1f}% of your book, above the "
            f"{cap:.0f}% single-name cap. Trimming or holding is fine; adding "
            f"compounds concentration risk.")
    elif signal in ("Buy", "Strong Buy") and in_zone:
        action, why = "ADD", "Engine Buy, price inside the buy-zone, room under the cap."
    elif signal in ("Buy", "Strong Buy"):
        action, why = "HOLD (add only on pullback)", (
            "Engine Buy, but price is outside the buy-zone — adding here buys extension.")
    else:
        action, why = "HOLD", f"Engine signal is {signal} — hold, no add."

    gaps = []
    if symbol not in (config.FUNDAMENTALS or {}) and not config.FUNDAMENTALS_AS_OF:
        gaps.append("No fundamentals on file — this read is price/volume only, "
                    "with no valuation or earnings input.")
    if config.WEIGHTS.get("macro_news", 0) == 0:
        gaps.append("News carries zero score weight — headlines below are for "
                    "manual cross-check only.")
    if (pos or {}).get("avg_cost") is None and pos:
        gaps.append("No average cost recorded for this position, so unrealised "
                    "P&L cannot be computed.")

    return {
        "symbol": symbol,
        "run_time": row.get("run_time"),
        "action": action,
        "why": why,
        "signal": signal,
        "final_score": row.get("final_score"),
        "confidence": row.get("confidence"),
        "risk_level": row.get("risk_level"),
        "main_reason": row.get("main_reason"),
        "shariah": row.get("shariah_status"),
        "data_quality": row.get("data_quality"),
        "regime": row.get("market_regime"),
        "relative_strength": row.get("relative_strength"),
        "confluence": row.get("confluence"),
        "cmf": row.get("cmf"),
        "early_watch": row.get("early_watch"),
        "early_reason": row.get("early_reason"),
        "flags": {FLAG_LABEL.get(k, k): bool(v) for k, v in flags.items()},
        "levels": lv,
        "in_zone": in_zone,
        "position": {"qty": (pos or {}).get("qty"),
                     "avg_cost": (pos or {}).get("avg_cost"),
                     "value": held_value or None,
                     "pos_pct": pos_pct,
                     "pl_pct": (pos or {}).get("pl_pct")} if pos else None,
        "cash": cash,
        "equity": equity,
        "add_shares": add_shares,
        "add_value": add_value,
        "over_cap": over_cap,
        "exit_plan": exit_plan((pos or {}).get("qty"), lv["price"], lv["stop"],
                               lv["target1"], equity, cap) if pos else [],
        "headlines": news_feed.raw_headlines(symbol, limit=5),
        "glm": news_feed.glm_rating(symbol),
        "track_record": _track_record(symbol),
        "gaps": gaps,
    }


def render_text(b):
    """Plain-text brief for the CLI and the morning report."""
    if not b:
        return "No stored run for the focus symbol yet."
    L = b["levels"]
    f = lambda x, d=2: "—" if x is None else f"{x:,.{d}f}"
    out = [f"=== {b['symbol']} morning brief — {b['action']} ===",
           f"{b['why']}",
           "",
           f"Engine signal : {b['signal']}  (score {f(b['final_score'], 1)}, "
           f"confidence {f(b['confidence'], 0)}%, {b['risk_level']} risk)",
           f"Regime        : {b['regime']}   RS {f(b['relative_strength'], 0)}   "
           f"confluence {b['confluence']}/4   CMF {f(b['cmf'])}",
           f"Shariah       : {b['shariah']}   data {b['data_quality']}",
           ""]
    if b["position"]:
        p = b["position"]
        out += [f"Position      : {f(p['qty'], 0)} shares @ market {f(L['price'])} "
                f"= PKR {f(p['value'], 0)} ({f(p['pos_pct'], 1)}% of book)",
                f"Unrealised    : {'unknown (no avg cost)' if p['pl_pct'] is None else f(p['pl_pct'], 1) + '%'}",
                f"Cash          : PKR {f(b['cash'], 0)}", ""]
    out += [f"Stop          : {f(L['stop'])}  ({f(L['risk_pct'], 1)}%)",
            f"Target 1      : {f(L['target1'])}  ({f(L['reward_pct'], 1)}%)   R:R {f(L['rr'], 1)}",
            f"Support/Res   : {f(L['support'])} / {f(L['resistance'])}",
            f"Buy-zone      : {f(L['buy_zone_low'])}–{f(L['buy_zone_high'])}"
            f"   (price {'INSIDE' if b['in_zone'] else 'outside'})", ""]
    if b["add_shares"]:
        out += [f"Sizing        : an add of up to {b['add_shares']:,} shares "
                f"(PKR {f(b['add_value'], 0)}) fits risk + position caps", ""]
    if b.get("exit_plan"):
        out.append("SCALED EXIT LADDER (position is over the single-name cap):")
        for t in b["exit_plan"]:
            out.append(f"  {t['tranche']}: {t['shares']:,} shares — {t['trigger']}")
            out.append(f"      ~PKR {t['proceeds']:,.0f}. {t['why']}")
        out.append("")
    on = [k for k, v in b["flags"].items() if v]
    off = [k for k, v in b["flags"].items() if not v]
    out += ["Confirming    : " + (", ".join(on) or "none"),
            "Not confirming: " + (", ".join(off) or "none"), ""]
    if b["headlines"]:
        out.append("News last 24h (UNSCORED — verify manually):")
        out += [f"  - {h['title']} [{h['publisher']}]" for h in b["headlines"]]
    else:
        out.append("News last 24h: none matched this company.")
    if b["glm"]:
        out.append(f"GLM second opinion: {b['glm'].get('rating')} — {b['glm'].get('reason', '')}")
    out.append("")
    for t in b["track_record"]:
        flag = "  [SMALL SAMPLE — noise, not edge]" if t.get("is_noise") else ""
        out.append(f"Track record  : {t.get('signal')} {t.get('n_worked')}/"
                   f"{t.get('n_total')} ({t.get('win_rate_pct')}%){flag}")
    if b["gaps"]:
        out.append("")
        out.append("Known gaps:")
        out += [f"  ! {g}" for g in b["gaps"]]
    out += ["", "Manual confirmation REQUIRED before any order — decision support, "
            "not financial advice."]
    return "\n".join(out)
