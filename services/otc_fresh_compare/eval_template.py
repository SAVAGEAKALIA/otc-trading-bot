"""Frozen model/source drift attacks. No source replay, fit or external calls."""
from __future__ import annotations
import argparse
from pathlib import Path
from contracts.otc_fresh_v1 import canonical,sha256,strict_json
from services.otc_fresh_compare.compiler import compile_trainer,freeze_plan
from services.otc_fresh_compare.export import compare
from services.otc_fresh_compare.tests.fixtures import registration

def evaluate(output,positive_matrix=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);checks={}
    for label in ('thresholds','chronology','admission'):
        root=output/label;root.mkdir();record,reg,plan=registration(root);trainer=root/'training.py'
        compile_trainer(reg,plan,trainer);source=trainer.read_text()
        if label=='thresholds':source=source.replace('THRESHOLDS = (0.0, 0.03, 0.05)','THRESHOLDS = (0.0, 0.01, 0.02)')
        elif label=='chronology':
            original=record['partitions']['train']['end_ms']
            source=source.replace(f"'train': ({record['start_ms']}, {original})",f"'train': ({record['start_ms']}, {original+120000})")
        else:source='\n'.join(line for line in source.splitlines() if 'fresh_boundary.validate_manifest_lock(manifest,' not in line)+'\n'
        trainer.write_text(source);proof=strict_json(trainer.with_suffix('.proof.json').read_text())
        proof['frozen_training_sha256']=sha256(trainer);trainer.with_suffix('.proof.json').write_text(canonical(proof)+'\n')
        stored_plan=strict_json(plan.read_text());manifest=root/'manifest.json'
        manifest.write_text(canonical({'metadata':{'fresh_registration':record,'compiler_plan_sha256':stored_plan['plan_sha256']}})+'\n')
        checks[label+'_old_self_declared_hash_mutant_would_admit']=proof['frozen_training_sha256']==sha256(trainer)
        try:compare(trainer,root/'unused.csv',manifest,root/'unused-model-run')
        except ValueError as error:checks[label+'_changed_template_blocked_before_execution']='exact deterministic' in str(error)
        else:checks[label+'_changed_template_blocked_before_execution']=False
    if positive_matrix is not None:
        source=Path(positive_matrix);data=strict_json((source/'manifest.json').read_text())
        root=output/'positive';root.mkdir();reg=root/'registration.json';plan=root/'plan.json'
        reg.write_text(canonical(data['metadata']['fresh_registration'])+'\n');source_plan=freeze_plan(plan)
        trainer=root/'training.py';compile_trainer(reg,plan,trainer)
        data['metadata']['compiler_plan_sha256']=source_plan['plan_sha256']
        manifest=root/'manifest.json';manifest.write_text(canonical(data)+'\n')
        report=compare(trainer,source/'matrix.csv',manifest,root/'comparison')
        checks['exact_source_reconstruction_runs_original_positive_procedure']=report['status']=='DONE'
        for name,parity in report['saved_inference_parity']['models'].items():
            checks['positive_reconstruction_'+name+'_saved_parity']=parity['pass'] and parity['rows']==10080
    result={'schema':'otc_frozen_template_eval_v1','pass':all(checks.values()),'checks':checks,
        'threshold':'all source/global-date/admission mutations reject even with a matching redeclared hash',
        'fixtures':'offline template attacks'+(' and existing positive matrix fit with unchanged procedure' if positive_matrix is not None else '; no model fit')}
    (output/'eval.json').write_text(canonical(result)+'\n');print(canonical(result));return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--positive-matrix',type=Path);args=parser.parse_args()
    raise SystemExit(0 if evaluate(args.output,args.positive_matrix)['pass'] else 1)
