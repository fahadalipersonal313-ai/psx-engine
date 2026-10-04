"""Five-minute observation slots inside the existing single engine writer.

Main analysis remains every 15 minutes. Never starts a second worker or retries
missed historical slots; publication conflicts remain hard failures.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import time

import session_calendar as cal

FILES=('research_quotes.json','research_quote_history.json','research_status.json','research_signals.json','research_decisions',
       'intraday_collection_state.json','intraday_collection_status.json','intraday_samples',
       'research_paper_summary.json','paper_events','research_activity.json','research_comparisons.json')


def due_targets(cycle_started,cycle_seconds=900,now=None):
    now=time.time() if now is None else now
    return [t for t in range(int(cycle_started)+300,int(cycle_started)+int(cycle_seconds),300) if t>=now]


def publish_small():
    from runtime_publish import publish
    import intraday_capture
    intraday_capture.recover()
    paths=[p for p in FILES if Path(p).exists()]
    if not paths:return
    subprocess.run(['git','add','--',*paths],check=True)
    changed=subprocess.run(['git','diff','--cached','--quiet']).returncode
    if changed==0:return
    if changed!=1:raise RuntimeError('Cannot inspect staged observation files')
    subprocess.run(['git','commit','-m','Record five-minute point observations '+datetime.now(timezone.utc).isoformat(timespec='seconds')],check=True)
    publish('runtime-state')


def run(cycle_started,cycle_seconds=900,*,clock=time.time,sleep=time.sleep,collect=None,checkpoint=None,publish=publish_small):
    import research_runtime
    collect=collect or research_runtime.collect_quotes
    checkpoint=checkpoint or research_runtime.checkpoint
    for target in due_targets(cycle_started,cycle_seconds,clock()):
        if Path('.engine-paused').exists():return
        at=datetime.fromtimestamp(target,timezone.utc)
        if not cal.is_live(at):break
        sleep(max(0,target-clock()))
        if Path('.engine-paused').exists():return
        if not cal.is_live(datetime.fromtimestamp(clock(),timezone.utc)):break
        # A slow prior request can overrun a slot. Never issue a burst of
        # retroactive polls or label a current response as the missed slot.
        if clock()-target>60:continue
        capture=collect(scheduled_at=at.isoformat())
        if capture.get('paused'):return
        checkpoint()
        publish()
        print('Point observation capture:',capture.get('checked_at'),'available',capture.get('available'),
              'of',capture.get('requested'),'NOT interval OHLCV',flush=True)
    deadline=int(cycle_started)+int(cycle_seconds)
    if cal.is_live(datetime.fromtimestamp(clock(),timezone.utc)):
        sleep(max(0,deadline-clock()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cycle-start',required=True,type=int)
    p.add_argument('--cycle-minutes',default=15,type=int);args=p.parse_args()
    if not 5<=args.cycle_minutes<=30:raise SystemExit('Cycle must be 5..30 minutes')
    run(args.cycle_start,args.cycle_minutes*60)
