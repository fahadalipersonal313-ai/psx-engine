"""Deterministic comparison tests; no source database writes or network calls."""
import copy
from datetime import datetime, timezone
import json
import statistics
import unittest
from unittest.mock import MagicMock, patch

import research_calendar
import research_comparisons as comparisons
from research_contract import UNIVERSE


NOW = datetime(2026, 10, 4, 10, tzinfo=timezone.utc)
CUTOFF = '2026-10-02'
STOCK_SOURCE = 'PSX DPS historical (official)'
INDEX_SOURCE = 'PSX closing_rates PDF (official download)'


def fixture():
    dates = research_calendar.expected(CUTOFF, 42)
    histories = {}
    for offset, symbol in enumerate(UNIVERSE):
        rows = []
        for number, day in enumerate(dates):
            close = 100 + offset * 10 + number
            rows.append({'date': day, 'open': close - .5, 'high': close + 1, 'low': close - 1,
                         'close': close, 'volume': 1000 + number * 10, 'source': STOCK_SOURCE})
        histories[symbol] = rows
    benchmark = [{'date': day, 'open': None, 'close': 100_000 + number * 100,
                  'volume': None, 'source': INDEX_SOURCE} for number, day in enumerate(dates)]
    actions = {symbol: [] for symbol in UNIVERSE}
    return histories, benchmark, actions


def row(result, symbol='PRL'):
    return next(stock for stock in result['stocks'] if stock['symbol'] == symbol)


def calculate(histories=None, benchmark=None, actions=None, **kwargs):
    default_histories, default_benchmark, default_actions = fixture()
    return comparisons.calculate(default_histories if histories is None else histories,
                                 default_benchmark if benchmark is None else benchmark,
                                 default_actions if actions is None else actions, now=kwargs.pop('now', NOW), **kwargs)


class ResearchComparisonsTests(unittest.TestCase):
    def test_measured_returns_need_n_plus_one_closes_and_report_basis(self):
        result = calculate()
        self.assertEqual(result['universe'], list(UNIVERSE))
        self.assertEqual(result['as_of_session'], CUTOFF)
        self.assertEqual(result['benchmark'], 'KSE100')
        self.assertIn('not a like-for-like', result['benchmark_basis'])
        for sessions, start in ((5, 136), (20, 121)):
            metric = row(result)['returns'][str(sessions)]
            expected_stock = (141 / start - 1) * 100
            expected_index = (104100 / (100000 + (41 - sessions) * 100) - 1) * 100
            self.assertEqual(metric['status'], 'available')
            self.assertEqual(metric['required_closes'], sessions + 1)
            self.assertAlmostEqual(metric['stock_change_pct'], expected_stock)
            self.assertAlmostEqual(metric['benchmark_change_pct'], expected_index)
            self.assertAlmostEqual(metric['difference_pp'], expected_stock - expected_index)
            self.assertEqual(metric['source']['stock'], [STOCK_SOURCE])
            self.assertEqual(metric['source']['benchmark'], [INDEX_SOURCE])
        json.dumps(result, allow_nan=False)

    def test_liquidity_is_median_of_twenty_daily_products(self):
        histories, _, _ = fixture()
        # Deliberately decorrelate volume and close to distinguish the median
        # product from the (incorrect) product of two independent medians.
        for i, bar in enumerate(histories['PRL'][-20:]):
            bar['volume'] = 10000 if i % 3 == 0 else 100 + 1000 * (19 - i)
        selected = histories['PRL'][-20:]
        metric = row(calculate(histories=histories))['liquidity']
        self.assertEqual(metric['status'], 'available')
        self.assertEqual(metric['median20_volume_shares'], statistics.median(bar['volume'] for bar in selected))
        self.assertEqual(metric['median20_turnover_pkr'], statistics.median(bar['volume'] * bar['close'] for bar in selected))
        self.assertIn('proxy', metric['turnover_basis'])
        self.assertEqual(metric['observed_sessions'], 20)

    def test_zero_volume_is_valid_and_has_zero_liquidity(self):
        histories, _, _ = fixture()
        for bar in histories['PRL']:
            bar['volume'] = 0
        metric = row(calculate(histories=histories))['liquidity']
        self.assertEqual(metric['status'], 'available')
        self.assertEqual(metric['median20_volume_shares'], 0)
        self.assertEqual(metric['median20_turnover_pkr'], 0)

    def test_joint_missing_date_cannot_be_mistaken_for_an_exchange_holiday(self):
        histories, benchmark, _ = fixture()
        for bars in [*histories.values(), benchmark]:
            bars.pop(-3)
        metric = row(calculate(histories, benchmark))['returns']['5']
        self.assertEqual(metric['status'], 'unavailable')
        self.assertIsNone(metric['difference_pp'])
        self.assertTrue(any('independent completed-session calendar' in reason for reason in metric['reasons']))

    def test_stale_data_does_not_move_cutoff_backwards(self):
        histories, benchmark, _ = fixture()
        for bars in [*histories.values(), benchmark]:
            bars.pop()
        result = calculate(histories, benchmark)
        self.assertEqual(result['as_of_session'], CUTOFF)
        self.assertEqual(row(result)['returns']['5']['status'], 'unavailable')

    def test_twenty_closes_cannot_be_reported_as_twenty_session_return(self):
        histories, benchmark, _ = fixture()
        histories['PRL'] = histories['PRL'][-20:]
        result = row(calculate(histories, benchmark))
        self.assertEqual(result['returns']['20']['status'], 'unavailable')
        self.assertEqual(result['returns']['5']['status'], 'available')
        self.assertEqual(result['liquidity']['status'], 'available')

    def test_duplicate_unexpected_and_malformed_dates_fail_closed(self):
        for bad_date in ('2026-09-27', CUTOFF, 'not-a-date', '2026-10-02T00:00:00'):
            with self.subTest(bad_date=bad_date):
                histories, _, _ = fixture()
                histories['PRL'].append(dict(histories['PRL'][-1], date=bad_date))
                self.assertEqual(row(calculate(histories))['returns']['5']['status'], 'unavailable')

    def test_future_rows_are_ignored_and_history_order_is_not_assumed(self):
        histories, benchmark, _ = fixture()
        expected = calculate(histories, benchmark)
        for bars in [*histories.values(), benchmark]:
            bars.append({'date': '2026-10-05', 'close': float('nan')})
            bars.reverse()
        self.assertEqual(calculate(histories, benchmark), expected)

    def test_live_monday_uses_friday_completed_session(self):
        during_monday = datetime(2026, 10, 5, 5, tzinfo=timezone.utc)
        result = calculate(now=during_monday)
        self.assertEqual(result['as_of_session'], CUTOFF)
        self.assertEqual(row(result)['returns']['5']['status'], 'available')

    def test_prices_and_volumes_are_finite_and_full_bar_shape_validated(self):
        for field, value in (('close', float('nan')), ('close', float('inf')), ('close', 0),
                             ('close', True), ('volume', float('inf')), ('volume', -1),
                             ('volume', None), ('volume', True), ('low', 9999)):
            with self.subTest(field=field, value=value):
                histories, _, _ = fixture()
                histories['PRL'][-3][field] = value
                result = row(calculate(histories))
                self.assertEqual(result['returns']['5']['status'], 'unavailable')
                self.assertEqual(result['liquidity']['status'], 'unavailable')
                json.dumps(result, allow_nan=False)

    def test_benchmark_requires_finite_close_but_not_fabricated_ohlc_or_volume(self):
        _, benchmark, _ = fixture()
        self.assertEqual(row(calculate(benchmark=benchmark))['returns']['5']['status'], 'available')
        for value in (float('nan'), float('inf'), False, 0, None):
            with self.subTest(value=value):
                bad = copy.deepcopy(benchmark)
                bad[-3]['close'] = value
                metric = row(calculate(benchmark=bad))['returns']['5']
                self.assertEqual(metric['benchmark_status'], 'unavailable')
                self.assertIsNone(metric['difference_pp'])

    def test_sources_must_be_finalized_stock_and_psx_benchmark(self):
        for source in ('PSX official intraday', 'PSX historical intraday', '', None):
            with self.subTest(source=source):
                histories, _, _ = fixture()
                histories['PRL'][-2]['source'] = source
                self.assertEqual(row(calculate(histories))['returns']['5']['status'], 'unavailable')
        _, benchmark, _ = fixture()
        benchmark[-1].pop('source')
        self.assertEqual(row(calculate(benchmark=benchmark))['returns']['5']['status'], 'unavailable')

    def test_each_window_is_validated_independently(self):
        histories, _, _ = fixture()
        histories['PRL'][-12]['close'] = None
        result = row(calculate(histories))
        self.assertEqual(result['returns']['5']['status'], 'available')
        self.assertEqual(result['returns']['20']['status'], 'unavailable')
        self.assertEqual(result['liquidity']['status'], 'unavailable')

    def test_unstored_beyond_circuit_gap_blocks_returns(self):
        histories, _, _ = fixture()
        for bar in histories['PRL'][-3:]:
            for field in ('open', 'high', 'low', 'close'):
                bar[field] *= .8
        metric = row(calculate(histories))['returns']['5']
        self.assertEqual(metric['status'], 'unavailable')
        self.assertTrue(any('discontinuity' in reason for reason in metric['reasons']))

    def test_all_known_actions_block_raw_comparison_even_if_verified_and_small(self):
        for kind, verified in (('bonus', False), ('bonus', True), ('split', True), ('rights', True), ('dividend', True)):
            with self.subTest(kind=kind, verified=verified):
                _, _, actions = fixture()
                actions['PRL'] = [{'kind': kind, 'ex_date': '2026-09-30', 'known_at': '2026-09-20',
                                   'factor': .95, 'volume_factor': 1 / .95,
                                   'source': 'Verified action notice', 'verified': verified}]
                result = row(calculate(actions=actions))
                self.assertEqual(result['returns']['5']['status'], 'unavailable')
                self.assertIsNone(result['returns']['5']['stock_change_pct'])
                self.assertEqual(result['liquidity']['status'], 'unavailable')
                self.assertTrue(any('corporate action' in reason for reason in result['reasons']))

    def test_action_date_and_knowledge_boundaries_are_not_lookahead(self):
        for ex, known in (('2026-08-03', '2026-08-01'), ('2026-10-05', '2026-10-01'),
                          ('2026-09-30', '2026-10-05'), ('2026-09-25', '2026-09-01')):
            with self.subTest(ex=ex, known=known):
                _, _, actions = fixture()
                actions['PRL'] = [{'kind': 'bonus', 'ex_date': ex, 'known_at': known}]
                # Sep 25 is the exact five-session baseline, so its post-action
                # closing price does not cross an action in this five-day window.
                self.assertEqual(row(calculate(actions=actions))['returns']['5']['status'], 'available')

    def test_malformed_actions_fail_closed(self):
        for action in ({'ex_date': 'bad'}, {'ex_date': '2026-09-30'}, {'ex_date': '2026-09-30', 'known_at': 'bad'}):
            with self.subTest(action=action):
                result = row(calculate(actions={'PRL': [action]}))
                self.assertEqual(result['returns']['5']['status'], 'unavailable')

    def test_malformed_sequences_fail_closed_and_pure_helper_requires_now(self):
        histories, benchmark, actions = fixture()
        histories['PRL'] = None
        self.assertEqual(row(calculate(histories))['returns']['5']['status'], 'unavailable')
        self.assertEqual(row(calculate(actions={'PRL': None}))['returns']['5']['status'], 'unavailable')
        with self.assertRaises(ValueError):
            comparisons.calculate(histories, benchmark, actions, now=None)

    def test_peer_mean_excludes_self_and_uses_complete_selected_membership(self):
        result = calculate()
        metric = row(result)['sector_peers']['5']
        self.assertEqual(metric['status'], 'available')
        self.assertEqual(metric['sector_members'], ['PRL', 'ATRL', 'NRL', 'CNERGY'])
        self.assertEqual(metric['peer_members'], ['ATRL', 'NRL', 'CNERGY'])
        peer_returns = [row(result, symbol)['returns']['5']['stock_change_pct'] for symbol in metric['peer_members']]
        self.assertAlmostEqual(metric['peer_mean_change_pct'], sum(peer_returns) / 3)
        self.assertAlmostEqual(metric['stock_minus_peers_pp'], row(result)['returns']['5']['stock_change_pct'] - sum(peer_returns) / 3)
        self.assertEqual(metric['coverage_count'], metric['required_count'])
        self.assertTrue(metric['excludes_self'])
        self.assertIn('not a sector index', metric['basis'])

    def test_missing_peer_withholds_benchmark_instead_of_changing_membership(self):
        histories, _, _ = fixture()
        histories['NRL'].pop(-2)
        metric = row(calculate(histories))['sector_peers']['5']
        self.assertEqual(metric['status'], 'unavailable')
        self.assertEqual(metric['coverage_count'], 2)
        self.assertEqual(metric['required_count'], 3)
        self.assertEqual(metric['missing_members'], ['NRL'])
        self.assertIsNone(metric['peer_mean_change_pct'])
        self.assertIsNone(metric['stock_minus_peers_pp'])

    def test_singleton_and_two_stock_sectors_do_not_create_benchmarks(self):
        result = calculate()
        for symbol, count in (('MEBL', 1), ('SYS', 0), ('EFERT', 0)):
            metric = row(result, symbol)['sector_peers']['5']
            self.assertEqual(metric['status'], 'unavailable')
            self.assertEqual(metric['required_count'], count)
            self.assertIsNone(metric['peer_mean_change_pct'])
        metric = row(calculate(sectors={}), 'PRL')['sector_peers']['5']
        self.assertIn('Configured sector unavailable', metric['reasons'])

    def test_calendar_outside_verified_range_fails_closed(self):
        for now in (datetime(2026, 8, 4, 12, tzinfo=timezone.utc), datetime(2027, 1, 5, 12, tzinfo=timezone.utc)):
            result = calculate(now=now)
            self.assertEqual(row(result)['returns']['20']['status'], 'unavailable')
            self.assertEqual(row(result)['liquidity']['status'], 'unavailable')

    def test_guards_are_enforced_and_missing_guards_fail_closed(self):
        guards = {symbol: {'valid': True, 'checks': []} for symbol in UNIVERSE}
        guards['PRL'] = {'valid': False, 'checks': ['Known unresolved corporate action 2026-09-30']}
        result = row(calculate(guards=guards))
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('Research guard:', '; '.join(result['reasons']))
        self.assertEqual(row(calculate(guards={}))['status'], 'unavailable')

    def test_inputs_are_not_mutated_and_nonfinite_derived_values_never_escape(self):
        histories, benchmark, actions = fixture()
        originals = copy.deepcopy((histories, benchmark, actions))
        calculate(histories, benchmark, actions)
        self.assertEqual((histories, benchmark, actions), originals)
        for bar in histories['PRL']:
            for field in ('open', 'high', 'low', 'close'):
                bar[field] = 1e308
            bar['volume'] = 1e308
        result = calculate(histories, benchmark, actions)
        self.assertEqual(row(result)['liquidity']['status'], 'unavailable')
        self.assertIsNone(row(result)['liquidity']['median20_turnover_pkr'])
        json.dumps(result, allow_nan=False)

    def test_build_uses_existing_read_apis_and_restores_index_source_metadata(self):
        histories, benchmark, actions = fixture()
        connection = MagicMock()
        connection.__enter__.return_value.execute.return_value = [(bar['date'], INDEX_SOURCE) for bar in benchmark]
        raw_index = [{key: value for key, value in bar.items() if key != 'source'} for bar in benchmark]
        with patch('database.get_daily_ohlc', side_effect=lambda symbol, limit: histories[symbol]) as stocks_read, \
                patch('database.get_eod_history', return_value=raw_index) as index_read, \
                patch('database.get_corporate_actions', side_effect=lambda symbol: actions.get(symbol, [])), \
                patch('database.conn', return_value=connection), \
                patch('research_guard.check', return_value={'valid': True, 'checks': []}) as guard_check, \
                patch('database.init_db') as init_db, patch('database.save_eod_history') as save_index, \
                patch('database.save_hl_bar') as save_stock:
            result = comparisons.build(NOW)
        self.assertEqual(stocks_read.call_count, 15)
        self.assertEqual(guard_check.call_count, 15)
        self.assertEqual(index_read.call_args.args[0], 'KSE100')
        self.assertEqual(row(result)['returns']['20']['status'], 'available')
        self.assertEqual(row(result)['returns']['5']['source']['benchmark'], [INDEX_SOURCE])
        init_db.assert_not_called()
        save_index.assert_not_called()
        save_stock.assert_not_called()
        self.assertEqual(connection.__enter__.return_value.execute.call_count, 1)
        self.assertTrue(connection.__enter__.return_value.execute.call_args.args[0].startswith('SELECT'))


if __name__ == '__main__':
    unittest.main()
