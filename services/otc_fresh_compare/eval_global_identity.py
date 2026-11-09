"""Held-out whole-chain identity attacks, loss population and bounded cleanup."""
from __future__ import annotations
import argparse
import contextlib
import csv
from pathlib import Path
import sqlite3
from contracts.otc_fresh_v1 import ASSETS,GRID_MS,canonical,strict_json
from . import export
from .source_chain import SourceChain
from .tests.fixtures import registration
from .tests.test_full_census import single_source,seal_snapshot,old_sql_census_admits
from .tests.test_global_identity import make_identity_chain,admit_chain,session_cases


def evaluate(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    seed=output/'seed';seed.mkdir()
    record,reg,plan=registration(seed,start='2026-12-03T11:26:00Z')
    checks={};cases=[]
    for label,(sql,params) in session_cases(record).items():
        root=output/('session-'+label);root.mkdir()
        _,source=single_source(root,record,memory=True)
        try:
            source.execute(sql,params);source.commit()
            previous=old_sql_census_admits(source,record)
            try:export.validate_source_scope(source,record)
            except ValueError as error:blocked=True;reason=str(error)
            else:blocked=False;reason=None
            checks['session_'+label+'_blocked']=blocked
            if label=='orphan_null_transition':checks['literal_old_sql_mutant_admits_null_orphan']=previous
            cases.append({'case':'session-'+label,'blocked':blocked,'old_sql_admits':previous,'error':reason})
        finally:source.close()
    # Different schedule,4 closed physical shards,2 assets and all3 kinds.
    # Most source records are days outside replay tails and never selected.
    modes=('session','frame','empty_frame','event','contradictory_event',
           'quarantined_event','identical_event','local_sequence','null_transition')
    for asset in ASSETS:
        for kind in ('quote','mood','payout'):
            for mode in modes:
                name=asset+'-'+kind+'-'+mode
                path,_,_,records=make_identity_chain(output/name,record,mode=mode,shards=4,asset=asset,kind=kind)
                reader=SourceChain(path,record,record['end_ms'])
                try:
                    export.replay_decision(reader,record['start_ms']+17*GRID_MS)
                    ledger=reader.identity_ledger_path
                    try:reader.close()
                    except ValueError as error:blocked=True;reason=str(error)
                    else:blocked=False;reason=None
                    checks[name+'_blocked']=blocked
                    checks[name+'_bounded_cleanup']=reader.closed and reader.identity_ledger_path is None and not ledger.exists()
                    cases.append({'case':name,'blocked':blocked,'error':reason,'chain':str(path),
                        'receipt_gap_ms':records[-1]['received_at_ms']-records[0]['received_at_ms'],
                        'census':reader.source_census})
                finally:reader.abort()
    for mode in ('valid','boundary_valid'):
        root=output/('positive-'+mode)
        path,mono_path,cuts,_=make_identity_chain(root,record,mode=mode,shards=4,asset=ASSETS[1],kind='mood')
        mono=sqlite3.connect(mono_path.as_uri()+'?mode=ro&immutable=1',uri=True)
        reader=SourceChain(path,record,record['end_ms'])
        try:
            for index,moment in enumerate((cuts[1]-GRID_MS,cuts[1],cuts[1]+GRID_MS,cuts[3])):
                checks[mode+'_replay_parity_'+str(index)]=export.replay_decision(reader,moment)==export.replay_decision(mono,moment)
            reader.close()
            census=reader.source_census;ledger=census['global_identity_ledger']
            checks[mode+'_all_owned_keys_counted']=(ledger['checked_session_ids']==4 and
                ledger['checked_frame_ids']==8 and ledger['checked_session_sequences']==8 and ledger['checked_event_ids']==4)
            checks[mode+'_key_row_and_byte_bound']=(ledger['maximum_key_batch_rows']<=ledger['key_batch_row_cap'] and
                ledger['maximum_key_batch_bytes']<=ledger['key_batch_byte_cap'])
            checks[mode+'_disk_cache_bounds_and_cleanup']=(ledger['maximum_database_bytes']<=ledger['database_byte_cap'] and
                ledger['maximum_temporary_bytes']<=ledger['temporary_byte_cap'] and ledger['cleanup_completed'])
        finally:mono.close();reader.abort()
        with (root/'full-export.log').open('w') as log,contextlib.redirect_stdout(log):
            audit=export.export_matrix(path,reg,plan,root/'matrix',now_ms=record['end_ms'],synthetic_eval=True)
        with (root/'matrix/matrix.csv').open(newline='') as stream:
            rows=list(csv.DictReader(stream))
        checks[mode+'_all10080_unknown_loss_opportunities_retained']=len(rows)==10080 and audit['opportunities']==10080 and all(row['label']=='' for row in rows)
        checks[mode+'_complete_census_zero_violations']=audit['source_census']['violations']==0 and audit['source_census']['checked_receipts']==8
        cases.append({'case':mode,'audit':audit,'matrix':str(root/'matrix/matrix.csv')})
    # Actual export paths reject both early and late failures. A late failure
    # may leave partial CSV evidence but cannot publish a successful manifest.
    for mode in ('null_transition','session','contradictory_event'):
        root=output/('full-export-'+mode)
        path,_,_,_=make_identity_chain(root,record,mode=mode,shards=4)
        with (root/'export.log').open('w') as log,contextlib.redirect_stdout(log):
            try:export.export_matrix(path,reg,plan,root/'matrix',now_ms=record['end_ms'])
            except ValueError as error:blocked=True;reason=str(error)
            else:blocked=False;reason=None
        checks['full_export_'+mode+'_no_success_manifest']=blocked and not (root/'matrix/manifest.json').exists() and not (root/'matrix/audit.json').exists()
        cases.append({'case':'full-export-'+mode,'blocked':blocked,'error':reason,'chain':str(path)})
    result={'schema':'otc_whole_chain_identity_eval_v1','pass':all(checks.values()),'checks':checks,
        'threshold':'every held-out SQL/session/global identity attack rejects; full population/parity and metadata bounds hold',
        'reference':'frozen round3 NULL-session/global-event/global-session repro; unchanged original model/data procedure',
        'fixtures':'synthetic shifted UTC schedule; both assets, all3 kinds,4 monotone archives',
        'fit_calls':0,'network_calls':0,'broker_calls':0}
    (output/'cases.json').write_text(canonical(cases)+'\n')
    (output/'eval.json').write_text(canonical(result)+'\n')
    print(canonical(result));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();raise SystemExit(0 if evaluate(args.output)['pass'] else 1)
