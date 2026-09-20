import copy
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import short_horizon as sh
import short_horizon_refresh as refresh


def fixture():
    dates = [d.strftime('%Y-%m-%d') for d in pd.bdate_range(end='2026-09-18', periods=42)]
    bars = []
    for i, day in enumerate(dates):
        c = 100 + i * .3 + math.sin(i)
        bars.append(dict(date=day, open=c-.2, high=c+1, low=c-1, close=c, volume=200000,
                         source='PSX official historical'))
    u = dict(symbol='ASL', member=True, exchange_nc=False, quote_price=110, market_cap=2e9,
             average_volume=200000, membership_effective_date=None, sector='Test', pe=None)
    return dict(as_of='2026-09-20T12:00:00+05:00', market_session=dates[-1], sessions=dates,
                universe_observed_at='2026-09-20T11:00:00+05:00', universe=[u], bars={'ASL': bars},
                evidence=[], actions=[], config=sh.config())


def good_metrics():
    return dict(price=110, ema10=109, ema20=108, ema40=107, rsi=60, macd_histogram=1,
                return_10_sessions=3, relative_volume=1.2, atr_percent=2, extension_atr=1,
                adx=25, money_flow=.1, median_turnover=20e6, volume=200000, change=1)


def evidence():
    return dict(symbol='ASL', published_at='2026-09-18T10:00:00+05:00',
                known_at='2026-09-18T11:00:00+05:00', expires_at='2026-09-21T23:00:00+05:00',
                source='https://dps.psx.com.pk/example.pdf', rationale='Read original notice',
                quality='primary-full', linkage='direct', assessment='positive', event_risk='resolved',
                event_date='2026-09-17')


class ResearchTests(unittest.TestCase):
    def test_numbers_and_missing(self):
        for value in (None, '', '—', 'N/A', 'nan', 'inf', True, '1,234oops'):
            self.assertIsNone(sh.number(value))
        self.assertEqual(sh.number('1.25B'), 1250000000)
        self.assertEqual(sh.number('−3.2%'), -3.2)
        self.assertEqual(sh.number('12,345'), 12345)
        self.assertEqual(sh.number(5.8e-5), 5.8e-5)
        self.assertEqual(sh.number('5.8e-5'), 5.8e-5)

    def test_exact_share_identity_and_membership(self):
        rows = sh.universe_rows([dict(symbol='ASLPS NC', listed='ALLSHR,KMIALLSHR'),
                                 dict(symbol='ASL', listed='ALLSHR,NOTKMIALLSHR')])
        self.assertEqual(rows[0]['symbol'], 'ASLPS')
        self.assertTrue(rows[0]['exchange_nc'])
        self.assertTrue(rows[0]['member'])
        self.assertFalse(rows[1]['member'])
        self.assertFalse(sh.news_for('ASLPS', [evidence()], sh.stamp(fixture()['as_of']), sh.config())['items'])

    def test_raw_screener_precision_and_index_separator(self):
        html = '<thead><tr><th data-name="symbol"></th><th data-name="listed"></th><th data-name="marketcap"></th></tr></thead><tr><td>ASL</td><td>ALLSHR,KMIALLSHR</td><td data-order="1234567890">1.2B</td></tr>'
        _, rows = refresh.parse_screener(html)
        u = sh.universe_rows(rows)[0]
        self.assertTrue(u['member'])
        self.assertEqual(u['market_cap'], 1234567890)

    def test_effective_membership_and_nc_are_separate(self):
        data = fixture()
        data['universe'][0]['membership_effective_date'] = '2026-09-21'
        self.assertFalse(sh.build(data)['rows'])
        data['universe'][0]['membership_effective_date'] = None
        data['universe'][0]['exchange_nc'] = True
        result = sh.build(data)
        self.assertIn('not a Shariah ruling', str(result['excluded']))

    def test_future_bars_do_not_change_features(self):
        data = fixture()
        before = sh.build(data)['rows']
        data['bars']['ASL'].append({**data['bars']['ASL'][-1], 'date': '2026-09-21', 'close': 9000})
        self.assertEqual(before, sh.build(data)['rows'])

    def test_future_session_rejected(self):
        data = fixture()
        data['market_session'] = '2026-09-21'
        with self.assertRaises(ValueError):
            sh.build(data)

    def test_missing_duplicate_bad_source_and_action_block(self):
        for change in ('missing', 'duplicate', 'source', 'action'):
            data = fixture()
            if change == 'missing':
                data['bars']['ASL'].pop(5)
            elif change == 'duplicate':
                data['bars']['ASL'].append(data['bars']['ASL'][0])
            elif change == 'source':
                data['bars']['ASL'][0]['source'] = 'unverified intraday'
            else:
                data['actions'] = [dict(symbol='ASL', ex_date='2026-09-15', verified=False)]
            row = sh.build(data)['rows'][0]
            self.assertIsNone(row['score'], change)
            self.assertEqual(row['classification'], 'Data incomplete')

    def test_universe_freshness_and_failed_refresh(self):
        for key, value in (('universe_observed_at', '2026-09-18'),
                           ('universe_observed_at', '2026-09-21'), ('universe_refresh_failed', True)):
            data = fixture()
            data[key] = value
            self.assertIsNone(sh.build(data)['rows'][0]['score'])

    def test_publication_known_time_event_date_and_expiry(self):
        item = evidence()
        cfg = sh.config()
        # An event occurring yesterday cannot leak a notice published tomorrow.
        item['published_at'] = '2026-09-21'
        self.assertFalse(sh.news_for('ASL', [item], sh.stamp(fixture()['as_of']), cfg)['items'])
        item = evidence()
        item['known_at'] = '2026-09-21T10:00:00+05:00'
        self.assertFalse(sh.news_for('ASL', [item], sh.stamp(fixture()['as_of']), cfg)['items'])
        item = evidence()
        item['published_at'] = '2026-09-20'
        self.assertFalse(sh.news_for('ASL', [item], sh.stamp(fixture()['as_of']), cfg)['items'])
        item = evidence()
        item['expires_at'] = '2026-09-19'
        self.assertFalse(sh.news_for('ASL', [item], sh.stamp(fixture()['as_of']), cfg)['items'])

    def test_classification_boundaries_and_precedence(self):
        cfg = sh.config()
        news = {'verified': [evidence()], 'items': [evidence()]}
        m = good_metrics()
        self.assertEqual(sh.classify(m, news, cfg)[:2], ('Momentum candidate', 100))
        m['rsi'] = 76
        m['macd_histogram'] = -1
        self.assertEqual(sh.classify(m, news, cfg)[0], 'Overextended')
        m['volume'] = 0
        self.assertEqual(sh.classify(m, news, cfg)[0], 'Liquidity too low')
        m['adx'] = None
        self.assertEqual(sh.classify(m, news, cfg)[:2], ('Data incomplete', None))
        m = good_metrics()
        m['adx'] = 19.99
        self.assertEqual(sh.classify(m, news, cfg)[0], 'Confirmation required')
        self.assertEqual(sh.classify(good_metrics(), {'verified': [], 'items': []}, cfg)[0], 'Confirmation required')

    def test_periods_never_collapsed(self):
        f = sh.financial_context(dict(annualGrowth=-36.98, growth=533.18, annualYear=2026))
        self.assertTrue(f['opposite_directions'])
        self.assertIsNone(f['ttm_period_end'])
        self.assertEqual(f['annual_period'], 2026)

    def test_reproducible_rank_and_input_immutability(self):
        data = fixture()
        data['universe'].append({**data['universe'][0], 'symbol': 'ZZZ'})
        data['bars']['ZZZ'] = copy.deepcopy(data['bars']['ASL'])
        original = copy.deepcopy(data)
        result = sh.build(data)
        self.assertEqual(data, original)
        self.assertEqual(result, sh.build(data))
        self.assertEqual([r['symbol'] for r in result['rows']], ['ASL', 'ZZZ'])
        data['universe'].reverse()
        self.assertEqual(result['rows'], sh.build(data)['rows'])

    def test_baseline_hashes(self):
        manifest = json.loads((sh.ROOT / 'analysis/baselines/2026-09-18/manifest.json').read_text())
        with zipfile.ZipFile(sh.ROOT / 'analysis/baselines/2026-09-18/original.zip') as z:
            for name, meta in manifest['files'].items():
                import hashlib
                self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), meta['sha256'], name)

    def test_failed_refresh_publishes_status_without_replacing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'short_horizon_latest.json').write_text('{"original": true}')
            with patch.object(refresh, 'ROOT', root), patch.object(refresh, 'collect', side_effect=RuntimeError('Provider down')):
                with self.assertRaises(RuntimeError):
                    refresh.safe_refresh()
            self.assertEqual(json.loads((root / 'short_horizon_latest.json').read_text()), {'original': True})
            self.assertFalse(json.loads((root / 'short_horizon_status.json').read_text())['ok'])


if __name__ == '__main__':
    unittest.main()
