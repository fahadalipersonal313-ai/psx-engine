#!/usr/bin/env python3
"""Turn-Confirmation Theory - PAPER TRADER (self-contained, standard library only).

Runs in the cloud on a schedule. Modes (picked automatically from Pakistan time, or forced with --mode):
  open      first run of the day (09:30-10:59 PKT): fill pending paper orders at today's OPEN
  intraday  11:00-15:29 PKT: live stop / trail checks on open positions
  close     >= 15:30 PKT or weekend/holiday run: finalise the day's bars, evaluate the two gates,
            scan both legs, place paper orders for the next open, manage positions with the final bar
State lives in ./state (bars, breadth, positions, orders); closed trades in ./trades.csv; reports in ./runs.
Prices come from TradingView's public scanner (PSX). Nothing is ever invented: if data cannot be fetched,
the run stops and says so.
"""
import json, os, sys, csv, math, datetime, urllib.request, argparse

ROOT = os.path.dirname(os.path.abspath(__file__))
S = lambda *p: os.path.join(ROOT, 'state', *p)
CFG = json.load(open(os.path.join(ROOT, 'config.json')))
PKT = datetime.timezone(datetime.timedelta(hours=5))


def jload(p, default=None):
    return json.load(open(p)) if os.path.exists(p) else default


def jsave(p, obj):
    json.dump(obj, open(p, 'w'), separators=(',', ':') if p.endswith('bars.json') else (', ', ': '), indent=None if p.endswith('bars.json') else 1)


# ------------------------------------------------------------------ data
def fetch_quotes(symbols):
    """TradingView scanner: today's open/high/low/close/volume for each PSX symbol (final after the close)."""
    tickers = ['PSX:%s' % s for s in symbols]
    body = json.dumps({'symbols': {'tickers': tickers, 'query': {'types': []}},
                       'columns': ['open', 'high', 'low', 'close', 'volume']}).encode()
    req = urllib.request.Request('https://scanner.tradingview.com/pakistan/scan', data=body, method='POST',
                                 headers={'Content-Type': 'text/plain;charset=UTF-8', 'User-Agent': 'Mozilla/5.0',
                                          'Origin': 'https://www.tradingview.com', 'Referer': 'https://www.tradingview.com/'})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    out = {}
    for row in data.get('data', []):
        sym = row['s'].split(':', 1)[1]; o, h, l, c, v = row['d']
        if c and c > 0:
            out[sym] = dict(o=o or c, h=h or c, l=l or c, c=c, v=v or 0.0)
    return out


# ------------------------------------------------------------------ indicators (plain lists of [date,o,h,l,c,v])
def atr14(b):
    trs = []
    for i in range(1, len(b)):
        trs.append(max(b[i][2] - b[i][3], abs(b[i][2] - b[i - 1][4]), abs(b[i][3] - b[i - 1][4])))
    if len(trs) < 15:
        return None
    a = sum(trs[:14]) / 14
    for t in trs[14:]:
        a = (a * 13 + t) / 14
    return a


def tr_mean(b, n):
    trs = [max(b[i][2] - b[i][3], abs(b[i][2] - b[i - 1][4]), abs(b[i][3] - b[i - 1][4])) for i in range(len(b) - n, len(b))]
    return sum(trs) / n


def turnover(b, n=60):
    seg = b[-n:]
    return sum(x[4] * x[5] for x in seg) / len(seg) / 1e6


def legB(b):
    """52-week-high breakout today. Returns stop or None. b includes today's final bar."""
    if len(b) < 260:
        return None
    c = b[-1][4]; hi250 = max(x[2] for x in b[-251:-1]); sma200 = sum(x[4] for x in b[-200:]) / 200
    v50 = sum(x[5] for x in b[-51:-1]) / 50; a = atr14(b)
    if not a or v50 <= 0:
        return None
    if c > hi250 and c > sma200 and b[-1][5] >= CFG['vol_mult'] * v50 and turnover(b) >= CFG['min_turnover_mn']:
        lo10 = min(x[3] for x in b[-10:])
        return round(max(lo10 - 0.25 * a, c - 3 * a), 2)
    return None


def legA(b):
    """Washout within the last 10 sessions + demand close today. Returns (stop, washout_date) or None."""
    if len(b) < 80 or turnover(b) < CFG['min_turnover_mn']:
        return None
    t = b[-1]; rng = t[2] - t[3]
    if not (rng > 0 and (t[4] - t[3]) >= 0.7 * rng and t[4] > b[-2][4]):
        return None
    n = len(b)
    for k in range(n - 10, n):
        seg = b[:k + 1]
        dd = seg[-1][4] / max(x[2] for x in seg[-60:]) - 1
        path = sum(abs(seg[i][4] - seg[i - 1][4]) for i in range(len(seg) - 20, len(seg)))
        eff = abs(seg[-1][4] - seg[-21][4]) / path if path > 0 else 0
        comp = tr_mean(seg, 5) / max(tr_mean(seg, 50), 1e-9)
        if dd <= -0.30 and eff >= 0.5 and comp >= 1.1 and seg[-1][4] < seg[-21][4]:
            a = atr14(b); lo = min(x[3] for x in b[k:])
            return (round(lo - 0.25 * a, 2), b[k][0]) if a else None
    return None


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--mode', default='auto'); ap.add_argument('--date', default=None)
    args = ap.parse_args()
    now = datetime.datetime.now(PKT); today = args.date or now.strftime('%Y-%m-%d'); hm = now.hour * 100 + now.minute
    mode = args.mode
    if mode == 'auto':
        mode = 'open' if hm < 1100 else ('intraday' if hm < 1530 else 'close')
        if now.weekday() >= 5:
            mode = 'close'
    bars = jload(S('bars.json')); uni = jload(S('universe.json')); breadth = jload(S('breadth.json'), {})
    positions = jload(S('positions.json'), []); orders = jload(S('orders.json'), []); log = []
    say = lambda s: (log.append(s), print(s))
    say('# Paper-trade run  %s  %s PKT  mode=%s' % (today, now.strftime('%H:%M'), mode))
    symbols = uni['shariah'] + uni['non_shariah'] + ['KSE100']
    try:
        q = fetch_quotes(symbols)
    except Exception as e:
        say('DATA FETCH FAILED: %s - no prices, no actions taken.' % e); write_report(today, now, mode, log); sys.exit(2)
    say('quotes received for %d of %d symbols; KSE100=%s' % (len(q), len(symbols), q.get('KSE100', {}).get('c')))
    last_date = bars['PRL'][-1][0]
    same = sum(1 for s in q if s in bars and bars[s][-1][1:5] == [q[s]['o'], q[s]['h'], q[s]['l'], q[s]['c']])
    if today > last_date and same >= 0.8 * len(q):
        say('Market CLOSED today (holiday/weekend): %d of %d quotes are identical to the last stored session %s. No actions.' % (same, len(q), last_date))
        write_report(today, now, mode, log); return
    if today <= last_date and mode == 'close':
        say('Bars already final for %s - nothing to append.' % last_date)
    risk_rs = CFG['capital'] * CFG['risk_per_trade_pct'] / 100

    # ---- OPEN / INTRADAY: fill pending orders at today's official OPEN (once the stock has actually traded today)
    if mode in ('open', 'intraday') and orders:
        keep = []
        for od in orders:
            qq = q.get(od['sym'])
            stale = qq is not None and od['sym'] in bars and bars[od['sym']][-1][1:5] == [qq['o'], qq['h'], qq['l'], qq['c']]
            if not qq or qq['o'] <= 0 or stale:
                say('order %s: has not traded yet today - kept for the next run' % od['sym']); keep.append(od); continue
            if qq['o'] > od['signal_close'] + 0.3 * od['atr']:
                say('order %s: open %.2f is above the entry zone (%.2f) - NOT chased, cancelled' % (od['sym'], qq['o'], od['signal_close'] + 0.3 * od['atr'])); continue
            stop = min(od['stop'], qq['o'] - 0.5 * od['atr']); risk = qq['o'] - stop
            if risk <= 0:
                say('order %s: open below stop - cancelled' % od['sym']); continue
            shares = int(risk_rs // risk)
            pid = '%s-%s-%s' % (od['book'], od['sym'], today)
            positions.append(dict(id=pid, book=od['book'], sym=od['sym'], list=od['list'], signal_date=od['signal_date'], entry_date=today,
                                  entry=round(qq['o'], 2), stop0=round(stop, 2), stop=round(stop, 2), atr=od['atr'], hh=qq['h'], shares=shares, days=0, note=od.get('note', '')))
            say('FILLED %s %s at %.2f (official open), stop %.2f, risk %.2f%%, %d shares' % (od['book'], od['sym'], qq['o'], stop, 100 * risk / qq['o'], shares))
        orders = keep

    # ---- manage open positions with today's prices (partial during the day, final after the close)
    closed = []
    for p in positions:
        qq = q.get(p['sym'])
        if not qq:
            continue
        exit_px = None; reason = ''
        if qq['o'] <= p['stop'] and p.get('last_check') != today:
            exit_px, reason = qq['o'], 'gap below stop at the open'
        elif qq['l'] <= p['stop']:
            exit_px, reason = p['stop'], 'stop hit'
        if exit_px is None and mode == 'close':
            p['days'] += 1
            if p['days'] >= CFG['time_stop']:
                exit_px, reason = qq['c'], 'time stop (%d sessions)' % CFG['time_stop']
        p['hh'] = max(p['hh'], qq['h']); p['last_check'] = today
        if exit_px is None:
            new_stop = round(max(p['stop'], p['hh'] - CFG['trail_atr'] * p['atr']), 2)
            if new_stop > p['stop']:
                say('trail %s: stop %.2f -> %.2f (high %.2f)' % (p['sym'], p['stop'], new_stop, p['hh'])); p['stop'] = new_stop
            continue
        R = (exit_px - p['entry']) / (p['entry'] - p['stop0']); pnl = (exit_px - p['entry']) * p['shares']
        with open(os.path.join(ROOT, 'trades.csv'), 'a', newline='') as f:
            csv.writer(f).writerow([p['id'], p['book'], p['sym'], p['list'], p['signal_date'], p['entry_date'], p['entry'], p['stop0'], today, round(exit_px, 2), reason,
                                    round(R, 2), round(100 * (exit_px / p['entry'] - 1), 2), p['days'], p['shares'], round(pnl)])
        say('EXIT %s %s at %.2f (%s): %+.2fR, %+.1f%%, Rs %+.0f' % (p['book'], p['sym'], exit_px, reason, R, 100 * (exit_px / p['entry'] - 1), pnl))
        closed.append(p['id'])
    positions = [p for p in positions if p['id'] not in closed]

    # ---- CLOSE: finalise bars, gates, scan, orders
    if mode == 'close' and today > last_date:
        for s in symbols:
            if s in q and s in bars:
                qq = q[s]; bars[s].append([today, qq['o'], qq['h'], qq['l'], qq['c'], qq['v']]); bars[s] = bars[s][-330:]
        say('appended final bars for %s' % today)
        ib = bars['KSE100']; lo20 = min(x[4] for x in ib[-20:]); bounce = ib[-1][4] / lo20 - 1
        gate1 = bounce >= CFG['gate_bounce']
        above = tot = 0
        for s in uni['shariah']:
            b = bars.get(s)
            if b and len(b) >= 20 and b[-1][0] == today:
                tot += 1; above += b[-1][4] > sum(x[4] for x in b[-20:]) / 20
        breadth[today] = round(100 * above / tot, 2) if tot else None
        keys = sorted(breadth); prev5 = breadth[keys[-6]] if len(keys) >= 6 else None
        gate2 = (prev5 is not None and breadth[today] is not None and breadth[today] > prev5)
        say('GATE 1 price: KSE-100 %.0f vs 20-day low %.0f -> bounce %+.1f%% -> %s (needs >= %.0f)' % (ib[-1][4], lo20, 100 * bounce, 'OPEN' if gate1 else 'closed', lo20 * (1 + CFG['gate_bounce'])))
        say('GATE 2 breadth: %.0f%% above 20-day avg vs %s five sessions ago -> %s' % (breadth[today] or 0, prev5, 'OPEN' if gate2 else 'closed'))
        held = {p['sym'] for p in positions}
        sigs = []
        for s in uni['shariah'] + uni['non_shariah']:
            b = bars.get(s)
            if not b or b[-1][0] != today or s in held:
                continue
            lst = 'Shariah' if s in uni['shariah'] else 'non-Shariah'; a = atr14(b)
            stp = legB(b)
            if stp:
                sigs.append(dict(book='B', sym=s, list=lst, signal_date=today, signal_close=b[-1][4], stop=stp, atr=round(a, 4), note='52-week-high breakout'))
            la = legA(b)
            if la:
                sigs.append(dict(book='A', sym=s, list=lst, signal_date=today, signal_close=b[-1][4], stop=la[0], atr=round(a, 4), note='washout %s + demand close (research book)' % la[1]))
        for sg in sigs:
            say('SIGNAL %s %s (%s) close %.2f stop %.2f risk %.1f%% - %s' % (sg['book'], sg['sym'], sg['list'], sg['signal_close'], sg['stop'], 100 * (1 - sg['stop'] / sg['signal_close']), sg['note']))
        for od in orders:
            say('order %s never traded today - cancelled' % od['sym'])
        if gate1 and gate2:
            orders = sigs
            say('BOTH GATES OPEN -> %d paper orders placed for the next open.' % len(orders))
        else:
            orders = []
            say('Gate(s) closed -> %d signal(s) logged, NO orders.' % len(sigs))
        jsave(S('bars.json'), bars); jsave(S('breadth.json'), breadth)
    jsave(S('positions.json'), positions); jsave(S('orders.json'), orders)
    say('open positions: %d | pending orders: %d' % (len(positions), len(orders)))
    for p in positions:
        qq = q.get(p['sym'], {}); last = qq.get('c', p['entry'])
        say('  %s %s entry %.2f stop %.2f last %.2f (%+.1f%%) day %d' % (p['book'], p['sym'], p['entry'], p['stop'], last, 100 * (last / p['entry'] - 1), p['days']))
    rows = list(csv.DictReader(open(os.path.join(ROOT, 'trades.csv'))))
    if rows:
        Rs = [float(r['R']) for r in rows]; gp = sum(x for x in Rs if x > 0); gl = -sum(x for x in Rs if x < 0)
        say('closed trades so far: %d | total %+.2fR | PF %.2f | win %.0f%%' % (len(Rs), sum(Rs), gp / gl if gl else 99, 100 * sum(x > 0 for x in Rs) / len(Rs)))
    write_report(today, now, mode, log)


def write_report(today, now, mode, log):
    os.makedirs(os.path.join(ROOT, 'runs'), exist_ok=True)
    open(os.path.join(ROOT, 'runs', '%s_%s_%s.md' % (today, now.strftime('%H%M'), mode)), 'w').write('\n'.join(log) + '\n')


if __name__ == '__main__':
    main()
