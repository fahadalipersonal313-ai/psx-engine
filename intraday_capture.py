"""Immutable, honest point observations. These are NOT 1/5-minute OHLCV bars.

One runtime-state writer owns capture files, state, and the latest coverage view.
No timestamp interpolation, OHLC reconstruction, trades, or paper fills.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

import research_contract as contract
import session_calendar as cal

VERSION = 'intraday-point-observations-v1'
CADENCE_SECONDS = 300
MAX_SOURCE_GAP_SECONDS = 660
STATE_PATH = Path('intraday_collection_state.json')
STATUS_PATH = Path('intraday_collection_status.json')
ROOT = Path('intraday_samples')


def _read(path, default):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError): return default


def _load_state(path, default):
    path=Path(path)
    if not path.exists():return default
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or any(not isinstance(value.get(k),dict) for k in ('by_symbol','sessions','network')):
            raise ValueError('Missing observation state maps')
        return value
    except (OSError,ValueError,TypeError) as exc:
        raise RuntimeError('Observation state is unreadable; refusing to reset collection history') from exc


def _write(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def segment(at):
    local=cal.local_now(at)
    for start,end in cal.intervals(local.date()):
        if start <= local.strftime('%H:%M') < end:
            return local.date().isoformat(),start
    return None


def _number(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)


def audit(quote, previous, collected_at):
    """An actual source-to-source volume difference, never an assumed 5m bar."""
    flags=['partial_point_observation_not_ohlcv','source_time_is_quote_update_not_verified_trade_time']
    row={'symbol':quote.get('symbol'),'market':quote.get('market'),'source_url':quote.get('source_url'),
         'source_as_of':quote.get('source_as_of'),'fetched_at':quote.get('fetched_at'),
         'price':quote.get('price'),'cumulative_session_volume':quote.get('day_volume'),
         'previous_observation_id':(previous or {}).get('observation_id'),
         'observed_volume_delta':None,'volume_interval_seconds':None,
         'quality_flags':flags,'usable_point':False,'ohlcv_bar':False,
         'source_running_daily_ohlc':{k:quote.get(k) for k in ('open','high','low')},
         'running_ohlc_scope':'Official running session values, not interval extremes'}
    try:
        at=contract.stamp(quote['source_as_of']);fetched=contract.stamp(quote['fetched_at'])
        if (quote['symbol'] not in contract.UNIVERSE or quote.get('market')!='REG' or
            quote.get('source_url')!='https://dps.psx.com.pk/company/'+quote['symbol'] or
            quote.get('volume_kind')!='cumulative_session' or
            not _number(quote['price']) or quote['price']<=0 or
            not _number(quote['day_volume']) or quote['day_volume']<0 or not float(quote['day_volume']).is_integer()):
            flags.append('invalid_source_fields');return row
        if at>fetched or fetched>collected_at:
            flags.append('future_timestamp');return row
        if segment(collected_at) is None:
            flags.append('collection_outside_regular_session')
        if segment(at) is None:
            flags.append('source_preopen_break_or_after_close')
        if segment(at)!=segment(collected_at):
            flags.append('source_not_current_trading_segment')
        if (collected_at-at).total_seconds()>1200:
            flags.append('stale_source')
        if len(flags)>2:return row
        row['usable_point']=True
        if not previous:
            flags.append('first_point_no_volume_interval');return row
        before=contract.stamp(previous['source_as_of'])
        gap=(at-before).total_seconds()
        if gap==0:
            same=(quote['price']==previous['price'] and quote['day_volume']==previous['cumulative_session_volume'])
            flags.append('duplicate_source_timestamp' if same else 'conflicting_source_timestamp')
            row['usable_point']=False;return row
        if gap<0:
            flags.append('non_monotonic_source_timestamp');row['usable_point']=False;return row
        if cal.local_now(at).date()!=cal.local_now(before).date():
            flags.append('new_session_volume_counter');return row
        if segment(at)!=segment(before):
            flags.append('trading_segment_boundary');return row
        delta=quote['day_volume']-previous['cumulative_session_volume']
        if delta<0:
            flags.append('cumulative_volume_reset');return row
        row['volume_interval_seconds']=gap
        if gap>MAX_SOURCE_GAP_SECONDS:
            flags.append('source_gap_volume_interval_withheld');return row
        row['observed_volume_delta']=int(delta)
        if not 240 <= gap <= 360:flags.append('irregular_source_interval_not_five_minutes')
        return row
    except (ValueError,KeyError,TypeError,OverflowError):
        flags.append('malformed_timestamp_or_source');row['usable_point']=False;return row


def poll_slots(at, grace_seconds=0):
    local=cal.local_now(at);out=set()
    for start,end in cal.intervals(local.date()):
        a=datetime.fromisoformat(local.date().isoformat()+'T'+start+':00').replace(tzinfo=cal.PKT)
        b=datetime.fromisoformat(local.date().isoformat()+'T'+end+':00').replace(tzinfo=cal.PKT)
        t=a
        while t<b and t<=local-timedelta(seconds=grace_seconds):
            out.add(start+'/'+str(int((t-a).total_seconds()/CADENCE_SECONDS)))
            t+=timedelta(seconds=CADENCE_SECONDS)
    return out


def current_slot(at):
    seg=segment(at)
    if not seg:return None
    local=cal.local_now(at)
    a=datetime.fromisoformat(seg[0]+'T'+seg[1]+':00').replace(tzinfo=cal.PKT)
    return seg[1]+'/'+str(int((local-a).total_seconds()/CADENCE_SECONDS))


def recover(*, state_path=STATE_PATH, status_path=STATUS_PATH, root=ROOT):
    """Replay an interrupted local transaction before another request or publish."""
    pending=Path(state_path).with_suffix('.pending.json')
    if not pending.exists():return False
    transaction=_read(pending,None)
    if not isinstance(transaction,dict):raise RuntimeError('Unreadable pending observation transaction')
    capture_path=Path(transaction['capture_path'])
    if not capture_path.resolve().is_relative_to(Path(root).resolve()):
        raise RuntimeError('Pending capture path outside observation directory')
    state=_load_state(state_path,{})
    if state.get('last_collection') and contract.stamp(state['last_collection'])>contract.stamp(transaction['state']['last_collection']):
        raise RuntimeError('Pending observation transaction would regress current state')
    document=transaction['document']
    if capture_path.exists():
        if _read(capture_path,None)!=document:raise RuntimeError('Immutable observation conflict')
    else:_write(capture_path,document)
    _write(state_path,transaction['state'])
    _write(status_path,transaction['status'])
    pending.unlink()
    return True


def record(capture, *, state_path=STATE_PATH, status_path=STATUS_PATH, root=ROOT):
    """Capture ID is idempotent; old captures never replace newer status/state."""
    recover(state_path=state_path,status_path=status_path,root=root)
    at=contract.stamp(capture['checked_at'])
    cid=_digest({'version':VERSION,'capture':capture})
    path=Path(root)/cal.local_now(at).date().isoformat()/(at.strftime('%H%M%S')+'-'+cid[:16]+'.json')
    if path.exists():return _read(path,{})
    state=_load_state(state_path,{'by_symbol':{},'sessions':{},'network':{}})
    if state.get('last_collection') and at<=contract.stamp(state['last_collection']):
        raise ValueError('Out-of-order capture cannot replace current collection state')
    quotes={x['symbol']:x for x in capture.get('prices',[])}
    errors={x['symbol']:x for x in capture.get('errors',[])}
    skipped=set(capture.get('skipped',[]));rows=[]
    day=cal.local_now(at).date().isoformat()
    session=state['sessions'].setdefault(day,{'captures':0,'usable_points':{},'errors':0,'duplicates':0})
    session['captures']+=1
    slots=set(session.get('collected_poll_slots',[]))
    slot=current_slot(at)
    if slot is not None:slots.add(slot)
    session['collected_poll_slots']=sorted(slots)
    expected=poll_slots(at,grace_seconds=60)
    missed=expected-slots
    for symbol in contract.UNIVERSE:
        previous=state['by_symbol'].get(symbol)
        if symbol in quotes:
            row=audit(quotes[symbol],previous,at)
        else:
            flag='source_backoff' if symbol in skipped else 'source_fetch_failed'
            row={'symbol':symbol,'market':'REG','source_url':'https://dps.psx.com.pk/company/'+symbol,
                 'source_as_of':None,'fetched_at':None,'price':None,'cumulative_session_volume':None,
                 'observed_volume_delta':None,'volume_interval_seconds':None,'usable_point':False,
                 'ohlcv_bar':False,'previous_observation_id':(previous or {}).get('observation_id'),
                 'quality_flags':['partial_point_observation_not_ohlcv',flag],
                 'error':errors.get(symbol,{}).get('error','No usable observation')}
            session['errors']+=1
        row['observation_id']=_digest({'capture_id':cid,'symbol':symbol})
        row['collected_at']=at.isoformat()
        if row['usable_point']:
            state['by_symbol'][symbol]=row
            session['usable_points'][symbol]=session['usable_points'].get(symbol,0)+1
        if 'duplicate_source_timestamp' in row['quality_flags']:session['duplicates']+=1
        rows.append(row)
    state['sessions']={d:v for d,v in state['sessions'].items() if d>=(cal.local_now(at).date()-timedelta(days=90)).isoformat()}
    state['last_collection']=at.isoformat();state['last_capture_id']=cid
    if 'network_state' in capture:state['network']=capture['network_state']
    document={'schema_version':1,'version':VERSION,'capture_id':cid,'collected_at':at.isoformat(),
              'scheduled_at':capture.get('scheduled_at'),'cadence_target_seconds':CADENCE_SECONDS,
              'dataset_kind':'delayed_REG_point_observations','source_delayed':True,'ohlcv_status':'unavailable',
              'paper_strategy_status':'collection_only_no_fills','observations':rows}
    status={'schema_version':1,'version':VERSION,'checked_at':at.isoformat(),'capture_id':cid,'capture_path':str(path),
            'dataset_kind':document['dataset_kind'],'ohlcv_status':'unavailable',
            'target_minutes':5,'collection_session':day,'capture_count_this_date':session['captures'],
            'regular_poll_windows_elapsed':len(expected),'regular_poll_windows_observed':len(slots),
            'missed_poll_windows':len(missed),'missed_poll_window_ids':sorted(missed),
            'poll_count_note':'Expected exchange-session five-minute windows, with 60-second grace; counts are as of this capture, not candle completeness.',
            'usable_points_this_date':session['usable_points'],'current_usable_points':sum(x['usable_point'] for x in rows),
            'coverage':'partial observations; no complete 1-minute or 5-minute candles',
            'rows':[{'symbol':x['symbol'],'source_as_of':x['source_as_of'],'quality_flags':x['quality_flags'],
                     'observed_volume_delta':x['observed_volume_delta'],'volume_interval_seconds':x['volume_interval_seconds']} for x in rows],
            'paper_strategy_status':'Collection only; strategy, costs and executable-fill assumptions not yet frozen',
            'prerequisites':['Enough representative session coverage','Explicit prospective strategy and risk specification',
                             'Declared costs, spread and fill assumptions','Independent outcomes with ambiguous intervals unresolved'],
            'next_retry_at':{s:v.get('next_retry_at') for s,v in state['network'].items() if v.get('next_retry_at')}}
    transaction={'capture_path':str(path),'document':document,'state':state,'status':status}
    _write(Path(state_path).with_suffix('.pending.json'),transaction)
    recover(state_path=state_path,status_path=status_path,root=root)
    return document


def collect(*, now=None, scheduled_at=None, fetcher=None, state_path=STATE_PATH, status_path=STATUS_PATH, root=ROOT):
    """Polite per-symbol backoff; ordinary GETs only, no retry of refusals here."""
    import psx_company_quotes as source
    recover(state_path=state_path,status_path=status_path,root=root)
    if Path('.engine-paused').exists():
        return {'paused':True,'checked_at':(now or datetime.now(timezone.utc)).isoformat(),'available':0,'requested':15}
    start=now or datetime.now(timezone.utc)
    state=_load_state(state_path,{'by_symbol':{},'sessions':{},'network':{}});network=state.get('network',{})
    skipped=[s for s in contract.UNIVERSE if network.get(s,{}).get('next_retry_at') and
             contract.stamp(network[s]['next_retry_at'])>start]
    wanted=[s for s in contract.UNIVERSE if s not in skipped]
    if wanted:
        # 15 requests / 2 workers at <=12s each fit the outer 180s budget.
        bounded_fetch=fetcher or (lambda symbol:source.fetch(symbol,timeout=12))
        def guarded_fetch(symbol):
            if Path('.engine-paused').exists():raise InterruptedError('Engine paused before source request')
            return bounded_fetch(symbol)
        capture=source.collect(symbols=wanted,now=now,workers=2,fetcher=guarded_fetch)
    else:
        capture={'checked_at':start.isoformat(),'prices':[],'errors':[],'failed':[],'available':0}
    checked=now or datetime.now(timezone.utc);capture['checked_at']=checked.isoformat()
    for quote in capture['prices']:network.pop(quote['symbol'],None)
    for error in capture['errors']:
        symbol=error['symbol'];failures=network.get(symbol,{}).get('consecutive_failures',0)+1
        refused=error.get('http_status') in (401,403,404,429)
        delay=3600 if refused else min(3600,CADENCE_SECONDS*2**min(failures-1,4))
        network[symbol]={'consecutive_failures':failures,'next_retry_at':(checked+timedelta(seconds=delay)).isoformat(),
                         'reason':error['error'],'http_status':error.get('http_status')}
    capture.update(requested=len(contract.UNIVERSE),attempted=len(wanted),skipped=skipped,
                   universe=list(contract.UNIVERSE),scheduled_at=scheduled_at,
                   network_state=network,coverage='partial_point_observations_not_ohlcv')
    document=record(capture,state_path=state_path,status_path=status_path,root=root)
    capture['observation_capture_id']=document['capture_id']
    return capture
