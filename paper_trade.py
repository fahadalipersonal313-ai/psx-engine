#!/usr/bin/env python3
"""Turn-Confirmation Theory - PAPER TRADER (self-contained, standard library only).

Every paper decision is made from PSX's OFFICIAL end-of-day bars, one completed session at a time.

  Official source (the only one that changes state): market_eod.json on the psx-engine
  `runtime-state` branch. The engine writes it from PSX's mkt_summary download (all stocks:
  open, high, low, official close, volume, previous close) and PSX's closing-rates PDF (KSE-100).

  Each new session is FINALISED exactly once, oldest first:
    1. price-adjustment guard (bonus / split / rights: stored close vs PSX's previous close)
    2. fill pending orders at the session's official OPEN (not chased above the entry zone)
    3. manage positions with the official bar: gap below stop at the open, stop hit, time stop
       (one session counted per finalised session), then raise the 3-ATR chandelier trail
    4. append the bars, evaluate the two gates, scan both legs, place orders for the next open
  A session that is already stored is never processed again, so re-running is harmless and a
  missed run is caught up by the next one (up to the sessions the file keeps).

  Book C - buy-close-sell-open (BCSM, research book, runs in EVERY market - no gates): a Shariah stock at support
  (near its 20-day low, or at a rising 50-day EMA) that closes green, above yesterday, in the upper half of its range,
  on at least its 20-day average volume, is bought at that session's official CLOSE and sold at the next session's
  official OPEN. Fixed notional per trade; results are reported after the round-trip cost and kept apart from the
  Turn-Confirmation books (A, B), whose rules, stats and dashboard fields are unchanged.

  Live view (informational only, never changes state): TradingView's public scanner, when reachable.

State lives in ./state, closed trades in ./trades.csv, run reports in ./runs, and a small summary for
the dashboard in ./state/status.json. Nothing is ever invented: if the official file is unavailable,
or a session's KSE-100 close is not yet published, the run says so and waits.
"""
import argparse
import csv
import datetime
import json
import os
import subprocess
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
S = lambda *p: os.path.join(ROOT, 'state', *p)
CFG = json.load(open(os.path.join(ROOT, 'config.json')))
PKT = datetime.timezone(datetime.timedelta(hours=5))
OFFICIAL_URL = 'https://raw.githubusercontent.com/fahadalipersonal313-ai/psx-engine/runtime-state/market_eod.json'
ADJUST_TOL = 0.005      # stored close vs PSX previous close; beyond this PSX adjusted the previous close
CAPITAL_FLAGS = ('XB', 'XR')   # PSX's ex-bonus / ex-rights markers: history is rescaled (as TradingView's research data is)
KEEP_BARS = 330


def jload(p, default=None):
    return json.load(open(p)) if os.path.exists(p) else default


def jsave(p, obj):
    compact = p.endswith('bars.json')
    json.dump(obj, open(p, 'w'), separators=(',', ':') if compact else (',', ': '), indent=None if compact else 1)


# ------------------------------------------------------------------ data
def fetch_official(local=None):
    """PSX's official sessions as published by the engine. Raises with every attempt's error."""
    if local:
        return json.load(open(local))
    errors = []
    try:
        req = urllib.request.Request(OFFICIAL_URL + '?t=%d' % int(time.time()), headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        errors.append('raw.githubusercontent.com: %s' % e)
    try:
        # Partial fetch: commit and trees only; git then downloads just this one blob (not the engine database).
        subprocess.run(['git', 'fetch', '--depth', '1', '--filter=blob:none', 'origin', 'runtime-state'], cwd=ROOT, check=True,
                       capture_output=True, timeout=300)
        out = subprocess.run(['git', 'show', 'FETCH_HEAD:market_eod.json'], cwd=ROOT, check=True,
                             capture_output=True, timeout=60)
        return json.loads(out.stdout.decode())
    except Exception as e:
        errors.append('git fetch runtime-state: %s' % (getattr(e, 'stderr', b'') or e))
    raise RuntimeError('; '.join(str(x) for x in errors))


def fetch_live(symbols):
    """TradingView scanner: delayed live open/high/low/close/volume. Informational only."""
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
            out[sym] = dict(o=o, h=h, l=l, c=c, v=v)
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


def ema(vals, n):
    k = 2 / (n + 1); e = vals[0]; out = []
    for v in vals:
        e = v * k + e * (1 - k); out.append(e)
    return out


def bcsm(b):
    """Book C setup on today's final bar (same definitions as the research test, scripts/intraday_test.build).
    Returns (kind, level, atr) or None. b includes today's final bar."""
    C = CFG['bcsm']
    if len(b) < 211 or turnover(b) < C['min_turnover_mn']:      # build() starts at index 210
        return None
    x, p = b[-1], b[-2]; a = atr14(b)
    if not a or not x[1] or x[2] <= x[3]:
        return None
    v20 = sum(y[5] for y in b[-21:-1]) / 20
    reversal = x[4] > x[1] and x[4] > p[4] and (x[4] - x[3]) >= 0.5 * (x[2] - x[3])
    if not (reversal and v20 > 0 and x[5] >= v20):
        return None
    lo20 = min(y[3] for y in b[-20:])
    if (x[4] - lo20) / a <= 1.5 and x[3] > lo20 and p[3] > lo20 - 1e-9 and min(y[3] for y in b[-20:-2]) <= lo20 + 1e-9:
        return '20-day-low support', lo20, a
    e = ema([y[4] for y in b], 50); sma200 = sum(y[4] for y in b[-200:]) / 200
    if x[4] > sma200 and e[-1] > e[-11] and min(y[3] for y in b[-3:]) <= e[-1] * 1.01 and x[4] >= e[-1]:
        return 'rising 50-day EMA', e[-1], a
    return None


def bcsm_scan(bars, uni, day):
    sigs = []
    for lst in CFG['bcsm']['lists']:
        for s in uni[lst]:
            b = bars.get(s)
            if not b or b[-1][0] != day:
                continue
            r = bcsm(b)
            if r:
                c = b[-1][4]
                sigs.append(dict(book='C', sym=s, list='Shariah' if lst == 'shariah' else 'non-Shariah', signal_date=day, signal_close=c,
                                 stop=round(c - r[2], 2), atr=round(r[2], 4), note='%s %.2f' % (r[0], r[1])))
    return sigs


def bcsm_buy(sigs, st, day, say):
    """Book C buys at the signal session's official close (a closing-session order). stop0 = close - 1 ATR is a
    REFERENCE for R only: no stop is used, the position is always sold at the next official open."""
    for sg in sigs:
        c = sg['signal_close']; shares = int(CFG['bcsm']['notional_rs'] // c)
        if shares <= 0 or any(p['book'] == 'C' and p['sym'] == sg['sym'] for p in st['positions']):
            continue
        st['positions'].append(dict(id='C-%s-%s' % (sg['sym'], day), book='C', sym=sg['sym'], list=sg['list'], signal_date=day,
                                    entry_date=day, entry=round(c, 2), stop0=sg['stop'], stop=sg['stop'], atr=sg['atr'], hh=c,
                                    shares=shares, days=0, note='buy-close-sell-open: ' + sg['note']))
        say('FILLED C %s at %.2f (official close %s, %s) - %d shares, Rs %.0f; sells at the next official open'
            % (sg['sym'], c, day, sg['note'], shares, shares * c))
    st.setdefault('bcsm', {})['last_scanned'] = day


# ------------------------------------------------------------------ gates and scan (pure functions of stored history)
def gates(bars, breadth, day):
    ib = [x for x in bars['KSE100'] if x[0] <= day]
    lo20 = min(x[4] for x in ib[-20:]); close = ib[-1][4]
    keys = sorted(k for k in breadth if k <= day)
    now = breadth.get(day); prev_day = keys[-6] if len(keys) >= 6 else None
    prev = breadth[prev_day] if prev_day else None
    return dict(date=day, kse100=round(close, 2), low20=round(lo20, 2), gate1_level=round(lo20 * (1 + CFG['gate_bounce']), 2),
                bounce_pct=round(100 * (close / lo20 - 1), 2), gate1_open=close / lo20 - 1 >= CFG['gate_bounce'],
                breadth=now, breadth_prev=prev, breadth_prev_date=prev_day,
                gate2_open=(prev is not None and now is not None and now > prev))


def held_ab(st):
    """Stocks held by the Turn-Confirmation books (A, B). Book C positions never block their scan."""
    return {p['sym'] for p in st['positions'] if p['book'] != 'C'}


def scan(bars, uni, day, held):
    sigs = []
    for s in uni['shariah'] + uni['non_shariah']:
        b = bars.get(s)
        if not b or b[-1][0] != day or s in held:
            continue
        lst = 'Shariah' if s in uni['shariah'] else 'non-Shariah'; a = atr14(b)
        stp = legB(b)
        if stp:
            sigs.append(dict(book='B', sym=s, list=lst, signal_date=day, signal_close=b[-1][4], stop=stp, atr=round(a, 4), note='52-week-high breakout'))
        la = legA(b)
        if la:
            sigs.append(dict(book='A', sym=s, list=lst, signal_date=day, signal_close=b[-1][4], stop=la[0], atr=round(a, 4), note='washout %s + demand close (research book)' % la[1]))
    return sigs


# ------------------------------------------------------------------ one official session
def continuous(bars, uni, stocks, last):
    """Does this session directly follow our last stored session? PSX's previous close (LDCP) for each stock that
    traded on our last day should equal our stored close. Ex-dates only ever LOWER it (dividend, bonus, rights), and
    a busy book-closure day can lower it for many stocks; a missing session instead moves it both ways for most stocks.
    So the test is: at least half match, and almost none (<= 5%) are HIGHER than our close.
    Returns (ok, compared, matched, higher)."""
    n = m = up = 0
    for s in uni['shariah'] + uni['non_shariah']:
        row, b = stocks.get(s), bars.get(s)
        if row and b and len(row) > 5 and row[5] and b[-1][0] == last:
            r = b[-1][4] / row[5] - 1
            n += 1; m += abs(r) <= ADJUST_TOL; up += r < -ADJUST_TOL
    return (n >= 20 and m >= 0.5 * n and up <= 0.05 * n), n, m, up


def finalise(day, sess, st, say):
    bars, uni, breadth = st['bars'], st['uni'], st['breadth']
    stocks = sess['stocks']; universe = uni['shariah'] + uni['non_shariah']
    risk_rs = CFG['capital'] * CFG['risk_per_trade_pct'] / 100
    say('## Session %s (PSX official file: %d stocks, KSE-100 %.2f)' % (day, len(stocks), sess['kse100']))

    # 1. ex-dates: PSX lowers its previous close by the dividend (XD) or by the bonus/rights ratio (XB/XR).
    #    Only XB/XR rescale our history, matching the research data (TradingView adjusts those, not dividends).
    exdiv = []
    for s in universe:
        row, b = stocks.get(s), bars.get(s)
        if not row or not b or len(row) < 6 or not row[5]:
            continue
        prev, ldcp = b[-1][4], row[5]; flags = row[6] if len(row) > 6 and row[6] else ''
        if not prev or abs(prev / ldcp - 1) <= ADJUST_TOL:
            continue
        if not any(x in flags for x in CAPITAL_FLAGS):
            if 'XD' in flags:
                exdiv.append('%s Rs %.2f' % (s, prev - ldcp))
            else:
                say('UNEXPLAINED previous-close change %s: stored %.2f vs PSX %.2f with no ex-date marker (%r) - history left '
                    'unchanged; check PSX announcements' % (s, prev, ldcp, flags))
            continue
        f = ldcp / prev
        bars[s] = [[x[0], x[1] * f, x[2] * f, x[3] * f, x[4] * f, x[5] / f] for x in b]
        for p in st['positions']:
            if p['sym'] == s:
                for k in ('entry', 'stop0', 'stop', 'hh', 'atr'):
                    p[k] = round(p[k] * f, 4)
                p['shares'] = int(round(p['shares'] / f)); p['note'] = (p.get('note', '') + ' | adjusted x%.4f on %s' % (f, day)).strip(' |')
        for od in st['orders']:
            if od['sym'] == s:
                for k in ('signal_close', 'stop', 'atr'):
                    od[k] = round(od[k] * f, 4)
        say('PRICE ADJUSTMENT %s (%s): stored close %.2f vs PSX previous close %.2f -> history, positions and orders scaled x%.4f'
            % (s, flags, prev, ldcp, f))
    if exdiv:
        say('ex-dividend today, history unchanged (as in the research data): ' + ', '.join(exdiv))

    # 2. fill orders placed at the previous session's close, at this session's official open
    for od in st['orders']:
        row = stocks.get(od['sym'])
        if not row:
            say('order %s: did not trade on %s - cancelled' % (od['sym'], day)); continue
        o = row[0]; zone = od['signal_close'] + 0.3 * od['atr']
        if o > zone:
            say('order %s: open %.2f is above the entry zone (%.2f) - NOT chased, cancelled' % (od['sym'], o, zone)); continue
        stop = min(od['stop'], o - 0.5 * od['atr']); risk = o - stop
        if risk <= 0:
            say('order %s: open below stop - cancelled' % od['sym']); continue
        shares = int(risk_rs // risk)
        st['positions'].append(dict(id='%s-%s-%s' % (od['book'], od['sym'], day), book=od['book'], sym=od['sym'], list=od['list'],
                                    signal_date=od['signal_date'], entry_date=day, entry=round(o, 2), stop0=round(stop, 2),
                                    stop=round(stop, 2), atr=od['atr'], hh=o, shares=shares, days=0, note=od.get('note', '')))
        say('FILLED %s %s at %.2f (official open %s), stop %.2f, risk %.2f%%, %d shares'
            % (od['book'], od['sym'], o, day, stop, 100 * risk / o, shares))
    st['orders'] = []

    # 3. manage positions with the official bar
    keep = []
    for p in st['positions']:
        row = stocks.get(p['sym'])
        if p['book'] == 'C':
            # Book C: always sold at the next official open (no stop, no trail). The stock was bought cum, so if PSX
            # lowered its previous close for an ex-date, that reduction is added back. PSX's file carries no reliable
            # XD/XB/XR marker, so the reduction itself is the evidence: up to 10% it is treated as a cash dividend
            # (rupees added back), above 10% as a bonus/rights ratio (open scaled up).
            p['days'] += 1
            if not row:
                say('C %s did not trade on %s - still held, sells at its next official open' % (p['sym'], day))
                keep.append(p); continue
            exit_px, reason = row[0], 'next official open'
            prev = bars[p['sym']][-1][4] if bars.get(p['sym']) else p['entry']
            ldcp = row[5] if len(row) > 5 and row[5] else None
            if ldcp and prev - ldcp > 0.005:
                if ldcp >= 0.9 * prev:
                    exit_px = row[0] + (prev - ldcp)
                    reason += ' + Rs %.2f ex-date reduction added back (PSX previous close %.2f vs our close %.2f; dividend, bought cum)' % (prev - ldcp, ldcp, prev)
                else:
                    exit_px = row[0] * prev / ldcp
                    reason += ' x %.4f ex-date ratio (PSX previous close %.2f vs our close %.2f; bonus/rights, bought cum)' % (prev / ldcp, ldcp, prev)
            elif ldcp and ldcp - prev > 0.005:
                say('C %s: PSX previous close %.2f is ABOVE our stored close %.2f - not adjusted; check the data' % (p['sym'], ldcp, prev))
        elif not row:
            keep.append(p); continue                      # did not trade: no bar, no session counted
        else:
            o, h, l, c = row[:4]; exit_px = None; reason = ''
            if p['entry_date'] != day and o <= p['stop']:
                exit_px, reason = o, 'gap below stop at the open'
            elif l <= p['stop']:
                exit_px, reason = p['stop'], 'stop hit'
            else:
                p['days'] += 1
                if p['days'] >= CFG['time_stop']:
                    exit_px, reason = c, 'time stop (%d sessions)' % CFG['time_stop']
        if exit_px is None:
            p['hh'] = max(p['hh'], h)
            new_stop = round(max(p['stop'], p['hh'] - CFG['trail_atr'] * p['atr']), 2)
            if new_stop > p['stop']:
                say('trail %s: stop %.2f -> %.2f (high %.2f)' % (p['sym'], p['stop'], new_stop, p['hh'])); p['stop'] = new_stop
            p['last_close'] = c; keep.append(p); continue
        R = (exit_px - p['entry']) / (p['entry'] - p['stop0']); pnl = (exit_px - p['entry']) * p['shares']
        with open(os.path.join(ROOT, 'trades.csv'), 'a', newline='') as f:
            csv.writer(f).writerow([p['id'], p['book'], p['sym'], p['list'], p['signal_date'], p['entry_date'], p['entry'], p['stop0'], day,
                                    round(exit_px, 2), reason, round(R, 2), round(100 * (exit_px / p['entry'] - 1), 2), p['days'], p['shares'], round(pnl)])
        say('EXIT %s %s at %.2f (%s): %+.2fR, %+.1f%%, Rs %+.0f' % (p['book'], p['sym'], exit_px, reason, R, 100 * (exit_px / p['entry'] - 1), pnl))
    st['positions'] = keep

    # 4. append bars, gates, scan, orders for the next open
    for s in universe:
        if s in stocks and s in bars:
            bars[s].append([day] + list(stocks[s][:5])); bars[s] = bars[s][-KEEP_BARS:]
    bars['KSE100'].append([day, None, None, None, sess['kse100'], 0.0]); bars['KSE100'] = bars['KSE100'][-KEEP_BARS:]
    above = tot = 0
    for s in uni['shariah']:
        b = bars.get(s)
        if b and len(b) >= 20 and b[-1][0] == day:
            tot += 1; above += b[-1][4] > sum(x[4] for x in b[-20:]) / 20
    breadth[day] = round(100 * above / tot, 2) if tot else None
    g = gates(bars, breadth, day)
    say('GATE 1 price: KSE-100 %.0f vs 20-day low %.0f -> bounce %+.1f%% -> %s (needs >= %.0f)'
        % (g['kse100'], g['low20'], g['bounce_pct'], 'OPEN' if g['gate1_open'] else 'closed', g['gate1_level']))
    say('GATE 2 breadth: %.0f%% above 20-day avg vs %s on %s -> %s'
        % (g['breadth'] or 0, g['breadth_prev'], g['breadth_prev_date'], 'OPEN' if g['gate2_open'] else 'closed'))
    sigs = scan(bars, uni, day, held_ab(st))
    for sg in sigs:
        say('SIGNAL %s %s (%s) close %.2f stop %.2f risk %.1f%% - %s' % (sg['book'], sg['sym'], sg['list'], sg['signal_close'], sg['stop'],
                                                                      100 * (1 - sg['stop'] / sg['signal_close']), sg['note']))
    if g['gate1_open'] and g['gate2_open']:
        st['orders'] = sigs
        say('BOTH GATES OPEN -> %d paper orders placed for the next open.' % len(sigs))
    else:
        say('Gate(s) closed -> %d signal(s) logged, NO orders.' % len(sigs))
    csigs = bcsm_scan(bars, uni, day)
    say('BOOK C (buy-close-sell-open, no gates): %d setup(s) at the %s close' % (len(csigs), day))
    bcsm_buy(csigs, st, day, say)
    st['last_scan'] = dict(date=day, gates=g, signals=sigs, orders_placed=len(st['orders']), bcsm=csigs)


# ------------------------------------------------------------------ main
def live_summary(live):
    out = {k: v for k, v in live.items() if k != 'quotes'}
    if live.get('ok'):
        out['kse100'] = live['quotes'].get('KSE100', {}).get('c')
    return out


def closed_stats():
    """(Turn-Confirmation stats, their rows, book C stats, book C rows). The A/B figures are exactly as before book C
    existed; book C is judged on % after the round-trip cost, because an overnight move is small next to the cost."""
    allrows = list(csv.DictReader(open(os.path.join(ROOT, 'trades.csv'))))
    rows = [r for r in allrows if r['book'] != 'C']; crows = [r for r in allrows if r['book'] == 'C']
    if rows:
        Rs = [float(r['R']) for r in rows]; gp = sum(x for x in Rs if x > 0); gl = -sum(x for x in Rs if x < 0)
        stats = dict(n=len(Rs), total_R=round(sum(Rs), 2), pf=round(gp / gl, 2) if gl else None,
                     win_pct=round(100 * sum(x > 0 for x in Rs) / len(Rs)), pnl_rs=round(sum(float(r['pnl_rs']) for r in rows)))
    else:
        stats = dict(n=0)
    cost = CFG['bcsm']['cost_pct']
    if crows:
        net = [float(r['pct']) - cost for r in crows]; gp = sum(x for x in net if x > 0); gl = -sum(x for x in net if x < 0)
        cstats = dict(n=len(net), cost_pct=cost, avg_net_pct=round(sum(net) / len(net), 3), pf_net=round(gp / gl, 2) if gl else None,
                      win_pct=round(100 * sum(x > 0 for x in net) / len(net)),
                      pnl_rs_net=round(sum(float(r['pnl_rs']) - cost / 100 * float(r['entry']) * float(r['shares']) for r in crows)))
    else:
        cstats = dict(n=0, cost_pct=cost)
    return stats, rows, cstats, crows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--official', help='read the official sessions from this local file (testing)')
    ap.add_argument('--no-live', action='store_true', help='skip the informational live view')
    ap.add_argument('--now', help='ISO time, Pakistan time (testing)')
    args = ap.parse_args()
    now = datetime.datetime.fromisoformat(args.now).replace(tzinfo=PKT) if args.now else datetime.datetime.now(PKT)
    st = dict(bars=jload(S('bars.json')), uni=jload(S('universe.json')), breadth=jload(S('breadth.json'), {}),
              positions=jload(S('positions.json'), []), orders=jload(S('orders.json'), []), last_scan=jload(S('last_scan.json')),
              bcsm=jload(S('bcsm.json'), dict(last_scanned=None)))
    log = []
    say = lambda s: (log.append(s), print(s))
    say('# Paper-trade run  %s PKT' % now.strftime('%Y-%m-%d %H:%M'))
    last = st['bars']['KSE100'][-1][0]
    official_note = ''
    if (st['bcsm'].get('last_scanned') or '') < last:
        # The newest stored session was finalised before book C existed: scan it now from its stored official bars,
        # exactly as finalise() would have, so it is sold at the next session's official open.
        say('BOOK C catch-up: session %s was finalised before book C ran - scanned now from its stored official bars.' % last)
        csigs = bcsm_scan(st['bars'], st['uni'], last)
        say('BOOK C (buy-close-sell-open, no gates): %d setup(s) at the %s close' % (len(csigs), last))
        bcsm_buy(csigs, st, last, say)
        if st['last_scan'] and st['last_scan'].get('date') == last:
            st['last_scan']['bcsm'] = csigs
    try:
        off = fetch_official(args.official)
        sessions = off.get('sessions') or {}
        new = sorted(d for d in sessions if d > last)
        done = []
        for d in new:
            if sessions[d].get('kse100') is None:
                official_note = 'PSX stock file for %s is in, but the official KSE-100 close is not yet - waiting.' % d
                say(official_note); break
            ok, n, m, up = continuous(st['bars'], st['uni'], sessions[d]['stocks'], st['bars']['KSE100'][-1][0])
            if not ok:
                official_note = ('HISTORY GAP: PSX\'s previous close in the %s file matches our stored close for %d of %d stocks and is '
                                 'higher for %d; a session is probably missing. Nothing processed - this needs a deliberate backfill.'
                                 % (d, m, n, up))
                say(official_note); break
            finalise(d, sessions[d], st, say); done.append(d)
        last = st['bars']['KSE100'][-1][0]
        if not done and not official_note:
            official_note = 'No new official session since %s (newest in the file: %s).' % (last, max(sessions) if sessions else 'none')
            say(official_note)
        elif done:
            official_note = 'Finalised %s from PSX official data.' % ', '.join(done)
    except Exception as e:
        official_note = 'OFFICIAL DATA UNAVAILABLE: %s - nothing processed, nothing invented.' % e
        say(official_note)
    if st['last_scan'] is None or st['last_scan']['date'] != last:
        # Same pure computation as finalise(); recorded so the dashboard can show the latest stored session.
        g = gates(st['bars'], st['breadth'], last)
        st['last_scan'] = dict(date=last, gates=g, signals=scan(st['bars'], st['uni'], last, held_ab(st)),
                               orders_placed=len(st['orders']), recomputed=True, bcsm=bcsm_scan(st['bars'], st['uni'], last))

    # ---- informational live view (never changes state)
    live = dict(ok=False)
    if not args.no_live:
        want = sorted({p['sym'] for p in st['positions']} | {o['sym'] for o in st['orders']} | {'KSE100'})
        try:
            q = fetch_live(want)
            live = dict(ok=True, at=now.isoformat(timespec='minutes'), quotes=q)
            g = st['last_scan']['gates']
            if 'KSE100' in q:
                say('LIVE (TradingView, delayed, not official; no action taken): KSE-100 %.0f; Gate 1 needs an official close >= %.0f'
                    % (q['KSE100']['c'], g['gate1_level']))
            for p in st['positions']:
                qq = q.get(p['sym'])
                if not qq:
                    continue
                if p['book'] == 'C':
                    if qq.get('o'):
                        say('  live C %s: open %.2f (%+.2f%% vs entry %.2f, before costs) - the paper exit is the official open when '
                            'PSX publishes it' % (p['sym'], qq['o'], 100 * (qq['o'] / p['entry'] - 1), p['entry']))
                else:
                    say('  live %s %.2f vs stop %.2f (%+.1f%% from entry %.2f)' % (p['sym'], qq['c'], p['stop'], 100 * (qq['c'] / p['entry'] - 1), p['entry']))
            for od in st['orders']:
                qq = q.get(od['sym'])
                if qq and qq.get('o'):
                    zone = od['signal_close'] + 0.3 * od['atr']
                    say('  order %s: live open %.2f vs entry zone <= %.2f -> %s when PSX publishes the official open'
                        % (od['sym'], qq['o'], zone, 'would fill' if qq['o'] <= zone else 'would be cancelled'))
        except Exception as e:
            live = dict(ok=False, error=str(e))
            say('live quotes unavailable (%s) - informational only, the paper test does not depend on them.' % e)

    jsave(S('bars.json'), st['bars']); jsave(S('breadth.json'), st['breadth'])
    jsave(S('positions.json'), st['positions']); jsave(S('orders.json'), st['orders']); jsave(S('last_scan.json'), st['last_scan'])
    jsave(S('bcsm.json'), st['bcsm'])
    say('official data through %s | open positions: %d | pending orders: %d' % (last, len(st['positions']), len(st['orders'])))
    for p in st['positions']:
        if p['book'] == 'C':
            say('  C %s bought %.2f at the %s official close, %d shares - sells at the next official open' % (p['sym'], p['entry'], p['entry_date'], p['shares']))
        else:
            say('  %s %s entry %.2f stop %.2f last official close %.2f day %d' % (p['book'], p['sym'], p['entry'], p['stop'], p.get('last_close', p['entry']), p['days']))
    stats, rows, cstats, crows = closed_stats()
    if stats['n']:
        say('closed trades so far: %d | total %+.2fR | PF %s | win %d%%' % (stats['n'], stats['total_R'], stats['pf'], stats['win_pct']))
    if cstats['n']:
        say('closed trades so far (book C, after %.2f%% costs): %d | avg %+.3f%% | PF %s | win %d%% | Rs %+d'
            % (cstats['cost_pct'], cstats['n'], cstats['avg_net_pct'], cstats['pf_net'], cstats['win_pct'], cstats['pnl_rs_net']))
    # The Turn-Confirmation fields (positions, closed, recent_trades) keep their old meaning for the dashboard;
    # book C has its own block.
    jsave(S('status.json'), dict(updated_pkt=now.isoformat(timespec='minutes'), official_through=last, official_note=official_note,
                                 last_scan=st['last_scan'], orders=st['orders'], positions=[p for p in st['positions'] if p['book'] != 'C'],
                                 closed=stats, recent_trades=rows[-10:],
                                 bcsm=dict(about='Book C - buy at the official close of a support + reversal + volume day, sell at the next '
                                                 'official open. %s stocks, every market (no gates), Rs %s per trade, research book.'
                                                 % (' and '.join('Shariah' if x == 'shariah' else 'non-Shariah' for x in CFG['bcsm']['lists']), format(CFG['bcsm']['notional_rs'], ',')),
                                           signals=st['last_scan'].get('bcsm', []), positions=[p for p in st['positions'] if p['book'] == 'C'],
                                           closed=cstats, recent_trades=crows[-10:]),
                                 live=live_summary(live),
                                 config=CFG, note='Paper test only: no real orders, zero weight in the engine\'s signals. Research, not investment advice.'))
    os.makedirs(os.path.join(ROOT, 'runs'), exist_ok=True)
    open(os.path.join(ROOT, 'runs', '%s.md' % now.strftime('%Y-%m-%d_%H%M')), 'w').write('\n'.join(log) + '\n')


if __name__ == '__main__':
    main()
