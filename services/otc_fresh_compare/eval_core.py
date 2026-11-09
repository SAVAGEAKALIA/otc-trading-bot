"""Only core end-to-end synthetic positive/null/gap and saved inference parity."""
from __future__ import annotations
import argparse
import contextlib
import csv
import importlib.util
import json
from pathlib import Path
import sys
from contracts.otc_fresh_v1 import canonical,sha256,strict_json
from services.otc_fresh_compare.compiler import compile_trainer
from services.otc_fresh_compare.export import export_matrix,compare
from services.otc_fresh_compare.tests.fixtures import registration,collector_boundary

def evaluate(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);checks={};reports={}
    for label,positive,gaps in [('positive',True,0),('null',False,0),('source-gap',True,97)]:
        root=output/label;root.mkdir();record,reg,plan=registration(root)
        snapshot=collector_boundary(root,record,positive=positive,gap_every=gaps)
        frozen=root/'frozen_training.py';proof=compile_trainer(reg,plan,frozen)
        audit=export_matrix(snapshot,reg,plan,root/'matrix',now_ms=record['end_ms'],synthetic_eval=True)
        matrix=root/'matrix/matrix.csv';manifest=root/'matrix/manifest.json'
        checks[label+'_full_population']=audit['opportunities']==10080
        checks[label+'_causal_receipt_references']=audit['measured_future_feature_references']==0
        checks[label+'_nanosecond_causal_receipt_references']=audit['measured_future_nanosecond_feature_references']==0 and audit['nanosecond_feature_references_checked']>0
        checks[label+'_bounded_memory']=audit['maximum_loaded_window_rows']<audit['window_memory_budget_rows'] and audit['maximum_window_serialized_bytes']<audit['window_memory_budget_bytes']
        report=compare(frozen,matrix,manifest,root/'comparison');reports[label]=str(root/'comparison/report.json')
        checks[label+'_nonpromotable']=report['promotable'] is False and report['evidence_class']=='synthetic_training_eval'
        for name,model in report['models'].items():
            parity=report['saved_inference_parity']['models'][name]
            checks[label+'_'+name+'_saved_inference_parity']=parity['pass'] is True and parity['rows']==10080
            metric=model['proper_scores']['diagnostic_test']['calibrated']['log_loss']
            if label=='positive':checks[name+'_positive_logloss_below_0_85']=metric<.85
            if label=='null':checks[name+'_null_logloss_above_0_70']=metric>.70
        if gaps:
            checks['source_gap_ineligible_retained']=audit['statuses'].get('ineligible',0)>0
            checks['source_gap_unresolved_retained']=audit['statuses'].get('unresolved',0)>0
        if label=='positive':
            rotated=root/'rotated.csv'
            with matrix.open(newline='') as stream:rows=list(csv.DictReader(stream))
            for row in rows:
                if int(row['decision_ms'])>=record['partitions']['diagnostic_test']['start_ms'] and row['label']:
                    row['label']={'up':'down','down':'tie','tie':'up'}[row['label']]
            with rotated.open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            changed=strict_json(manifest.read_text());changed['input_sha256']=sha256(rotated)
            rotated_manifest=root/'rotated-manifest.json';rotated_manifest.write_text(canonical(changed)+'\n')
            rotated_report=compare(frozen,rotated,rotated_manifest,root/'rotated-comparison')
            checks['rotated_diagnostic_saved_parity']=rotated_report['saved_inference_parity']['pass'] is True
            checks['rotated_diagnostic_preference_unchanged']=report['development_preference']==rotated_report['development_preference']
            for name in report['models']:
                checks[name+'_diagnostic_labels_do_not_change_selection']=strict_json((root/'comparison'/f'{name}_policy_selection.json').read_text())==strict_json((root/'rotated-comparison'/f'{name}_policy_selection.json').read_text())
                with (root/'comparison'/f'{name}_decisions.csv').open() as first,(root/'rotated-comparison'/f'{name}_decisions.csv').open() as second:
                    left=list(csv.DictReader(first));right=list(csv.DictReader(second))
                checks[name+'_diagnostic_labels_do_not_change_probabilities_or_actions']=all(
                    all(a[column]==b[column] for column in ('opportunity_id','p_up','p_down','p_tie','accepted','direction','reason')) for a,b in zip(left,right))
    # A complete seven-day grid with receipt evidence only at the start must
    # preserve missing periods and fail class/sample admission before any fit.
    root=output/'empty-periods';root.mkdir();record,reg,plan=registration(root)
    snapshot=collector_boundary(root,record,first_only=True);frozen=root/'training.py'
    compile_trainer(reg,plan,frozen)
    audit=export_matrix(snapshot,reg,plan,root/'matrix',now_ms=record['end_ms'],synthetic_eval=True)
    try:compare(frozen,root/'matrix/matrix.csv',root/'matrix/manifest.json',root/'comparison')
    except ValueError:checks['missing_source_periods_block_before_fit']=strict_json((root/'comparison/report.json').read_text())['status']=='BLOCKED'
    else:checks['missing_source_periods_block_before_fit']=False
    checks['missing_source_periods_preserve_grid']=audit['opportunities']==10080 and audit['statuses'].get('ineligible',0)>10000
    verdict={'schema':'otc_fresh_core_eval_v1','pass':all(checks.values()),'checks':checks,
        'threshold':'all checks pass; positive diagnostic logloss <0.85; null >0.70',
        'fixture_scope':'deterministic synthetic receipts only, no market/capital evidence','reports':reports}
    (output/'eval.json').write_text(canonical(verdict)+'\n');print(canonical(verdict));return verdict

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    raise SystemExit(0 if evaluate(args.output)['pass'] else 1)
