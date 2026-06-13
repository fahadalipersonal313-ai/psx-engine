"""main.py — Entry point and orchestrator.

Usage (Windows-friendly):
    python main.py run            # one full analysis run + report
    python main.py schedule       # auto-run every 10 min + 9AM/9PM reports
    python main.py morning        # print morning report
    python main.py evening        # print evening report
    python main.py backtest PSO   # technical backtest for one symbol
    python main.py accuracy       # signal & indicator accuracy stats
    python main.py history PSO    # recent stored runs for a symbol
"""

import sys
import io
import logging
from datetime import datetime

# Force UTF-8 output on Windows consoles that default to cp1252
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import config
import ssl_compat
ssl_compat.enable()   # OS trust store for HTTPS (must precede any network call)
import database as db
import data_fetcher
import shariah_checker
import macro_news_analyzer
import sentiment_analyzer
import technical_analyzer
import fundamentals_analyzer
import market_regime
import scoring_engine
import risk_manager
import signal_generator
import reports
import backtester

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
              logging.StreamHandler()])
log = logging.getLogger("main")


def analyze_stock(symbol, news_items, index_eod=None, regime=None):
    """Full pipeline for one symbol. Returns the result dict and stores it."""
    shariah = shariah_checker.check(symbol)
    quote = data_fetcher.latest_quote(symbol)
    eod, eod_meta = data_fetcher.fetch_eod(symbol)

    rs = market_regime.relative_strength(eod, index_eod) if index_eod is not None else None
    rs_score = rs["rs_score"] if rs else None
    technical = technical_analyzer.analyze(symbol, eod, quote, rs_score=rs_score)
    sentiment = sentiment_analyzer.analyze(symbol, news_items)
    macro = macro_news_analyzer.analyze(symbol, news_items)
    fundamentals = fundamentals_analyzer.analyze(symbol)
    scoring = scoring_engine.compute(symbol, macro, sentiment, technical,
                                     fundamentals)
    risk = risk_manager.assess(symbol, technical, sentiment, macro)
    signal = signal_generator.generate(symbol, scoring["final_score"],
                                       scoring["confidence"], risk,
                                       shariah, technical,
                                       regime=(regime or {}).get("regime"))

    db.save_run({
        "run_time": datetime.now().isoformat(), "symbol": symbol,
        "price": technical.get("price"), "volume": technical.get("volume"),
        "technical_score": technical.get("score"),
        "sentiment_score": sentiment.get("score"),
        "macro_news_score": macro.get("score"),
        "final_score": scoring["final_score"], "signal": signal["signal"],
        "confidence": signal["confidence"],
        "stop_loss": technical.get("stop_loss"),
        "target1": technical.get("target1"), "target2": technical.get("target2"),
        "support": technical.get("support"),
        "resistance": technical.get("resistance"),
        "risk_level": risk["risk_level"], "shariah_status": shariah["status"],
        "data_quality": scoring["data_quality"],
        "relative_strength": rs_score,
        "market_regime": (regime or {}).get("regime"),
        "main_reason": "; ".join(signal["reasons"])[:400],
        "main_risk": (risk["warnings"][0] if risk["warnings"] else "")[:400],
    })

    if quote.get("warning"):
        log.warning("%s: %s", symbol, quote["warning"])
    if eod_meta.get("warning"):
        log.warning("%s: %s", symbol, eod_meta["warning"])

    return {"symbol": symbol, "shariah": shariah, "quote": quote,
            "technical": technical, "sentiment": sentiment, "macro": macro,
            "fundamentals": fundamentals, "relative_strength": rs,
            "scoring": scoring, "risk": risk, "signal": signal}


def full_run():
    log.info("=== Engine run started ===")
    db.init_db()
    news_items = data_fetcher.fetch_news()
    # Per-company public news (Google News RSS) -> real per-stock sentiment.
    for s in config.STOCKS:
        news_items += data_fetcher.fetch_company_news(s)
    backtester.update_outcomes()          # learning loop first

    # Tier 2: fetch the benchmark index ONCE; judge the market regime. Both feed
    # relative strength (per stock) and the regime gate (market-wide).
    index_eod, index_meta = market_regime.fetch_index()
    regime = market_regime.assess_regime(index_eod)
    log.info("Market regime: %s", regime["note"])

    results = [analyze_stock(s, news_items, index_eod, regime)
               for s in config.STOCKS]

    macro_titles = [n["title"] for n in news_items][:6]
    market_notes = "Market regime: " + regime["note"]
    if macro_titles:
        market_notes += " | Headlines: " + " | ".join(t[:80] for t in macro_titles)
    report = reports.build_run_report(results, market_notes)
    print("\n" + report)
    reports.save_report(report, "run")

    # Excel export + email (email only fires per config.EMAIL_MODE; both are
    # no-ops if their prerequisites/secrets are absent, never fatal).
    try:
        import excel_export
        import notify
        xlsx = excel_export.export(results)
        notify.send_report(results, report, xlsx)
    except Exception as e:
        log.warning("Excel/email step failed: %s", e)

    log.info("=== Engine run finished ===")
    return results


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    db.init_db()
    if cmd == "run":
        full_run()
    elif cmd == "schedule":
        import scheduler
        scheduler.start()
    elif cmd == "morning":
        text = reports.morning_report()
        print(text); reports.save_report(text, "morning")
    elif cmd == "evening":
        backtester.update_outcomes()
        text = reports.evening_report()
        print(text); reports.save_report(text, "evening")
        try:
            import notify
            notify.send_text(f"PSX Evening Summary {datetime.now():%Y-%m-%d}", text)
        except Exception as e:
            log.warning("Evening email step failed: %s", e)
    elif cmd == "backtest":
        sym = sys.argv[2].upper() if len(sys.argv) > 2 else "PSO"
        res = backtester.backtest(sym)
        import json; print(json.dumps(res, indent=2, default=str))
    elif cmd == "fundamentals":
        import fundamentals_fetcher
        p = fundamentals_fetcher.fetch_all()
        n = len(p["data"]); fields = sum(len(v) for v in p["data"].values())
        print(f"Fundamentals refreshed: {n}/{len(config.STOCKS)} stocks, "
              f"{fields} ratios, as_of {p['as_of']}")
    elif cmd == "accuracy":
        print("Signal accuracy:", db.signal_accuracy())
        print("Indicator accuracy:", db.indicator_stats())
    elif cmd == "history":
        sym = sys.argv[2].upper() if len(sys.argv) > 2 else "PSO"
        for r in db.run_history(sym, 20):
            print(f"{r['run_time'][:16]} {r['symbol']} score={r['final_score']} "
                  f"signal={r['signal']} conf={r['confidence']}% "
                  f"outcome={r['outcome']}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
