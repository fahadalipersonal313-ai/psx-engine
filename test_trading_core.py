import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import config
import database as db
import decision_engine as de
import swing_evaluation as ev
import technical_analyzer as ta
import corporate_actions as ca
from data_quality import bar_error, valid_levels
import session_calendar as cal


SOURCE = 'PSX DPS historical (official)'


def fixture(n=230):
    days = pd.bdate_range('2025-01-01', periods=n)
    close = 100 + np.arange(n) * .08 + np.sin(np.arange(n) / 3)
    bars = [dict(date=d.strftime('%Y-%m-%d'), open=float(c-.3), high=float(c+1), low=float(c-1.5),
                 close=float(c), volume=500000., source=SOURCE) for d,c in zip(days,close)]
    index = [dict(date=b['date'], close=100 + i*.02) for i,b in enumerate(bars)]
    return bars,index


class IndicatorTests(unittest.TestCase):
    def test_rsi_boundaries(self):
        for values, expected in [(range(30),100),(range(30,0,-1),0),([5]*30,50)]:
            result = ta.rsi(pd.Series(values,dtype=float))
            self.assertTrue(result.iloc[:14].isna().all())
            self.assertEqual(result.iloc[-1],expected)

    def test_wilder_reference(self):
        closes = pd.Series([44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28])
        self.assertAlmostEqual(ta.rsi(closes).iloc[-1],70.464135,places=5)

    def test_prior_structure(self):
        a = pd.Series([100.]*60+[120.])
        b = pd.Series([100.]*60+[80.])
        self.assertEqual(ta.support_resistance(a),ta.support_resistance(b))
        self.assertLess(ta.support_resistance(a)[1],a.iloc[-1])

    def test_true_atr_and_cmf(self):
        bars,_ = fixture(40)
        for b in bars:
            b.update(open=10,high=12,low=8,close=11,volume=100)
        self.assertAlmostEqual(ta.true_atr_adx(bars)['atr'],4)
        self.assertAlmostEqual(ta.chaikin_money_flow(bars),.5)

    def test_level_validation(self):
        self.assertTrue(valid_levels(100,90,110,None))
        for target in [90,100,float('nan'),float('inf'),None]:
            self.assertFalse(valid_levels(100,90,target))
        self.assertFalse(valid_levels(100,90,110,105))


class DecisionTests(unittest.TestCase):
    def test_short_contract_uses_exactly_42_sessions(self):
        bars, ix = fixture(43)
        result = de.decide('PSO', bars, ix, bars[-1]['date'])
        self.assertNotEqual(result['signal']['signal'], 'No data', result['signal'])
        self.assertEqual(len(result['snapshot']['bars']), 42)
        self.assertEqual(len(result['snapshot']['benchmark']), 42)

    def test_older_bars_cannot_change_short_decision(self):
        bars, ix = fixture(84)
        baseline = de.decide('PSO', bars, ix, bars[-1]['date'])
        changed = copy.deepcopy(bars)
        for row in changed[:-42]:
            row.update(open=1., high=1.1, low=.9, close=1., volume=1.)
        self.assertEqual(de.canonical(baseline), de.canonical(
            de.decide('PSO', changed, ix, bars[-1]['date'])))

    def test_relative_strength_uses_short_windows(self):
        bars, ix = fixture(42)
        result = de.decide('PSO', bars, ix, bars[-1]['date'])
        self.assertEqual(set(result['relative_strength']['rel']), {'2w', '1m', '2m'})

    def test_future_invariance_and_pure_dependencies(self):
        bars,ix = fixture()
        with patch('database.conn',side_effect=AssertionError('DB in pure path')), patch('market_regime.fetch_index',side_effect=AssertionError('network')):
            old = de.decide('PSO',bars[:210],ix[:210],bars[209]['date'])
            future = de.decide('PSO',bars,ix,bars[209]['date'])
        self.assertNotEqual(old['signal']['signal'],'No data',old['signal'])
        self.assertEqual(de.canonical(old),de.canonical(future))

    def test_invalid_inputs_fail_closed(self):
        bars,ix = fixture()
        for field,value in [('close',float('nan')),('open','bad'),('low',999),('volume',-1),('source','intraday')]:
            modified = copy.deepcopy(bars); modified[-1][field]=value
            self.assertEqual(de.decide('PSO',modified,ix,bars[-1]['date'])['signal']['signal'],'No data')
        self.assertEqual(de.decide('PSO',bars,ix[:-1],bars[-1]['date'])['signal']['signal'],'No data')

    def test_config_hash_changes_with_guard(self):
        old = de.digest(de.contract())
        with patch.object(config,'BUY_MIN_CMF',.123):
            self.assertNotEqual(old,de.digest(de.contract()))

    def test_news_cannot_move_technical_score(self):
        import scoring_engine
        technical = {'score':70.,'low_confidence':False}
        outputs=[]
        for value in (10,50,90):
            outputs.append(scoring_engine.compute('PSO',{'score':value,'news_score':value,'sector_news_score':value},{'score':value},technical))
        self.assertEqual({o['final_score'] for o in outputs},{70.})
        self.assertEqual({o['confidence'] for o in outputs},{70.})

    def test_confirmation_distinct_sessions(self):
        bars,ix = fixture()
        with patch.object(config,'SIGNAL_THRESHOLDS',{'strong_buy':0,'buy':0,'watch':0,'hold':0}), patch('signal_generator.T',{'strong_buy':0,'buy':0,'watch':0,'hold':0}), patch.object(config,'BUY_MIN_CMF',-1), patch.object(config,'RS_LAGGARD_VETO',0), patch.object(config,'HYSTERESIS_BAND',0), patch.object(config,'REGIME_GATE_ENABLED',False), patch('technical_analyzer.analyze',wraps=ta.analyze) as analyze:
            # Actual classification also qualifies; use a controlled technical
            # snapshot to isolate confirmation rather than fitting a price path.
            real=ta.analyze('PSO',pd.DataFrame(bars),{'price':bars[-1]['close']},70,bars)
            p=real['price']
            real.update(classification='Bullish',breakdown=False,cmf=.2,
                        relative_strength=70,stop_loss=p*.95,target1=p*1.1,
                        target2=p*1.2,extended=False,ext_pct=0,momentum_20d=0)
            analyze.side_effect=None; analyze.return_value=real
            a=de.decide('PSO',bars,ix,bars[-2]['date'])
            same=de.decide('PSO',bars,ix,bars[-2]['date'],previous=de.state(a))
            nxt=de.decide('PSO',bars,ix,bars[-1]['date'],previous=de.state(a))
        self.assertEqual(a['signal']['signal'],'Buy')
        self.assertEqual(same['signal']['signal'],'Buy')
        self.assertEqual(nxt['signal']['signal'],'Strong Buy')


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.item={'session':'2026-09-01','reference_entry':100,'stop':90,'target':110,'target2':None,'quantity':1,
                   'prior_avg_volume': 10000,
                   'execution':dict(config.EXECUTION,slippage_bps=0,fee_bps_per_side=0)}
        self.bar=dict(date='2026-09-02',open=100,high=111,low=95,close=108,volume=10000,source=SOURCE)
    def resolve(self,**fields):
        b=dict(self.bar,**fields)
        return ev.resolve(self.item,[b],[b['date']])
    def test_target(self):
        r=self.resolve(); self.assertEqual(r['status'],'target'); self.assertAlmostEqual(r['net_return_pct'],10)
    def test_stop_first(self):
        r=self.resolve(low=85); self.assertEqual(r['status'],'stop'); self.assertTrue(r['ambiguous'])
    def test_gap_stop(self):
        first=dict(self.bar,high=105,close=102)
        second=dict(self.bar,date='2026-09-03',open=80,high=85,low=75,close=82)
        r=ev.resolve(self.item,[first,second],[first['date'],second['date']])
        self.assertEqual(r['exit_price'],80); self.assertAlmostEqual(r['net_return_pct'],-20)
    def test_unfilled_and_missing(self):
        self.assertEqual(self.resolve(open=109)['status'],'unfilled')
        self.assertEqual(ev.resolve(self.item,[],['2026-09-02'])['status'],'unavailable')
    def test_expiry_at_the_contract_horizon(self):
        """Expires after exactly holding_sessions, whatever the contract says.

        Derived from the contract rather than hardcoded: this asserted 10 until
        the v5 change moved the horizon to 30, and a test pinned to the old
        number fails for the wrong reason -- it was never checking 'ten', it was
        checking 'the horizon is honoured'."""
        horizon = int(self.item['execution']['holding_sessions'])
        bars=[dict(self.bar,date=d.strftime('%Y-%m-%d'),high=105,close=102)
              for d in pd.bdate_range('2026-09-02',periods=horizon)]
        r=ev.resolve(self.item,bars,[b['date'] for b in bars])
        self.assertEqual(r['status'],'expired')
        self.assertEqual(r['holding_sessions'],horizon)

    def test_horizon_outside_the_allowed_band_is_invalid(self):
        item=copy.deepcopy(self.item); item['execution']['holding_sessions']=61
        self.assertEqual(ev.resolve(item,[self.bar],[self.bar['date']])['status'],'invalid')
        item['execution']['holding_sessions']=0
        self.assertEqual(ev.resolve(item,[self.bar],[self.bar['date']])['status'],'invalid')
    def test_unavailable_visible(self):
        result=ev.metrics([{'status':'unavailable'},{'status':'unfilled'},{'status':'pending'}])
        self.assertEqual(result['unresolved_risk'],2); self.assertEqual(result['opportunities'],3)
        self.assertIsNone(result['net_expectancy_pct'])
    def test_frozen_costs(self):
        a=self.resolve()
        with patch.dict(config.EXECUTION,fee_bps_per_side=500):
            self.assertEqual(a,self.resolve())


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch.object(config,'DB_PATH',str(Path(self.tmp.name)/'test.db')); self.patch.start(); db.init_db()
    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()
    def test_source_precedence_both_orders(self):
        for order in [(SOURCE,'PSX intraday'),('PSX intraday',SOURCE)]:
            for source in order:
                db.save_hl_bar('PSO','2026-09-01',100,110 if source==SOURCE else 105,95,101,100,source,True)
            self.assertEqual(db.get_daily_ohlc('PSO')[-1]['high'],110)
    def test_invalid_quarantine(self):
        self.assertEqual(db.save_hl_bar('PSO','2026-09-01',100,95,90,101,100,SOURCE),0)
        with db.conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM quarantined_bars').fetchone()[0],1)
    def test_batch_rollback(self):
        with self.assertRaises(ValueError):
            with db.analysis_batch(2) as bid:
                db.save_run(dict(symbol='PSO',run_time='2026-09-01',signal='Buy',batch_id=bid))
        with db.conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM runs').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT status FROM run_batches').fetchone()[0],'failed')
    def test_opportunity_idempotence_and_retention(self):
        bars,ix=fixture(); d=de.decide('PSO',bars,ix,bars[-1]['date'])
        d['signal']['signal']='Buy'
        one=db.save_decision(d); two=db.save_decision(d)
        self.assertEqual(one,two)
        with db.conn() as c:
            c.execute('DELETE FROM runs')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0],1)


class CalendarAndActionTests(unittest.TestCase):
    def test_friday_and_delay(self):
        self.assertTrue(cal.is_live(datetime(2026,9,4,9,17)))
        self.assertFalse(cal.is_live(datetime(2026,9,4,13)))
        self.assertTrue(cal.is_live(datetime(2026,9,4,15)))
        self.assertEqual(cal.last_completed(datetime(2026,9,4,16,45)),'2026-09-03')
        self.assertEqual(cal.last_completed(datetime(2026,9,4,17)),'2026-09-04')
    def test_holiday(self):
        with patch.object(config,'EXCHANGE_HOLIDAYS',['2026-09-04']):
            self.assertFalse(cal.is_live(datetime(2026,9,4,10)))
            self.assertEqual(cal.last_completed(datetime(2026,9,5)),'2026-09-03')
    def test_no_inferred_adjustment(self):
        close=pd.DataFrame({'X':[100.,50.]},index=pd.date_range('2026-09-01',periods=2))
        self.assertIsNone(ca.detect({'close':close})[0]['factor'])
    def test_explicit_action_factors(self):
        bars,_=fixture(2)
        action=dict(symbol='PSO',ex_date=bars[-1]['date'],known_at=bars[0]['date'],factor=.5,volume_factor=2,kind='split',source='official notice',verified=True)
        out=ca.verified_bars(bars,[action],bars[-1]['date'])
        self.assertEqual(out[0]['close'],bars[0]['close']/2)
        self.assertEqual(out[0]['volume'],bars[0]['volume']*2)
        self.assertEqual(ca.verified_bars(bars,[dict(action,verified=False)],bars[-1]['date']),bars)


class IntegrationTests(StorageTests):
    def test_full_pipeline_without_network_or_notifications(self):
        import main
        import contextlib
        import io
        bars,ix=fixture()
        for symbol in ('PSO','MARI'):
            for b in bars:
                db.save_hl_bar(symbol,b['date'],b['open'],b['high'],b['low'],b['close'],b['volume'],SOURCE)
        with patch.object(config,'STOCKS',['PSO','MARI']), patch('market_regime.fetch_index',return_value=(pd.DataFrame(ix),{})), patch('session_calendar.last_completed',return_value=bars[-1]['date']), patch('psx_historical.fetch_day',return_value=[]), patch('data_fetcher.fetch_news',side_effect=AssertionError('News on technical path')), patch('data_fetcher.latest_quote',side_effect=AssertionError('Live quote on completed path')), patch('reports.save_report'), patch('excel_export.export'), patch('notify.send_report') as notify, patch('portfolio_advisor.load_portfolio',return_value={'cash_pkr':1000000,'holdings':[]}), contextlib.redirect_stdout(io.StringIO()):
            with patch('main.write_signal_state'):
                result=main.full_run()
        self.assertEqual(len(result),2)
        with db.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM runs WHERE strategy_version=?",(config.STRATEGY_VERSION,)).fetchone()[0],2)
            self.assertEqual(c.execute('SELECT status FROM run_batches').fetchone()[0],'complete')

    def test_report_with_unavailable_symbol(self):
        import reports
        d=de.decide('PSO',[],[],'2026-09-01')
        d['shariah']={'eligible_for_ranking':True,'status':'Verified'}
        text=reports.build_run_report([d],'Missing bars')
        self.assertIn('No data',text)

    def test_sizing_and_existing_exposure(self):
        from position_sizing import size
        import portfolio_risk
        self.assertIsNone(size(100,None,1000000))
        self.assertEqual(size(100,90,1000000,0)['shares'],0)
        candidate={'symbol':'PSO','score':90,'signal':'Buy','price':100,'stop':90}
        result=portfolio_risk.assess([candidate,candidate],cash=1000000)
        self.assertEqual(len(result['admitted']),1)
        self.assertEqual(len(result['deferred']),1)
        with self.assertRaises(ValueError):
            portfolio_risk.assess([candidate],holdings=[{'symbol':'MARI','qty':100,'price':100}])


if __name__ == '__main__':
    unittest.main()


class SessionCutoffResolution(unittest.TestCase):
    """The configured calendar cannot know PSX holidays (EXCHANGE_HOLIDAYS is
    empty), so the cutoff must be confirmed against the exchange's own record.
    On 2026-09-09 it was not, and the loop ran 24 cycles against the previous
    session's prices with every row stamped `good`."""

    def test_trading_day_costs_no_extra_request(self):
        import main
        calls = []

        def answers(day):
            calls.append(day)
            return [{"symbol": "X"}]

        cutoff, bars = main._resolve_cutoff("2026-09-08", answers)
        self.assertEqual(cutoff, "2026-09-08")
        self.assertEqual(calls, ["2026-09-08"])
        self.assertTrue(bars)

    def test_holiday_walks_back_to_the_real_session(self):
        import main

        def holiday(day):
            return [] if day == "2026-09-09" else [{"symbol": "X"}]

        cutoff, bars = main._resolve_cutoff("2026-09-09", holiday)
        self.assertEqual(cutoff, "2026-09-08")
        self.assertTrue(bars)

    def test_multi_day_closure_skips_the_weekend(self):
        import main

        def closed_from_monday(day):
            return [] if day >= "2026-09-07" else [{"symbol": "X"}]

        cutoff, _ = main._resolve_cutoff("2026-09-09", closed_from_monday)
        self.assertEqual(cutoff, "2026-09-04")      # Friday, not Sunday

    def test_feed_outage_does_not_rewind_the_cutoff(self):
        """A dead feed must degrade to standing still, never to silently moving
        the decision window back two weeks."""
        import main
        cutoff, bars = main._resolve_cutoff("2026-09-09", lambda day: [])
        self.assertEqual(cutoff, "2026-09-09")
        self.assertEqual(bars, [])


class PayloadCompression(unittest.TestCase):
    """decisions + decision_snapshots were 59.4 MB of a 104.7 MB database across
    1,492 rows: each decision embeds a copy of the snapshot that
    decision_snapshots already holds, and the ~16.5 KB config is written to every
    row although only three distinct configs exist. Compression is used rather
    than dropping the duplication because snapshot_hash and config_hash are
    digests OF that content -- it must round-trip byte-identically."""

    def test_round_trips_exactly(self):
        import database as db
        for text in ('{"a":1}', '', 'x' * 100000, '{"unicode":"روپے"}'):
            self.assertEqual(db.unpack_payload(db.pack_payload(text)), text)

    def test_reads_legacy_uncompressed_rows(self):
        """Rows written before compression are plain TEXT and must still read."""
        import database as db
        self.assertEqual(db.unpack_payload('{"legacy":true}'), '{"legacy":true}')

    def test_compression_actually_shrinks_a_decision_payload(self):
        import database as db
        payload = json.dumps({"config": {f"K{i}": [1, 2, 3] for i in range(400)}})
        self.assertLess(len(db.pack_payload(payload)), len(payload) / 2)


class TopTenSessionFallback(unittest.TestCase):
    def test_falls_back_to_the_newest_session_holding_decisions(self):
        """last_completed() names holidays as sessions while EXCHANGE_HOLIDAYS is
        empty, which left the panel empty on a day the market was merely shut."""
        import upward_candidates
        src = Path('upward_candidates.py').read_text(encoding='utf-8')
        self.assertIn('SELECT MAX(session) FROM decisions', src)
        self.assertIsInstance(upward_candidates.current(), list)


class TargetTiming(unittest.TestCase):
    """A target without a timeframe invites holding a dead position forever, but
    the obvious arithmetic lies: distance/ATR read ~4 sessions for an NRL target
    the name historically took 12 to reach, and said nothing about the 52% of
    attempts that never got there."""

    def test_returns_none_rather_than_guessing(self):
        import target_timing as tt
        self.assertIsNone(tt.estimate('NOSUCHSYMBOL', 100, 110))
        self.assertIsNone(tt.estimate('NRL', 508, 400))      # target below price
        self.assertIsNone(tt.estimate('NRL', 508, 508))      # zero distance
        self.assertIsNone(tt.estimate('NRL', 0, 100))

    def test_reports_a_hit_rate_alongside_the_median(self):
        import target_timing as tt
        got = tt.estimate('NRL', 508.14, 631.02)
        if got is None:
            self.skipTest('NRL history unavailable in this database')
        self.assertIn('hit_rate', got)
        self.assertGreater(got['attempts'], tt.MIN_ATTEMPTS)
        self.assertTrue(0.0 <= got['hit_rate'] <= 1.0)
        # The measured median must exceed the naive distance/ATR figure, which is
        # the whole reason this module exists.
        self.assertGreater(got['typical_sessions'], got['k_atr'])


class ProspectiveCohort(unittest.TestCase):
    """`opportunities` is only created for an EMITTED Buy. With every candidate
    currently held at Watch by the regime gate, the engine had produced 782
    decisions, zero Buys and zero opportunities -- it could not accumulate
    evidence about itself, and no gate could be measured because the side it
    rejects was never graded. The cohort grades that side."""

    def _decision(self, signal='Watch', score=78.0, raw=False, price=100.0):
        return {
            'symbol': 'TESTCO', 'decision_session': '2026-09-08',
            'strategy_version': 'test_v1', 'config_hash': 'cfg', 'snapshot_hash': 'snap',
            'technical': {'price': price, 'stop_loss': price * 0.95,
                          'target1': price * 1.10, 'target2': price * 1.20,
                          'relative_strength': 70, 'cmf': 0.1},
            'signal': {'signal': signal, 'raw_qualified': raw,
                       'reasons': ['Downgraded: market regime risk-off']},
            'scoring': {'final_score': score},
            'config': {'EXECUTION': dict(config.EXECUTION)},
        }

    def _record(self, decision, path):
        import database as db
        with db.conn() as c:
            return db._record_cohort_candidate(c, decision, 'snap')

    def test_records_a_vetoed_candidate(self):
        import database as db
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'c.db')):
                db.init_db()
                cid = self._record(self._decision(), tmp)
                self.assertIsNotNone(cid)
                with db.conn() as c:
                    row = c.execute('SELECT emitted, pre_veto FROM cohort_candidates').fetchone()
                self.assertEqual(row['emitted'], 'Watch')      # what was emitted
                self.assertEqual(row['pre_veto'], 'Buy')       # what the score reached

    def test_skips_below_the_watch_band(self):
        import database as db
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'c.db')):
                db.init_db()
                self.assertIsNone(self._record(self._decision(score=20.0), tmp))

    def test_skips_invalid_levels_rather_than_grading_nonsense(self):
        import database as db
        d = self._decision()
        d['technical']['stop_loss'] = d['technical']['target1'] * 2   # stop above target
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'c.db')):
                db.init_db()
                self.assertIsNone(self._record(d, tmp))

    def test_recording_never_raises_into_the_decision_path(self):
        """Measurement must never cost a signal."""
        import database as db
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'c.db')):
                db.init_db()
                with db.conn() as c:
                    self.assertIsNone(db._record_cohort_candidate(c, {'symbol': 'X'}, None))


class SignalChangeDetection(unittest.TestCase):
    """The database differs byte-for-byte every cycle -- each run inserts a
    `runs` row with a new timestamp -- so `git diff` cannot decide whether
    there is anything new to publish. The digest is over the SIGNALS."""

    def _r(self, **kw):
        base = {"symbol": "PSO", "signal": "Avoid", "stop_loss": 1.0,
                "target1": 2.0, "scoring": {"final_score": 35.5}}
        base.update(kw)
        return [base]

    def test_identical_signals_give_an_identical_digest(self):
        import main
        self.assertEqual(main.signal_state(self._r()), main.signal_state(self._r()))

    def test_a_moved_signal_score_stop_or_target_all_register(self):
        import main
        base = main.signal_state(self._r())
        self.assertNotEqual(base, main.signal_state(self._r(signal="Buy")))
        self.assertNotEqual(base, main.signal_state(self._r(stop_loss=1.5)))
        self.assertNotEqual(base, main.signal_state(self._r(target1=2.5)))
        self.assertNotEqual(base, main.signal_state(
            self._r(scoring={"final_score": 36.0})))

    def test_row_order_does_not_count_as_a_change(self):
        import main
        a = [{"symbol": "PSO", "signal": "Avoid", "stop_loss": 1.0, "target1": 2.0,
              "scoring": {"final_score": 1.0}},
             {"symbol": "OGDC", "signal": "Buy", "stop_loss": 3.0, "target1": 4.0,
              "scoring": {"final_score": 2.0}}]
        self.assertEqual(main.signal_state(a), main.signal_state(list(reversed(a))))

    def test_state_file_records_when_signals_actually_moved(self):
        """changed_at must hold at the moment of the change, not tick every
        cycle -- the dashboard reports it as a fact."""
        import main, time
        with tempfile.TemporaryDirectory() as tmp:
            p = str(Path(tmp) / "state.json")
            self.assertTrue(main.write_signal_state("aaa", "2026-09-10", p))
            first = main.read_signal_state(p)["changed_at"]
            time.sleep(1.1)
            self.assertFalse(main.write_signal_state("aaa", "2026-09-10", p))
            same = main.read_signal_state(p)
            self.assertEqual(same["changed_at"], first)      # held
            self.assertNotEqual(same["checked_at"], first)   # but still checked
            self.assertTrue(main.write_signal_state("bbb", "2026-09-11", p))
            self.assertNotEqual(main.read_signal_state(p)["changed_at"], first)

    def test_a_missing_state_file_reads_as_empty_not_as_a_crash(self):
        """The loop treats an unreadable hint as 'commit anyway', so this must
        degrade rather than raise."""
        import main
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main.read_signal_state(str(Path(tmp) / "nope.json")), {})
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json")
            self.assertEqual(main.read_signal_state(str(bad)), {})


class ArchiveDurability(unittest.TestCase):
    """decisions + decision_snapshots grow 0.67 MB per session, unbounded,
    against a 100 MB hard limit. They are immutable audit records, so they are
    archived rather than dropped -- and the restore is verified BEFORE the live
    rows go away."""

    def _seed(self):
        import database as db
        with db.conn() as c:
            for i, session in enumerate(('2026-09-01', '2026-09-02', '2026-09-03')):
                c.execute('INSERT OR IGNORE INTO decision_snapshots VALUES (?,?)',
                          (f'snap{i}', f'{{"bars":{i}}}'))
                c.execute('INSERT OR IGNORE INTO decisions VALUES (?,?,?,?,?,?,?)',
                          (f'SYM{i}', session, 'v', 'cfg', f'snap{i}', '{}', '{"a":1}'))

    def test_export_verify_purge_restore_round_trip(self):
        import database as db, archive
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'live.db')):
                db.init_db(); self._seed()
                out = str(Path(tmp) / 'a.db')
                man = archive.export('2026-09-03', out)
                self.assertEqual(man['decisions'], 2)
                self.assertTrue(archive.verify(out, man)['ok'])
                self.assertEqual(archive.purge(out, '2026-09-03')['purged'], 2)
                with db.conn() as c:
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 1)
                archive.restore(out)
                with db.conn() as c:
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 3)
                archive.restore(out)          # idempotent
                with db.conn() as c:
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 3)

    def test_unreferenced_snapshots_are_archived_not_stranded(self):
        """A regenerated decision set leaves snapshots nothing names again.
        They were previously stranded in the live DB forever: purge only ever
        considered snapshots belonging to the decisions it was moving."""
        import database as db, archive
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'live.db')):
                db.init_db(); self._seed()
                with db.conn() as c:
                    c.execute('INSERT INTO decision_snapshots VALUES (?,?)',
                              ('stranded', '{"bars":9}'))
                out = str(Path(tmp) / 'a.db')
                # A cutoff older than every decision: nothing is graded away,
                # only the snapshot no decision references is moved.
                man = archive.export('2026-09-01', out)
                self.assertEqual(man['decisions'], 0)
                self.assertEqual(man['snapshots'], 1)
                self.assertTrue(archive.verify(out, man)['ok'])
                res = archive.purge(out, '2026-09-01')
                self.assertEqual(res['purged'], 0)
                self.assertEqual(res['snapshots_purged'], 1)
                with db.conn() as c:
                    # Every decision, and every snapshot a decision names, stays.
                    self.assertEqual(
                        c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 3)
                    self.assertEqual(c.execute(
                        'SELECT COUNT(*) FROM decisions d WHERE NOT EXISTS ('
                        ' SELECT 1 FROM decision_snapshots s WHERE s.hash=d.snapshot_hash)'
                    ).fetchone()[0], 0)
                archive.restore(out)
                with db.conn() as c:
                    self.assertEqual(c.execute(
                        "SELECT COUNT(*) FROM decision_snapshots WHERE hash='stranded'"
                    ).fetchone()[0], 1)

    def test_retired_contract_versions_archive_without_touching_the_live_one(self):
        """Retired versions are unreachable by the engine already -- every live
        reader filters on version AND config_hash -- so they archive on version,
        not on age. A live-version decision from the same session stays."""
        import database as db, archive
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'live.db')):
                db.init_db()
                with db.conn() as c:
                    for ver, sym in (('v4', 'OLD1'), ('v4', 'OLD2'), ('v5', 'NEW')):
                        c.execute('INSERT OR IGNORE INTO decision_snapshots VALUES (?,?)',
                                  (f'snap{sym}', '{"b":1}'))
                        c.execute('INSERT OR IGNORE INTO decisions VALUES (?,?,?,?,?,?,?)',
                                  (sym, '2026-09-04', ver, 'cfg', f'snap{sym}', '{}', '{}'))
                out = str(Path(tmp) / 'r.db')
                man = archive.export_selection('retired_decisions', 'v5', out)
                self.assertEqual(man['decisions'], 2)
                self.assertTrue(archive.verify(out, man)['ok'])
                res = archive.purge_selection(out, 'retired_decisions', 'v5')
                self.assertEqual(res['purged'], 2)
                with db.conn() as c:
                    self.assertEqual(
                        [r[0] for r in c.execute('SELECT symbol FROM decisions')], ['NEW'])
                    # The surviving decision's snapshot must NOT have gone with them.
                    self.assertEqual(c.execute(
                        'SELECT COUNT(*) FROM decisions d WHERE NOT EXISTS ('
                        ' SELECT 1 FROM decision_snapshots s WHERE s.hash=d.snapshot_hash)'
                    ).fetchone()[0], 0)
                archive.restore_selection(out)
                with db.conn() as c:
                    self.assertEqual(
                        c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 3)

    def test_runs_archive_round_trip_and_cutoff_guard(self):
        import database as db, archive
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'live.db')):
                db.init_db()
                with db.conn() as c:
                    for t_ in ('2026-06-01T10:00:00', '2026-06-02T10:00:00',
                               '2026-09-01T10:00:00'):
                        c.execute('INSERT INTO runs (run_time, symbol) VALUES (?,?)',
                                  (t_, 'PSO'))
                out = str(Path(tmp) / 'runs.db')
                man = archive.export_selection('runs_before', '2026-07-01', out)
                self.assertEqual(man['runs'], 2)
                self.assertTrue(archive.verify(out, man)['ok'])
                # An archive holding one selection must refuse to purge another.
                wrong = archive.purge_selection(out, 'runs_before', '2026-08-01')
                self.assertEqual(wrong['purged'], 0)
                self.assertIn('refused', wrong)
                with db.conn() as c:
                    self.assertEqual(
                        c.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 3)
                self.assertEqual(
                    archive.purge_selection(out, 'runs_before', '2026-07-01')['runs_purged'], 2)
                with db.conn() as c:
                    self.assertEqual(
                        c.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 1)
                archive.restore_selection(out)
                with db.conn() as c:
                    self.assertEqual(
                        c.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 3)

    def test_selection_purge_refuses_a_corrupted_archive(self):
        """Same guarantee as the session archive: nothing is deleted that
        cannot be restored."""
        import database as db, archive, sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'live.db')):
                db.init_db()
                with db.conn() as c:
                    c.execute('INSERT INTO runs (run_time, symbol) VALUES (?,?)',
                              ('2026-06-01T10:00:00', 'PSO'))
                out = str(Path(tmp) / 'runs.db')
                archive.export_selection('runs_before', '2026-07-01', out)
                bad = sqlite3.connect(out)
                bad.execute('DELETE FROM runs'); bad.commit(); bad.close()
                res = archive.purge_selection(out, 'runs_before', '2026-07-01')
                self.assertEqual(res['purged'], 0)
                self.assertIn('verification', res['refused'])
                with db.conn() as c:
                    self.assertEqual(
                        c.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 1)

    def test_purge_refuses_a_corrupted_archive(self):
        """The guarantee worth having: nothing is deleted that cannot be restored."""
        import database as db, archive, sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'live.db')):
                db.init_db(); self._seed()
                out = str(Path(tmp) / 'a.db')
                archive.export('2026-09-03', out)
                bad = sqlite3.connect(out)
                bad.execute('DELETE FROM decisions WHERE rowid=1'); bad.commit(); bad.close()
                res = archive.purge(out, '2026-09-03')
                self.assertEqual(res['purged'], 0)
                self.assertIn('verification', res['refused'])
                with db.conn() as c:      # live rows untouched
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 3)

    def test_purge_refuses_a_cutoff_mismatch(self):
        import database as db, archive
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'live.db')):
                db.init_db(); self._seed()
                out = str(Path(tmp) / 'a.db')
                archive.export('2026-09-03', out)
                res = archive.purge(out, '2026-09-02')
                self.assertEqual(res['purged'], 0)
                self.assertIn('cutoff', res['refused'])

    def test_a_snapshot_still_referenced_is_never_purged(self):
        import database as db, archive
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, 'DB_PATH', str(Path(tmp) / 'live.db')):
                db.init_db()
                with db.conn() as c:
                    c.execute('INSERT INTO decision_snapshots VALUES (?,?)', ('shared', '{}'))
                    c.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?)',
                              ('OLD', '2026-09-01', 'v', 'cfg', 'shared', '{}', '{}'))
                    c.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?)',
                              ('NEW', '2026-09-05', 'v', 'cfg', 'shared', '{}', '{}'))
                out = str(Path(tmp) / 'a.db')
                archive.export('2026-09-05', out)
                archive.purge(out, '2026-09-05')
                with db.conn() as c:
                    kept = c.execute("SELECT COUNT(*) FROM decision_snapshots WHERE hash='shared'").fetchone()[0]
                self.assertEqual(kept, 1, 'a snapshot a live decision still points at was purged')


class NewsRatingsDisplayOnly(unittest.TestCase):
    """News is shown for manual cross-verification and must never move a signal.
    Restored to the dashboard on 2026-09-10 as an always-on compact panel: the
    per-card pills only render on Buy/Strong Buy cards, so in a risk-off market
    the ratings were invisible exactly when a second opinion was most wanted."""

    def test_news_carries_zero_score_weight(self):
        self.assertEqual(config.WEIGHTS.get('sentiment', 0), 0.0)
        self.assertEqual(config.WEIGHTS.get('macro_news', 0), 0.0)

    def test_only_the_claude_routine_file_is_read(self):
        """The GLM file is three weeks old and carries the OLD shape with no
        causality/horizon/confidence, so falling through to it would show a bare
        rating stripped of the qualifiers that make it interpretable."""
        import news_feed
        self.assertEqual(news_feed._RATING_FILES, ('news_ai_ratings.json',))
