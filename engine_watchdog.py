"""Start a missing session worker; never cancel an active worker or trade."""
import os
from datetime import datetime, timedelta, timezone
import requests
import session_calendar


def should_start(runs, now):
    if session_calendar.worker_state(now) == 'closed':
        return False
    if session_calendar.local_now(now).hour < 8:
        return False
    if any(r['status'] in ('queued', 'in_progress', 'waiting', 'requested', 'pending') for r in runs):
        return False
    # Bound repeated failures instead of spending runner minutes indefinitely.
    recent = [r for r in runs if datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')) > now - timedelta(hours=1)]
    return len(recent) < 3


def main():
    now = datetime.now(timezone.utc)
    repo = os.environ['GITHUB_REPOSITORY']
    api = f'https://api.github.com/repos/{repo}/actions/workflows/engine.yml'
    headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'}
    response = requests.get(api + '/runs', headers=headers, params={'branch': 'main', 'per_page': 30}, timeout=30)
    response.raise_for_status()
    if should_start(response.json()['workflow_runs'], now):
        response = requests.post(api + '/dispatches', headers=headers,
                                 json={'ref': 'main', 'inputs': {'force_now': False}}, timeout=30)
        response.raise_for_status()
        print('Missing worker: requested session loop on latest main')
    else:
        print('No restart: outside hours, worker already active/queued, or retry limit reached')


if __name__ == '__main__':
    main()
