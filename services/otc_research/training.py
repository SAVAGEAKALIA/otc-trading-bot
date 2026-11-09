"""Fixed, nonpromotable logistic/CatBoost comparison on received price proxies.

This module never calls a broker and cannot infer accepted contracts from quotes.
The pure admission/partition/policy layer uses only the Python standard library.
Third-party training imports are lazy so gate tests do not import ML libraries.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import time
from typing import Sequence

from contracts.otc_v1.training_schema import ASSETS, COLUMNS, FEATURES, MANIFEST_SCHEMA

LABELS = ('up', 'down', 'tie')
THRESHOLDS = (0.0, 0.03, 0.05)
MODEL_NAMES = ('logistic', 'catboost')
EVIDENCE_KINDS = {'received_price_proxy':'received_quote_observations',
                  'synthetic_training_eval':'synthetic_fixture'}
MINIMUM_ROWS = {'train': 300, 'early': 50, 'calibration': 50, 'policy': 100,
                'diagnostic_test': 100}
MINIMUM_POLICY_RESOLVED = 25
MAX_RECEIPT_AGE_MS = {'f_quote_age_ms': 5000, 'f_mood_age_ms': 60000,
                      'f_payout_age_ms': 600000}


def epoch_ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)


LIMITS = {
    'train': (0, epoch_ms('2026-08-10')),
    'early': (epoch_ms('2026-08-10'), epoch_ms('2026-08-12')),
    'calibration': (epoch_ms('2026-08-12'), epoch_ms('2026-08-14')),
    'policy': (epoch_ms('2026-08-14'), epoch_ms('2026-08-16')),
    'diagnostic_test': (epoch_ms('2026-08-16'), epoch_ms('2026-08-21')),
}


@dataclass(frozen=True, slots=True)
class Record:
    opportunity_id: str
    asset: str
    decision_ms: int
    expiry_ms: int
    status: str
    label: str
    payout: float | None
    features: tuple[float | None, ...]
    evidence_class: str


def sha256(path: Path) -> str:
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def partition(decision_ms: int) -> str:
    for name, (start, end) in LIMITS.items():
        if start <= decision_ms < end:
            return name
    raise ValueError('Decision is outside the fixed historical partitions')


def partition_purged(row: Record) -> bool:
    """Purge label intervals reaching the next partition, independent of asset."""
    return row.expiry_ms >= LIMITS[partition(row.decision_ms)][1]


def number(value: str, name: str, optional: bool = False) -> float | None:
    if value == '' and optional:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be numeric') from exc
    if not math.isfinite(result):
        raise ValueError(f'{name} must be finite; missing values must be blank')
    return result


def strict_json(text: str | bytes):
    def invalid_constant(value):
        raise ValueError(f'Nonfinite JSON constant {value} is forbidden')
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f'JSON numeric value overflows finite representation: {value}')
        return parsed
    return json.loads(text,parse_constant=invalid_constant,parse_float=finite_float)


def validate_manifest(manifest: dict) -> str:
    required = {'schema':MANIFEST_SCHEMA, 'expiry_basis':'hypothetical',
                'product_mapping':'explicit_assumed', 'clock':'receiver_utc',
                'feature_availability':'receiver_receipt_lte_decision',
                'outcome_basis':'last_received_quote_at_or_before_expiry'}
    allowed=set(required)|{'input_sha256','source_lineage','evidence_classes','metadata',
                           'promotable','horizon_seconds','assets'}
    if not isinstance(manifest,dict) or set(manifest)-allowed:
        raise ValueError('Unsupported dataset manifest fields')
    if any(manifest.get(key)!=value for key,value in required.items()):
        raise ValueError('Unsupported manifest schema, clock, product, expiry, availability or outcome declaration')
    if manifest.get('promotable',False) is not False or manifest.get('horizon_seconds',120)!=120:
        raise ValueError('Manifest contradicts nonpromotable 120-second research scope')
    if 'assets' in manifest and manifest['assets']!=list(ASSETS):
        raise ValueError('Manifest contradicts the registered asset order/universe')
    classes=manifest.get('evidence_classes')
    if not isinstance(classes,list) or len(classes)!=1 or classes[0] not in EVIDENCE_KINDS:
        raise ValueError('Manifest must declare one admitted evidence class; synthetic/received mixing is forbidden')
    lineage=manifest.get('source_lineage')
    if not isinstance(lineage,list) or not lineage:
        raise ValueError('Source lineage is required')
    for item in lineage:
        if not isinstance(item,dict) or set(item)!={'source_id','sha256','kind','clock'}:
            raise ValueError('Unsupported source lineage schema')
        if not isinstance(item['source_id'],str) or not item['source_id'].strip():
            raise ValueError('Source lineage identifier is required')
        digest=item['sha256']
        if not isinstance(digest,str) or len(digest)!=64 or any(char not in '0123456789abcdef' for char in digest):
            raise ValueError('Source lineage needs an exact lowercase SHA-256')
        if item['kind']!=EVIDENCE_KINDS[classes[0]] or item['clock']!='receiver_utc':
            raise ValueError('Source lineage contradicts received/synthetic evidence or receiver clock')
    if 'metadata' in manifest and not isinstance(manifest['metadata'],dict):
        raise ValueError('Manifest metadata must be an object')
    return classes[0]


def load_inputs(source: Path, manifest_path: Path) -> tuple[list[Record], dict]:
    if not manifest_path.is_file():
        raise ValueError('Dataset manifest is required')
    manifest = strict_json(manifest_path.read_text())
    evidence_class=validate_manifest(manifest)
    # Hash and parse the same immutable in-memory bytes, avoiding a hash/read race.
    source_bytes=source.read_bytes()
    if manifest.get('input_sha256') != hashlib.sha256(source_bytes).hexdigest():
        raise ValueError('Manifest input_sha256 does not match the exact CSV')
    rows = []; seen = set()
    with io.StringIO(source_bytes.decode('utf-8'),newline='') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) != len(COLUMNS) or set(reader.fieldnames) != set(COLUMNS):
            raise ValueError('CSV must contain exactly the canonical feature/metadata columns; unknown or future features are forbidden')
        for line, item in enumerate(reader, 2):
            if None in item or any(value is None for value in item.values()):
                raise ValueError(f'Malformed CSV row {line}')
            identifier = item['opportunity_id']
            if not identifier.strip() or identifier in seen:
                raise ValueError(f'Duplicate or empty opportunity_id at row {line}')
            seen.add(identifier)
            if item['asset'] not in ASSETS:
                raise ValueError(f'Asset outside the registered two-asset universe at row {line}')
            try:
                decision, expiry = int(item['decision_ms']), int(item['expiry_ms'])
            except ValueError as exc:
                raise ValueError(f'Noninteger timestamp at row {line}') from exc
            partition(decision)
            if expiry - decision != 120000:
                raise ValueError(f'Only the registered 120-second hypothetical horizon is allowed at row {line}')
            status, label = item['status'], item['label']
            if status not in {'resolved', 'unresolved', 'ineligible'}:
                raise ValueError(f'Unknown status at row {line}')
            if (status == 'resolved' and label not in LABELS) or (status != 'resolved' and label != ''):
                raise ValueError(f'Status/label contradiction at row {line}')
            payout = number(item['payout'], 'payout', optional=status == 'ineligible')
            if payout is not None and not 0 < payout <= 2:
                raise ValueError(f'Payout ratio must be in (0, 2] at row {line}')
            features = tuple(number(item[name], name, optional=True) for name in FEATURES)
            for name, value in zip(FEATURES, features):
                if value is not None and name in MAX_RECEIPT_AGE_MS:
                    if value != int(value) or not 0 <= value <= min(decision, MAX_RECEIPT_AGE_MS[name]):
                        raise ValueError(f'{name} exceeds the registered integer receipt-age bounds at row {line}')
                if value is not None and name in {'f_own_mood', 'f_market_mood'} and not 0 <= value <= 1:
                    raise ValueError(f'Mood must be a fraction at row {line}')
            f_payout = features[FEATURES.index('f_payout')]
            if f_payout is not None and (payout is None or abs(f_payout-payout)>1e-12):
                raise ValueError(f'Feature payout and observed scenario payout disagree at row {line}')
            present=dict(zip(FEATURES,features))
            needs_quote=status!='ineligible' or present['f_return_lookback'] is not None
            needs_mood=present['f_own_mood'] is not None or present['f_market_mood'] is not None
            needs_payout=status!='ineligible' or f_payout is not None
            if needs_quote and present['f_quote_age_ms'] is None:
                raise ValueError(f'Present quote-derived value has no receipt age at row {line}')
            if needs_mood and present['f_mood_age_ms'] is None:
                raise ValueError(f'Present mood value has no receipt age at row {line}')
            if needs_payout and (f_payout is None or present['f_payout_age_ms'] is None):
                raise ValueError(f'Present payout value has no payout feature/receipt age at row {line}')
            if item['evidence_class']!=evidence_class:
                raise ValueError(f'Unsupported or contradictory evidence class at row {line}')
            rows.append(Record(identifier,item['asset'],decision,expiry,status,label,
                               payout,features,item['evidence_class']))
    if not rows:
        raise ValueError('Empty candidate population')
    return rows, manifest


def probabilities(values: Sequence[float]) -> tuple[float, float, float]:
    if len(values) != 3 or any(not math.isfinite(float(p)) or p < 0 or p > 1 for p in values):
        raise ValueError('Probabilities must be three finite class probabilities')
    if abs(sum(values)-1) > 1e-6:
        raise ValueError('Class probabilities must sum to one')
    return tuple(float(value) for value in values)


def expected_returns(probs: Sequence[float], payout: float) -> tuple[float,float]:
    up,down,_tie = probabilities(probs)
    if not math.isfinite(payout) or not 0 < payout <= 2:
        raise ValueError('Expected return requires an observed finite payout ratio')
    # Explicit scenario: win earns r, loss loses 1, tie fully refunds stake.
    return up*payout-down, down*payout-up


def temperature_probs(values: Sequence[Sequence[float]], temperature: float) -> list[list[float]]:
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError('Temperature must be positive and finite')
    output=[]
    for row in values:
        logits=[math.log(max(p,1e-15))/temperature for p in probabilities(row)]
        maximum=max(logits);exps=[math.exp(value-maximum) for value in logits]
        total=sum(exps);output.append([value/total for value in exps])
    return output


def proper_scores(labels: Sequence[str], values: Sequence[Sequence[float]]) -> dict:
    if len(labels) != len(values):
        raise ValueError('Label/probability lengths differ')
    if not labels:
        return {'rows':0,'log_loss':None,'brier':None,'reason':'No resolved unpurged labels'}
    loss=brier=0.0
    for label,row in zip(labels,values):
        index=LABELS.index(label);probs=probabilities(row)
        loss-=math.log(max(probs[index],1e-15))
        brier+=sum((p-int(i==index))**2 for i,p in enumerate(probs))
    return {'rows':len(labels),'log_loss':loss/len(labels),'brier':brier/len(labels),
            'brier_definition':'sum of squared errors over three classes, averaged over rows'}


def policy_decisions(rows: Sequence[Record], values: Sequence[Sequence[float]],
                     threshold: float | None, enforce_position: bool=True) -> tuple[list[dict],dict]:
    if len(rows) != len(values):
        raise ValueError('Row/probability lengths differ')
    if threshold is not None and threshold not in THRESHOLDS:
        raise ValueError('Threshold outside the registered policy family')
    ordered=sorted(zip(rows,values),key=lambda pair:(pair[0].decision_ms,pair[0].asset,pair[0].opportunity_id))
    outstanding_until=-1;decisions=[];daily=defaultdict(Counter)
    for row,values_row in ordered:
        probs=probabilities(values_row);purged=partition_purged(row)
        ev_call,ev_put=expected_returns(probs,row.payout) if row.payout is not None else (None,None)
        direction='call' if ev_call is not None and ev_call >= ev_put else 'put'
        best=ev_call if direction=='call' else ev_put
        if row.status=='ineligible':reason='ineligible'
        elif purged:reason='partition_crossing'
        elif threshold is None:reason='no_supported_policy'
        elif best is None or best<threshold:reason='below_threshold'
        elif enforce_position and row.decision_ms<outstanding_until:reason='position_open'
        else:reason='accepted';outstanding_until=row.expiry_ms
        accepted=reason=='accepted';unit=None
        if accepted and row.status=='resolved':
            unit=0.0 if row.label=='tie' else row.payout if ((direction=='call')==(row.label=='up')) else -1.0
        day=datetime.fromtimestamp(row.decision_ms/1000,timezone.utc).date().isoformat()
        daily[day]['population']+=1;daily[day][row.status]+=1
        if accepted:
            daily[day]['accepted']+=1
            daily[day]['accepted_'+row.status]+=1
        decisions.append({'opportunity_id':row.opportunity_id,'asset':row.asset,
            'decision_ms':row.decision_ms,'expiry_ms':row.expiry_ms,'partition':partition(row.decision_ms),
            'status':row.status,'label':row.label or None,'payout':row.payout,
            'evidence_class':row.evidence_class,'partition_purged':purged,
            'p_up':probs[0],'p_down':probs[1],'p_tie':probs[2],
            'ev_call':ev_call,'ev_put':ev_put,'direction':direction if row.status!='ineligible' else None,
            'accepted':accepted,'reason':reason,'proxy_unit_return':unit})
    chosen=[row for row in decisions if row['accepted']]
    known=[row['proxy_unit_return'] for row in chosen if row['proxy_unit_return'] is not None]
    unresolved=sum(row['status']=='unresolved' for row in chosen)
    summary={'population':len(rows),'population_status':dict(Counter(row.status for row in rows)),
        'accepted':len(chosen),'accepted_resolved':len(known),'accepted_unresolved':unresolved,
        'accepted_ties':sum(row['label']=='tie' for row in chosen),
        'accepted_wins':sum(value>0 for value in known),
        'accepted_losses':sum(value<0 for value in known),
        'decisive_proxy_win_rate':sum(value>0 for value in known)/sum(value!=0 for value in known) if any(value!=0 for value in known) else None,
        'coverage':len(chosen)/len(rows) if rows else None,
        'unresolved_fraction':unresolved/len(chosen) if chosen else None,
        'known_return_sum':sum(known),'known_only_mean_unit_return':sum(known)/len(known) if known else None,
        'worst_case_mean_unit_return':(sum(known)-unresolved)/len(chosen) if chosen else None,
        'daily_counts':{day:dict(counts) for day,counts in sorted(daily.items())},
        'position_constraint':'one global outstanding position' if enforce_position else 'independent overlapping opportunities; not a portfolio',
        'tie_scenario':'full_refund','return_kind':'hypothetical_unit_return_not_observed_cash'}
    return decisions,summary


def registration() -> dict:
    return {'schema':'otc_training_registration_v1','evidence':'spent_historical_price_proxy',
        'promotable':False,'assets':list(ASSETS),'horizon_seconds':120,
        'thresholds':list(THRESHOLDS),'complete_policy_variants':6,
        'models':{'logistic':{'C':1.0,'max_iter':1000,'random_state':42},
                  'catboost':{'depth':6,'iterations':400,'learning_rate':.05,'random_seed':42,'early_stopping_rounds':40}},
        'partitions':{name:{'start_ms':bounds[0],'end_ms':bounds[1]} for name,bounds in LIMITS.items()},
        'purge_rule':'expiry_ms >= partition_end_ms, globally across assets',
        'minimum_resolved_unpurged_rows':MINIMUM_ROWS,
        'minimum_policy_resolved_selections':MINIMUM_POLICY_RESOLVED,
        'maximum_feature_receipt_age_ms':MAX_RECEIPT_AGE_MS,
        'calibration':'one shared procedure: scalar multiclass temperature optimized on calibration rows only in [0.05, 20]',
        'selection':'largest positive worst-case mean unit return on policy rows, otherwise abstain; unresolved selected outcomes count as full loss; ties by threshold ascending',
        'tie_scenario':'full_refund','test_role':'spent diagnostic only; never promotion evidence'}


def choose_policy(variants: Sequence[dict]) -> dict | None:
    """Abstention is the outcome when no registered policy supports an edge."""
    supported=[variant for variant in variants if variant['support_pass']
               and variant['selective']['worst_case_mean_unit_return'] is not None
               and variant['selective']['worst_case_mean_unit_return']>0]
    return max(supported,key=lambda variant:(variant['selective']['worst_case_mean_unit_return'],
                                            -variant['threshold'])) if supported else None


def dataset_counts(rows: Sequence[Record]) -> dict:
    result={}
    for name in LIMITS:
        subset=[row for row in rows if partition(row.decision_ms)==name]
        supervised=[row for row in subset if row.status=='resolved' and not partition_purged(row)]
        result[name]={'population':len(subset),'status':dict(Counter(row.status for row in subset)),
                      'purged_intervals':sum(partition_purged(row) for row in subset),
                      'supervised_rows':len(supervised),'supervised_labels':dict(Counter(row.label for row in supervised))}
    return result


def training_admission(rows: Sequence[Record]) -> dict:
    counts=dataset_counts(rows)
    for name,minimum in MINIMUM_ROWS.items():
        if counts[name]['supervised_rows']<minimum:
            raise ValueError(f'{name} needs at least {minimum} resolved unpurged rows; got {counts[name]["supervised_rows"]}')
    if set(counts['train']['supervised_labels']) != set(LABELS):
        raise ValueError('Training requires observed up, down and tie labels; no fabricated tie prior')
    return counts


def build_preprocessor():
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    numeric=Pipeline([('impute',SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)),
                      ('scale',StandardScaler())])
    return ColumnTransformer([('numeric',numeric,list(FEATURES)),
                              ('asset',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['asset'])],
                             sparse_threshold=0)


def fit_temperature(values, labels) -> float:
    import numpy as np
    from scipy.optimize import minimize_scalar
    probs=np.asarray(values,dtype=float);targets=np.asarray(labels,dtype=int)
    logits=np.log(np.clip(probs,1e-15,1))
    def objective(log_temperature):
        scaled=logits/math.exp(log_temperature)
        scaled-=scaled.max(axis=1,keepdims=True)
        normalizer=np.log(np.exp(scaled).sum(axis=1))
        return float(np.mean(normalizer-scaled[np.arange(len(targets)),targets]))
    result=minimize_scalar(objective,bounds=(math.log(.05),math.log(20)),method='bounded',options={'xatol':1e-7})
    if not result.success or not math.isfinite(result.fun):
        raise ValueError('Temperature calibration did not converge')
    return float(math.exp(result.x))


def json_write(path: Path, value) -> None:
    path.write_text(json.dumps(value,indent=2,allow_nan=False,sort_keys=True)+'\n')


def enforce_output_path(output: Path) -> Path:
    output=output.resolve()
    for parent in (output,*output.parents):
        marker=parent/'.git'
        # Empty placeholders (including this host's /tmp/.git) are not repositories.
        # A git init creates nonempty metadata; worktrees use a .git pointer file.
        bare=(parent/'HEAD').is_file() and (parent/'objects').is_dir() and (parent/'refs').is_dir()
        if marker.is_file() or (marker.is_dir() and any(marker.iterdir())) or bare:
            raise ValueError('Training artifacts must be outside the repository')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be new or empty; existing runs are immutable')
    output.mkdir(parents=True,exist_ok=True)
    return output


class Progress:
    """Measured phase completion; time remaining is unknown until work completes."""
    total = 9

    def __init__(self, output: Path):
        self.path = output/'progress.log'
        self.started = time.monotonic()
        self.completed = 0
        self.phase = 'starting'

    def emit(self, phase: str, completed: int | None = None, **details):
        if completed is not None:
            self.completed = completed
        self.phase = phase
        value = {'event':'otc_training_progress', 'phase':phase,
                 'timestamp_utc':datetime.now(timezone.utc).isoformat(),
                 'completed_phases':self.completed, 'total_phases':self.total,
                 'percent_complete':100*self.completed/self.total,
                 'elapsed_seconds':time.monotonic()-self.started,
                 'estimated_seconds_remaining':0 if self.completed == self.total else None,
                 'estimate_basis':'completed named phases; no fit-time prediction', **details}
        line = json.dumps(value,allow_nan=False,sort_keys=True)
        with self.path.open('a') as stream:
            stream.write(line+'\n')
        print(line,flush=True)


def verify_saved_inference(rows: Sequence[Record], output: Path) -> dict:
    """Reload saved preprocessing, classifiers and calibration, then replay every row."""
    import joblib
    import numpy as np
    import pandas as pd
    from catboost import CatBoostClassifier

    processor = joblib.load(output/'preprocessor.joblib')
    frame = pd.DataFrame([{**dict(zip(FEATURES,row.features)),'asset':row.asset} for row in rows])
    frame[list(FEATURES)] = frame[list(FEATURES)].astype(float)
    matrix = processor.transform(frame)
    declared = strict_json((output/'feature_order.json').read_bytes())
    if declared['transformed_features'] != processor.get_feature_names_out().tolist():
        raise ValueError('Saved preprocessing feature order changed')
    result = {'schema':'otc_saved_inference_parity_v1', 'rows':len(rows), 'models':{}}
    for name in MODEL_NAMES:
        if name == 'catboost':
            model = CatBoostClassifier()
            model.load_model(str(output/'catboost.cbm'))
        else:
            model = joblib.load(output/'logistic.joblib')
        classes = [int(value) for value in model.classes_]
        raw = np.asarray(model.predict_proba(matrix))[:,[classes.index(index) for index in range(3)]]
        calibration = strict_json((output/f'{name}_calibration.json').read_bytes())
        calibrated = temperature_probs(raw,calibration['temperature'])
        selected = strict_json((output/f'{name}_policy_selection.json').read_bytes())['selected_threshold']
        reloaded = []
        for split in LIMITS:
            indices = [i for i,row in enumerate(rows) if partition(row.decision_ms) == split]
            decisions,_ = policy_decisions([rows[i] for i in indices],
                                           [calibrated[i] for i in indices],selected)
            reloaded.extend(decisions)
        with (output/f'{name}_decisions.csv').open(newline='') as stream:
            stored = list(csv.DictReader(stream))
        error = max((abs(float(saved[column])-row[column]) for saved,row in zip(stored,reloaded)
                     for column in ('p_up','p_down','p_tie')),default=0.0)
        decisions_match = len(stored) == len(reloaded) and all(
            all(saved[column] == ('' if row[column] is None else str(row[column]))
                for column in ('opportunity_id','asset','decision_ms','expiry_ms','partition',
                               'status','label','direction','accepted','reason','proxy_unit_return'))
            for saved,row in zip(stored,reloaded))
        result['models'][name] = {'rows':len(stored),'max_probability_error':error,
                                  'decisions_match':decisions_match,
                                  'pass':decisions_match and error <= 1e-12}
    result['pass'] = all(entry['pass'] for entry in result['models'].values())
    return result


def run_comparison(source: Path, manifest_path: Path, output: Path, device: str='CPU') -> dict:
    if device not in {'CPU','GPU'}:
        raise ValueError('device must be CPU or GPU')
    output = enforce_output_path(output)
    progress = Progress(output)
    progress.emit('starting',0)
    try:
        report = _run_comparison(source,manifest_path,output,device,progress)
    except Exception as exc:
        blocked = {'status':'BLOCKED','promotable':False,'monetary_claim':False,
                   'reason':str(exc),'error_type':type(exc).__name__,
                   'failed_phase':progress.phase,'completed_phases':progress.completed}
        existing = output/'report.json'
        if existing.is_file():
            previous = strict_json(existing.read_bytes())
            if previous.get('status') == 'BLOCKED':
                blocked = {**previous,**blocked}
        json_write(existing,blocked)
        progress.emit('failed',error_type=type(exc).__name__)
        raise
    progress.emit('complete',9,status='DONE',report=str(output/'report.json'))
    return report


def _run_comparison(source: Path, manifest_path: Path, output: Path,
                    device: str, progress: Progress) -> dict:
    """Fit only after admission; persist registration before any model fit."""
    if device not in {'CPU','GPU'}:
        raise ValueError('device must be CPU or GPU')
    code_hash=sha256(Path(__file__))
    registered=registration();registered['code_sha256']=code_hash
    json_write(output/'registration.json',registered)
    try:
        manifest_bytes=manifest_path.read_bytes()
        rows,manifest=load_inputs(source,manifest_path)
        if strict_json(manifest_bytes)!=manifest or sha256(manifest_path)!=hashlib.sha256(manifest_bytes).hexdigest():
            raise ValueError('Dataset manifest changed during admission')
        counts=training_admission(rows)
    except (ValueError,OSError,json.JSONDecodeError) as exc:
        blocked={'status':'BLOCKED','promotable':False,'reason':str(exc),'registration':registered,
                 'input_sha256':sha256(source) if source.is_file() else None}
        json_write(output/'report.json',blocked)
        raise
    (output/'dataset_manifest.json').write_bytes(manifest_bytes)
    progress.emit('admission_complete',1,candidate_rows=len(rows))
    import importlib.metadata
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from catboost import CatBoostClassifier

    frame=pd.DataFrame([{**dict(zip(FEATURES,row.features)),'asset':row.asset} for row in rows])
    frame[list(FEATURES)]=frame[list(FEATURES)].astype(float)
    supervised={name:[i for i,row in enumerate(rows) if partition(row.decision_ms)==name and row.status=='resolved' and not partition_purged(row)] for name in LIMITS}
    population={name:[i for i,row in enumerate(rows) if partition(row.decision_ms)==name] for name in LIMITS}
    targets=np.array([LABELS.index(row.label) if row.label else -1 for row in rows])
    processor=build_preprocessor()
    train=supervised['train'];early=supervised['early'];calibration=supervised['calibration']
    processor.fit(frame.iloc[train])
    matrix=processor.transform(frame)
    if not np.isfinite(matrix).all():
        raise ValueError('Training-only preprocessing produced nonfinite transformed values')
    joblib.dump(processor,output/'preprocessor.joblib')
    json_write(output/'feature_order.json',{'raw_features':[*FEATURES,'asset'],
        'transformed_features':processor.get_feature_names_out().tolist(),'fit_partition':'train',
        'class_order':list(LABELS),'source_input_sha256':manifest['input_sha256']})
    progress.emit('preprocessing_complete',2,train_rows=len(train))
    report={'schema':'otc_training_comparison_v1','status':'DONE','promotable':False,
        'evidence_class':manifest['evidence_classes'][0],
        'cohort_role':'spent_historical_development_or_synthetic_eval','monetary_claim':False,
        'warning':'All historical partitions are spent; outputs cannot establish future or executable-contract profitability.',
        'input_sha256':manifest['input_sha256'],'manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest(),'code_sha256':code_hash,
        'source_manifest':manifest,'registration':registered,'counts':counts,'models':{},
        'observed_payout_scenarios':dict(sorted(Counter(str(row.payout) for row in rows if row.payout is not None).items())),
        'population_evidence_classes':dict(Counter(row.evidence_class for row in rows)),
        'tie_scenario':'full_refund','device':device,
        'runtime':{'python':sys.version,'packages':{name:importlib.metadata.version(name)
            for name in ['catboost','pandas','numpy','scikit-learn','scipy','joblib']}}}
    models={
        'logistic':LogisticRegression(C=1.0,max_iter=1000,random_state=42,solver='lbfgs'),
        'catboost':CatBoostClassifier(depth=6,iterations=400,learning_rate=.05,random_seed=42,
            loss_function='MultiClass',task_type=device,allow_writing_files=False,verbose=False,thread_count=2),
    }
    fitted={}
    for name,model in models.items():
        print(json.dumps({'event':'fit_start','model':name,'train_rows':len(train),'promotable':False}),flush=True)
        if name=='catboost':
            model.fit(matrix[train],targets[train],eval_set=(matrix[early],targets[early]),
                      early_stopping_rounds=40,use_best_model=True,verbose=False)
            model.save_model(str(output/'catboost.cbm'))
        else:
            model.fit(matrix[train],targets[train]);joblib.dump(model,output/'logistic.joblib')
        classes=[int(value) for value in model.classes_]
        if set(classes)!={0,1,2}:
            raise ValueError(f'{name} did not preserve all three outcome classes')
        raw=np.asarray(model.predict_proba(matrix))[:,[classes.index(index) for index in range(3)]]
        temperature=fit_temperature(raw[calibration],targets[calibration])
        calibrated=np.asarray(temperature_probs(raw,temperature))
        json_write(output/f'{name}_calibration.json',{'method':'multiclass_temperature','temperature':temperature,
            'fit_partition':'calibration','fit_rows':len(calibration),'class_order':list(LABELS)})
        policy_indices=population['policy'];policy_rows=[rows[i] for i in policy_indices]
        policy_probs=calibrated[policy_indices].tolist();variants=[]
        for threshold in THRESHOLDS:
            _decisions,selective=policy_decisions(policy_rows,policy_probs,threshold)
            _standalone,standalone=policy_decisions(policy_rows,policy_probs,threshold,enforce_position=False)
            variants.append({'threshold':threshold,'selective':selective,'standalone':standalone,
                'support_pass':selective['accepted_resolved']>=MINIMUM_POLICY_RESOLVED})
        selected=choose_policy(variants)
        threshold=selected['threshold'] if selected else None
        # Persist the policy choice before any diagnostic-label scoring.
        json_write(output/f'{name}_policy_selection.json',{'selected_threshold':threshold,
            'reason':'policy partition only' if selected else 'No supported threshold has positive worst-case policy return',
            'variants':variants,'diagnostic_labels_used':False})
        report['models'][name]={'temperature':temperature,'selected_threshold':threshold,
            'policy_variants':variants,'selected_policy_score':selected['selective']['worst_case_mean_unit_return'] if selected else None,
            'decision_artifact':f'{name}_decisions.csv','best_iteration':int(model.get_best_iteration()) if name=='catboost' else None}
        fitted[name]=(raw,calibrated)
        progress.emit('fit_and_policy_complete',3 if name=='logistic' else 4,model=name)
        print(json.dumps({'event':'fit_complete','model':name,'selected_threshold':threshold,'diagnostic_labels_used':False}),flush=True)
    eligible_models=[(name,entry) for name,entry in report['models'].items() if entry['selected_threshold'] is not None]
    winner=max(eligible_models,key=lambda pair:(pair[1]['selected_policy_score'],-MODEL_NAMES.index(pair[0])))[0] if eligible_models else None
    report['development_preference']={'model':winner,'basis':'policy worst-case mean only; diagnostic test never selects a winner',
        'promotable':False,'onnx_exported':False,'onnx_reason':'No deployment winner or runtime parity requirement exists for exploratory proxies'}
    json_write(output/'development_selection.json',{'preference':report['development_preference'],
        'selected_thresholds':{name:entry['selected_threshold'] for name,entry in report['models'].items()},
        'diagnostic_labels_used':False})
    progress.emit('development_choices_frozen',5)
    # Both model policies and the preference are frozen before diagnostic scoring.
    for name,(raw,calibrated) in fitted.items():
        threshold=report['models'][name]['selected_threshold']
        metrics={}
        for split in LIMITS:
            indices=supervised[split]
            metrics[split]={'raw':proper_scores([rows[i].label for i in indices],raw[indices].tolist()),
                            'calibrated':proper_scores([rows[i].label for i in indices],calibrated[indices].tolist())}
        decisions=[];performance={}
        for split in LIMITS:
            indices=population[split];subset=[rows[i] for i in indices]
            part_decisions,selective=policy_decisions(subset,calibrated[indices].tolist(),threshold)
            _,standalone=policy_decisions(subset,calibrated[indices].tolist(),threshold,enforce_position=False)
            decisions.extend(part_decisions);performance[split]={'selective':selective,'standalone':standalone}
        with (output/f'{name}_decisions.csv').open('w',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(decisions[0]));writer.writeheader();writer.writerows(decisions)
        report['models'][name].update(proper_scores=metrics,performance=performance)
        progress.emit('diagnostic_complete',6 if name=='logistic' else 7,model=name)
        print(json.dumps({'event':'diagnostic_complete','model':name,'candidate_rows_preserved':len(decisions)}),flush=True)
    parity = verify_saved_inference(rows,output)
    json_write(output/'saved_inference_parity.json',parity)
    if not parity['pass']:
        raise ValueError('Reloaded model probabilities or decisions changed')
    report['saved_inference_parity'] = parity
    progress.emit('saved_inference_verified',8)
    report['artifacts']={path.name:{'sha256':sha256(path),'bytes':path.stat().st_size} for path in sorted(output.iterdir()) if path.is_file() and path.name!='progress.log'}
    json_write(output/'report.json',report)
    write_summary(output/'report.md',report)
    json_write(output/'artifact_manifest.json',{'schema':'otc_training_artifacts_v1','promotable':False,
        'input_sha256':manifest['input_sha256'],'code_sha256':code_hash,
        'mutable_status_file':'progress.log',
        'files':{path.name:{'sha256':sha256(path),'bytes':path.stat().st_size} for path in sorted(output.iterdir()) if path.is_file() and path.name!='progress.log'}})
    return report


def write_summary(path: Path, report: dict) -> None:
    lines=['# Fixed OTC price-proxy comparison','','Exploratory and nonpromotable. This spent historical cohort cannot establish executable-contract or future profitability. Returns below are hypothetical units under a full-refund tie scenario, not observed cash.','',
        '| Model | Policy EV cutoff | Diagnostic log loss | Diagnostic Brier | Diagnostic selective coverage | Selected unresolved fraction | Known-only unit mean | Worst-case unit mean |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    def fmt(value):return 'unavailable' if value is None else f'{value:.6f}'
    for name,entry in report['models'].items():
        score=entry['proper_scores']['diagnostic_test']['calibrated'];perf=entry['performance']['diagnostic_test']['selective']
        lines.append('| '+' | '.join([name,fmt(entry['selected_threshold']),fmt(score['log_loss']),fmt(score['brier']),fmt(perf['coverage']),fmt(perf['unresolved_fraction']),fmt(perf['known_only_mean_unit_return']),fmt(perf['worst_case_mean_unit_return'])])+' |')
    lines+=['','Every input row is retained in each model’s decision CSV, including ineligible, unresolved, tied, purged, below-threshold and position-blocked opportunities. Proper scores use resolved, unpurged labels; their denominators are reported. Worst-case selection scores charge each accepted unresolved outcome a full loss.','',
        'The six registered development policies and daily population/selection counts are in report.json. Preprocessing fits training rows only. Both models use calibration-period scalar temperature scaling. CatBoost early stopping uses only the early partition. The policy cutoff is saved before diagnostic scoring.','',
        'No restart or deployment is required. Inspect the complete population and unresolved outcomes before considering any later research cycle.']
    path.write_text('\n'.join(lines)+'\n')


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--device',choices=('CPU','GPU'),default='CPU')
    args=parser.parse_args(argv)
    try:
        report=run_comparison(args.input,args.manifest,args.output,args.device)
    except Exception as exc:
        print(json.dumps({'status':'BLOCKED','promotable':False,'reason':str(exc)}),file=sys.stderr)
        return 2
    print(json.dumps({'status':report['status'],'promotable':False,'report':str(args.output/'report.json')}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
