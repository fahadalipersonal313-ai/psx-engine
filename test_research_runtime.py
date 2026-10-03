import copy
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

if __name__=='__main__':unittest.main()
