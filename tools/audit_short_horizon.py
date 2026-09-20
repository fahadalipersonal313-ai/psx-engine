"""Preserve supplied research byte-for-byte and audit its actual exported cells."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET


def preserve(source, destination):
    source, destination = Path(source), Path(destination)
    names = ['overview.json', 'technicals.json', 'performance.json', 'psx.json',
             'screen.mjs', 'screened.json', 'shortlist.json', 'company-details.json',
             'technical-details.json', 'notice-links.json', 'prepare.mjs',
             'final-data.json', 'build.mjs', 'workbook-inspection.ndjson']
    names += ['preview-' + x + '.png' for x in ('Watchlist', 'Technicals', 'Fundamentals', 'News', 'Method')]
    files = {f'work/{n}': source / 'work' / n for n in names}
    for ext in ('xlsx', 'csv'):
        name = f'Pakistan_Shariah_50_2026-09-20.{ext}'
        files['outputs/psx-50/' + name] = source / 'outputs/psx-50' / name
    missing = [str(p) for p in files.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError(str(missing))
    manifest = {'market_session': '2026-09-18', 'prepared_date': '2026-09-20',
                'retrieval_times': 'Not recorded in supplied raw captures; file timestamps are not publication times',
                'files': {n: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
                          for n, p in files.items()}}
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / 'original.zip'
    if target.exists():
        with zipfile.ZipFile(target) as z:
            if any(hashlib.sha256(z.read(n)).hexdigest() != v['sha256'] for n, v in manifest['files'].items()):
                raise ValueError('Historical baseline differs: refusing replacement')
    else:
        with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as z:
            for n, p in files.items():
                z.writestr(n, p.read_bytes())
    final = json.loads(files['work/final-data.json'].read_text())
    # Read every JSON artifact, not just the final list.
    manifest['record_counts'] = {n: len(json.loads(p.read_text())) for n, p in files.items() if n.endswith('.json')}
    workbook = next(p for p in files.values() if p.suffix == '.xlsx')
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(workbook) as z:
        manifest['sheets'] = [e.attrib['name'] for e in ET.fromstring(z.read('xl/workbook.xml')).findall('.//s:sheet', ns)]
        cells = [c for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')
                 for c in ET.fromstring(z.read(n)).findall('.//s:c', ns)]
        manifest['xlsx_cell_errors'] = [c.attrib for c in cells if c.get('t') == 'e']
        manifest['xlsx_formula_count'] = sum(c.find('s:f', ns) is not None for c in cells)
        manifest['xlsx_cells_read'] = len(cells)
    manifest['classifications'] = dict(collections.Counter(r['status'] for r in final))
    manifest['unique_tickers'] = len({r['ticker'] for r in final})
    manifest['range_failures'] = [r['ticker'] for r in final if not r['low'] <= r['price'] <= r['high']]
    manifest['period_conflicts'] = [r['ticker'] for r in final if r['fundamentalConflict']]
    manifest['weak_trend_candidates'] = [r['ticker'] for r in final if r['status'] == 'Momentum candidate' and r['adx'] < 20]
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source')
    p.add_argument('destination')
    a = p.parse_args()
    m = preserve(a.source, a.destination)
    print(json.dumps({k: v for k, v in m.items() if k != 'files'}, indent=2))
