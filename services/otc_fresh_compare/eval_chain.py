"""Focused archive-chain population/cutoff equivalence; no ML or side systems."""
from __future__ import annotations
import argparse
from pathlib import Path
import sqlite3
from contracts.otc_fresh_v1 import GRID_MS,canonical,strict_json
from services.otc_fresh_compare.export import export_matrix,replay_decision
from services.otc_fresh_compare.tests.test_chain import focused_chain
from services.otc_fresh_compare.source_chain import SourceChain,chain_wait_state,CLOSURE_ARCHIVE_GRACE_MS

def evaluate(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    record,reg,plan,single,chain,cutoff=focused_chain(output);checks={}
    source=sqlite3.connect(single.as_uri()+'?mode=ro&immutable=1',uri=True)
    reader=SourceChain(chain,record,record['end_ms'])
    try:
        for label,moment in [('before',cutoff-GRID_MS),('at',cutoff),('after',cutoff+GRID_MS)]:
            left=replay_decision(source,moment);right=replay_decision(reader,moment)
            checks[label+'_exact_rows_features_lineage_and_ns_parity']=left==right
        checks['two_shards_decoded_sequentially']=reader.decoded==2
        checks['cross_shard_tail_used']=reader.maximum_tail_rows>0
    finally:source.close();reader.close()
    original=strict_json(chain.read_text());lagged=strict_json(canonical(original))
    for segment in lagged['segments']:segment['closed_at_ms']+=7
    chain.write_text(canonical(lagged)+'\n')
    source=sqlite3.connect(single.as_uri()+'?mode=ro&immutable=1',uri=True)
    reader=SourceChain(chain,record,record['end_ms']+7)
    try:
        for label,moment in [('before',cutoff-GRID_MS),('at',cutoff),('after',cutoff+GRID_MS)]:
            checks['producer_closure_lag_'+label+'_exact_parity']=replay_decision(source,moment)==replay_decision(reader,moment)
    finally:source.close();reader.close()
    invalid=strict_json(canonical(original));invalid['segments'][0]['closed_at_ms']-=1
    chain.write_text(canonical(invalid)+'\n');reader=SourceChain(chain,record,record['end_ms'])
    try:replay_decision(reader,cutoff-GRID_MS)
    except ValueError:checks['session_close_beyond_producer_closure_blocked']=True
    else:checks['session_close_beyond_producer_closure_blocked']=False
    finally:reader.abort()
    pending=strict_json(canonical(original));pending['complete']=False;chain.write_text(canonical(pending)+'\n')
    waiting=chain_wait_state(chain,record,record['end_ms'])
    checks['archive_wait_eta_unknown']=waiting['status']=='WAITING_ARCHIVE' and waiting['eta_seconds'] is None
    checks['incomplete_chain_blocks_at_fixed_grace']=chain_wait_state(chain,record,record['end_ms']+CLOSURE_ARCHIVE_GRACE_MS)['status']=='BLOCKED'
    chain.write_text(canonical(original)+'\n')
    try:chain_wait_state(chain,record,record['end_ms']-1)
    except ValueError:checks['completed_chain_before_end_rejected']=True
    else:checks['completed_chain_before_end_rejected']=False
    audit=export_matrix(chain,reg,plan,output/'matrix',now_ms=record['end_ms'],synthetic_eval=True)
    checks['fixed_global_grid_retained']=audit['opportunities']==10080
    checks['missing_source_periods_retained']=audit['statuses'].get('ineligible',0)>9000
    checks['raw_ns_causality_proved']=audit['nanosecond_feature_references_checked']>0 and audit['measured_future_nanosecond_feature_references']==0
    checks['one_shard_per_decode']=audit['decoded_shards']==2
    result={'schema':'otc_closed_shard_eval_v1','pass':all(checks.values()),'checks':checks,
        'threshold':'all focused chain and fixed-cutoff parity checks pass',
        'fixtures':'synthetic closed gzip SQLite only; no fit or side services'}
    (output/'eval.json').write_text(canonical(result)+'\n');print(canonical(result));return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    raise SystemExit(0 if evaluate(args.output)['pass'] else 1)
