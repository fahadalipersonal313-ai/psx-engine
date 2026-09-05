import unittest
from unittest.mock import patch
import config
import swing_evaluation as ev
import upward_candidates as up
from test_trading_core import fixture


class RecentHistoryTests(unittest.TestCase):
    def test_complete_short_history_is_not_penalized_as_missing(self):
        import decision_engine
        bars, ix = fixture(42)
        d = decision_engine.decide('PSO', bars, ix, bars[-1]['date'])
        self.assertFalse(d['technical']['low_confidence'])
        self.assertEqual(d['scoring']['data_quality'], 'good')
        self.assertGreaterEqual(d['scoring']['confidence'], 45)

    def test_recent_replay_ignores_old_bad_rows(self):
        bars, ix = fixture(100)
        bars[0]['source'] = 'intraday'
        r = ev.replay('PSO', bars, ix, lookback=21)
        self.assertEqual(r['coverage']['tested_days'], 21)
        self.assertEqual(r['coverage']['usable_days'], 21)
        self.assertEqual(r['coverage']['missing_days'], 0)

    def test_missing_recent_bar_is_reported(self):
        bars, ix = fixture(64)
        bars.pop(-3)
        r = ev.replay('PSO', bars, ix, lookback=21)
        self.assertGreater(r['coverage']['missing_days'], 0)

    def test_warmup_not_counted_as_evaluation(self):
        bars, ix = fixture(64)
        r = ev.replay('PSO', bars, ix, lookback=21)
        self.assertEqual(r['decisions'][0]['decision_session'], ix[-21]['date'])
        self.assertEqual(len(r['decisions']), 21)

    def test_upward_filter_rejects_weak_momentum(self):
        d = {'signal': {'signal': 'Watch'}, 'snapshot': {'eligible': True},
             'technical': dict(price=100, ema10=98, ema20=96, ema40=94,
                rsi=60, macd_hist=1, momentum_20d=5, relative_strength=65,
                cmf=.2, avg_volume=500000, stop_loss=95, target1=110, target2=None)}
        self.assertTrue(up.qualifies(d))
        d['technical']['macd_hist'] = -1
        self.assertFalse(up.qualifies(d))
        d['technical']['macd_hist'] = 1
        d['snapshot']['eligible'] = False
        self.assertFalse(up.qualifies(d))


if __name__ == '__main__':
    unittest.main()
