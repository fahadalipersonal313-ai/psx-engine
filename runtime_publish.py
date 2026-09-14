"""Publish runtime commits with plain rebase; merge only raw headline snapshots.

Database, ratings and code conflicts remain hard failures. Never pick a Git side.
"""
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path


def merge_news(a, b):
    def stamp(value):
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('News timestamp needs timezone')
        return result
    older, newer = sorted((a, b), key=lambda x: stamp(x['fetched_at']))
    cutoff = stamp(newer['cutoff'])
    items = {}
    for data in (older, newer):
        for item in data['items']:
            if stamp(item['published']) >= cutoff:
                items[(item['url'], item.get('symbol'))] = item
    result = dict(newer)
    result['items'] = sorted(items.values(), key=lambda x: (x['published'], x['url']), reverse=True)
    result['count'] = len(result['items'])
    return result


def git(*args, capture=False):
    return subprocess.run(['git', *args], text=True, encoding='utf-8',
                          stdout=subprocess.PIPE if capture else None,
                          env={**os.environ, 'GIT_EDITOR': 'true'})


def publish(branch='main'):
    for attempt in range(4):
        if git('push', 'origin', f'HEAD:{branch}').returncode == 0:
            return
        pulled = git('pull', '--rebase', '--autostash', 'origin', branch)
        if pulled.returncode:
            conflicts = git('diff', '--name-only', '--diff-filter=U', capture=True).stdout.splitlines()
            if conflicts != ['news_raw_24h.json']:
                git('rebase', '--abort')
                raise RuntimeError(f'Publication conflict requires review: {conflicts}')
            try:
                sides = [json.loads(git('show', f':{n}:news_raw_24h.json', capture=True).stdout) for n in (2, 3)]
                Path('news_raw_24h.json').write_text(json.dumps(merge_news(*sides), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                if git('add', 'news_raw_24h.json').returncode or git('rebase', '--continue').returncode:
                    raise RuntimeError('Rebase did not finish')
            except Exception:
                git('rebase', '--abort')
                raise
        if git('diff', '--name-only', '--diff-filter=U', capture=True).stdout.strip():
            raise RuntimeError('Unresolved changes after restoring local database; refusing push')
        time.sleep(attempt + 1)
    raise RuntimeError('Publication failed after four attempts')


if __name__ == '__main__':
    publish()
