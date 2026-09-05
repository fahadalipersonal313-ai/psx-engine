"""Predeclared experiments and chronological splits, without performance claims."""
import json
from pathlib import Path
from decision_engine import canonical, digest


def register(path, specification):
    """Create once, before examining the designated evaluation data."""
    required = ('name','dataset_hash','strategy_version','config','train_end','validation_end','holdout_start','variants','primary_metric')
    if any(key not in specification for key in required):
        raise ValueError('Incomplete experiment specification')
    if not specification['train_end'] < specification['validation_end'] < specification['holdout_start']:
        raise ValueError('Experiment dates must be strictly chronological')
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = dict(specification, experiment_hash=digest(specification))
    with target.open('x', encoding='utf-8') as out:
        out.write(canonical(record))
    return record


def matured_training(rows, evaluation_start, embargo_sessions, sessions):
    """Purge every unresolved outcome and every outcome crossing the boundary."""
    if embargo_sessions < 0:
        raise ValueError('Negative embargo')
    earlier = sorted(set(s for s in sessions if s < evaluation_start))
    if len(earlier) <= embargo_sessions:
        return []
    boundary = earlier[-1-embargo_sessions]
    return [row for row in rows if row.get('exit_date') and row['exit_date'] <= boundary
            and row.get('entry_date') and row['entry_date'] <= row['exit_date']
            and row.get('status') in ('target','stop','expired')]


def calibration_report(predictions, trained_through):
    """Evaluate frozen earlier-trained probabilities; never train on test rows."""
    from data_quality import finite
    if any(not p.get('decision_session') or p['decision_session'] <= trained_through for p in predictions):
        raise ValueError('Predictions overlap training period')
    if any(not finite(p.get('probability')) or not 0 <= p['probability'] <= 1 or p.get('target_hit') not in (True,False) for p in predictions):
        raise ValueError('Invalid calibration inputs')
    n=len(predictions)
    return {'n':n, 'brier_score':sum((p['probability']-int(p['target_hit']))**2 for p in predictions)/n if n else None,
            'note':'Evaluation only; independent outcome sample size and temporal separation still require review.'}
