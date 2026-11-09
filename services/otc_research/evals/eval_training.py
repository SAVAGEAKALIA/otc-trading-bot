"""Synthetic-only fit eval: seeded edge/null, corruption and train-only transforms.

Run with the original project's ML venv. Artifacts always stay outside the repo.
No raw source data, broker access, Kaggle upload or LLM calls are used here.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import tempfile
import importlib.util
import sys
from unittest.mock import patch

from services.otc_research.training import (
    ASSETS, COLUMNS, FEATURES, LIMITS, MANIFEST_SCHEMA, build_preprocessor, epoch_ms, load_inputs,
    run_comparison,
)


def fixture(root: Path, edge: bool, seed: int):
    rng=random.Random(seed);rows=[]
    counts={'train':1000,'early':300,'calibration':300,'policy':500,'diagnostic_test':500}
    for split,count in counts.items():
        low,high=LIMITS[split]
        if split=='train':low=epoch_ms('2026-08-01')
        for index in range(count):
            decision=low+1000+(high-low-242000)*index//count
            feature=rng.gauss(0,1);draw=rng.random()
            if draw<.08:label='tie'
            else:
                follows=(rng.random()<.91) if edge else (rng.random()<.5)
                label='up' if ((feature>=0)==follows) else 'down'
            status='ineligible' if index%53==0 else 'unresolved' if index%37==0 else 'resolved'
            row={'opportunity_id':f'{split}-{index}','asset':ASSETS[index%2],
                 'decision_ms':decision,'expiry_ms':decision+120000,'status':status,
                 'label':label if status=='resolved' else '', 'payout':.84,
                 'f_return_lookback':feature,'f_own_mood':rng.random(),
                 'f_market_mood':rng.random(),'f_payout':.84,'f_quote_age_ms':rng.randrange(300),
                 'f_mood_age_ms':rng.randrange(5000),'f_payout_age_ms':rng.randrange(300000),
                 'evidence_class':'synthetic_training_eval'}
            if index%11==0:row['f_own_mood']=''
            rows.append(row)
    source=root/'input.csv'
    with source.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows)
    manifest=root/'manifest.json'
    recipe=root/'fixture_source.json'
    recipe.write_text(json.dumps({'seed':seed,'edge':edge,'counts':counts},sort_keys=True)+'\n')
    manifest.write_text(json.dumps({'schema':MANIFEST_SCHEMA,
        'expiry_basis':'hypothetical','product_mapping':'explicit_assumed',
        'clock':'receiver_utc','input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'feature_availability':'receiver_receipt_lte_decision',
        'outcome_basis':'last_received_quote_at_or_before_expiry',
        'evidence_classes':['synthetic_training_eval'],
        'source_lineage':[{'source_id':'fixture_source.json','sha256':hashlib.sha256(recipe.read_bytes()).hexdigest(),
                           'kind':'synthetic_fixture','clock':'receiver_utc'}],
        'metadata':{'source_kind':'fresh_seeded_synthetic_eval','seed':seed,'edge':edge}}))
    return source,manifest,len(rows)


def evaluate(output: Path):
    import numpy as np
    import pandas as pd
    output.mkdir(parents=True,exist_ok=True);checks={};runs={}
    for name,edge,seed in [('edge',True,61341),('null',False,81223)]:
        folder=output/name;folder.mkdir()
        source,manifest,total=fixture(folder,edge,seed)
        report=run_comparison(source,manifest,folder/'run','CPU');runs[name]=report
        for model,entry in report['models'].items():
            with (folder/'run'/entry['decision_artifact']).open() as handle:
                decisions=list(csv.DictReader(handle))
            checks[f'{name}_{model}_all_population_retained']=len(decisions)==total
            checks[f'{name}_{model}_ties_retained']=any(row['label']=='tie' for row in decisions)
            checks[f'{name}_{model}_unresolved_retained']=any(row['status']=='unresolved' for row in decisions)
            test=entry['performance']['diagnostic_test']['selective']
            if edge:
                checks[f'{model}_known_edge_logloss_below_0_85']=entry['proper_scores']['diagnostic_test']['calibrated']['log_loss']<.85
                checks[f'{model}_known_edge_selective_worst_mean_above_0_20']=test['worst_case_mean_unit_return'] is not None and test['worst_case_mean_unit_return']>.20
                checks[f'{model}_known_edge_coverage_above_0_25']=test['coverage']>.25
            else:
                checks[f'{model}_null_logloss_above_0_70']=entry['proper_scores']['diagnostic_test']['calibrated']['log_loss']>.70
                checks[f'{model}_null_coverage_below_0_20']=test['coverage']<.20
        checks[f'{name}_nonpromotable']=report['promotable'] is False
        checks[f'{name}_six_registered_policies']=report['registration']['complete_policy_variants']==6 and sum(len(entry['policy_variants']) for entry in report['models'].values())==6
        corrupt=json.loads(manifest.read_text());corrupt['clock']='source_event_utc'
        corrupt_manifest=folder/'wrong-clock-manifest.json';corrupt_manifest.write_text(json.dumps(corrupt))
        try:load_inputs(source,corrupt_manifest);checks[f'{name}_wrong_clock_rejected']=False
        except ValueError:checks[f'{name}_wrong_clock_rejected']=True
        checks[f'{name}_source_manifest_hash_preserved']=hashlib.sha256(manifest.read_bytes()).hexdigest()==report['manifest_sha256']
        checks[f'{name}_copied_manifest_hash_matches']=hashlib.sha256((folder/'run/dataset_manifest.json').read_bytes()).hexdigest()==report['manifest_sha256']
        artifact_manifest=json.loads((folder/'run/artifact_manifest.json').read_text())
        checks[f'{name}_artifact_hashes_match']=all(hashlib.sha256((folder/'run'/filename).read_bytes()).hexdigest()==entry['sha256'] for filename,entry in artifact_manifest['files'].items())
        parity=json.loads((folder/'run/saved_inference_parity.json').read_text())
        for model,entry in parity['models'].items():
            checks[f'{name}_{model}_saved_model_reload_parity']=entry['pass'] and entry['rows']==total
        progress=[json.loads(line) for line in (folder/'run/progress.log').read_text().splitlines()]
        checks[f'{name}_progress_finished']=progress[-1]['completed_phases']==9 and progress[-1]['phase']=='complete'

    # Full-sized corrupt datasets must block before the model/preprocess fit path.
    positive=output/'edge';source=positive/'input.csv';manifest=positive/'manifest.json'
    for mutation in ['unsupported_schema','noncausal_availability','missing_lineage','missing_receipt_ages','future_interpolation',
                     'negative_implied_receipt','huge_receipt_age','stale_quote','fractional_receipt_age',
                     'metadata_positive_overflow','metadata_negative_overflow','metadata_nested_overflow']:
        case=output/('corrupt-'+mutation);case.mkdir()
        data=json.loads(manifest.read_text());candidate=source
        if mutation=='unsupported_schema':data['schema']='unsupported_dataset_v999'
        elif mutation=='noncausal_availability':data['feature_availability']='source_event_time_even_if_received_later'
        elif mutation=='missing_lineage':data['source_lineage']=[]
        elif mutation.startswith('metadata_'):
            data['metadata']={'nested':[{'value':'NUMERIC_OVERFLOW'}]}
        else:
            with source.open() as handle:rows=list(csv.DictReader(handle))
            for row in rows:
                if mutation=='missing_receipt_ages':
                    for column in ['f_quote_age_ms','f_mood_age_ms','f_payout_age_ms']:row[column]=''
                elif mutation=='future_interpolation':row['evidence_class']='future_interpolated_candle_close'
                elif mutation=='negative_implied_receipt':row['f_quote_age_ms']=str(int(row['decision_ms'])+1)
                elif mutation=='huge_receipt_age':row['f_payout_age_ms']='1e100'
                elif mutation=='stale_quote':row['f_quote_age_ms']='5001'
                elif mutation=='fractional_receipt_age':row['f_mood_age_ms']='1.5'
            candidate=case/'input.csv'
            with candidate.open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows)
            data['input_sha256']=hashlib.sha256(candidate.read_bytes()).hexdigest()
        mutated_manifest=case/'manifest.json'
        serialized=json.dumps(data)
        if mutation.startswith('metadata_'):
            numeric='-1e10000' if mutation=='metadata_negative_overflow' else '1e10000'
            serialized=serialized.replace('"NUMERIC_OVERFLOW"',numeric)
        mutated_manifest.write_text(serialized)
        blocked=False
        with patch('services.otc_research.training.build_preprocessor',side_effect=AssertionError('Invalid input reached model path')):
            try:run_comparison(candidate,mutated_manifest,case/'run')
            except ValueError:blocked=True
        checks[mutation+'_blocked_before_fit']=blocked and json.loads((case/'run/report.json').read_text())['status']=='BLOCKED'
        if mutation.startswith('metadata_'):
            def old_parser(text):
                def reject_nonfinite_constant(value):
                    raise ValueError('Nonfinite JSON constant '+value)
                return json.loads(text,parse_constant=reject_nonfinite_constant)
            with patch('services.otc_research.training.strict_json',side_effect=old_parser):
                old_rows,old_manifest=load_inputs(candidate,mutated_manifest)
            old_value=old_manifest['metadata']['nested'][0]['value']
            checks[mutation+'_old_parser_mutant_admits_overflow']=len(old_rows)==len(load_inputs(source,manifest)[0]) and not math.isfinite(old_value)

    # Reintroduce the precise old admission bug. The positive-only age check admits
    # a receipt before epoch; the corrected loader above must reject that same CSV.
    from services.otc_research import training
    old_guard='if value != int(value) or not 0 <= value <= min(decision, MAX_RECEIPT_AGE_MS[name]):'
    code=Path(training.__file__).read_text()
    if code.count(old_guard)!=1:
        raise AssertionError('Receipt-age mutant marker changed; update the regression explicitly')
    mutant_path=output/'receipt_age_mutant.py'
    mutant_path.write_text(code.replace(old_guard,'if value < 0:'))
    spec=importlib.util.spec_from_file_location('otc_receipt_age_mutant',mutant_path)
    mutant=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mutant;spec.loader.exec_module(mutant)
    case=output/'corrupt-negative_implied_receipt'
    admitted,_=mutant.load_inputs(case/'input.csv',case/'manifest.json')
    checks['old_positive_only_age_mutant_admits_impossible_receipt']=len(admitted)==len(load_inputs(source,manifest)[0])

    # The training fit alone determines medians, scalers and category columns.
    train=pd.DataFrame([{**{name:float(index) for name in FEATURES},'asset':ASSETS[0]} for index in [1,2,3]])
    train.loc[1,FEATURES[0]]=np.nan
    held=pd.DataFrame([{**{name:1e9 for name in FEATURES},'asset':'never_seen_training_asset'}])
    processor=build_preprocessor();processor.fit(train)
    numeric=processor.named_transformers_['numeric']
    old_statistics=numeric.named_steps['impute'].statistics_.copy()
    transformed=processor.transform(held)
    checks['held_out_does_not_change_imputer']=bool(np.array_equal(old_statistics,numeric.named_steps['impute'].statistics_))
    checks['training_median_is_two']=float(old_statistics[0])==2.0
    checks['unknown_categories_safe']=bool(np.isfinite(transformed).all())
    checks['unknown_category_is_zero_encoded']=float(transformed[0,-1])==0.0
    verdict={'schema':'otc_training_eval_v1','pass':all(checks.values()),'checks':checks,
        'thresholds':{'edge_logloss_max':.85,'edge_worst_unit_mean_min':.20,'edge_coverage_min':.25,
                      'null_logloss_min':.70,'null_coverage_max':.20},
        'fixtures':'fresh seeded synthetic only; never proof of market profitability',
        'reports':{name:str(output/name/'run/report.json') for name in runs}}
    (output/'eval_report.json').write_text(json.dumps(verdict,indent=2)+'\n')
    print(json.dumps(verdict,indent=2))
    return verdict


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=args.output or Path(tempfile.mkdtemp(prefix='otc-training-eval-'))
    return 0 if evaluate(output)['pass'] else 1


if __name__=='__main__':
    raise SystemExit(main())
