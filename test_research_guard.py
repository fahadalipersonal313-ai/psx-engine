from datetime import datetime,timezone
from unittest.mock import patch,MagicMock
import unittest
import research_guard as g
import research_calendar as calendar
import session_calendar as cal

class ResearchGuardTests(unittest.TestCase):
    def check(self,missing=False,action=None):
        dates=calendar.expected('2026-10-02')
        if missing:dates.pop(-3)
        connection=MagicMock();connection.__enter__.return_value.execute.return_value=[(d,) for d in reversed(dates)]
        with patch.object(g.db,'get_daily_ohlc',return_value=[{'date':d} for d in dates]),patch.object(g.db,'get_eod_history',return_value=[{'date':d} for d in dates]),patch.object(g.db,'conn',return_value=connection),patch.object(g.db,'get_corporate_actions',return_value=[action] if action else []):
            return g.check({'symbol':'PRL','decision_session':'2026-10-02'},datetime(2026,10,3,18,tzinfo=timezone.utc))
    def test_valid_and_joint_missing_session(self):
        self.assertTrue(self.check()['valid']);result=self.check(missing=True);self.assertFalse(result['valid']);self.assertTrue(any('independent' in x for x in result['checks']))
    def test_unresolved_action_below_discontinuity_threshold_blocks(self):
        action={'kind':'bonus','ex_date':'2026-09-30','known_at':'2026-09-20','source':'notice','factor':None,'volume_factor':None,'verified':False}
        self.assertFalse(self.check(action=action)['valid'])
    def test_actual_closure_and_manifest_limit(self):
        dates=calendar.expected('2026-10-02');self.assertNotIn('2026-08-26',dates);self.assertIn('2026-08-25',dates)
        self.assertEqual(cal.intervals('2026-08-26'),[])
        with self.assertRaises(ValueError):calendar.expected('2027-01-04')
        with self.assertRaises(ValueError):calendar.expected('2026-08-03')

if __name__=='__main__':unittest.main()
