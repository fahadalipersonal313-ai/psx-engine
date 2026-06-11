"""reports.py — Builds the clean human-readable report after every run, plus
morning (9 AM) and evening (9 PM) summaries. Reports are printed and saved
to reports_out/ as markdown."""

import os
import logging
from datetime import datetime

import config
import database as db

log = logging.getLogger("reports")


def _fmt(v, nd=2):
    return f"{v:,.{nd}f}" if isinstance(v, (int, float)) and v is not None else "n/a"


def build_run_report(results, market_notes):
    """results: list of per-stock result dicts from main.analyze_stock."""
    ranked = sorted([r for r in results if r["shariah"]["eligible_for_ranking"]],
                    key=lambda r: r["scoring"]["final_score"], reverse=True)
    excluded = [r for r in results if not r["shariah"]["eligible_for_ranking"]]

    lines = [f"# PSX Shariah Engine Report — {datetime.now():%Y-%m-%d %H:%M}",
             "", "## Market summary",
             market_notes or "No macro headlines captured this run.",
             "", "## Top 10 ranking (shariah-verified only)", ""]
    hdr = ("| # | Stock | Shariah | Final | Macro | Sent | Tech | Price | "
           "Support | Resist | Entry zone | Stop | Target | Risk | Signal | Conf |")
    lines += [hdr, "|" + "---|" * 16]
    for i, r in enumerate(ranked[:10], 1):
        t, s = r["technical"], r["scoring"]
        entry = (f"{_fmt(t.get('support'))}–{_fmt(t.get('ema20'))}"
                 if t.get("support") else "n/a")
        lines.append(
            f"| {i} | {r['symbol']} | {r['shariah']['status'].split('(')[0].strip()} "
            f"| {s['final_score']} | {s['breakdown']['macro_news']} "
            f"| {s['breakdown']['sentiment']} | {s['breakdown']['technical']} "
            f"| {_fmt(t.get('price'))} | {_fmt(t.get('support'))} "
            f"| {_fmt(t.get('resistance'))} | {entry} | {_fmt(t.get('stop_loss'))} "
            f"| {_fmt(t.get('target1'))} | {r['risk']['risk_level']} "
            f"| {r['signal']['signal']} | {s['confidence']}% |")

    lines += ["", "## Per-stock detail", ""]
    for r in ranked:
        lines += [f"### {r['symbol']} — {r['signal']['signal']} "
                  f"({r['scoring']['confidence']}% confidence, "
                  f"{r['risk']['risk_level']} risk)",
                  f"- Why: {'; '.join(r['signal']['reasons'])}",
                  f"- Main risk: {r['risk']['warnings'][0] if r['risk']['warnings'] else 'n/a'}",
                  f"- Macro view: {r['macro']['explanation']}",
                  f"- Sentiment: {r['sentiment']['verdict']} "
                  f"({r['sentiment']['mentions']} public mentions, "
                  f"trend {r['sentiment'].get('trend_vs_prev')})",
                  f"- Data quality: {r['scoring']['data_quality']} | "
                  f"{r['scoring']['history_note']}",
                  f"- Watch next: price vs {_fmt(r['technical'].get('resistance'))} "
                  f"resistance and {_fmt(r['technical'].get('support'))} support; "
                  "next earnings/news flow.", ""]

    if excluded:
        lines += ["## Excluded (shariah unverified)", ""]
        for r in excluded:
            lines.append(f"- {r['symbol']}: {r['shariah']['status']} — "
                         f"{'; '.join(r['shariah']['notes'])}")

    lines += ["", "---", "⚠ " + config.DISCLAIMER]
    return "\n".join(lines)


def save_report(text, tag="run"):
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    path = os.path.join(config.REPORT_DIR,
                        f"{tag}_{datetime.now():%Y%m%d_%H%M}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    log.info("Report saved: %s", path)
    return path


def morning_report():
    """Pre-market plan from the latest stored runs."""
    lines = [f"# Morning Report — {datetime.now():%Y-%m-%d 09:00}", ""]
    for sym in config.STOCKS:
        r = db.last_run(sym)
        if not r:
            lines.append(f"- {sym}: no data yet")
            continue
        lines.append(f"- {sym}: last signal **{r['signal']}** "
                      f"(score {r['final_score']}, conf {r['confidence']}%), "
                      f"price {r['price']}, stop {r['stop_loss']}, "
                      f"target {r['target1']}, risk {r['risk_level']}")
    lines += ["", "Plan: act only on signals re-confirmed after the open; "
              "check overnight news first.", "", "⚠ " + config.DISCLAIMER]
    return "\n".join(lines)


def evening_report():
    """Post-market review: what changed today + accuracy snapshot."""
    lines = [f"# Evening Report — {datetime.now():%Y-%m-%d 21:00}", ""]
    for sym in config.STOCKS:
        r = db.last_run(sym)
        if r:
            lines.append(f"- {sym}: close-of-day signal {r['signal']}, "
                          f"score {r['final_score']}, risk {r['risk_level']}")
    acc = db.signal_accuracy()
    if acc:
        lines += ["", "## Signal accuracy to date"]
        for row in acc:
            lines.append(f"- {row['signal']}: {row['outcome']} × {row['n']}")
    else:
        lines += ["", "No completed signal outcomes yet (need 1/3/7-day "
                  "follow-up prices)."]
    lines += ["", "⚠ " + config.DISCLAIMER]
    return "\n".join(lines)
