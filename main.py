"""main.py — Entry point and orchestrator.

Usage (Windows-friendly):
    python main.py run            # one full analysis run + report
    python main.py schedule       # auto-run every 10 min + 9AM/9PM reports
    python main.py morning        # print morning report
    python main.py evening        # print evening report
    python main.py backtest PSO   # technical backtest for one symbol (metrics)
    python main.py metrics        # whole-universe edge: expectancy/PF/maxDD/OOS
    python main.py portfolio      # book-level risk (heat + sector caps) from Buys
    python main.py accuracy       # signal & indicator accuracy stats
    python main.py history PSO    # recent stored runs for a symbol
"""

import sys
import io
import json
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
import confluence_axes
import portfolio_risk
import portfolio_advisor
import reports
import backtester
import news_feed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
              logging.StreamHandler()])
log = logging.getLogger("main")


def _days_to_earnings(symbol):
    """Days until a KNOWN earnings/result date (config override, else the news
    feed's optional earnings_date). None when unknown — no blackout is invented."""
    ed = (getattr(config, "EARNINGS_DATES", {}) or {}).get(symbol)
    if not ed:
        av = news_feed.get(symbol)
        ed = av.get("earnings_date") if av else None
    if not ed:
        return None
    try:
        return (datetime.fromisoformat(str(ed)).date() - datetime.now().date()).days
    except Exception:
        return None


def analyze_stock(symbol, news_items, index_eod=None, regime=None,
                  holdings=None):
    """Full pipeline for one symbol. Returns the result dict and stores it."""
    shariah = shariah_checker.check(symbol)
    quote = data_fetcher.latest_quote(symbol)
    eod, eod_meta = data_fetcher.fetch_eod(symbol)

    # A cached-EOD fallback still yields a full technical read, so nothing
    # downstream would otherwise reveal that the prices are days old — and a row
    # stamped with today's run_time reading "good" is exactly how the 2026-08-13
    # outage hid four stale days. Carry the price date into data_quality so the
    # dashboard's Data column and its good-count tile both show it.
    stale_prices = None if eod is None or eod_meta.get("live") else eod_meta.get("as_of")

    rs = market_regime.relative_strength(eod, index_eod) if index_eod is not None else None
    rs_score = rs["rs_score"] if rs else None
    ohlc = db.get_daily_ohlc(symbol)          # real H/L bars → true ATR/ADX when ready
    technical = technical_analyzer.analyze(symbol, eod, quote, rs_score=rs_score, ohlc=ohlc)
    sentiment = sentiment_analyzer.analyze(symbol, news_items)
    macro = macro_news_analyzer.analyze(symbol, news_items)
    fundamentals = fundamentals_analyzer.analyze(symbol)
    tech_flags = technical.get("tech_flags")
    scoring = scoring_engine.compute(symbol, macro, sentiment, technical,
                                     fundamentals, tech_flags=tech_flags)
    risk = risk_manager.assess(symbol, technical, sentiment, macro,
                               regime=(regime or {}).get("regime"),
                               regime_pct_above=(regime or {}).get("pct_above"),
                               holdings=holdings)
    prev_sig = (db.last_run(symbol) or {}).get("signal")
    signal = signal_generator.generate(symbol, scoring["final_score"],
                                       scoring["confidence"], risk,
                                       shariah, technical,
                                       regime=(regime or {}).get("regime"),
                                       regime_pct_above=(regime or {}).get("pct_above"),
                                       prev_signal=prev_sig,
                                       days_to_earnings=_days_to_earnings(symbol))
    is_early, early_reason = signal_generator.early_watch(
        scoring["final_score"], technical, shariah)

    row = {
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
        "data_quality": (f"STALE prices ({stale_prices})" if stale_prices
                         else scoring["data_quality"]),
        "relative_strength": rs_score,
        "market_regime": (regime or {}).get("regime"),
        "main_reason": "; ".join(signal["reasons"])[:400],
        "main_risk": (risk["warnings"][0] if risk["warnings"] else "")[:400],
        "tech_flags": json.dumps(tech_flags) if tech_flags else None,
        "confluence": signal.get("confluence", 0),
        "buy_zone_low": signal.get("buy_zone_low"),
        "buy_zone_high": signal.get("buy_zone_high"),
        "accumulation_candidate": int(bool(technical.get("accumulation_candidate"))),
        "accumulation_reasons": json.dumps(technical.get("accumulation_reasons") or []),
        "cmf": technical.get("cmf"),
        "obv_divergence_bullish": (int(technical["obv_divergence_bullish"])
                                   if technical.get("obv_divergence_bullish") is not None
                                   else None),
        "early_watch": int(is_early),
        "early_reason": early_reason or None,
    }

    # Computed LAST and wrapped, per the 2026-08-13 outage rule: a fault here
    # costs the axes, never the signal. Measurement-only — nothing reads these
    # back into a decision until each axis has been graded on its own.
    try:
        ca = confluence_axes.for_symbol(symbol, technical, db)
        row["confluence_axes"] = json.dumps(ca)
        row["confluence_composite"] = ca["composite"]
    except Exception as e:
        log.warning("confluence axes failed for %s: %s", symbol, e)

    db.save_run(row)

    if quote.get("warning"):
        log.warning("%s: %s", symbol, quote["warning"])
    if eod_meta.get("warning"):
        log.warning("%s: %s", symbol, eod_meta["warning"])

    return {"symbol": symbol, "shariah": shariah, "quote": quote,
            "technical": technical, "sentiment": sentiment, "macro": macro,
            "fundamentals": fundamentals, "relative_strength": rs,
            "scoring": scoring, "risk": risk, "signal": signal}


def full_run(fast=False):
    """fast=True trims everything that does not affect TODAY'S signals, so the
    first cycle after the 09:32 open commits sooner. Safe because:
      - news carries 0% score weight (config.WEIGHTS macro_news/sentiment = 0.0)
        and PURE_TECHNICAL already demotes its vetoes to warnings, so an empty
        news list cannot change a signal. The dashboard's news window comes from
        news.yml's separate raw fetch, not from here.
      - update_outcomes() grades PAST runs; it has no bearing on today's output
        and still runs on every later cycle and in the evening job.
    Nothing that feeds a signal is skipped: quote, EOD, regime, RS, technicals
    and the whole risk layer run exactly as normal."""
    log.info("=== Engine run started%s ===", " (fast first cycle)" if fast else "")
    db.init_db()
    news_items = []
    if fast:
        log.info("Fast cycle: skipping news fetch and outcome grading "
                 "(~30s saved; neither affects today's signals).")
    else:
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

    # Real book (portfolio.json) so the concentration cap can see what is already
    # held — per-trade sizing alone is blind to it. Missing/unreadable file = no
    # holdings = the cap simply never fires (never a fabricated position).
    holdings = portfolio_advisor.load_portfolio().get("holdings", [])

    results = [analyze_stock(s, news_items, index_eod, regime, holdings)
               for s in config.STOCKS]

    # Tier 2 #9: book-level risk across every Buy this run (heat + sector caps).
    candidates = [{"symbol": r["symbol"],
                   "score": r["scoring"]["final_score"],
                   "signal": r["signal"]["signal"],
                   "price": r["technical"].get("price"),
                   "stop": r["technical"].get("stop_loss"),
                   "sector": config.SECTORS.get(r["symbol"], "Unknown")}
                  for r in results
                  if r["signal"]["signal"] in ("Buy", "Strong Buy")]
    portfolio = portfolio_risk.assess(candidates)
    log.info("Portfolio risk: %s", portfolio_risk.summary_line(portfolio))

    macro_titles = [n["title"] for n in news_items][:6]
    market_notes = "Market regime: " + regime["note"]
    if macro_titles:
        market_notes += " | Headlines: " + " | ".join(t[:80] for t in macro_titles)
    report = reports.build_run_report(results, market_notes, portfolio)
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

    # Focus brief LAST and never fatal: signals are already saved by this point,
    # so a fault here costs one brief, not the whole run. (2026-08-17: an
    # unguarded AssertionError early in full_run froze every signal for four
    # days while the workflow still reported success.)
    try:
        _save_focus_brief()
    except Exception as e:
        log.warning("Focus brief skipped: %s", e)

    log.info("=== Engine run finished ===")
    return results


def _save_focus_brief():
    import focus_brief
    with db.conn() as c:
        latest = {r["symbol"]: dict(r) for r in c.execute(
            "SELECT * FROM runs WHERE id IN (SELECT MAX(id) FROM runs GROUP BY symbol)")}
    advice = portfolio_advisor.advise(portfolio_advisor.load_portfolio(), latest)
    brief = focus_brief.build(advice=advice)
    if brief:
        db.save_focus_brief(brief)
        log.info("Focus brief (%s): %s", brief["symbol"], brief["action"])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    db.init_db()
    if cmd == "run":
        full_run(fast="--fast" in sys.argv)
    elif cmd == "schedule":
        import scheduler
        scheduler.start()
    elif cmd == "morning":
        text = reports.morning_report()
        print(text); reports.save_report(text, "morning")
    elif cmd == "prune":
        print(db.prune())
    elif cmd == "axes":
        # Read-only: no fetch, no write. Reports each axis so a weak one is
        # visible before anyone proposes wiring the composite into a decision.
        names = ["trend_quality", "relative_strength", "stability",
                 "participation", "structure", "persistence"]
        print(f"{'sym':8s}{'sig':11s}{'score':>6s}{'comp':>7s}{'bars':>6s}  " +
              "".join(f"{n[:9]:>10s}" for n in names))
        for sym in config.STOCKS:
            r = db.last_run(sym)
            if not r:
                continue
            ca = confluence_axes.for_symbol(sym, {
                "price": r["price"], "support": r["support"],
                "relative_strength": r["relative_strength"]}, db)
            def _cell(v):
                return "—" if v is None else f"{v:.2f}"
            cells = "".join(f"{_cell(ca['axes'][n]):>10s}" for n in names)
            comp = "—" if ca["composite"] is None else f"{ca['composite']:.3f}"
            flag = "" if ca["trustworthy"] else "  (thin history)"
            print(f"{sym:8s}{str(r['signal'])[:10]:11s}"
                  f"{(r['final_score'] or 0):6.1f}{comp:>7s}{ca['bars']:6d}  "
                  f"{cells}{flag}")
        print("\nAll axes are UNMEASURED and feed no signal. Grade each one "
              "with measure.render() before proposing it as a ranker or sizer; "
              "this repo's history says a new gate is the change most likely "
              "to destroy edge.")
    elif cmd == "backfill":
        # One-shot EOD history backfill. Needs a host that can reach PSX DPS —
        # from a sandbox every symbol fails and nothing is written (never
        # fabricated). fetch_eod banks as a side effect; this just drives it.
        ok = failed = 0
        for sym in config.STOCKS:
            _, meta = data_fetcher.fetch_eod(sym)
            n, latest = db.eod_history_state(sym)
            if meta.get("live"):
                ok += 1
                print(f"  {sym:8s} {n:5d} bars through {latest}")
            else:
                failed += 1
                print(f"  {sym:8s} SKIPPED — no live EOD ({meta.get('warning')})")
        total = sum(db.eod_history_state(s)[0] for s in config.STOCKS)
        print(f"\n{ok} symbols banked, {failed} unavailable — "
              f"{total} EOD bars stored in total")
    elif cmd == "measure":
        import measure
        rows = measure.load()
        buy_min = config.SIGNAL_THRESHOLDS["buy"]
        cand = [r for r in rows if (r.get("final_score") or 0) >= buy_min
                and (r.get("relative_strength") or 0) >= config.RS_LAGGARD_VETO]
        print(measure.render("Candidate pool (score>=%s & RS>=%s)"
                             % (buy_min, config.RS_LAGGARD_VETO),
                             measure.cohort(cand, rows, 3)))
        print(measure.render("", measure.cohort(cand, rows, 7)))
        print(measure.render("\nEmitted Buys",
                             measure.cohort([r for r in rows if r.get("signal")
                                             in ("Buy", "Strong Buy")], rows, 3)))
    elif cmd == "brief":
        import focus_brief
        sym = sys.argv[2] if len(sys.argv) > 2 else None
        _save_focus_brief()
        print(focus_brief.render_text(db.last_focus_brief(sym or config.FOCUS_SYMBOL)))
    elif cmd == "evening":
        backtester.update_outcomes()
        # Refresh the focus brief post-close so the overnight view reflects the
        # last cycle rather than whatever the loop happened to write at 15:30.
        try:
            _save_focus_brief()
        except Exception as e:
            log.warning("Focus brief skipped: %s", e)
        text = reports.evening_report()
        print(text); reports.save_report(text, "evening")
        # Keep the tracked DB from creeping back to the 54 MB it had reached.
        # Runs once a day, after grading, so nothing it drops is still needed.
        # Last, and wrapped: a prune fault must never cost the evening report.
        try:
            log.info("DB prune: %s", db.prune())
        except Exception as e:
            log.warning("DB prune skipped: %s", e)
        try:
            import notify
            notify.send_text(f"PSX Evening Summary {datetime.now():%Y-%m-%d}", text)
        except Exception as e:
            log.warning("Evening email step failed: %s", e)
    elif cmd == "backtest":
        sym = sys.argv[2].upper() if len(sys.argv) > 2 else "PSO"
        res = backtester.backtest(sym)
        res.pop("detail", None)            # keep the console summary readable
        for v in ("in_sample", "out_of_sample"):
            res.get(v, {}).pop("equity_curve", None)
        res.pop("equity_curve", None)
        import json; print(json.dumps(res, indent=2, default=str))
    elif cmd == "metrics":
        # Whole-universe backtest with profit metrics (expectancy / profit
        # factor / max drawdown) + out-of-sample verdict per symbol.
        res = backtester.backtest_portfolio()
        agg = res["aggregate"]
        print(f"\n=== Strategy edge across {res['symbols_traded']} symbols "
              f"({agg.get('trades', 0)} trades) ===")
        print(f"Expectancy/trade: {agg.get('expectancy_pct')}%  |  "
              f"Profit factor: {agg.get('profit_factor')}  |  "
              f"Win rate: {agg.get('win_rate_pct')}%  |  "
              f"Max drawdown: {agg.get('max_drawdown_pct')}%  |  "
              f"Total return: {agg.get('total_return_pct')}%")
        print("\nPer symbol:")
        for s, m in sorted(res["per_symbol"].items(),
                           key=lambda kv: (kv[1].get("expectancy_pct") or 0),
                           reverse=True):
            print(f"  {s:<7} trades={m['trades']:<3} "
                  f"exp={m['expectancy_pct']}%  pf={m['profit_factor']}  "
                  f"win={m['win_rate_pct']}%  maxDD={m['max_drawdown_pct']}%")
        print("\n" + res["warning"])
    elif cmd == "portfolio":
        # Book-level risk from the latest stored Buys: heat + sector caps.
        cap = int(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000
        cands = []
        for s in config.STOCKS:
            r = db.last_run(s)
            if r and r["signal"] in ("Buy", "Strong Buy"):
                cands.append({"symbol": s, "score": r["final_score"],
                              "signal": r["signal"], "price": r["price"],
                              "stop": r["stop_loss"],
                              "sector": config.SECTORS.get(s, "Unknown")})
        res = portfolio_risk.assess(cands, capital=cap)
        print(f"\n=== Portfolio risk (capital PKR {cap:,}) ===")
        print(portfolio_risk.summary_line(res))
        print("\nAdmitted:")
        for a in res["admitted"]:
            print(f"  {a['symbol']:<7} {a['shares']:>6,} sh  "
                  f"PKR {a['value']:>12,.0f}  heat {a['heat_pct']:.2f}%  "
                  f"[{a['sector']}]")
        if res["deferred"]:
            print("Deferred (cap would be breached):")
            for d in res["deferred"]:
                print(f"  {d['symbol']:<7} — {d['reason']}")
    elif cmd == "fundamentals":
        import fundamentals_fetcher
        p = fundamentals_fetcher.fetch_all()
        n = len(p["data"]); fields = sum(len(v) for v in p["data"].values())
        print(f"Fundamentals refreshed: {n}/{len(config.STOCKS)} stocks, "
              f"{fields} ratios, as_of {p['as_of']}")
    elif cmd == "accuracy":
        rows = db.signal_accuracy_summary()
        print("\n=== Signal accuracy (with sample-size reliability) ===")
        for r in rows:
            wr = "n/a" if r["win_rate_pct"] is None else f"{r['win_rate_pct']}%"
            print(f"  {r['signal']:<11} n={r['n_total']:<4} win={wr:<7} "
                  f"sample={r['n_confidence']}")
        low = [r for r in rows if r["n_confidence"] == "low"]
        if low:
            print("\n⚠ Low-sample signals (read these win rates as NOISE, not "
                  "edge — too few graded trades to trust):")
            for r in low:
                print(f"   - {r['signal']}: only {r['n_total']} graded outcome(s)")
        print("\nIndicator accuracy:", db.indicator_stats())
    elif cmd == "regrade":
        res = backtester.regrade_all()
        print(f"Re-graded {res['regraded']} runs; {res['flipped']} outcomes changed.")
        print("Signal accuracy now:", db.signal_accuracy())
    elif cmd == "accumulating":
        rows = db.accumulating_now(lookback=10, min_streak=1)
        if not rows:
            print("No stocks currently flagged as accumulation candidates.")
        else:
            print(f"\n=== Accumulation candidates ({len(rows)}) ===")
            for r in rows:
                reasons = json.loads(r["reasons"] or "[]")
                print(f"  {r['symbol']:<7}  signal={r['signal']:<11} "
                      f"score={r['final_score']}  price={r['price']}  — "
                      + "; ".join(reasons))
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
