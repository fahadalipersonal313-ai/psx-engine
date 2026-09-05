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
        with patch.object(config,'SIGNAL_THRESHOLDS',{'strong_buy':0,'buy':0,'watch':0,'hold':0}), patch('signal_generator.T',{'strong_buy':0,'buy':0,'watch':0,'hold':0}), patch.object(config,'BUY_MIN_CMF',-1), patch.object(config,'RS_LAGGARD_VETO',0), patch.object(config,'HYSTERESIS_BAND',0), patch('technical_analyzer.analyze',wraps=ta.analyze) as analyze:
            # Actual classification also qualifies; use a controlled technical
            # snapshot to isolate confirmation rather than fitting a price path.
            real=ta.analyze('PSO',pd.DataFrame(bars),{'price':bars[-1]['close']},70,bars)
            real.update(classification='Bullish',breakdown=False,cmf=.2,relative_strength=70)
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
    def test_expiry_ten_sessions(self):
        bars=[dict(self.bar,date=d.strftime('%Y-%m-%d'),high=105,close=102) for d in pd.bdate_range('2026-09-02',periods=10)]
        r=ev.resolve(self.item,bars,[b['date'] for b in bars]); self.assertEqual(r['status'],'expired'); self.assertEqual(r['holding_sessions'],10)
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
