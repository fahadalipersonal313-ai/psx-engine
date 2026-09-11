import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import config
import decision_engine as de
import depth_analysis as depth
import signal_generator as sg
from test_trading_core import fixture


class MarketWarningTests(unittest.TestCase):
    def decision(self, vetoes=()):
        bars, ix = fixture()
        tech = de.decide('PSO', bars, ix, bars[-1]['date'])['technical']
        tech.update(classification='Bullish', cmf=.2, relative_strength=70, shock_up_today=False, extended=False)
        return sg.generate('PSO', 85, 80, {'vetoes':list(vetoes), 'risk_level':'Low'},
                           {'eligible_for_ranking':True}, tech, regime='risk-off', previous_qualified=True)

    def test_market_only_warns_but_stock_guards_remain(self):
        with patch.object(config, 'REGIME_GATE_ENABLED', False):
            result = self.decision()
            self.assertEqual(result['signal'], 'Strong Buy')
            self.assertIn('warning', ' '.join(result['reasons']))
            self.assertEqual(self.decision(['illiquid'])['signal'], 'Watch')
            self.assertEqual(self.decision(['breakdown'])['signal'], 'Avoid')
        with patch.object(config, 'REGIME_GATE_ENABLED', True):
            self.assertEqual(self.decision()['signal'], 'Watch')


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, 5, 20, tzinfo=timezone.utc)
        self.rows = [dict(symbol='PSO', time=self.now-timedelta(seconds=(15-i)*5),
                          source='test', levels=[(100,300+i,100.02,100)], day_volume=None) for i in range(16)]

    def test_persistent_quotes_are_context_not_buy(self):
        result = depth.analyze(self.rows, 'PSO', self.now)
        self.assertIn('buying interest', result['Read'])
        self.assertEqual(result['Data shown'], 'Best bid/offer only')
        self.assertIn('None', result['Score effect'])
        self.assertNotIn('accumulation', result['Read'])

    def test_stale_future_closed_and_unchanging_fail_closed(self):
        self.assertIn('too old', depth.analyze(self.rows, 'PSO', self.now+timedelta(seconds=40))['Read'])
        self.assertEqual(depth.analyze(self.rows, 'PSO', self.now-timedelta(minutes=10))['Read'], 'No recent quotes')
        self.assertIn('closed', depth.analyze(self.rows, 'PSO', self.now+timedelta(hours=12))['Read'])
        for row in self.rows:
            row['levels'] = [(100,300,100.02,100)]
        self.assertIn('Collect', depth.analyze(self.rows, 'PSO', self.now)['Read'])

    def test_gaps_and_fading_interest(self):
        self.rows[0]['time'] -= timedelta(seconds=40)
        self.assertIn('gaps', depth.analyze(self.rows, 'PSO', self.now)['Read'])
        self.rows[0]['time'] += timedelta(seconds=40)
        self.rows[-1]['levels'] = [(100,10,100.02,500)]
        self.assertIn('faded', depth.analyze(self.rows, 'PSO', self.now)['Read'])

    def test_vendor_and_level_counts_are_not_pooled(self):
        self.rows[-1]['source'] = 'other'
        self.assertIn('Collect', depth.analyze(self.rows, 'PSO', self.now)['Read'])

    def test_csv_validation_and_timezone(self):
        header = 'symbol,captured_at,bid_price,bid_volume,ask_price,ask_volume\n'
        good = 'PSO,2026-09-11T10:20:00+05:00,100,300,100.02,100\n'
        rows, bad = depth.parse(header+good)
        self.assertEqual(bad, 0)
        self.assertEqual(rows[0]['time'], self.now)
        for data in [good.replace('100.02','99'), good.replace(',300,',',0,'), good.replace('+05:00','')]:
            rows, bad = depth.parse(header+data)
            self.assertEqual(rows, [])
            self.assertEqual(bad, 1)

    def test_multilevel_and_conflicting_timestamp(self):
        header = 'symbol,timestamp,level,bid_price,bid_size,ask_price,ask_size\n'
        a = 'PSO,2026-09-11T05:20:00Z,1,100,300,100.02,100\n'
        b = 'PSO,2026-09-11T05:20:00Z,2,99.9,200,100.1,100\n'
        rows, bad = depth.parse(header+a+b)
        self.assertEqual(len(rows[0]['levels']), 2)
        rows, bad = depth.parse(header+a+a.replace(',300,',',400,'))
        self.assertFalse(rows)
        self.assertEqual(bad, 1)

    def test_legacy_clock_requires_filename_date(self):
        data = 'symbol,t,bid_price,bid_volume,ask_price,ask_volume\nPSO,10:20:00,100,300,100.02,100\n'
        self.assertFalse(depth.parse(data)[0])
        self.assertEqual(depth.parse(data, 'PSO_2026-09-11.csv')[0][0]['time'], self.now)
