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


class LivePriceQuoteTests(unittest.TestCase):
    """quote() keeps the price for EVERY symbol. detect() answers a different
    question and returns None for most of them, which is why a day with 60
    freshly-trading stocks could render an empty dashboard."""

    def setUp(self):
        from datetime import datetime, timezone
        import session_calendar as calendar
        self.now = datetime.now(timezone.utc)
        self.today = calendar.local_now(self.now).date().isoformat()
        self.prior_day = "2000-01-03"

    def _ticks(self, price, minutes_ago=1, n=3):
        base = self.now.timestamp() - minutes_ago * 60
        return [[base - i * 60, price, 100.0] for i in range(n)][::-1]

    def _hist(self, close=100.0, source="PSX historical"):
        # "PSX historical" is the only source scoring >=3 in source_priority;
        # the banked daily bars carry it. A weaker source must not be trusted
        # as a change baseline, which test_an_unvalidated_prior_bar checks.
        return [{"date": self.prior_day, "open": close, "high": close,
                 "low": close, "close": close, "volume": 1000.0, "source": source}]

    def test_price_and_change_for_an_ordinary_symbol(self):
        import intraday_momentum as im
        q = im.quote("PSO", self._ticks(105.0), self._hist(100.0), self.now)
        self.assertEqual(q["symbol"], "PSO")
        self.assertAlmostEqual(q["price"], 105.0)
        self.assertAlmostEqual(q["change_pct"], 5.0)
        self.assertAlmostEqual(q["prior_close"], 100.0)
        self.assertFalse(q["stale"])
        self.assertEqual(q["trades"], 3)

    def test_no_prior_close_yields_no_change_not_a_guess(self):
        import intraday_momentum as im
        q = im.quote("PSO", self._ticks(105.0), [], self.now)
        self.assertIsNone(q["change_pct"])
        self.assertIsNone(q["prior_close"])
        self.assertAlmostEqual(q["price"], 105.0)   # the price is still real

    def test_an_unvalidated_prior_bar_is_not_used_as_a_baseline(self):
        import intraday_momentum as im
        bad = self._hist(100.0, source="scraped guess")
        self.assertIsNone(im.quote("PSO", self._ticks(105.0), bad, self.now)["change_pct"])

    def test_a_move_past_the_circuit_limit_withholds_the_percentage(self):
        """Beyond +-10.5% is an unadjusted corporate action far more often than
        a real gap, so the number is withheld and the reason given."""
        import intraday_momentum as im
        q = im.quote("PSO", self._ticks(150.0), self._hist(100.0), self.now)
        self.assertIsNone(q["change_pct"])
        self.assertIn("corporate action", q["note"])
        self.assertAlmostEqual(q["price"], 150.0)

    def test_a_stale_price_is_shown_and_marked_never_hidden(self):
        import intraday_momentum as im
        q = im.quote("PSO", self._ticks(105.0, minutes_ago=45), self._hist(100.0), self.now)
        self.assertTrue(q["stale"])
        self.assertGreater(q["age_minutes"], 20)
        self.assertAlmostEqual(q["price"], 105.0)

    def test_no_same_day_trades_returns_nothing(self):
        import intraday_momentum as im
        old = [[self.now.timestamp() - 86400 * 3, 105.0, 100.0]]
        self.assertIsNone(im.quote("PSO", old, self._hist(), self.now))

    def test_future_and_malformed_ticks_are_dropped_not_raised(self):
        """quote() runs for all 60 symbols; one bad tick must not blank the panel."""
        import intraday_momentum as im
        ticks = self._ticks(105.0) + [
            [self.now.timestamp() + 3600, 999.0, 1.0],   # future
            ["x", "y", "z"],                              # malformed
            [self.now.timestamp(), -5.0, 1.0],            # negative price
        ]
        q = im.quote("PSO", ticks, self._hist(100.0), self.now)
        self.assertAlmostEqual(q["price"], 105.0)         # never 999.0


class LivePricePanelRendersWhenMomentumIsStale(unittest.TestCase):
    """The prices panel must NOT sit behind the momentum freshness gate.

    It did, and the early return meant that whenever the dashboard's checkout
    lagged the loop -- which is most of the time, the loop commits every ~15
    minutes and the host does not redeploy on every commit -- the whole panel
    vanished. A stale price is shown WITH its age, never hidden.
    """

    class FakeSt:
        def __init__(self):
            self.md, self.captions, self.warns, self.infos, self.frames = \
                [], [], [], [], []
        def markdown(self, t, **k): self.md.append(t)
        def caption(self, t, **k): self.captions.append(t)
        def warning(self, t, **k): self.warns.append(t)
        def info(self, t, **k): self.infos.append(t)
        def dataframe(self, rows, **k): self.frames.append(rows)

    def _write(self, tmp, checked_at, session, prices):
        import json, pathlib
        p = pathlib.Path(tmp) / "intraday_momentum.json"
        p.write_text(json.dumps({"session": session, "checked_at": checked_at,
                                 "source": "t", "checked": 1, "fresh": 1,
                                 "failed": [], "items": [], "prices": prices}))
        return p

    def _price(self, sym="PSO", stale=False):
        from datetime import datetime, timezone
        return {"symbol": sym, "price": 105.0, "prior_close": 100.0,
                "change_pct": 5.0, "day_volume": 10.0, "trades": 3,
                "last_trade": datetime.now(timezone.utc).isoformat(),
                "stale": stale, "age_minutes": 1.0, "note": None}

    def test_prices_render_even_when_the_capture_is_far_too_old(self):
        import tempfile, intraday_momentum as im, session_calendar as cal
        from datetime import datetime, timezone, timedelta
        from unittest import mock
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=90)).isoformat()
        today = cal.local_now(now).date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, old, today, [self._price()])
            st = self.FakeSt()
            with mock.patch.object(im, "PATH", p):
                im.show(st, now)
            self.assertTrue(any("Live prices" in m for m in st.md),
                            "prices panel missing on a stale capture")
            self.assertTrue(st.frames, "no price table rendered")
            self.assertTrue(any("minutes ago" in w for w in st.warns),
                            "stale capture not labelled with its age")

    def test_a_previous_session_capture_is_labelled_not_passed_off_as_live(self):
        import tempfile, intraday_momentum as im
        from datetime import datetime, timezone
        from unittest import mock
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, now.isoformat(), "1999-01-04", [self._price()])
            st = self.FakeSt()
            with mock.patch.object(im, "PATH", p):
                im.show(st, now)
            self.assertTrue(any("1999-01-04" in w and "not today" in w
                                for w in st.warns))
            self.assertTrue(st.frames)

    def test_a_missing_file_still_renders_the_momentum_notice_without_crashing(self):
        import tempfile, pathlib, intraday_momentum as im
        from datetime import datetime, timezone
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            st = self.FakeSt()
            with mock.patch.object(im, "PATH", pathlib.Path(tmp) / "absent.json"):
                im.show(st, datetime.now(timezone.utc))
            self.assertFalse(st.frames)
            self.assertTrue(st.infos)
