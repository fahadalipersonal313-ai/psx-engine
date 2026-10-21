"""Tests for paper_trade.py on synthetic fixtures in a temporary copy (never the real state).

    python3 -m unittest test_paper_trade -v
"""
import csv
import importlib.util
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SYMS = ['S%02d' % i for i in range(25)]


def load_module(root):
    spec = importlib.util.spec_from_file_location('paper_trade_under_test', os.path.join(root, 'paper_trade.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def day(i):
    return '2025-%02d-%02d' % (1 + i // 28, 1 + i % 28)


class PaperTrade(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for f in ('paper_trade.py', 'config.json'):
            shutil.copy(os.path.join(HERE, f), self.root)
        os.makedirs(os.path.join(self.root, 'state'))
        with open(os.path.join(self.root, 'trades.csv'), 'w') as fh:
            fh.write('id,book,sym,list,signal_date,entry_date,entry,stop0,exit_date,exit,reason,R,pct,days,shares,pnl_rs\n')
        self.m = load_module(self.root)
        self.last = day(299)
        bars = {s: [[day(i), 100.0, 101.0, 99.0, 100.0, 1e6] for i in range(300)] for s in SYMS}
        bars['KSE100'] = [[day(i), None, None, None, 1000.0, 0.0] for i in range(300)]
        self.st = dict(bars=bars, uni=dict(shariah=SYMS, non_shariah=[]), breadth={}, positions=[], orders=[], last_scan=None)
        self.log = []

    def tearDown(self):
        shutil.rmtree(self.root)

    def say(self, s):
        self.log.append(s)

    def session(self, overrides=None, kse=1000.0):
        stocks = {s: [100.0, 101.0, 99.0, 100.0, 1e6, 100.0] for s in SYMS}
        stocks.update(overrides or {})
        return dict(kse100=kse, stocks=stocks)

    def position(self, **kw):
        p = dict(id='B-S00-x', book='B', sym='S00', list='Shariah', signal_date=day(298), entry_date=day(299), entry=100.0,
                 stop0=95.0, stop=95.0, atr=2.0, hh=100.0, shares=500, days=3, note='')
        p.update(kw); self.st['positions'].append(p)
        return p

    def trades(self):
        return list(csv.DictReader(open(os.path.join(self.root, 'trades.csv'))))

    # ---- continuity and waiting
    def test_matching_previous_closes_are_continuous(self):
        ok, n, m, up = self.m.continuous(self.st['bars'], self.st['uni'], self.session()['stocks'], self.last)
        self.assertEqual((ok, n, m, up), (True, 25, 25, 0))

    def test_a_busy_ex_dividend_day_is_still_continuous(self):
        over = {s: [97.0, 98.0, 96.0, 97.0, 1e6, 97.0, 'XD'] for s in SYMS[:10]}   # 40% book closures
        ok, n, m, up = self.m.continuous(self.st['bars'], self.st['uni'], self.session(over)['stocks'], self.last)
        self.assertEqual((ok, m, up), (True, 15, 0))

    def test_a_missing_session_is_detected(self):
        moves = [3.0, -2.0, 1.5, -4.0, 2.5]                       # the missing day moved stocks both ways
        stocks = {s: [100.0, 101.0, 99.0, 100.0, 1e6, 100.0 + moves[i % 5]] for i, s in enumerate(SYMS)}
        ok, n, m, up = self.m.continuous(self.st['bars'], self.st['uni'], stocks, self.last)
        self.assertFalse(ok)
        self.assertEqual((m, up), (0, 15))

    def test_a_missing_session_stops_the_run_before_anything_changes(self):
        stocks = {s: [104.0, 105.0, 103.0, 104.0, 1e6, 103.0] for s in SYMS}
        out = self.run_main(dict(sessions={'2026-01-01': dict(kse100=1000.0, stocks=stocks)}))
        self.assertIn('HISTORY GAP', out.stdout)
        self.assertIn('official data through %s' % self.last, out.stdout)

    # ---- orders
    def test_order_fills_at_the_official_open(self):
        self.st['orders'] = [dict(book='B', sym='S01', list='Shariah', signal_date=self.last, signal_close=100.0, stop=94.0, atr=2.0, note='')]
        self.m.finalise('2026-01-01', self.session({'S01': [100.4, 102.0, 99.5, 101.0, 1e6, 100.0]}), self.st, self.say)
        p = self.st['positions'][0]
        self.assertEqual((p['entry'], p['stop0'], p['days']), (100.4, 94.0, 1))
        self.assertEqual(p['shares'], int(2500 // (100.4 - 94.0)))

    def test_order_is_not_chased_above_the_entry_zone(self):
        self.st['orders'] = [dict(book='B', sym='S01', list='Shariah', signal_date=self.last, signal_close=100.0, stop=94.0, atr=2.0, note='')]
        self.m.finalise('2026-01-01', self.session({'S01': [100.7, 102.0, 100.5, 101.0, 1e6, 100.0]}), self.st, self.say)
        self.assertEqual(self.st['positions'], [])
        self.assertTrue(any('NOT chased' in x for x in self.log))

    def test_order_for_a_stock_that_did_not_trade_is_cancelled(self):
        self.st['orders'] = [dict(book='B', sym='S01', list='Shariah', signal_date=self.last, signal_close=100.0, stop=94.0, atr=2.0, note='')]
        sess = self.session(); del sess['stocks']['S01']
        self.m.finalise('2026-01-01', sess, self.st, self.say)
        self.assertEqual((self.st['positions'], self.st['orders']), ([], []))

    # ---- exits and day counting
    def test_gap_below_stop_exits_at_the_open(self):
        self.position()
        self.m.finalise('2026-01-01', self.session({'S00': [94.0, 96.0, 93.0, 95.5, 1e6, 100.0]}), self.st, self.say)
        t = self.trades()[0]
        self.assertEqual((t['exit'], t['reason'], t['R']), ('94.0', 'gap below stop at the open', '-1.2'))

    def test_stop_hit_exits_at_the_stop(self):
        self.position()
        self.m.finalise('2026-01-01', self.session({'S00': [99.0, 99.5, 94.5, 96.0, 1e6, 100.0]}), self.st, self.say)
        self.assertEqual(self.trades()[0]['exit'], '95.0')

    def test_one_session_counts_one_day_and_raises_the_trail(self):
        p = self.position()
        self.m.finalise('2026-01-01', self.session({'S00': [100.0, 110.0, 99.5, 109.0, 1e6, 100.0]}), self.st, self.say)
        self.assertEqual(p['days'], 4)
        self.assertEqual(p['stop'], 104.0)                 # 110 - 3 x 2.0

    def test_time_stop_exits_at_the_close_after_thirty_sessions(self):
        self.position(days=29)
        self.m.finalise('2026-01-01', self.session({'S00': [100.0, 101.0, 99.5, 100.5, 1e6, 100.0]}), self.st, self.say)
        t = self.trades()[0]
        self.assertEqual((t['exit'], t['reason'], t['days']), ('100.5', 'time stop (30 sessions)', '30'))

    def test_a_position_that_did_not_trade_counts_no_session(self):
        p = self.position()
        sess = self.session(); del sess['stocks']['S00']
        self.m.finalise('2026-01-01', sess, self.st, self.say)
        self.assertEqual(p['days'], 3)

    # ---- price adjustment
    def test_bonus_issue_rescales_history_and_the_open_position(self):
        p = self.position()
        self.m.finalise('2026-01-01', self.session({'S00': [50.2, 51.0, 49.8, 50.5, 2e6, 50.0, 'XB']}), self.st, self.say)
        self.assertEqual(self.st['bars']['S00'][-2][4], 50.0)       # stored history halved
        self.assertEqual(self.st['bars']['S00'][-2][5], 2e6)        # volume doubled
        self.assertEqual((p['entry'], p['stop0'], p['atr'], p['shares']), (50.0, 47.5, 1.0, 1000))
        self.assertEqual(p['stop'], 48.0)                 # then trailed by the session's high: 51 - 3 x 1.0
        self.assertEqual(self.trades(), [])
        self.assertTrue(any('PRICE ADJUSTMENT S00' in x for x in self.log))

    def test_ex_dividend_is_reported_and_history_is_not_rescaled(self):
        p = self.position()
        self.m.finalise('2026-01-01', self.session({'S00': [97.2, 98.0, 96.5, 97.5, 1e6, 97.0, 'XD']}), self.st, self.say)
        self.assertEqual(self.st['bars']['S00'][-2][4], 100.0)
        self.assertEqual((p['entry'], p['stop0'], p['shares']), (100.0, 95.0, 500))
        self.assertTrue(any('ex-dividend today' in x and 'S00 Rs 3.00' in x for x in self.log))

    def test_an_unmarked_previous_close_change_is_reported_not_guessed(self):
        self.m.finalise('2026-01-01', self.session({'S01': [80.0, 81.0, 79.0, 80.0, 1e6, 80.0]}), self.st, self.say)
        self.assertEqual(self.st['bars']['S01'][-2][4], 100.0)
        self.assertTrue(any(x.startswith('UNEXPLAINED previous-close change S01') for x in self.log))

    # ---- whole run: waits for the index, is idempotent
    def run_main(self, official, now='2026-01-02T16:45'):
        import json, subprocess, sys
        for k in ('bars', 'breadth', 'positions', 'orders'):
            json.dump(self.st[k], open(os.path.join(self.root, 'state', '%s.json' % k), 'w'))
        json.dump(self.st['uni'], open(os.path.join(self.root, 'state', 'universe.json'), 'w'))
        json.dump(official, open(os.path.join(self.root, 'official.json'), 'w'))
        return subprocess.run([sys.executable, 'paper_trade.py', '--official', 'official.json', '--no-live', '--now', now],
                              cwd=self.root, capture_output=True, text=True)

    def test_a_session_without_the_official_index_close_waits(self):
        out = self.run_main(dict(sessions={'2026-01-01': self.session(kse=None)}))
        self.assertIn('official KSE-100 close is not yet', out.stdout)
        self.assertIn('official data through %s' % self.last, out.stdout)

    def test_running_twice_processes_the_session_once(self):
        import json
        self.position()
        off = dict(sessions={'2026-01-01': self.session()})
        self.run_main(off)
        import subprocess, sys
        out = subprocess.run([sys.executable, 'paper_trade.py', '--official', 'official.json', '--no-live', '--now', '2026-01-02T17:45'],
                             cwd=self.root, capture_output=True, text=True)
        self.assertIn('No new official session since 2026-01-01', out.stdout)
        pos = json.load(open(os.path.join(self.root, 'state', 'positions.json')))
        self.assertEqual(pos[0]['days'], 4)
        status = json.load(open(os.path.join(self.root, 'state', 'status.json')))
        self.assertEqual(status['official_through'], '2026-01-01')
        self.assertEqual(status['last_scan']['date'], '2026-01-01')

    # ---- book C: buy at the official close of a support-reversal day, sell at the next official open
    SETUP = [99.6, 101.5, 99.5, 101.2, 1.5e6, 100.0]     # green, above yesterday, upper half, 1.5x volume, 1.1 ATR off the 20-day low

    def c_buy(self):
        self.m.finalise('2026-01-01', self.session({'S02': list(self.SETUP)}), self.st, self.say)
        return [p for p in self.st['positions'] if p['book'] == 'C']

    def test_book_c_setup_is_detected_on_the_final_bar(self):
        b = self.st['bars']['S02'] + [['2026-01-01'] + self.SETUP[:5]]
        kind, level, atr = self.m.bcsm(b)
        self.assertEqual((kind, level, round(atr, 2)), ('20-day-low support', 99.0, 2.0))
        self.assertIsNone(self.m.bcsm(self.st['bars']['S03']))            # flat bar: no reversal

    def test_book_c_buys_at_the_official_close_even_with_the_gates_closed(self):
        c = self.c_buy()
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]['sym'], c[0]['entry'], c[0]['entry_date'], c[0]['shares']), ('S02', 101.2, '2026-01-01', int(100000 // 101.2)))
        self.assertEqual(self.st['orders'], [])                          # gates closed: no A/B orders
        self.assertTrue(any(x.startswith('FILLED C S02 at 101.20') for x in self.log))
        self.assertEqual(self.st['bcsm']['last_scanned'], '2026-01-01')

    def test_book_c_sells_at_the_next_official_open(self):
        self.c_buy()
        self.m.finalise('2026-01-02', self.session({'S02': [102.0, 102.5, 100.8, 101.0, 1e6, 101.2]}), self.st, self.say)
        t = self.trades()[0]
        self.assertEqual((t['book'], t['exit'], t['reason'], t['days'], t['pnl_rs']), ('C', '102.0', 'next official open', '1', '790'))
        self.assertEqual(self.st['positions'], [])

    def test_book_c_waits_when_the_stock_does_not_trade(self):
        self.c_buy()
        sess = self.session(); del sess['stocks']['S02']
        self.m.finalise('2026-01-02', sess, self.st, self.say)
        self.assertEqual((len(self.st['positions']), self.trades()), (1, []))
        self.m.finalise('2026-01-03', self.session({'S02': [101.5, 102.0, 101.0, 101.4, 1e6, 101.2]}), self.st, self.say)
        t = self.trades()[0]
        self.assertEqual((t['exit'], t['days']), ('101.5', '2'))

    def test_book_c_adds_back_the_dividend_on_an_ex_date_open(self):
        self.c_buy()
        self.m.finalise('2026-01-02', self.session({'S02': [99.7, 100.5, 99.0, 99.5, 1e6, 99.2, 'XD']}), self.st, self.say)
        t = self.trades()[0]
        self.assertEqual(t['exit'], '101.7')                              # open 99.70 + Rs 2.00 dividend
        self.assertIn('dividend', t['reason'])

    def test_book_c_adds_back_an_unmarked_dividend(self):
        self.c_buy()                                                      # PSX's real file carries no XD marker
        self.m.finalise('2026-01-02', self.session({'S02': [99.7, 100.5, 99.0, 99.5, 1e6, 99.2, '']}), self.st, self.say)
        self.assertEqual(self.trades()[0]['exit'], '101.7')

    def test_book_c_adds_back_a_dividend_below_the_history_tolerance(self):
        self.c_buy()                                                      # Rs 0.45 = 0.44%, under ADJUST_TOL
        self.m.finalise('2026-01-02', self.session({'S02': [100.8, 101.0, 100.5, 100.9, 1e6, 100.75, 'XD']}), self.st, self.say)
        self.assertEqual(self.trades()[0]['exit'], '101.25')

    def test_book_c_scales_an_unmarked_bonus_ex_date(self):
        self.c_buy()                                                      # 1-for-1 bonus: previous close halved, no marker
        self.m.finalise('2026-01-02', self.session({'S02': [51.0, 51.5, 50.2, 50.8, 2e6, 50.6, '']}), self.st, self.say)
        t = self.trades()[0]
        self.assertEqual((t['exit'], t['pct']), ('102.0', '0.79'))       # 51.00 x 2
        self.assertIn('bonus/rights', t['reason'])

    def test_book_c_needs_211_bars_like_the_research(self):
        b = self.st['bars']['S02'][-210:]
        b = b[:-1] + [['2026-01-01'] + self.SETUP[:5]]
        self.assertIsNone(self.m.bcsm(b))
        self.assertIsNotNone(self.m.bcsm(self.st['bars']['S02'][-211:-1] + [['2026-01-01'] + self.SETUP[:5]]))

    def test_book_c_stats_are_kept_apart_from_the_turn_confirmation_books(self):
        import json
        s1 = self.session({'S02': list(self.SETUP)})
        s2 = self.session({'S02': [102.0, 102.5, 100.8, 101.0, 1e6, 101.2]})
        out = self.run_main(dict(sessions={'2026-01-01': s1, '2026-01-02': s2}), now='2026-01-03T09:45')
        self.assertIn('FILLED C S02', out.stdout)
        self.assertIn('EXIT C S02 at 102.00', out.stdout)
        status = json.load(open(os.path.join(self.root, 'state', 'status.json')))
        self.assertEqual((status['closed']['n'], status['positions'], status['recent_trades']), (0, [], []))
        c = status['bcsm']['closed']
        self.assertEqual((c['n'], c['avg_net_pct'], c['win_pct']), (1, round(100 * (102.0 / 101.2 - 1), 2) - 0.25, 100))

    def test_book_c_catch_up_scans_the_newest_stored_session_once(self):
        import json, subprocess, sys
        self.st['bars']['S02'][-1] = [self.last] + self.SETUP[:5]
        out = self.run_main(dict(sessions={}))
        self.assertIn('BOOK C catch-up: session %s' % self.last, out.stdout)
        pos = json.load(open(os.path.join(self.root, 'state', 'positions.json')))
        self.assertEqual([(p['book'], p['sym'], p['entry'], p['entry_date']) for p in pos], [('C', 'S02', 101.2, self.last)])
        again = subprocess.run([sys.executable, 'paper_trade.py', '--official', 'official.json', '--no-live', '--now', '2026-01-02T17:45'],
                               cwd=self.root, capture_output=True, text=True)
        self.assertNotIn('catch-up', again.stdout)
        self.assertEqual(len(json.load(open(os.path.join(self.root, 'state', 'positions.json')))), 1)


if __name__ == '__main__':
    unittest.main()
