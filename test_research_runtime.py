import copy
import os
from datetime import timedelta
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import research_runtime as r
from test_research_contract import NOW,fixture,technical,quote

class RuntimeResearchTests(unittest.TestCase):
    def test_snapshot_coldstart_duplicates_resets_and_observed_window(self):
        q=quote();q.update(prior_close=98.,change_pct=2.)
        self.assertIn('Warming',r.observe(q,[],NOW)['state'])
        prev=[]
        for minutes,price,vol in [(35,98.,10000),(20,99.,20000)]:
            prev.append({**q,'source_as_of':(NOW-timedelta(minutes=minutes)).isoformat(),'price':price,'day_volume':vol})
        out=r.observe(q,prev,NOW);self.assertTrue(out['qualifies']);self.assertEqual(out['window_minutes'],15)
        self.assertEqual(out['window_volume'],280000)
        q['day_volume']=1;self.assertIn('reset',r.observe(q,prev,NOW)['state'])
    def test_intermediate_counter_reset_invalidates_whole_watch_window(self):
        q=quote();q.update(prior_close=98.,change_pct=2.,day_volume=120000)
        previous=[]
        for minutes,price,volume in [(35,98.,20000),(20,99.,100000),(15,99.2,1000),(10,99.5,90000)]:
            previous.append({**q,'source_as_of':(NOW-timedelta(minutes=minutes)).isoformat(),'price':price,'day_volume':volume})
        out=r.observe(q,previous,NOW)
        self.assertFalse(out['qualifies']);self.assertIn('reset inside',out['state'])

    def test_five_minute_sampling_preserves_actual_fifteen_minute_watch(self):
        q=quote();q.update(prior_close=98.,change_pct=2.,day_volume=310000)
        previous=[{**q,'source_as_of':(NOW-timedelta(minutes=m)).isoformat(),'price':98+(35-m)/30,'day_volume':10000+(35-m)*10000} for m in (35,30,25,20,15,10)]
        out=r.observe(q,previous,NOW);self.assertTrue(out['qualifies']);self.assertEqual(out['window_minutes'],15)

    def test_stale_friday_lunch_and_future_never_qualify(self):
        q=quote();q['source_as_of']=(NOW-timedelta(minutes=25)).isoformat();self.assertFalse(r.observe(q,[],NOW)['qualifies'])
        q['source_as_of']=(NOW+timedelta(minutes=1)).isoformat();self.assertFalse(r.observe(q,[],NOW)['qualifies'])
    def test_checkpoint_idempotent_and_never_claims_execution(self):
        class Response:
            def raise_for_status(self):pass
            def json(self):return fixture()
        import os
        prior=Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder);r.write('dashboard_snapshot.json',{'rows':[technical()]});r.write('research_quotes.json',{'prices':[quote()]})
                with patch('requests.get',return_value=Response()):
                    a=r.checkpoint(NOW);b=r.checkpoint(NOW)
                self.assertEqual(a['id'],b['id']);self.assertEqual(len(list(Path('research_decisions').rglob('*.json'))),1)
                data=r.read(a['checkpoint']);self.assertEqual(len(data['decisions']),15)
                self.assertTrue(all(x['execution_status']=='not_entered' and x['outcome']=='pending_execution_evidence' for x in data['decisions']))
                self.assertEqual(data['context_sha256'],r.digest(fixture()))
            finally:os.chdir(prior)

class CombinedCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.root=tempfile.TemporaryDirectory()
        self.prior=Path.cwd()
        os.chdir(self.root.name)
        self.addCleanup(self.root.cleanup)
        self.addCleanup(os.chdir,self.prior)
        self.snapshot={'rows':[technical()]}
        self.quotes={'checked_at':NOW.isoformat(),'prices':[quote()]}
        r.write('dashboard_snapshot.json',self.snapshot)
        r.write('research_quotes.json',self.quotes)

    def checkpoint(self,now=NOW,context=None):
        class Response:
            def raise_for_status(self):pass
            def json(self):return fixture() if context is None else context
        with patch('requests.get',return_value=Response()):
            return r.checkpoint(now)

    def test_evaluate_once_and_freeze_exact_primary_and_original_inputs(self):
        import research_signals
        old=Path('research_decisions/2026-10-01/legacy.json')
        old.parent.mkdir(parents=True)
        legacy=b'{"version":"combined-research-v1","decisions":[{"symbol":"PRL","plan":{"reference_entry":91}}]}\n'
        old.write_bytes(legacy)
        snapshot_bytes=Path('dashboard_snapshot.json').read_bytes()
        with patch.object(research_signals,'evaluate',wraps=research_signals.evaluate) as evaluate:
            status=self.checkpoint()
        evaluate.assert_called_once_with(fixture(),self.snapshot,self.quotes,now=NOW)
        record=r.read(status['checkpoint']);artifact=r.read('research_signals.json')
        self.assertEqual(record['version'],'combined-research-v1')
        self.assertEqual(record['signal_version'],research_signals.VERSION)
        self.assertEqual(record['technical_snapshot'],self.snapshot)
        self.assertEqual(record['quote_snapshot'],self.quotes)
        self.assertEqual(record['research'],fixture())
        self.assertEqual(Path('dashboard_snapshot.json').read_bytes(),snapshot_bytes)
        self.assertEqual(old.read_bytes(),legacy)
        self.assertNotIn('desk',record['combined_signals'])
        self.assertNotIn('desk',artifact)
        for key,value in record['combined_signals'].items():self.assertEqual(artifact[key],value)
        for key in ('context_sha256','technical_sha256','quotes_sha256'):
            self.assertEqual(artifact[key],record[key])
            self.assertEqual(record['combined_signals']['source_hashes'][key],record[key])
        self.assertEqual(artifact['checkpoint_id'],status['id'])
        self.assertEqual(artifact['checkpoint'],status['checkpoint'])
        self.assertEqual(status['signal_counts'],record['combined_signals']['counts'])
        self.assertEqual(status['signal_counts']['Ready for review'],1)
        self.assertEqual(record['decisions'][0]['status'],'Ready for review')
        self.assertEqual(record['decisions'][0]['plan'],record['combined_signals']['signals'][0]['plan'])
        rid=record.pop('id');self.assertEqual(r.digest(record),rid)

    def test_watching_with_reference_levels_withholds_primary_plan(self):
        self.quotes['prices'][0]['price']=104
        r.write('research_quotes.json',self.quotes)
        status=self.checkpoint();record=r.read(status['checkpoint'])
        decision=record['decisions'][0]
        self.assertEqual(decision['status'],'Watching')
        self.assertIsNone(decision['plan'])
        self.assertEqual(decision['activation'],'watch_or_blocked')
        self.assertIsNone(record['combined_signals']['signals'][0]['plan'])
        self.assertEqual(record['technical_snapshot']['rows'][0]['stop_loss'],95)
        self.assertEqual(status['paper_candidate_count'],0)

    def test_missing_quote_and_context_failure_never_publish_ready(self):
        r.write('research_quotes.json',{})
        first=self.checkpoint()
        self.assertEqual(first['signal_counts']['Ready for review'],0)
        self.assertTrue(all(s['plan'] is None for s in r.read('research_signals.json')['signals']))
        with patch('requests.get',side_effect=OSError('research source unavailable')):
            second=r.checkpoint(NOW+timedelta(minutes=1))
        record=r.read(second['checkpoint'])
        self.assertEqual(second['signal_counts']['Ready for review'],0)
        self.assertFalse(second['research_current'])
        self.assertIn('OSError',record['context_error'])
        self.assertIsNone(record['research'])
        self.assertTrue(all(s['plan'] is None for s in record['decisions']))

    def test_malformed_quote_envelope_is_recorded_as_blocked_input(self):
        r.write('research_quotes.json',[quote()])
        status=self.checkpoint()
        record=r.read(status['checkpoint'])
        self.assertIsNone(status['quotes_as_of'])
        self.assertEqual(status['signal_counts']['Ready for review'],0)
        self.assertEqual(record['quote_snapshot'],[quote()])
        self.assertTrue(record['combined_signals']['errors'])

    def test_immutable_checkpoint_bytes_and_attribution_stay_deterministic(self):
        first=self.checkpoint();path=Path(first['checkpoint']);original=path.read_bytes()
        with patch.object(r,'write',wraps=r.write) as write:
            second=self.checkpoint()
        self.assertEqual(first,second)
        self.assertEqual(path.read_bytes(),original)
        self.assertFalse(any(Path(call.args[0])==path for call in write.call_args_list))
        self.assertEqual(len(list(Path('research_decisions').rglob('*.json'))),1)

    def test_artifact_failure_keeps_previous_manifest_and_retry_reuses_journal(self):
        r.write('research_status.json',{'id':'prior'})
        r.write('research_signals.json',{'checkpoint_id':'prior'})
        real=r.write
        def fail_artifact(path,value):
            if str(path)=='research_signals.json':raise OSError('simulated artifact publication failure')
            return real(path,value)
        with patch.object(r,'write',side_effect=fail_artifact):
            with self.assertRaisesRegex(OSError,'artifact publication'):self.checkpoint()
        self.assertEqual(r.read('research_status.json'),{'id':'prior'})
        self.assertEqual(r.read('research_signals.json'),{'checkpoint_id':'prior'})
        journals=list(Path('research_decisions').rglob('*.json'))
        self.assertEqual(len(journals),1)
        original=journals[0].read_bytes()
        status=self.checkpoint()
        self.assertEqual(journals[0].read_bytes(),original)
        self.assertEqual(len(list(Path('research_decisions').rglob('*.json'))),1)
        self.assertEqual(r.read('research_signals.json')['checkpoint_id'],status['id'])

    def test_evaluation_failure_does_not_advance_publications(self):
        r.write('research_status.json',{'id':'prior'})
        r.write('research_signals.json',{'checkpoint_id':'prior'})
        with patch('research_signals.evaluate',side_effect=ValueError('invalid canonical evaluation')):
            with self.assertRaisesRegex(ValueError,'canonical evaluation'):self.checkpoint()
        self.assertEqual(r.read('research_status.json'),{'id':'prior'})
        self.assertEqual(r.read('research_signals.json'),{'checkpoint_id':'prior'})
        self.assertFalse(Path('research_decisions').exists())

    def test_compact_artifact_is_in_all_runtime_publication_lists(self):
        import research_sampler
        self.assertIn('research_signals.json',research_sampler.FILES)
        for name in ('engine','evening','recovery-last-close','sync-runtime'):
            self.assertIn('research_signals.json',(self.prior/'.github/workflows'/f'{name}.yml').read_text())


if __name__=='__main__':unittest.main()
