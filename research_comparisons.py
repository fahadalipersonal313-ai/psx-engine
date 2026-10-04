"""Read-only, completed-session measurements for the approved research universe.

``calculate`` accepts injected banked data and never reads the database. ``build``
loads it through the existing database APIs and adds the current research guard.
These are descriptive raw-price measurements, not total returns, forecasts,
sector indices, executable liquidity or changes to the technical strategy.
"""
from collections.abc import Mapping
from datetime import date, datetime
import math
from statistics import median

import config
import corporate_actions
from data_quality import bar_error, finite, source_priority
import research_calendar
from research_contract import UNIVERSE
import session_calendar as cal


VERSION = 'completed-session-comparisons-v1'
BENCHMARK = 'KSE100'
HORIZONS = (5, 20)
PRICE_BASIS = 'Raw unadjusted stock closing-price change; excludes cash distributions and costs'
BENCHMARK_BASIS = 'Reported KSE100 index-level change; not a like-for-like stock total return'
PEER_BASIS = 'Equal-weight mean price change of all other selected-15 sector members; not a sector index'
TURNOVER_BASIS = 'Median of daily raw close × traded shares; PKR turnover proxy, not actual traded value'


def _unique(values):
    return list(dict.fromkeys(values))


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('Session dates must be YYYY-MM-DD strings')
    return date.fromisoformat(value).isoformat()


def _window(rows, dates, *, stock):
    """Require the entire independently expected sequence, including both ends."""
    selected, reasons = [], []
    if not isinstance(rows, (list, tuple)):
        return selected, ['Malformed history: expected a sequence of session rows']
    for row in rows:
        try:
            day = _day(row['date'])
        except (ValueError, TypeError, KeyError):
            reasons.append('Malformed session date in supplied history')
            continue
        if dates[0] <= day <= dates[-1]:
            selected.append(row)
    selected.sort(key=lambda row: row['date'])
    observed = [row['date'] for row in selected]
    if observed != dates:
        reasons.append('History does not exactly match the independent completed-session calendar')
    for row in selected:
        day = row['date']
        if stock:
            error = bar_error(row)
            if error:
                reasons.append(error + ' on ' + day)
            if source_priority(row.get('source')) < 3 or 'intraday' in str(row.get('source')).lower():
                reasons.append('Finalized official stock history required on ' + day)
        else:
            if not finite(row.get('close'), True):
                reasons.append('Invalid benchmark close on ' + day)
            # Index OHLC/open/volume may be absent in official closing-rate PDFs.
            # Only the published index level enters the benchmark calculation.
            source = str(row.get('source') or '').lower()
            if 'psx' not in source or 'intraday' in source:
                reasons.append('PSX completed-session benchmark provenance required on ' + day)
    return selected, _unique(reasons)


def _action_reasons(actions, start, end, now):
    reasons = []
    if not isinstance(actions, (list, tuple)):
        return ['Malformed corporate action evidence']
    for action in actions:
        try:
            ex = _day(action['ex_date'])
            if not start < ex <= end:
                continue
            known = action['known_at']
            if isinstance(known, str) and len(known) == 10:
                known_before_now = _day(known) <= now.date().isoformat()
            else:
                known_before_now = cal.local_now(datetime.fromisoformat(known.replace('Z', '+00:00'))) <= now
            if not known_before_now:
                continue
            if not corporate_actions.valid_action(action):
                reasons.append('Known unresolved corporate action on ' + ex)
            else:
                # Even a verified split/bonus/rights/dividend is not applied to
                # these raw bars. Do not silently relabel it an adjusted return.
                reasons.append('Raw price basis spans corporate action on ' + ex + '; adjusted comparison unavailable')
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            reasons.append('Malformed corporate action evidence')
    return _unique(reasons)


def _discontinuities(rows):
    reasons = []
    for before, after in zip(rows, rows[1:]):
        if finite(before.get('close'), True) and finite(after.get('close'), True):
            change = (float(after['close']) / float(before['close']) - 1) * 100
            if not finite(change) or abs(change) > corporate_actions.DETECT_PCT:
                reasons.append('Unresolved raw-price discontinuity on ' + after['date'])
    return reasons


def _measurement(rows, dates, actions, now, guard_reasons=(), *, stock=True):
    selected, reasons = _window(rows, dates, stock=stock)
    reasons += list(guard_reasons)
    reasons += _action_reasons(actions, dates[0], dates[-1], now)
    if stock:
        reasons += _discontinuities(selected)
    return selected, _unique(reasons)


def _return(rows, dates, actions, now, guard_reasons=(), *, stock=True):
    selected, reasons = _measurement(rows, dates, actions, now, guard_reasons, stock=stock)
    change = None
    if not reasons:
        candidate = (float(selected[-1]['close']) / float(selected[0]['close']) - 1) * 100
        if finite(candidate):
            change = candidate
        else:
            reasons.append('Non-finite measured change')
    return {'status': 'unavailable' if reasons else 'available', 'reasons': reasons,
            'change_pct': change, 'start_session': dates[0], 'end_session': dates[-1],
            'observed_sessions': len(selected), 'required_sessions': len(dates),
            'sources': sorted({str(row['source']) for row in selected if row.get('source')})}


def _guard_reasons(guard):
    if guard is None:
        return []
    if not isinstance(guard, Mapping) or guard.get('valid') is not True:
        checks = guard.get('checks') if isinstance(guard, Mapping) else None
        if not isinstance(checks, list) or not checks:
            return ['Research guard unavailable or invalid']
        return ['Research guard: ' + str(check) for check in checks]
    return []


def _empty_return(reason, cutoff, sessions):
    return {'status': 'unavailable', 'reasons': [reason], 'change_pct': None,
            'start_session': None, 'end_session': cutoff, 'observed_sessions': 0,
            'required_sessions': sessions + 1, 'sources': []}


def _liquidity(rows, dates, actions, now, guard_reasons=()):
    selected, reasons = _measurement(rows, dates, actions, now, guard_reasons)
    volume, turnover = None, None
    if not reasons:
        turnovers = [float(row['close']) * float(row['volume']) for row in selected]
        if not all(finite(value) for value in turnovers):
            reasons.append('Non-finite daily close-times-volume turnover proxy')
        else:
            volume = median(float(row['volume']) for row in selected)
            turnover = median(turnovers)
            if not finite(volume) or not finite(turnover):
                reasons.append('Non-finite liquidity median')
                volume, turnover = None, None
    return {'status': 'unavailable' if reasons else 'available', 'reasons': reasons,
            'sessions': 20, 'start_session': dates[0], 'end_session': dates[-1],
            'observed_sessions': len(selected), 'median20_volume_shares': volume,
            'median20_turnover_pkr': turnover, 'turnover_basis': TURNOVER_BASIS,
            'volume_basis': 'Raw daily traded shares; not action-adjusted or executable order capacity',
            'sources': sorted({str(row['source']) for row in selected if row.get('source')})}


def calculate(histories, benchmark, actions, *, now, sectors=None, guards=None):
    """Pure injected-data calculator; data and configuration are never mutated.

    ``histories`` and ``actions`` map symbols to row lists. Benchmark rows must
    carry source metadata (``build`` restores it from daily_eod). ``now`` is
    explicit: no wall-clock input leaks into replay/tests. Optional ``guards``
    is a mapping of research_guard results; when supplied, missing guards fail
    closed. Individual windows need N+1 exact closes for N-session changes.
    """
    if not isinstance(now, datetime):
        raise ValueError('An explicit measurement datetime is required')
    now = cal.local_now(now)
    cutoff = cal.last_completed(now)
    sectors = config.SECTORS if sectors is None else sectors
    windows, window_errors = {}, {}
    for count in (6, 20, 21):
        try:
            windows[count] = research_calendar.expected(cutoff, count)
        except ValueError as exc:
            window_errors[count] = str(exc)
    measurements = {}
    for symbol in (*UNIVERSE, BENCHMARK):
        guard = None if guards is None else guards.get(symbol, {'valid': False})
        blocked = _guard_reasons(guard) if symbol != BENCHMARK else []
        rows = benchmark if symbol == BENCHMARK else histories.get(symbol, [])
        measurements[symbol] = {}
        for horizon in HORIZONS:
            count = horizon + 1
            measurements[symbol][str(horizon)] = (
                _return(rows, windows[count], actions.get(symbol, []), now, blocked, stock=symbol != BENCHMARK)
                if count in windows else _empty_return(window_errors[count], cutoff, horizon))
    stocks = []
    for symbol in UNIVERSE:
        sector = sectors.get(symbol)
        members = [other for other in UNIVERSE if sector and sectors.get(other) == sector]
        peers = [other for other in members if other != symbol]
        row = {'symbol': symbol, 'sector': sector, 'as_of_session': cutoff,
               'price_basis': PRICE_BASIS, 'returns': {}, 'sector_peers': {}}
        for horizon in HORIZONS:
            key = str(horizon)
            stock = measurements[symbol][key]
            index = measurements[BENCHMARK][key]
            reasons = [symbol + ': ' + reason for reason in stock['reasons']]
            reasons += [BENCHMARK + ': ' + reason for reason in index['reasons']]
            difference = stock['change_pct'] - index['change_pct'] if not reasons else None
            if difference is not None and not finite(difference):
                reasons.append('Non-finite stock-versus-benchmark difference')
                difference = None
            row['returns'][key] = {
                'status': 'unavailable' if reasons else 'available', 'reasons': reasons,
                'sessions': horizon, 'start_session': stock['start_session'], 'end_session': cutoff,
                'stock_change_pct': stock['change_pct'], 'benchmark_change_pct': index['change_pct'],
                'difference_pp': difference, 'stock_status': stock['status'], 'benchmark_status': index['status'],
                'price_basis': PRICE_BASIS, 'benchmark': BENCHMARK, 'benchmark_basis': BENCHMARK_BASIS,
                'source': {'stock': stock['sources'], 'benchmark': index['sources']},
                'stock_observed_sessions': stock['observed_sessions'],
                'benchmark_observed_sessions': index['observed_sessions'], 'required_closes': horizon + 1,
            }
            eligible = [peer for peer in peers if measurements[peer][key]['status'] == 'available']
            missing = [peer for peer in peers if peer not in eligible]
            reasons = [symbol + ': ' + reason for reason in stock['reasons']]
            if not sector:
                reasons.append('Configured sector unavailable')
            if len(peers) < 2:
                reasons.append('At least two other selected-15 sector members required')
            for peer in missing:
                reasons.extend(peer + ': ' + reason for reason in measurements[peer][key]['reasons'])
            mean, difference = None, None
            if not reasons:
                # Divide first to avoid overflow in a sum of large finite values.
                mean = math.fsum(measurements[peer][key]['change_pct'] / len(peers) for peer in peers)
                difference = stock['change_pct'] - mean
                if not finite(mean) or not finite(difference):
                    reasons.append('Non-finite peer comparison')
                    mean, difference = None, None
            row['sector_peers'][key] = {
                'status': 'unavailable' if reasons else 'available', 'reasons': _unique(reasons),
                'sessions': horizon, 'start_session': stock['start_session'], 'end_session': cutoff,
                'basis': PEER_BASIS, 'sector_members': members, 'peer_members': peers,
                'available_members': eligible, 'missing_members': missing,
                'coverage_count': len(eligible), 'required_count': len(peers), 'excludes_self': True,
                'peer_mean_change_pct': mean, 'stock_minus_peers_pp': difference,
                'member_changes_pct': {peer: measurements[peer][key]['change_pct'] for peer in peers},
                'source': {peer: measurements[peer][key]['sources'] for peer in peers},
            }
        guard = None if guards is None else guards.get(symbol, {'valid': False})
        if 20 in windows:
            row['liquidity'] = _liquidity(histories.get(symbol, []), windows[20], actions.get(symbol, []), now,
                                          _guard_reasons(guard))
        else:
            row['liquidity'] = {'status': 'unavailable', 'reasons': [window_errors[20]], 'sessions': 20,
                                'start_session': None, 'end_session': cutoff, 'observed_sessions': 0,
                                'median20_volume_shares': None, 'median20_turnover_pkr': None,
                                'turnover_basis': TURNOVER_BASIS, 'sources': []}
        metrics = [*row['returns'].values(), *row['sector_peers'].values(), row['liquidity']]
        available = sum(item['status'] == 'available' for item in metrics)
        row['status'] = 'available' if available == len(metrics) else 'partial' if available else 'unavailable'
        row['reasons'] = _unique(reason for item in metrics for reason in item['reasons'])
        row['research_guard'] = guard
        stocks.append(row)
    available = sum(row['status'] != 'unavailable' for row in stocks)
    return {
        'schema_version': 1, 'version': VERSION, 'generated_at': now.isoformat(),
        'as_of_session': cutoff, 'status': 'available' if all(row['status'] == 'available' for row in stocks)
        else 'partial' if available else 'unavailable', 'universe': list(UNIVERSE),
        'benchmark': BENCHMARK, 'price_basis': PRICE_BASIS, 'benchmark_basis': BENCHMARK_BASIS,
        'source': {'stocks': 'Banked database.daily_ohlc', 'benchmark': 'Banked database.daily_eod/KSE100',
                   'calendar': list(research_calendar.SOURCES), 'calendar_verified_at': research_calendar.VERIFIED_AT,
                   'sector_membership': 'config.SECTORS restricted to research_contract.UNIVERSE'},
        'session_basis': 'Exact independent completed-session dates; no backward fallback when a session is missing',
        'corporate_action_policy': 'Any known action within a window blocks raw-basis comparison; no inferred adjustments',
        'peer_basis': PEER_BASIS, 'turnover_basis': TURNOVER_BASIS,
        'limitations': ['Selected-15 membership is current, not a reconstructed historical sector universe',
                        'Price/index-level differences are descriptive, not alpha, investment advice or forecasts',
                        'Liquidity uses full completed sessions, not intraday volume or executable fills'],
        'stocks': stocks,
    }


def build(now=None):
    """Read banked data and research guards without fetching or mutating data."""
    import database as db
    import research_guard

    now = cal.local_now(now)
    cutoff = cal.last_completed(now)
    limit = max(90, config.FEATURE_HISTORY_LIMIT)
    histories, actions, guards = {}, {}, {}
    for symbol in UNIVERSE:
        histories[symbol] = db.get_daily_ohlc(symbol, limit)
        actions[symbol] = db.get_corporate_actions(symbol)
        guards[symbol] = research_guard.check({'symbol': symbol, 'decision_session': cutoff}, now)
        if config.BENCHMARK_INDEX != BENCHMARK:
            guards[symbol] = {'valid': False, 'checks': ['Research guard benchmark differs from KSE100']}
    benchmark = db.get_eod_history(BENCHMARK, limit)
    # get_eod_history deliberately omits its source column; restore provenance
    # with a read-only SELECT rather than attributing every row to one source.
    with db.conn() as connection:
        sources = dict(connection.execute('SELECT date, source FROM daily_eod WHERE symbol=?', (BENCHMARK,)))
    benchmark = [dict(row, source=sources.get(row['date'])) for row in benchmark]
    actions[BENCHMARK] = db.get_corporate_actions(BENCHMARK)
    return calculate(histories, benchmark, actions, now=now, guards=guards)
