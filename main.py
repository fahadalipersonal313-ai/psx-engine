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
if __name__ == "__main__" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import config
import ssl_compat
ssl_compat.enable()   # OS trust store for HTTPS (must precede any network call)
import database as db
import data_fetcher
import shariah_checker
import market_regime
import confluence_axes
import psx_market_watch
import orderbook
import portfolio_risk
import portfolio_advisor
import reports
import backtester
import news_feed
import decision_engine
import session_calendar
import swing_evaluation

if __name__ == "__main__":
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
                  holdings=None, cutoff=None, batch_id=None):
    """Full pipeline for one symbol. Returns the result dict and stores it."""
    shariah = shariah_checker.check(symbol)
    cutoff = cutoff or session_calendar.last_completed()
    # Ingestion runs outside the pure decision function. Decisions use finalized
    # historical bars, not a quote collected during the signal session.
    params_hash = decision_engine.digest(decision_engine.contract())
    previous = db.previous_decision(symbol, cutoff, config.STRATEGY_VERSION, params_hash)
    decision = decision_engine.decide(symbol, db.get_daily_ohlc(symbol, config.FEATURE_HISTORY_LIMIT),
                index_eod, cutoff, shariah['eligible_for_ranking'], previous, db.get_corporate_actions(symbol))
    technical, scoring, risk, signal = (decision[k] for k in ('technical','scoring','risk','signal'))
    macro, sentiment, fundamentals = (decision[k] for k in ('macro','sentiment','fundamentals'))
    rs = decision['relative_strength']
    rs_score = rs['rs_score'] if rs else None
    regime = decision['regime']
    quote = {'price': technical.get('price'), 'volume': technical.get('volume'),
             'source': 'finalized historical OHLC', 'as_of': cutoff}
    stale_prices = None
    tech_flags = technical.get('tech_flags')
    is_early, early_reason = False, ''

    row = {
        "run_time": session_calendar.local_now().isoformat(), "symbol": symbol,
        "strategy_version": decision["strategy_version"], "decision_session": cutoff,
        "config_hash": decision["config_hash"], "snapshot_hash": decision.get("snapshot_hash"),
        "raw_qualified": int(bool(signal.get("raw_qualified"))), "batch_id": batch_id,
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

    db.save_run(row)
    db.save_decision(decision)

    return {"symbol": symbol, "shariah": shariah, "quote": quote,
            "technical": technical, "sentiment": sentiment, "macro": macro,
            "fundamentals": fundamentals, "relative_strength": rs,
            "scoring": scoring, "risk": risk, "signal": signal}


def _is_live_session(now=None):
    return session_calendar.is_live(now)


def _bank_official_hl(bars, now=None):
    """Write the exchange's own intraday High/Low into daily_ohlc for today.

    overwrite=True on purpose: this REPLACES a bar reconstructed from 15-minute
    polls with the official figure. That is the trade-off recorded during the
    2026-09-01 backfill, where INSERT OR IGNORE deliberately kept the poll-derived
    value and the official one had to be preferred by hand. Here the official
    value is available live, so it wins.

    Banking is skipped entirely outside a live session (see _is_live_session),
    and a bar identical to the symbol's previous stored bar is skipped too — that
    is the market-watch feed repeating the last session, which is what a public
    holiday looks like when the clock check alone cannot see it.
    """
    if not bars:
        return
    now = now or datetime.now()
    if not _is_live_session(now):
        log.info("market-watch: outside a live session — not banking %d bars "
                 "(the feed serves the previous session once the market shuts)",
                 len(bars))
        return
    today = now.strftime("%Y-%m-%d")
    n = repeats = 0
    for sym, b in bars.items():
        try:
            prev = db.get_daily_ohlc(sym, limit=1)
            if prev and prev[-1]["date"] != today and _same_bar(prev[-1], b):
                repeats += 1
                continue
            n += db.save_hl_bar(sym, today, b.get("open"), b["high"], b["low"],
                                b.get("current"), b.get("volume"),
                                "PSX market-watch (official intraday)",
                                overwrite=True)
        except Exception as e:
            log.warning("banking official H/L failed for %s: %s", sym, e)
    log.info("Banked official intraday High/Low for %d symbols%s", n,
             f" ({repeats} skipped as repeats of the previous session)" if repeats else "")


def _same_bar(stored, live):
    """Whether a market-watch bar just repeats the stored one (holiday case)."""
    def eq(a, b):
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-9
    return (eq(stored.get("high"), live.get("high"))
            and eq(stored.get("low"), live.get("low"))
            and eq(stored.get("close"), live.get("current")))


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
    # Technical strategy never fetches or waits on optional news adapters.
    index_eod, index_meta = market_regime.fetch_index()
    cutoff = session_calendar.last_completed()
    regime = market_regime.assess_regime(index_eod)
    import psx_historical
    bars = psx_historical.fetch_day(cutoff)
    for bar in bars:
        if bar['symbol'] in config.STOCKS:
            db.save_hl_bar(bar['symbol'], cutoff, bar['open'], bar['high'], bar['low'],
                           bar['close'], bar['volume'], psx_historical.SOURCE, overwrite=True)
    account = portfolio_advisor.load_portfolio()
    holdings = account.get('holdings', [])
    with db.analysis_batch(len(config.STOCKS)) as batch_id:
        results = [analyze_stock(symbol, [], index_eod, regime, holdings, cutoff, batch_id)
                   for symbol in config.STOCKS]
        portfolio = _assess_account(results, account, batch_id)
    swing_evaluation.update_outcomes()

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

    log.info("=== Engine run finished ===")
    return results


def _assess_account(results, account, batch_id):
    candidates = [{"symbol": r["symbol"],
                   "score": r["scoring"]["final_score"],
                   "signal": r["signal"]["signal"],
                   "price": r["technical"].get("price"),
                   "stop": r["technical"].get("stop_loss"),
                   "avg_volume": r["technical"].get("avg_volume"),
                   "sector": config.SECTORS.get(r["symbol"], "Unknown")}
                  for r in results
                  if r["signal"]["signal"] in ("Buy", "Strong Buy")]
    holdings = account.get('holdings', [])
    marks = {r['symbol']: r['technical'].get('price') for r in results}
    marked = [{**h, 'price': marks.get(h['symbol'])} for h in holdings]
    from data_quality import finite
    equity = account['cash_pkr'] + sum(h['qty'] * h['price'] for h in marked if finite(h.get('price'), True))
    try:
        portfolio = portfolio_risk.assess(candidates, capital=equity, holdings=marked,
                    cash=account['cash_pkr'], pending=account.get('pending', []))
    except ValueError as exc:
        portfolio = None
        log.warning('Account admission unavailable: %s', exc)
    if portfolio:
        log.info("Portfolio risk: %s", portfolio_risk.summary_line(portfolio))

    admitted = {r['symbol']: r for r in (portfolio or {}).get('admitted', [])}
    deferred = {r['symbol']: r['reason'] for r in (portfolio or {}).get('deferred', []) + (portfolio or {}).get('unsizable', [])}
    for result in results:
        symbol = result['symbol']
        admission = 'admitted' if symbol in admitted else 'deferred' if symbol in deferred else 'unavailable' if portfolio is None else 'not_candidate'
        reason = deferred.get(symbol, 'Account marks, cash and actual stops required' if portfolio is None else '')
        result['account_admission'] = {'status': admission, 'reason': reason}
        result['risk']['position_sizing'] = None
        if symbol in admitted:
            item = admitted[symbol]
            result['risk']['position_sizing'] = {'capital_assumed_pkr': equity, 'suggested_shares': item['shares'], 'position_value_pkr': item['value'], 'max_loss_if_stopped_pkr': item['risk']}
        with db.conn() as c:
            c.execute('UPDATE runs SET account_admission=?, account_reason=? WHERE batch_id=? AND symbol=?', (admission, reason, batch_id, symbol))
    return portfolio


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
    elif cmd == "actions":
        import corporate_actions, market_factors
        raw = market_factors.load_panel(db, adjust=False)
        acts = corporate_actions.detect(raw)
        print(f"detected {len(acts)}, newly stored {db.save_corporate_actions(acts)}")
        cuts = [a for a in acts if a["factor"]]
        print(f"adjustable price cuts {len(cuts)} | unexplained gap-ups "
              f"{len(acts) - len(cuts)} (flagged, never adjusted)")
    elif cmd == "events":
        import event_library
        if len(sys.argv) > 2:
            print(event_library.for_symbol(db, sys.argv[2].upper()))
        else:
            evs = event_library.build(db)
            print(f"detected {len(evs)}, newly stored {db.save_events(evs)}\n")
            print(event_library.summarise(evs))
            print("\nUNMEASURED and wired into nothing.")
    elif cmd == "orderbook":
        files, rows, new = orderbook.ingest(db)
        cov = db.order_book_coverage()
        print(f"files {files} | distinct states {rows} | newly stored {new}")
        print(f"coverage: {cov['syms']} symbols, {cov['n']} snapshots, "
              f"{cov['days']} sessions, {cov['lo']} .. {cov['hi']}")
        print("UNMEASURED and wired into nothing — grade it with measure.render() first.")
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
        full_run()
        backtester.update_outcomes()
        # Refresh the focus brief post-close so the overnight view reflects the
        # last cycle rather than whatever the loop happened to write at 15:30.
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
        print(json.dumps(res, indent=2, default=str))
    elif cmd == "metrics":
        print(json.dumps(backtester.backtest_portfolio(), indent=2, default=str))
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
        print("\n=== Legacy benchmark-relative labels (not target success) ===")
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
