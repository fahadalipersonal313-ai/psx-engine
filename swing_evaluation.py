"""Daily-bar target-before-stop evaluation; no invented portfolio equity curve."""
from collections import Counter
from copy import deepcopy
import json
import config
import decision_engine
from data_quality import bar_error, valid_levels, source_priority

RESOLVED = ('target', 'stop', 'expired')


def opportunity(decision):
    tech = decision['technical']
    return {'symbol': decision['symbol'], 'session': decision['decision_session'],
            'reference_entry': tech['price'], 'stop': tech['stop_loss'],
            'target': tech['target1'], 'target2': tech.get('target2'),
            'strategy_version': decision['strategy_version'], 'config_hash': decision['config_hash'],
            'snapshot_hash': decision['snapshot_hash'], 'execution': deepcopy(decision['config']['EXECUTION']),
            'quantity': 1, 'probability': None, 'probability_label': 'uncalibrated'}


def resolve(item, bars, sessions, as_of=None, actions=None):
    """One next-session opening order, expires if not fillable that session.

    sessions comes from dated benchmark observations, never stock row positions.
    Missing/locked bars after entry retain unresolved exposure. Same-bar barrier
    ambiguity is stop-first. Fees and slippage are frozen with the opportunity.
    """
    policy = item['execution']
    from data_quality import finite
    if any(not finite(policy.get(k)) or policy[k] < 0 for k in ('holding_sessions','slippage_bps','fee_bps_per_side','entry_gap_limit','max_volume_participation')) or policy['max_volume_participation'] > 1 or policy['slippage_bps'] >= 10000 or policy['fee_bps_per_side'] >= 10000:
        return {'status':'invalid', 'reason':'Invalid frozen execution assumptions'}
    horizon = int(policy['holding_sessions'])
    if horizon < 1 or horizon > 10:
        return {'status': 'invalid', 'reason': 'Holding horizon must be 1..10 sessions'}
    if not valid_levels(item['reference_entry'], item['stop'], item['target'], item.get('target2')):
        return {'status': 'invalid', 'reason': 'Invalid frozen trade levels'}
    dates = sorted(set(str(d)[:10] for d in sessions if str(d)[:10] > item['session'] and (as_of is None or str(d)[:10] <= as_of)))[:horizon]
    if as_of and as_of > item['session'] and (not dates or (len(dates) < horizon and dates[-1] < as_of)):
        return {'status':'unavailable','reason':'Benchmark session coverage unavailable'}
    indexed = {}
    for bar in bars:
        day = str(bar['date'])[:10]
        if day in indexed:
            return {'status': 'unavailable', 'reason': 'Duplicate execution session'}
        indexed[day] = bar
    slip, fee = policy['slippage_bps'] / 10000, policy['fee_bps_per_side'] / 10000
    entry = None
    entry_date = None
    def result(status, **extra):
        return dict(status=status, entry=entry, entry_date=entry_date, **extra)
    for number, day in enumerate(dates, 1):
        bar = indexed.get(day)
        if bar is None or bar_error(bar) or source_priority(bar.get('source')) < 3:
            return result('unavailable', reason='Missing, invalid or nonfinal execution bar', unresolved_session=day)
        if any(a['ex_date'] == day for a in actions or []):
            return result('unavailable', reason='Corporate action during opportunity requires reconciliation', unresolved_session=day)
        o, h, l, c, v = (float(bar[k]) for k in ('open', 'high', 'low', 'close', 'volume'))
        if h == l or v <= 0:
            return result('unfilled' if entry is None else 'unavailable', reason='Locked or untraded session', exit_date=day)
        if entry is None:
            entry = o * (1 + slip)
            entry_date = day
            if abs(entry / item['reference_entry'] - 1) > policy['entry_gap_limit'] or not item['stop'] < entry < item['target'] or item.get('quantity', 1) > v * policy['max_volume_participation']:
                entry = None
                return result('unfilled', reason='Opening price or participation outside entry policy', exit_date=day)
        ambiguous = l <= item['stop'] and h >= item['target']
        if o <= item['stop']:
            status, exit_price = 'stop', o * (1 - slip)
        elif o >= item['target']:
            status, exit_price = 'target', item['target']  # resting limit; no favorable gap windfall
        elif l <= item['stop']:
            status, exit_price = 'stop', item['stop'] * (1 - slip)
        elif h >= item['target']:
            status, exit_price = 'target', item['target']
        elif number == horizon:
            status, exit_price = 'expired', c * (1 - slip)
        else:
            continue
        net = (exit_price * (1 - fee) / (entry * (1 + fee)) - 1) * 100
        return result(status, exit_price=exit_price, exit_date=day, holding_sessions=number,
                      net_return_pct=net, ambiguous=ambiguous,
                      target_by_5=status == 'target' and number <= 5,
                      target_by_10=status == 'target' and number <= 10)
    return result('pending', observed_sessions=len(dates))


def metrics(outcomes):
    counts = Counter(o['status'] for o in outcomes)
    resolved = [o for o in outcomes if o['status'] in RESOLVED]
    returns = [o['net_return_pct'] for o in resolved]
    gains = sum(max(0, r) for r in returns)
    losses = -sum(min(0, r) for r in returns)
    n = len(resolved)
    return {'opportunities': len(outcomes), 'counts': dict(counts), 'resolved': n,
            'target_by_5_pct': 100 * sum(o.get('target_by_5', False) for o in resolved) / n if n else None,
            'target_by_10_pct': 100 * counts['target'] / n if n else None,
            'net_expectancy_pct': sum(returns) / n if n else None,
            'profit_factor': gains / losses if losses else None,
            'unresolved_risk': counts['pending'] + counts['unavailable'],
            'note': 'Resolved-opportunity statistics, not calibrated forecasts. Unavailable exposure remains unresolved. No portfolio return or drawdown is inferred.'}


def replay(symbol, bars, benchmark, lookback=250, eligible=True, actions=None):
    bars = sorted(bars, key=lambda b: str(b['date']))
    benchmark = sorted(benchmark, key=lambda b: str(b['date']))
    sessions = [str(b['date'])[:10] for b in benchmark]
    start = sessions[max(0, len(sessions) - lookback)] if sessions else ''
    previous, active, outcomes, decisions = None, None, [], []
    vetoes = Counter()
    # Warm up the same previous-session state before the evaluation boundary.
    # Each decision trims only at its own cutoff using the same live limit.
    for day in sessions:
        decision = decision_engine.decide(symbol, bars, benchmark, day, eligible, previous, actions)
        previous = decision_engine.state(decision)
        if day < start:
            continue
        if active:
            outcome = resolve(active, bars, sessions, as_of=day, actions=actions)
            if outcome['status'] not in ('pending', 'unavailable'):
                outcomes.append(outcome)
                active = None
        decisions.append(previous)
        if decision['signal']['signal'] == 'No data':
            vetoes.update(decision['signal']['reasons'])
        if not active and decision['signal']['signal'] in ('Buy', 'Strong Buy'):
            active = opportunity(decision)
    if active:
        outcomes.append(resolve(active, bars, sessions, actions=actions))
    return {'symbol': symbol, 'metrics': metrics(outcomes), 'outcomes': outcomes,
            'decisions': decisions, 'vetoes': dict(vetoes),
            'validation': 'Historical descriptive replay with current universe eligibility; not untouched out-of-sample validation.'}


def backtest(symbol, lookback=None, hold_days=None, **kwargs):
    import database as db
    if hold_days is not None and hold_days != config.EXECUTION['holding_sessions']:
        raise ValueError('Change and register the execution contract before using a different horizon')
    return replay(symbol, db.get_daily_ohlc(symbol, 100000), db.get_eod_history(config.BENCHMARK_INDEX, 100000),
                  lookback or config.BACKTEST['lookback'], symbol in config.STOCKS, db.get_corporate_actions(symbol))


def backtest_portfolio(symbols=None, **kwargs):
    results = [backtest(symbol, **kwargs) for symbol in (symbols or config.STOCKS)]
    return {'metrics': metrics([o for r in results for o in r['outcomes']]), 'results': results,
            'note': 'Aggregated single-opportunity study; no capital-constrained equity curve.'}


def update_outcomes():
    import database as db
    from session_calendar import last_completed
    cutoff = last_completed()
    sessions = [b['date'] for b in db.get_eod_history(config.BENCHMARK_INDEX, 100000)]
    for row in db.open_opportunities():
        item = json.loads(row['payload'])
        with db.conn() as c:
            old = c.execute('SELECT payload FROM opportunity_outcomes WHERE opportunity_id=?',(row['id'],)).fetchone()
        old = json.loads(old['payload']) if old else {}
        bars = {b['date']: b for b in db.get_daily_ohlc(row['symbol'], 100000) if item['session'] < b['date'] <= cutoff}
        # Once a finalized execution observation has been used, later feed
        # revisions cannot silently change the recorded fill or economic path.
        bars.update({b['date']: b for b in old.get('execution_bars', [])})
        result = resolve(item, list(bars.values()), sessions, cutoff, db.get_corporate_actions(row['symbol']))
        end = result.get('exit_date') or result.get('unresolved_session') or cutoff
        result['execution_bars'] = [b for b in bars.values() if b['date'] <= end and not bar_error(b) and source_priority(b.get('source')) >= 3]
        result['observed_at_session'] = cutoff
        db.save_opportunity_outcome(row['id'], result)
