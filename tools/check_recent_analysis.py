"""Check all stocks and save current analysis from stored official prices only."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import database as db
import pandas as pd
import swing_evaluation


def run(path, output):
    config.DB_PATH = path
    import main
    import upward_candidates
    benchmark = pd.DataFrame(db.get_eod_history(config.BENCHMARK_INDEX, 100000))
    cutoff = benchmark.iloc[-1]['date']
    account = main.portfolio_advisor.load_portfolio()
    with db.analysis_batch(len(config.STOCKS)) as batch:
        results = [main.analyze_stock(s, [], benchmark, cutoff=cutoff, batch_id=batch)
                   for s in config.STOCKS]
        main._assess_account(results, account, batch)
    study = swing_evaluation.backtest_portfolio()
    summary = {'version': config.STRATEGY_VERSION, 'session': cutoff,
        'stocks': len(config.STOCKS),
        'current_signals': dict(Counter(r['signal']['signal'] for r in results)),
        'upward_stocks': upward_candidates.current(), 'past_results': study['metrics'],
        'coverage': [{'symbol': r['symbol'], **r['coverage'], 'reasons': r['vetoes'],
                      'buy_signals': r['metrics']['opportunities']} for r in study['results']],
        'pso': next(r for r in study['results'] if r['symbol'] == 'PSO')}
    Path(output).write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('coverage','pso')}, indent=2), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    run(args.database, args.output)
