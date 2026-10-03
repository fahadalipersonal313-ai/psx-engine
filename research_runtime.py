"""Single-writer research snapshots and immutable decision checkpoints.

Runs in runtime-state's existing engine worker. Never writes source or model
research branches. Observed public quotes are snapshots, never invented ticks.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import research_contract as contract
import research_desk
import session_calendar as cal

VERSION = 'combined-research-v1'


def read(path, default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError): return default


def write(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,allow_nan=False,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def segment(at):
    local=cal.local_now(at)
    for start,end in cal.intervals(local.date()):
        if start <= local.strftime('%H:%M') < end:
            return local.date().isoformat(),start
    return None


def observe(quote, previous, now):
    """Distinct source timestamps only; cumulative volume differs within one segment."""
    out=dict(quote)
    out.update(state='Warming up: three distinct source snapshots required',qualifies=False,
               observation_type='delayed public REG snapshot',recent_pct=None,window_volume=None,
               risk='No tick tape, spread, depth or executable fill verified. Watch only.')
    try:
        at=contract.stamp(research_desk.source_time(quote))
        if previous and at <= max(contract.stamp(research_desk.source_time(p)) for p in previous):
            out['state']='Warming up: unchanged or regressing source timestamp';return out
        if not research_desk.fresh_quote(quote,now) or segment(at) != segment(now):
            out['state']='Unavailable: stale quote or market closed';return out
        points=[p for p in previous if segment(contract.stamp(research_desk.source_time(p)))==segment(at)
                and contract.stamp(research_desk.source_time(p)) < at]
        points.sort(key=lambda p:contract.stamp(research_desk.source_time(p)))
        if len(points)<2: return out
        anchors=[p for p in points if 600 <= (at-contract.stamp(research_desk.source_time(p))).total_seconds() <= 1200]
        if not anchors: return out
        anchor=min(anchors,key=lambda p:abs((at-contract.stamp(research_desk.source_time(p))).total_seconds()-900))
        before=contract.stamp(research_desk.source_time(anchor))
        older=[p for p in points if 600 <= (before-contract.stamp(research_desk.source_time(p))).total_seconds() <= 1200]
        if not older:return out
        predecessor=min(older,key=lambda p:abs((before-contract.stamp(research_desk.source_time(p))).total_seconds()-900))
        gap=(at-before).total_seconds()
        earlier=(before-contract.stamp(research_desk.source_time(predecessor))).total_seconds()
        if not (600 <= gap <= 1200 and 600 <= earlier <= 1200):
            out['state']='Warming up: source-time sampling gap';return out
        # An intervening counter reset invalidates the whole selected window,
        # even if the current total has subsequently exceeded the old anchor.
        start=contract.stamp(research_desk.source_time(predecessor))
        chain=[p for p in points if start <= contract.stamp(research_desk.source_time(p)) < at]+[quote]
        if any(b['day_volume']<a['day_volume'] for a,b in zip(chain,chain[1:])):
            out['state']='Unavailable: cumulative volume reset inside observation window';return out
        delta=quote['day_volume']-anchor['day_volume']
        if delta<0:
            out['state']='Unavailable: cumulative volume reset';return out
        change=(quote['price']/anchor['price']-1)*100
        out.update(window_volume=delta,recent_pct=round(change,3),window_minutes=round(gap/60,2),
                   window_start=research_desk.source_time(anchor),window_end=research_desk.source_time(quote),
                   volume_rule='Experimental: at least 10,000 additional shares; no measured window turnover or same-time baseline')
        out['state']='Watching: observed snapshot move'
        if quote.get('change_pct') is not None and quote['change_pct']>=1 and change>=.15 and delta>=10000:
            out.update(state='Confirmed delayed-data watch',qualifies=True)
        return out
    except (ValueError,TypeError,KeyError,ZeroDivisionError):
        out['state']='Unavailable: malformed source observation';return out


def collect_quotes(now=None, scheduled_at=None):
    import intraday_capture
    fixed_now=now
    now=now or datetime.now(timezone.utc)
    capture=intraday_capture.collect(now=fixed_now,scheduled_at=scheduled_at)
    now=fixed_now or datetime.now(timezone.utc)
    if capture.get('paused'):return capture
    previous=read('research_quote_history.json',{})
    observations=[]
    for quote in capture.get('prices',[]):
        sym=quote['symbol'];history=previous.get(sym,[])
        observations.append(observe(quote,history,now))
        at=contract.stamp(research_desk.source_time(quote))
        if not history or at>contract.stamp(research_desk.source_time(history[-1])):
            history.append(quote)
        previous[sym]=[p for p in history if now-contract.stamp(research_desk.source_time(p))<timedelta(days=5)][-100:]
    capture['observations']=observations
    write('research_quote_history.json',previous)
    write('research_quotes.json',capture)
    return capture


def checkpoint(now=None):
    import requests
    import intraday_capture
    intraday_capture.recover()
    now=now or datetime.now(timezone.utc)
    context=None;error=None
    try:
        r=requests.get(research_desk.RESEARCH_URL,timeout=10,headers={'User-Agent':'PSXResearch/1.0','Cache-Control':'no-cache'})
        r.raise_for_status();context=contract.validate(r.json())
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)[:200]
    snapshot=read('dashboard_snapshot.json',{})
    quotes=read('research_quotes.json',{})
    desk=research_desk.build(context,snapshot,quotes,now)
    record={'schema_version':1,'version':VERSION,'recorded_at':now.isoformat(),
            'context_sha256':digest(context),'technical_sha256':digest(snapshot),'quotes_sha256':digest(quotes),
            'context_error':error,'research':context,'technical_snapshot':snapshot,'quote_snapshot':quotes,
            'decisions':[{'symbol':r['symbol'],'intraday':r['intraday_state'],'swing':r['swing_state'],
                          'investment':r['investment_state'],'plan':r['plan'],'missing':r['missing'],
                          'activation':'research_candidate' if r['swing_state']=='Swing setup for review' else 'watch_or_blocked',
                          'execution_status':'not_entered','outcome':'pending_execution_evidence'} for r in desk['rows']],
            'evaluation_policy':{'order_execution':'No orders placed; candidate is not an entered trade',
                                 'entry':'Next observation must independently satisfy frozen entry conditions; no retrospective entry',
                                 'costs':'Not yet specified; no net-return claim',
                                 'same_bar_stop_target':'Unresolved unless timestamped sequencing establishes order',
                                 'status':'Prospective observation journal only; outcomes require a separately verified evaluator'}}
    rid=digest(record);record['id']=rid
    path=Path('research_decisions')/cal.local_now(now).date().isoformat()/(now.strftime('%H%M%S')+'-'+rid[:12]+'.json')
    if path.exists() and read(path)!=record:raise RuntimeError('Immutable checkpoint conflict')
    if not path.exists():write(path,record)
    status={'schema_version':1,'checked_at':now.isoformat(),'version':VERSION,'checkpoint':str(path),'id':rid,
            'research_current':desk['research_current'],'context_error':error,
            'calendar_verified_through':'2026-12-31','calendar_maintenance_due':'2026-12-01',
            'quotes_as_of':quotes.get('checked_at'),'decision_count':len(desk['rows']),
            'execution_status':'No orders or assumed fills','outcomes':'Pending independently verified evaluation'}
    write('research_status.json',status)
    return status


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--quotes-only',action='store_true');args=parser.parse_args()
    print(json.dumps(collect_quotes() if args.quotes_only else checkpoint(),default=str))
