"""Produce an auditable comparison with the untouched supplied baseline."""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from short_horizon import ROOT
from short_horizon_refresh import baseline, csv_report


def main():
    report = json.loads((ROOT / 'short_horizon_latest.json').read_text(encoding='utf-8'))
    current = {r['symbol']: r for r in report['all_eligible']}
    excluded = {r['symbol']: '; '.join(r['reasons']) for r in report['excluded']}
    lines = ['# September 18 baseline versus revised research', '',
             f"Review: {report['as_of']}. Completed price session: {report['market_session']}.",
             f"Input SHA-256: `{report['input_sha256']}`.", '',
             'Scores use different methods and are not performance improvements or probabilities.',
             'New ranks are across the complete eligible universe, not just the previous 50.', '',
             f"Eligible: {report['eligible_count']}; shown: {len(report['rows'])}.",
             'Shown classifications: ' + str(dict(collections.Counter(r['classification'] for r in report['rows']))) + '.', '',
             '|Stock|Old rank|New rank|Old points /110|New points /100|Old status|New status|',
             '|---|---:|---:|---:|---:|---|---|']
    for old in baseline():
        new = current.get(old['ticker'], {})
        lines.append(f"|{old['ticker']}|{old['rank']}|{new.get('rank', 'Excluded')}|{old['finalScore']}|{new.get('score', '—')}|{old['status']}|{new.get('classification', excluded.get(old['ticker'], 'Not in refreshed universe'))}|")
    lines += ['', '## Blocked data', '']
    lines += [f"- {r['symbol']}: {'; '.join(r['reasons'])}" for r in report['all_eligible'] if r['score'] is None]
    lines += ['', '## Evidence limits', '',
              'The official screener and whole-market daily history were refreshed. Annual/TTM figures remain labelled historical context. No full primary announcement verification was completed in this integration; existing news reviews are shown with dates and quality but do not certify a direct catalyst. No stock currently clears every candidate check.',
              'MFL and NETSOL require confirmation under the new rules; the higher/lower point totals do not indicate better expected returns.',
              'Four blocked names remain in all_eligible with explicit reasons. Low-liquidity rows are sorted after usable research rows, not promoted to fill the list.']
    (ROOT / 'docs/SHORT_HORIZON_COMPARISON.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (ROOT / 'analysis/short_horizon_sample.csv').write_text(csv_report(report), encoding='utf-8-sig')


if __name__ == '__main__':
    main()
