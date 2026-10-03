import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import intraday_capture as c
import research_sampler as sampler

NOW=datetime(2026,10,5,5,0,tzinfo=timezone.utc)

def quote(at=NOW,price=100,volume=1000,symbol='PRL'):
    return {'symbol':symbol,'market':'REG','source_url':'https://dps.psx.com.pk/company/'+symbol,
            'source_as_of':at.isoformat(),'fetched_at':(at+timedelta(minutes=5)).isoformat(),
            'price':price,'day_volume':volume,'volume_kind':'cumulative_session','open':99,'high':101,'low':98}

def capture(at,q):return {'checked_at':at.isoformat(),'prices':[q],'errors':[],'failed':[]}

class ObservationTests(unittest.TestCase):
    def test_real_source_delta_not_ohlcv(self):
        first=c.audit(quote(),None,NOW+timedelta(minutes=5))
        first['observation_id']='first'
        second=c.audit(quote(NOW+timedelta(minutes=5),101,1800),first,NOW+timedelta(minutes=10))
        self.assertTrue(second['usable_point']);self.assertEqual(second['observed_volume_delta'],800)
        self.assertEqual(second['volume_interval_seconds'],300);self.assertFalse(second['ohlcv_bar'])
        self.assertEqual(second['previous_observation_id'],'first')
    def test_duplicate_conflict_regression_reset_and_gap(self):
        previous=c.audit(quote(),None,NOW+timedelta(minutes=5))
        for q,flag in [(quote(),'duplicate_source_timestamp'),(quote(price=102),'conflicting_source_timestamp'),
                       (quote(NOW-timedelta(minutes=1)),'non_monotonic_source_timestamp'),
                       (quote(NOW+timedelta(minutes=5),volume=1),'cumulative_volume_reset'),
                       (quote(NOW+timedelta(minutes=15),volume=2000),'source_gap_volume_interval_withheld')]:
            r=c.audit(q,previous,max(NOW+timedelta(minutes=10),datetime.fromisoformat(q['fetched_at'])));self.assertIn(flag,r['quality_flags']);self.assertIsNone(r['observed_volume_delta'])
    def test_no_delta_across_overnight_or_friday_break(self):
        before=datetime(2026,10,9,6,55,tzinfo=timezone.utc)
        previous=c.audit(quote(before),None,before+timedelta(minutes=4))
        after=datetime(2026,10,9,9,35,tzinfo=timezone.utc)
        r=c.audit(quote(after,volume=2000),previous,after+timedelta(minutes=5))
        self.assertIn('trading_segment_boundary',r['quality_flags']);self.assertIsNone(r['observed_volume_delta'])
        monday=datetime(2026,10,12,5,0,tzinfo=timezone.utc)
        r=c.audit(quote(monday,volume=500),previous,monday+timedelta(minutes=5))
        self.assertIn('new_session_volume_counter',r['quality_flags']);self.assertIsNone(r['observed_volume_delta'])
    def test_preopen_closed_future_stale_fail_closed(self):
        for at,now,flag in [(NOW.replace(hour=4,minute=30),NOW.replace(hour=4,minute=35),'source_preopen_break_or_after_close'),
                            (NOW,NOW+timedelta(minutes=26),'stale_source')]:
            r=c.audit(quote(at),None,now);self.assertFalse(r['usable_point']);self.assertIn(flag,r['quality_flags'])
        q=quote();q['source_as_of']=(NOW+timedelta(minutes=6)).isoformat()
        self.assertIn('future_timestamp',c.audit(q,None,NOW+timedelta(minutes=5))['quality_flags'])
    def test_irregular_interval_keeps_actual_span_and_is_not_bar(self):
        p=c.audit(quote(),None,NOW+timedelta(minutes=5));r=c.audit(quote(NOW+timedelta(minutes=7),volume=2500),p,NOW+timedelta(minutes=12))
        self.assertEqual(r['volume_interval_seconds'],420);self.assertEqual(r['observed_volume_delta'],1500)
        self.assertIn('irregular_source_interval_not_five_minutes',r['quality_flags'])
    def test_record_idempotent_immutable_and_out_of_order_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            kw={'state_path':Path(tmp)/'state.json','status_path':Path(tmp)/'status.json','root':Path(tmp)/'samples'}
            cap=capture(NOW+timedelta(minutes=5),quote())
            a=c.record(cap,**kw);b=c.record(cap,**kw);self.assertEqual(a,b)
            self.assertEqual(len(list(kw['root'].rglob('*.json'))),1)
            self.assertEqual(json.loads(kw['state_path'].read_text())['sessions']['2026-10-05']['captures'],1)
            c.record(capture(NOW+timedelta(minutes=10),quote(NOW+timedelta(minutes=5),volume=2000)),**kw)
            with self.assertRaises(ValueError):c.record(capture(NOW+timedelta(minutes=6),quote()),**kw)
    def test_each_interrupted_write_recovers_exactly_once(self):
        for fail_number in (2,3,4):
            with tempfile.TemporaryDirectory() as tmp:
                kw={'state_path':Path(tmp)/'state.json','status_path':Path(tmp)/'status.json','root':Path(tmp)/'samples'}
                cap=capture(NOW+timedelta(minutes=5),quote());real=c._write;count=[0]
                def failing(path,data):
                    count[0]+=1
                    if count[0]==fail_number:raise OSError('simulated crash')
                    return real(path,data)
                with patch.object(c,'_write',side_effect=failing):
                    with self.assertRaises(OSError):c.record(cap,**kw)
                doc=c.record(cap,**kw)
                self.assertTrue(kw['state_path'].exists());self.assertTrue(kw['status_path'].exists())
                state=json.loads(kw['state_path'].read_text());self.assertEqual(state['sessions']['2026-10-05']['captures'],1)
                self.assertEqual(state['last_capture_id'],doc['capture_id'])
                self.assertFalse(kw['state_path'].with_suffix('.pending.json').exists())
                self.assertEqual(len(list(kw['root'].rglob('*.json'))),1)

    def test_malformed_state_refuses_network_and_silent_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'state.json';state.write_text('{broken')
            with self.assertRaises(RuntimeError):c.collect(now=NOW,state_path=state,fetcher=lambda _:self.fail('network called'))
            self.assertEqual(state.read_text(),'{broken')

    def test_paused_collection_does_not_request_or_overwrite_data(self):
        with patch.object(c.Path,'exists',return_value=True),patch.object(c,'recover'):
            result=c.collect(now=NOW,fetcher=lambda _:self.fail('network called'))
            self.assertTrue(result['paused'])

    def test_backoff_refusals_skip_without_new_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            kw={'state_path':Path(tmp)/'state.json','status_path':Path(tmp)/'status.json','root':Path(tmp)/'samples'}
            calls=[]
            def denied(symbol):calls.append(symbol);raise HTTPError('https://dps.psx.com.pk/company/'+symbol,403,'Forbidden',{},None)
            first=c.collect(now=NOW,fetcher=denied,**kw);self.assertEqual(len(calls),15)
            second=c.collect(now=NOW+timedelta(minutes=5),fetcher=denied,**kw)
            self.assertEqual(len(calls),15);self.assertEqual(len(second['skipped']),15)
            self.assertEqual(first['network_state']['PRL']['next_retry_at'],(NOW+timedelta(hours=1)).isoformat())
    def test_expected_poll_windows_and_misses_are_explicit(self):
        self.assertEqual(len(c.poll_slots(datetime(2026,10,5,4,43,tzinfo=timezone.utc),60)),3)
        self.assertEqual(c.poll_slots(datetime(2026,10,4,5,tzinfo=timezone.utc)),set())
        with tempfile.TemporaryDirectory() as tmp:
            kw={'state_path':Path(tmp)/'s.json','status_path':Path(tmp)/'v.json','root':Path(tmp)/'r'}
            c.record(capture(NOW+timedelta(minutes=5),quote()),**kw)
            status=json.loads(kw['status_path'].read_text());self.assertGreater(status['missed_poll_windows'],0)
            self.assertIn('partial',status['coverage'])

class SamplerTests(unittest.TestCase):
    def test_due_targets_never_backfill_overruns(self):
        self.assertEqual(sampler.due_targets(1000,900,1200),[1300,1600])
        self.assertEqual(sampler.due_targets(1000,900,1450),[1600])
        self.assertEqual(sampler.due_targets(1000,900,1800),[])
    def test_same_writer_two_polls_then_analysis_deadline(self):
        start=NOW.timestamp();clock=[start+60];calls=[];published=[]
        def sleep(seconds):clock[0]+=seconds
        def collect(**kw):calls.append(kw['scheduled_at']);return {'checked_at':clock[0],'available':15,'requested':15}
        sampler.run(start,clock=lambda:clock[0],sleep=sleep,collect=collect,checkpoint=lambda:None,publish=lambda:published.append(1))
        self.assertEqual(len(calls),2);self.assertEqual(len(published),2);self.assertEqual(clock[0],start+900)
    def test_no_requests_during_friday_break_or_after_close(self):
        start=datetime(2026,10,9,6,57,tzinfo=timezone.utc).timestamp();calls=[]
        sampler.run(start,clock=lambda:start+60,sleep=lambda s:None,collect=lambda **kw:calls.append(kw),checkpoint=lambda:None,publish=lambda:None)
        self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
