import copy
import sqlite3
import json
import unittest
from unittest.mock import patch
import config
import database as db
import decision_engine as de
import swing_evaluation as ev
import target_timing as tt
import upward_candidates as up
from test_trading_core import fixture, SOURCE


class AuditRegressions(unittest.TestCase):
    def test_shortlist_exposes_stale_session(self):
        bars, index = fixture()
        d = de.decide('PSO', bars, index, bars[-1]['date'])
        connection = sqlite3.connect(':memory:')
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('CREATE TABLE decisions(session,version,config_hash,payload)')
            connection.execute('INSERT INTO decisions VALUES (?,?,?,?)',
                               (bars[-1]['date'], config.STRATEGY_VERSION, de.digest(de.contract()), json.dumps(d)))
            with patch.object(db, 'conn', return_value=connection), patch('session_calendar.last_completed', return_value='2026-09-11'), patch.object(up, 'qualifies', return_value=True):
                rows = up.current()
            self.assertEqual(rows[0]['Analysis date'], bars[-1]['date'])
            self.assertIn('Older data', rows[0]['Freshness'])
        finally:
            connection.close()

    def test_history_displays_actual_horizon_and_unknown_membership(self):
        import history_view
        class Display:
            def __init__(self):
                self.frames, self.warnings = [], []
            def columns(self, n): return [self] * n
            def metric(self, *args): pass
            def caption(self, text): pass
            def info(self, text): raise AssertionError('Unknown membership must not look like no qualifying signals')
            def warning(self, text): self.warnings.append(text)
            def dataframe(self, frame, **kwargs): self.frames.append(frame)
        view = Display()
        outcome = dict(symbol='PSO', signal_date='2026-09-01', status='expired',
                       holding_sessions=30, planned_holding_sessions=30, net_return_pct=1)
        result = dict(symbol='PSO', coverage=dict(usable_days=1, missing_days=0, membership_unverified_days=1),
                      metrics=ev.metrics([outcome]), outcomes=[outcome])
        history_view.show(view, result)
        self.assertEqual(view.frames[-1].iloc[0]['Trading days held'], 30)
        self.assertEqual(view.frames[-1].iloc[0]['Planned holding limit'], 30)
        self.assertTrue(any('membership' in w for w in view.warnings))

    def item(self):
        return dict(session='2026-09-01', reference_entry=100, stop=90, target=110,
                    quantity=50, prior_avg_volume=10000,
                    execution=dict(config.EXECUTION, slippage_bps=0, fee_bps_per_side=0))

    def bar(self, volume):
        return dict(date='2026-09-02', open=100, high=111, low=95, close=108,
                    volume=volume, source=SOURCE)

    def test_late_target_not_counted_as_ten_day_success(self):
        m = ev.metrics([dict(status='target', net_return_pct=5, target_by_10=False)])
        self.assertEqual(m['target_by_10_pct'], 0)
        self.assertEqual(m['target_within_horizon_pct'], 100)

    def test_capacity_uses_frozen_prior_volume_and_preserves_legacy(self):
        item = self.item()
        statuses = [ev.resolve(item, [self.bar(v)], ['2026-09-02'])['status'] for v in (100, 100000)]
        self.assertEqual(statuses, ['target', 'target'])
        item['quantity'] = 101
        self.assertEqual(ev.resolve(item, [self.bar(1000000)], ['2026-09-02'])['status'], 'unfilled')
        item = self.item()
        item['execution'].pop('capacity_basis')
        self.assertEqual(ev.resolve(item, [self.bar(100)], ['2026-09-02'])['status'], 'unfilled')

    def test_locked_opening_is_unknown_not_a_claimed_nonfill(self):
        bar = self.bar(10000)
        bar.update(high=100, low=100, close=100)
        self.assertEqual(ev.resolve(self.item(), [bar], [bar['date']])['status'], 'unavailable')

    def test_opportunity_freezes_real_size(self):
        bars, index = fixture()
        decision = de.decide('PSO', bars, index, bars[-1]['date'])
        item = ev.opportunity(decision)
        self.assertEqual(item['quantity'], decision['risk']['position_sizing']['suggested_shares'])
        self.assertGreater(item['quantity'], 1)

    def test_pkr_liquidity_is_required_by_core_and_shortlist(self):
        bars, index = fixture()
        with patch.object(config, 'MIN_TURNOVER_PKR', 1e12):
            d = de.decide('PSO', bars, index, bars[-1]['date'])
            self.assertIn('illiquid', d['risk']['vetoes'])
            self.assertNotIn(d['signal']['signal'], ('Buy', 'Strong Buy'))
            self.assertFalse(up.qualifies(d))

    def test_target_history_cuts_future_and_rejects_invalid_bars(self):
        bars, _ = fixture(300)
        cutoff = bars[280]['date']
        with patch.object(db, 'get_daily_ohlc', return_value=bars), patch.object(db, 'get_corporate_actions', return_value=[]):
            self.assertEqual(len(tt.verified_history('PSO', cutoff)), 281)
            bars[290]['close'] = -100
            self.assertEqual(len(tt.verified_history('PSO', cutoff)), 281)
            bars[20]['close'] = -100
            self.assertEqual(tt.verified_history('PSO', cutoff), [])

    def test_target_history_adjusts_verified_actions(self):
        bars, _ = fixture(300)
        original = copy.deepcopy(bars)
        for b in bars[:150]:
            for k in ('open', 'high', 'low', 'close'):
                b[k] *= 2
            b['volume'] /= 2
        action = dict(kind='split', verified=True, source='test evidence', factor=.5,
                      volume_factor=2, ex_date=bars[150]['date'], known_at=bars[149]['date'])
        with patch.object(db, 'get_daily_ohlc', return_value=bars), patch.object(db, 'get_corporate_actions', return_value=[action]):
            self.assertEqual(tt.verified_history('PSO', bars[-1]['date']), original)

    def test_unrelated_config_does_not_invalidate_decisions(self):
        before = de.digest(de.contract())
        with patch.object(config, 'REPLAY_LOOKBACK', 99):
            self.assertEqual(de.digest(de.contract()), before)
        with patch.object(config, 'MIN_TURNOVER_PKR', 1):
            self.assertNotEqual(de.digest(de.contract()), before)

    def test_backtest_does_not_invent_early_membership(self):
        with patch.object(db, 'get_daily_ohlc', return_value=[]), patch.object(db, 'get_eod_history', return_value=[]), patch.object(db, 'get_corporate_actions', return_value=[]), patch('shariah_checker.check', return_value={'eligible_for_ranking': True}), patch.object(ev, 'replay') as replay:
            ev.backtest('PSO')
            eligible = replay.call_args.args[4]
            self.assertFalse(eligible('2026-09-08'))
            self.assertTrue(eligible(config.UNIVERSE_KNOWN_FROM))

    def test_cohort_summary_separates_versions_and_contracts(self):
        connection = sqlite3.connect(':memory:')
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript('CREATE TABLE cohort_candidates(id,version,config_hash); CREATE TABLE cohort_outcomes(candidate_id,status);')
            connection.executemany('INSERT INTO cohort_candidates VALUES (?,?,?)', [('a','v4','x'),('b','v5','y'),('c','v5','z')])
            connection.executemany('INSERT INTO cohort_outcomes VALUES (?,?)', [('a','stop'),('b','stop'),('c','stop')])
            with patch.object(db, 'conn', return_value=connection):
                rows = db.cohort_summary()
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(r['n'] == 1 for r in rows))
        finally:
            connection.close()
