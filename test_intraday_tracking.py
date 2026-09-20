import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import intraday_tracking as it
from opportunity_cards import card_html


class QuoteFreshnessTests(unittest.TestCase):
    def test_saved_fresh_flag_does_not_survive_weekend(self):
        from intraday_momentum import quote_is_current
        quote = {'last_trade': '2026-09-18T06:00:00+00:00', 'stale': False}
        self.assertFalse(quote_is_current(quote, datetime(2026, 9, 20, 6, tzinfo=timezone.utc)))

    def test_live_quote_boundary_and_future(self):
        from intraday_momentum import quote_is_current
        now = datetime(2026, 9, 21, 6, tzinfo=timezone.utc)
        for seconds, expected in [(0, True), (1200, True), (1201, False), (-1, False)]:
            quote = {'last_trade': (now-timedelta(seconds=seconds)).isoformat()}
            self.assertEqual(quote_is_current(quote, now), expected)
        self.assertFalse(quote_is_current({'last_trade': 'broken'}, now))


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 21, 5, 30, tzinfo=timezone.utc)
        self.quote = {'symbol': 'PSO', 'price': 102., 'prior_close': 100., 'change_pct': 2.,
                      'last_trade': self.now.isoformat(), 'note': None}
        self.ticks = [[datetime(2026, 9, 21, 4, 32, tzinfo=timezone.utc).timestamp(), 100., 1000.],
                      [(self.now-timedelta(minutes=15)).timestamp(), 101., 1000.],
                      [(self.now-timedelta(minutes=5)).timestamp(), 101.5, 10000.],
                      [self.now.timestamp(), 102., 10000.]]

    def row(self):
        return it.assess(self.quote, self.ticks, {'open': 100.}, self.now)

    def capture(self, at, row=None):
        row = copy.deepcopy(row or self.row())
        row['last_trade'] = at.isoformat()
        return {'session': '2026-09-21', 'checked_at': at.isoformat(), 'observations': [row], 'news_reviews': {}}

    def test_fixed_window_and_open_are_separate(self):
        row = self.row()
        self.assertTrue(row['qualifies'])
        self.assertEqual(row['gap_pct'], 0)
        self.assertAlmostEqual(row['since_open_pct'], 2)
        self.assertAlmostEqual(row['recent_pct'], (102/101-1)*100)
        self.assertEqual(row['window_volume'], 20000)
        self.assertEqual(row['window_turnover'], 2035000)

    def test_missing_open_and_anchor_never_qualify(self):
        self.assertFalse(it.assess(self.quote, self.ticks, None, self.now)['qualifies'])
        self.assertFalse(it.assess(self.quote, self.ticks[2:], {'open': 100}, self.now)['qualifies'])
        # Comparing to the previous run 30 minutes ago is not a 15-minute measure.
        self.ticks[1][0] -= 900
        self.assertIsNone(self.row()['recent_pct'])

    def test_future_stale_and_compliance(self):
        self.assertFalse(it.assess(self.quote, self.ticks, {'open': 100}, self.now, eligible=False)['qualifies'])
        self.assertFalse(it.assess(self.quote, self.ticks, {'open': 100}, self.now+timedelta(minutes=21))['qualifies'])
        future = {**self.quote, 'last_trade': (self.now+timedelta(seconds=1)).isoformat()}
        self.assertFalse(it.assess(future, self.ticks, {'open': 100}, self.now)['qualifies'])

    def test_friday_break_and_closed_market(self):
        now = datetime(2026, 9, 18, 9, 35, tzinfo=timezone.utc)  # 14:35: first minutes after break
        q = {**self.quote, 'last_trade': now.isoformat()}
        ticks = [[(now-timedelta(minutes=15)).timestamp(), 100, 100000], [now.timestamp(), 102, 100000]]
        self.assertFalse(it.assess(q, ticks, {'open': 100}, now)['qualifies'])
        self.assertFalse(it.assess(q, ticks, {'open': 100}, now+timedelta(hours=4))['qualifies'])

    def test_every_run_retained_but_continuing_setup_one_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'ticks.db'
            first = self.capture(self.now)
            a = it.archive(first, path)
            self.assertEqual(it.archive(first, path), a)
            b = it.archive(self.capture(self.now+timedelta(minutes=15)), path)
            c = it.archive(self.capture(self.now+timedelta(minutes=30)), path)
            self.assertIsNone(a['observations'][0]['episode'])
            self.assertEqual(b['observations'][0]['episode'], c['observations'][0]['episode'])
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('select count(*) from observations').fetchone()[0], 3)
                self.assertEqual(db.execute('select count(*) from episodes').fetchone()[0], 1)
                self.assertEqual(db.execute('select count(*) from sessions').fetchone()[0], 1)

    def test_deterioration_closes_setup_reentry_needs_two_new_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'ticks.db'
            it.archive(self.capture(self.now), path)
            b = it.archive(self.capture(self.now+timedelta(minutes=15)), path)
            weak = {**self.row(), 'qualifies': False, 'state': 'Weakening'}
            c = it.archive(self.capture(self.now+timedelta(minutes=30), weak), path)
            d = it.archive(self.capture(self.now+timedelta(minutes=45)), path)
            e = it.archive(self.capture(self.now+timedelta(minutes=60)), path)
            self.assertIsNone(c['observations'][0]['episode'])
            self.assertIsNone(d['observations'][0]['episode'])
            self.assertNotEqual(b['observations'][0]['episode'], e['observations'][0]['episode'])

    def test_delays_and_repeated_ticks_do_not_confirm(self):
        for minutes in (1, 31):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'ticks.db'
                it.archive(self.capture(self.now), path)
                b = it.archive(self.capture(self.now+timedelta(minutes=minutes)), path)
                self.assertIsNone(b['observations'][0]['episode'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'ticks.db'
            it.archive(self.capture(self.now), path)
            b = self.capture(self.now+timedelta(minutes=15))
            b['observations'][0]['last_trade'] = self.now.isoformat()
            self.assertIsNone(it.archive(b, path)['observations'][0]['episode'])

    def test_out_of_order_refused_without_overwriting_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'ticks.db'
            it.archive(self.capture(self.now+timedelta(minutes=15)), path)
            with self.assertRaises(ValueError):
                it.archive(self.capture(self.now), path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('select count(*) from observations').fetchone()[0], 1)

    def test_html_source_text_is_escaped(self):
        s = card_html('<script>', 'Swing', 'Buy', [('Price', '<b>')], '<img>', 'Wait', 'Risk', ['<script>'], 'time', 'foot')
        self.assertNotIn('<script>', s)
        self.assertNotIn('<img>', s)
        self.assertIn('&lt;script&gt;', s)


if __name__ == '__main__':
    unittest.main()
