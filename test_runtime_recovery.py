import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import engine_watchdog
import intraday_momentum as live
import runtime_publish


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 14, 5, tzinfo=timezone.utc)
        dates = []
        day = self.now.date() - timedelta(days=1)
        while len(dates) < 20:
            if day.weekday() < 5:
                dates.append(day.isoformat())
            day -= timedelta(days=1)
        self.history = [{'date': d, 'open': 100, 'high': 101, 'low': 99,
                         'close': 100, 'volume': 100000, 'source': 'PSX historical'}
                        for d in sorted(dates)]
        self.ticks = [[self.now.timestamp() - 10, 103, 150000]]

    def test_live_requires_current_fresh_verified_data(self):
        with patch.object(live.shariah_checker, 'check', return_value={'eligible_for_ranking': True}):
            self.assertIsNotNone(live.detect('PSO', self.ticks, self.history, self.now))
            for offset in (1800, 86400):
                self.assertIsNone(live.detect('PSO', [[self.now.timestamp()-offset, 103, 150000]], self.history, self.now))
            with self.assertRaises(ValueError):
                live.detect('PSO', [[self.now.timestamp()+1, 103, 150000]], self.history, self.now)
            bad = copy.deepcopy(self.history)
            bad[-1]['source'] = 'intraday'
            self.assertIsNone(live.detect('PSO', self.ticks, bad, self.now))
            self.assertIsNone(live.detect('PSO', self.ticks, self.history[:-1], self.now))
            self.assertIsNone(live.detect('PSO', [[self.now.timestamp()-10, 103, 120000]], self.history, self.now))
        with patch.object(live.shariah_checker, 'check', return_value={'eligible_for_ranking': False}):
            self.assertIsNone(live.detect('PSO', self.ticks, self.history, self.now))

    def test_watchdog_avoids_duplicate_and_unbounded_restarts(self):
        self.assertTrue(engine_watchdog.should_start([], self.now))
        self.assertFalse(engine_watchdog.should_start([{'status': 'in_progress'}], self.now))
        failed = {'status': 'completed', 'created_at': self.now.isoformat()}
        self.assertFalse(engine_watchdog.should_start([failed]*3, self.now))
        self.assertFalse(engine_watchdog.should_start([], self.now.replace(day=13)))

    def test_news_merge_preserves_both_writers_and_newest_duplicate(self):
        a = {'fetched_at': '2026-09-14T05:00:00+00:00', 'cutoff': '2026-09-13T05:00:00+00:00',
             'items': [{'url': 'a', 'symbol': 'PSO', 'published': '2026-09-14T04:00:00+00:00', 'title': 'old'}]}
        b = copy.deepcopy(a)
        b['fetched_at'] = '2026-09-14T05:01:00+00:00'
        b['items'] = [{'url': 'b', 'published': '2026-09-14T04:01:00+00:00'}]
        self.assertEqual(runtime_publish.merge_news(a,b)['count'], 2)
        b['items'].append({**a['items'][0], 'title': 'new'})
        merged = runtime_publish.merge_news(a,b)
        self.assertEqual(next(x for x in merged['items'] if x['url']=='a')['title'], 'new')

    def test_real_git_news_race_and_database_conflict(self):
        def run(cwd, *args):
            result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote, a, b = [root/x for x in ('remote', 'a', 'b')]
            run(root, 'init', '--bare', str(remote))
            run(root, 'clone', str(remote), str(a))
            for path in (a,):
                run(path, 'config', 'user.email', 'test@example.invalid')
                run(path, 'config', 'user.name', 'test')
            run(a, 'checkout', '-b', 'main')
            base = {'fetched_at': '2026-09-14T05:00:00+00:00', 'cutoff': '2026-09-13T05:00:00+00:00', 'items': []}
            (a/'news_raw_24h.json').write_text(json.dumps(base))
            (a/'psx_engine.db').write_bytes(b'\0baseline')
            run(a, 'add', '.')
            run(a, 'commit', '-m', 'base')
            run(a, 'push', '-u', 'origin', 'main')
            run(root, 'clone', '-b', 'main', str(remote), str(b))
            run(b, 'config', 'user.email', 'test@example.invalid')
            run(b, 'config', 'user.name', 'test')
            for path, url in ((a,'a'), (b,'b')):
                data = {**base, 'items': [{'url': url, 'published': '2026-09-14T04:00:00+00:00'}]}
                (path/'news_raw_24h.json').write_text(json.dumps(data))
                run(path, 'add', '.')
                run(path, 'commit', '-m', url)
            run(b, 'push')
            original = Path.cwd()
            try:
                os.chdir(a)
                with patch.object(runtime_publish.time, 'sleep'):
                    runtime_publish.publish()
                self.assertEqual(json.loads((a/'news_raw_24h.json').read_text())['count'], 2)
                run(b, 'pull', '--rebase')
                for path in (a,b):
                    (path/'psx_engine.db').write_bytes(b'\0' + path.name.encode())
                    run(path,'add','.')
                    run(path,'commit','-m','db update')
                run(b,'push')
                with self.assertRaises(RuntimeError):
                    runtime_publish.publish()
                self.assertEqual((a/'psx_engine.db').read_bytes(), b'\0a')
            finally:
                os.chdir(original)
