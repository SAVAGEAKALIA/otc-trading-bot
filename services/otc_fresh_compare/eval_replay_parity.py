"""Re-export frozen integer-ms fixtures and compare exact prior matrix bytes."""
from pathlib import Path
import argparse
from contracts.otc_fresh_v1 import canonical,sha256,strict_json
from services.otc_fresh_compare.compiler import freeze_plan
from services.otc_fresh_compare.export import export_matrix


def evaluate(reference,output):
    reference=Path(reference);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    checks={};plan=output/'plan.json';freeze_plan(plan)
    for label in ('positive','null','source-gap'):
        original=reference/label;root=output/label
        record=strict_json((original/'registration.json').read_text())
        audit=export_matrix(original/'snapshot',original/'registration.json',plan,root,
            now_ms=record['end_ms'],synthetic_eval=True)
        for filename in ('matrix.csv','decision_lineage.jsonl'):
            checks[label+'_'+filename+'_byte_parity']=sha256(root/filename)==sha256(original/'matrix'/filename)
        checks[label+'_full_fixed_grid']=audit['opportunities']==10080
        checks[label+'_causal_ns_references']=audit['measured_future_nanosecond_feature_references']==0
    result={'schema':'otc_fresh_integer_ms_replay_parity_v1','pass':all(checks.values()),'checks':checks,
        'reference':str(reference),'threshold':'exact matrix and decision-lineage bytes on all existing integer-ms fixtures',
        'fixtures':'existing synthetic positive/null/gap source replay only; no model fit'}
    (output/'eval.json').write_text(canonical(result)+'\n');print(canonical(result));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--reference',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    raise SystemExit(0 if evaluate(args.reference,args.output)['pass'] else 1)
