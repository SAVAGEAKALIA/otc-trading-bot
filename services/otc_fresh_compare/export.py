"""Bounded receipt-window SQL replay through the unchanged original dataset builder."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
from datetime import datetime,timezone
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from contracts.otc_fresh_v1 import ASSETS,CONFIG,DAY_MS,GRID_MS,canonical,digest,sha256,strict_json,validate_registration
from contracts.otc_v1 import Observation,Opportunity
from contracts.otc_v1.training_schema import COLUMNS,MANIFEST_SCHEMA
from services.otc_research.dataset import build_rows
from services.otc_research.export import canonical_rows
from .compiler import compile_trainer,validate_plan,ROOT

MAX_WINDOW_ROWS=20000
MAX_RECORD_BYTES=65536
MAX_ENVELOPE_BYTES=1048576
MAX_WINDOW_BYTES=16*1024*1024
FETCH_BATCH=256
NS_PER_MS=1000000

def validate_source_scope(connection,record,*,min_session_open_ms=None):
    from .census import validate_source_scope as census
    return census(connection,record,min_session_open_ms=min_session_open_ms,
        record_bytes=MAX_RECORD_BYTES,envelope_bytes=MAX_ENVELOPE_BYTES)

def boundary(snapshot,registration,plan_path,now_ms):
    snapshot=Path(snapshot).resolve(strict=True)
    record=strict_json(Path(registration).read_text())
    limits=validate_registration(record);plan=validate_plan(plan_path)
    if type(now_ms) is not int or now_ms<record['end_ms']:raise ValueError('Fresh collection has not finished')
    if plan['original_source_frozen_at_ms']>=record['start_ms']:raise ValueError('Original model source was not frozen before start')
    for name,value in plan['original_files'].items():
        if record['research_code_files'].get(name)!=value:raise ValueError('Registered original source changed: '+name)
    if snapshot.is_file():
        from .source_chain import SourceChain
        connection=SourceChain(snapshot,record,now_ms)
        source_manifest={'source_type':'closed_sqlite_chain','receipt_source_sha256':sha256(snapshot),
            'source_lineage':[{'source_id':item['path'],'sha256':item['sqlite_sha256']} for item in connection.segments],
            'registration_sha256':record['registration_sha256']}
        return connection,record,plan,source_manifest,snapshot.read_bytes()
    raw=(snapshot/'manifest.json').read_bytes();manifest=strict_json(raw)
    lock=dict(manifest);expected=lock.pop('manifest_sha256',None)
    if expected!=digest(lock) or manifest.get('schema')!='fresh_otc_export_v1':raise ValueError('Unsupported collector backup boundary')
    if manifest.get('registration_sha256')!=record['registration_sha256'] or manifest.get('code_sha256')!=record['code_sha256'] or manifest.get('config_sha256')!=record['config_sha256']:
        raise ValueError('Collector boundary registration/source/config changed')
    file_hashes=manifest.get('hashes')
    if not isinstance(file_hashes,dict) or 'receipts.sqlite' not in file_hashes:raise ValueError('Immutable receipt backup hash is required')
    for name,value in file_hashes.items():
        path=snapshot/name
        if Path(name).name!=name or path.is_symlink() or not path.is_file() or sha256(path)!=value:
            raise ValueError('Immutable collector source changed: '+name)
    database=snapshot/'receipts.sqlite'
    connection=sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Receipt backup integrity failed')
        stored=connection.execute('SELECT record_json,record_sha256 FROM registration WHERE singleton=1').fetchone()
        if stored is None or strict_json(stored[0])!=record or stored[1]!=digest(record):raise ValueError('Backup registration changed')
        unclosed=connection.execute("SELECT count(*) FROM sessions s WHERE s.transition='open' AND NOT EXISTS (SELECT 1 FROM sessions c WHERE c.session_id=s.session_id AND c.transition='close')").fetchone()[0]
        latest=connection.execute("SELECT max(at_ms) FROM sessions WHERE transition='close'").fetchone()[0]
        if unclosed or type(latest) is not int or latest<record['end_ms'] or latest>now_ms:raise ValueError('Snapshot has unfinished collection sessions')
        if manifest.get('unclosed_sessions')!=unclosed:raise ValueError('Snapshot session inventory changed')
        census=validate_source_scope(connection,record)
        manifest={**manifest,'source_census':census}
        observed=connection.execute('SELECT count(*) FROM observations').fetchone()[0]
        clock_admitted=connection.execute("SELECT count(*) FROM observations WHERE clock_status='ok'").fetchone()[0]
        if manifest.get('observation_count')!=observed or manifest.get('admissible_clock_observation_count')!=clock_admitted:
            raise ValueError('Snapshot observation inventory changed')
    except Exception:
        connection.close();raise
    return connection,record,plan,manifest,raw

def receipt_window(connection,decision,expiry):
    """Complete simultaneous receipt batches fit a strict bounded list, or block."""
    earliest=decision-max(CONFIG['max_age_ms']['payout'],CONFIG['lookback_ms']+CONFIG['max_age_ms']['quote'])
    count=connection.execute('SELECT count(*) FROM observations WHERE available_ms BETWEEN ? AND ?',
                             (earliest,expiry)).fetchone()[0]
    if count>MAX_WINDOW_ROWS:raise ValueError('Receipt window exceeds deterministic memory budget; no truncation is permitted')
    byte_count=connection.execute('SELECT coalesce(sum(length(CAST(o.observation_json AS BLOB))+length(CAST(o.lineage_json AS BLOB))+length(CAST(r.envelope_json AS BLOB))),0) FROM observations o JOIN receipts r ON r.frame_id=o.frame_id WHERE o.available_ms BETWEEN ? AND ?',
                                 (earliest,expiry)).fetchone()[0]
    if byte_count>MAX_WINDOW_BYTES:raise ValueError('Receipt window exceeds serialized byte memory budget')
    oversize=connection.execute('SELECT count(*) FROM observations o JOIN receipts r ON r.frame_id=o.frame_id WHERE o.available_ms BETWEEN ? AND ? AND (length(CAST(o.observation_json AS BLOB))>? OR length(CAST(o.lineage_json AS BLOB))>? OR length(CAST(r.envelope_json AS BLOB))>?)',
                               (earliest,expiry,MAX_RECORD_BYTES,MAX_RECORD_BYTES,MAX_ENVELOPE_BYTES)).fetchone()[0]
    if oversize:raise ValueError('Receipt record exceeds deterministic memory budget')
    cursor=connection.execute('SELECT o.observation_json,o.lineage_json,o.clock_status,r.received_at_ms,o.available_ms,o.asset,o.kind,o.source,o.event_id,r.frame_id,r.envelope_json,r.envelope_sha256 FROM observations o JOIN receipts r ON r.frame_id=o.frame_id WHERE o.available_ms BETWEEN ? AND ? ORDER BY o.available_ms,o.event_id',(earliest,expiry))
    observations=[];metadata={};seen=0
    identities={}
    while True:
        batch=cursor.fetchmany(FETCH_BATCH)
        if not batch:break
        for raw,lineage,clock_status,receipt,available,asset,kind,source,event_id,frame_id,envelope_raw,envelope_sha in batch:
            seen+=1;row=strict_json(raw);meta=strict_json(lineage);envelope=strict_json(envelope_raw)
            if digest(envelope)!=envelope_sha or envelope.get('frame_id')!=frame_id or type(envelope.get('received_at_ms')) is not int or envelope.get('received_at_ms')!=receipt:
                raise ValueError('Immutable receipt envelope/hash/clock changed')
            entries=envelope.get('events')
            if not isinstance(entries,list) or sum(item.get('observation')==row and item.get('lineage')==meta for item in entries if isinstance(item,dict))!=1:
                raise ValueError('Observation differs from its immutable receipt envelope')
            event=Observation(**row)
            if event.asset not in ASSETS or event.broker!='iqoption' or event.product!='turbo-option' or event.clock_id!='receiver_utc':
                raise ValueError('Fresh observation scope changed')
            if type(receipt) is not int or type(available) is not int or event.available_ms!=receipt or event.event_ms!=receipt or available!=receipt:
                raise ValueError('Canonical receipt clock does not match immutable receipt')
            if (row['event_id'],row['asset'],row['kind'],row['source'])!=(event_id,asset,kind,source):
                raise ValueError('Observation SQL/canonical identity changed')
            if row['source'] not in CONFIG['source_priority'][row['kind']]:raise ValueError('Unregistered observation source')
            if meta.get('clock_status')!=clock_status:raise ValueError('Observation lineage clock status changed')
            if clock_status=='ok':
                received_ns=meta.get('received_at_ns')
                if type(received_ns) is not int or received_ns<0 or received_ns//1000000!=receipt:
                    raise ValueError('Fresh v2 receipt needs exact nanoseconds matching its millisecond floor')
                if envelope.get('received_at_ns',received_ns)!=received_ns:
                    raise ValueError('Receipt envelope/lineage nanoseconds changed')
                # The original builder accepts integer clock ticks. Replay in
                # exact nanosecond ticks with all physical durations scaled by
                # the same factor; its source and selection rules stay intact.
                row={**row,'available_ms':received_ns,'event_ms':received_ns}
                identity=digest({'observation':row,'lineage':meta})
                if row['event_id'] in identities:
                    if identities[row['event_id']]!=identity:raise ValueError('Cross-source observation identity conflict')
                else:observations.append(row);metadata[row['event_id']]=meta;identities[row['event_id']]=identity
    if seen!=count:raise ValueError('Receipt observation has no matching immutable frame')
    groups={}
    for row in observations:
        groups.setdefault((row['asset'],row['kind'],row['source'],row['available_ms']),[]).append(row)
    conflicts=[];excluded=set()
    for (asset,kind,source,moment),events in groups.items():
        if len({Decimal(event['value']) for event in events})>1:
            ids=tuple(sorted(event['event_id'] for event in events))
            conflicts.append({'asset':asset,'kind':kind,'source':source,'received_at_ns':moment,
                'batch_basis':'exact_received_at_ns','event_ids':list(ids),
                'values':sorted({event['value'] for event in events})})
            excluded.update(event['event_id'] for event in events)
        elif len(events)>1:
            newest=max(events,key=lambda event:event['event_id'])
            excluded.update(event['event_id'] for event in events if event is not newest)
    observations=[row for row in observations if row['event_id'] not in excluded]
    return observations,metadata,{'rows':count,'serialized_bytes':byte_count,'conflicts':conflicts}

def replay_decision(connection,decision):
    opportunities=[Opportunity(f'{asset}@{decision}','iqoption',asset,'turbo-option','receiver_utc',
        decision,decision+GRID_MS,decision+CONFIG['max_entry_wait_ms'],'hypothetical',None,0).as_record() for asset in ASSETS]
    observations,metadata,count=receipt_window(connection,decision,decision+GRID_MS)
    tick_config={**CONFIG,'max_age_ms':{kind:value*NS_PER_MS for kind,value in CONFIG['max_age_ms'].items()}}
    for key in ('max_entry_wait_ms','max_settlement_wait_ms','lookback_ms'):
        tick_config[key]=CONFIG[key]*NS_PER_MS
    tick_opportunities=[{**op,**{key:op[key]*NS_PER_MS for key in
        ('decision_ms','expiry_ms','latest_entry_ms','acceptance_delay_ms')}} for op in opportunities]
    result=build_rows(observations,tick_opportunities,tick_config)
    events={row['event_id']:row for row in observations}
    decision_ns=decision*NS_PER_MS
    checked=0
    for row,opportunity in zip(result['rows'],sorted(opportunities,key=lambda item:(item['decision_ms'],item['opportunity_id']))):
        features=row['lineage'];ids=[features[name] for name in ('decision_quote','payout','lookback_quote','own_mood') if features[name] is not None]
        ids.extend(features['market_mood'])
        invalid_feature=False
        for identity in ids:
            if events[identity]['available_ms']>decision_ns:raise ValueError('Future feature receipt was referenced')
            receipt_ns=metadata[identity]['received_at_ns'];checked+=1
            cutoff=decision-CONFIG['lookback_ms'] if identity==features['lookback_quote'] else decision
            if receipt_ns>cutoff*NS_PER_MS:raise ValueError('Future nanosecond feature receipt was referenced')
            if cutoff*NS_PER_MS-receipt_ns>CONFIG['max_age_ms'][events[identity]['kind']]*NS_PER_MS:
                invalid_feature=True
        if features['lookback_quote'] is not None and events[features['lookback_quote']]['available_ms']>(decision-CONFIG['lookback_ms'])*NS_PER_MS:
            raise ValueError('Lookback references a future receipt')
        terminal=features['terminal_quote'];strike=features['modeled_strike']
        if terminal is not None and events[terminal]['available_ms']>row['expiry_ms']:raise ValueError('Terminal quote is after expiry')
        if strike is not None and not decision_ns<=events[strike]['available_ms']<=(decision+CONFIG['max_entry_wait_ms'])*NS_PER_MS:
            raise ValueError('Modeled entry is outside fixed entry window')
        feature_conflict=False;outcome_conflict=False
        stale_terminal=terminal is not None and row['expiry_ms']-metadata[terminal]['received_at_ns']>CONFIG['max_age_ms']['quote']*NS_PER_MS
        for conflict in count['conflicts']:
            kind=conflict['kind'];moment=conflict['received_at_ns'];same=conflict['asset']==opportunity['asset']
            if kind=='mood' and decision_ns-CONFIG['max_age_ms']['mood']*NS_PER_MS<=moment<=decision_ns:feature_conflict=True
            if same and kind in ('quote','payout') and decision_ns-CONFIG['max_age_ms'][kind]*NS_PER_MS<=moment<=decision_ns:feature_conflict=True
            if same and kind=='quote':
                lookback=(decision-CONFIG['lookback_ms'])*NS_PER_MS
                if lookback-CONFIG['max_age_ms']['quote']*NS_PER_MS<=moment<=lookback:feature_conflict=True
                if decision_ns<=moment<=decision_ns+CONFIG['max_entry_wait_ms']*NS_PER_MS or row['expiry_ms']-CONFIG['max_age_ms']['quote']*NS_PER_MS<=moment<=row['expiry_ms']:
                    outcome_conflict=True
        if invalid_feature or feature_conflict:
            row.update(status='ineligible',features=None,label=None,training_eligible=False,unit_pnl=None)
            row['reason_codes'].append('conflicting_received_batch_at_feature_cutoff' if feature_conflict else 'feature_receipt_ns_stale')
        elif (outcome_conflict or stale_terminal) and row['status']!='ineligible':
            row.update(status='unresolved',label=None,training_eligible=False,unit_pnl=None)
            row['reason_codes'].append('conflicting_received_batch_at_outcome_cutoff' if outcome_conflict else 'terminal_receipt_ns_stale')
    count['nanosecond_feature_references_checked']=checked
    rows=canonical_rows(result,tick_opportunities,observations)
    # External contracts and model columns remain milliseconds. Ceiling ages
    # avoids understating the true age of a fractional-millisecond receipt.
    for row in rows:
        row['decision_ms']//=NS_PER_MS;row['expiry_ms']//=NS_PER_MS
        for key in ('f_quote_age_ms','f_mood_age_ms','f_payout_age_ms'):
            if row[key]!='':row[key]=(row[key]+NS_PER_MS-1)//NS_PER_MS
    for row in result['rows']:
        row['decision_ms']//=NS_PER_MS;row['expiry_ms']//=NS_PER_MS
        if row['features'] is not None:
            for key in ('quote_age_ms','mood_age_ms','payout_age_ms'):
                if row['features'][key] is not None:row['features'][key]=(row['features'][key]+NS_PER_MS-1)//NS_PER_MS
    return rows,result['rows'],count

def export_matrix(snapshot,registration,plan,output,*,now_ms=None,synthetic_eval=False):
    output=Path(output).resolve();snapshot=Path(snapshot).resolve()
    if output==snapshot or snapshot in output.parents or output.exists():raise ValueError('Fresh matrix output must be a new separate directory')
    now_ms=time.time_ns()//1000000 if now_ms is None else now_ms
    connection,record,source_plan,manifest,manifest_bytes=boundary(snapshot,registration,plan,now_ms)
    output.mkdir(parents=True);counts=Counter();labels=Counter();reasons=Counter();max_rows=0;max_bytes=0;done=0;ns_checked=0;conflict_windows=0
    expected=(record['end_ms']-record['start_ms'])//GRID_MS*len(ASSETS)
    def emit(phase):
        progress={'event':'Fresh OTC core replay','phase':phase,'done':done,'total':expected,
                  'percent_done':done/expected*100,'eta_seconds':None if done<expected else 0,
                  'max_window_rows':max_rows,'utc':datetime.now(timezone.utc).isoformat()}
        line=canonical(progress);print(line,flush=True)
        with (output/'progress.log').open('a') as stream:stream.write(line+'\n')
    replayed=False
    try:
        with (output/'matrix.csv').open('w',newline='') as stream,(output/'decision_lineage.jsonl').open('w') as lineage,(output/'receipt_batch_conflicts.jsonl').open('w') as conflict_stream:
            writer=csv.DictWriter(stream,fieldnames=COLUMNS);writer.writeheader()
            for decision in range(record['start_ms'],record['end_ms'],GRID_MS):
                rows,details,loaded=replay_decision(connection,decision);max_rows=max(max_rows,loaded['rows']);max_bytes=max(max_bytes,loaded['serialized_bytes'])
                ns_checked+=loaded['nanosecond_feature_references_checked']
                if loaded['conflicts']:
                    conflict_windows+=1
                    conflict_stream.write(canonical({'decision_ms':decision,'complete_conflicting_batches':loaded['conflicts']})+'\n')
                for row,detail in zip(rows,details):
                    if synthetic_eval:row['evidence_class']='synthetic_training_eval'
                    writer.writerow(row);lineage.write(canonical(detail)+'\n')
                    counts[row['status']]+=1;labels[row['label']]+=1;reasons.update(detail['reason_codes']);done+=1
                if done%1440==0:emit('replaying')
        replayed=True
    finally:
        if not replayed and hasattr(connection,'abort'):connection.abort()
        else:connection.close()
    # The immutable source must still match after every replay window.
    is_chain=manifest.get('source_type')=='closed_sqlite_chain'
    if is_chain:
        if snapshot.read_bytes()!=manifest_bytes:raise ValueError('Source chain changed during replay')
    elif (snapshot/'manifest.json').read_bytes()!=manifest_bytes or any(sha256(snapshot/name)!=value for name,value in manifest['hashes'].items()):
        raise ValueError('Collector snapshot changed during replay')
    if done!=expected:raise ValueError('Fresh replay did not retain every fixed-grid opportunity')
    evidence='synthetic_training_eval' if synthetic_eval else 'received_price_proxy'
    matrix_manifest={'schema':MANIFEST_SCHEMA,'expiry_basis':'hypothetical','product_mapping':'explicit_assumed',
        'clock':'receiver_utc','feature_availability':'receiver_receipt_lte_decision',
        'outcome_basis':'last_received_quote_at_or_before_expiry','input_sha256':sha256(output/'matrix.csv'),
        'promotable':False,'horizon_seconds':120,'assets':list(ASSETS),'evidence_classes':[evidence],
        'source_lineage':[{**item,'kind':'synthetic_fixture' if synthetic_eval else 'received_quote_observations','clock':'receiver_utc'} for item in (manifest['source_lineage'] if is_chain else [{'source_id':str(snapshot/'receipts.sqlite'),'sha256':manifest['hashes']['receipts.sqlite']}])],
        'metadata':{'fresh_registration':record,'compiler_plan_sha256':source_plan['plan_sha256'],
            'original_training_sha256':source_plan['original_training_sha256'],
            'expected_opportunities':expected,'fresh_confirmation':False,'capital_permission':False,
            'synthetic_replay':synthetic_eval,'source_manifest_sha256':sha256(snapshot if is_chain else snapshot/'manifest.json'),
            'availability_quantization':'exact_utc_nanosecond_replay_then_conservative_millisecond_ages',
            'decision_lineage_sha256':sha256(output/'decision_lineage.jsonl')}}
    (output/'manifest.json').write_text(canonical(matrix_manifest)+'\n')
    audit={'schema':'otc_fresh_core_audit_v1','status':'DONE','opportunities':done,'expected_opportunities':expected,
        'statuses':dict(counts),'labels':dict(labels),'reason_counts':dict(reasons),
        'measured_future_feature_references':0,'maximum_loaded_window_rows':max_rows,
        'nanosecond_feature_references_checked':ns_checked,'measured_future_nanosecond_feature_references':0,
        'decision_windows_with_complete_receipt_batch_conflicts':conflict_windows,
        'receipt_batch_conflicts_sha256':sha256(output/'receipt_batch_conflicts.jsonl'),
        'window_memory_budget_rows':MAX_WINDOW_ROWS,'sql_fetch_batch':FETCH_BATCH,
        'maximum_window_serialized_bytes':max_bytes,'window_memory_budget_bytes':MAX_WINDOW_BYTES,
        'original_dataset_sha256':source_plan['original_files']['services/otc_research/dataset.py'],
        'registration_sha256':record['registration_sha256'],'promotable':False,'fresh_confirmation':False,
        'capital_permission':False,'receipt_source_sha256':manifest['receipt_source_sha256'] if is_chain else manifest['hashes']['receipts.sqlite']}
    if is_chain:audit.update(decoded_shards=connection.decoded,maximum_cross_shard_tail_rows=connection.maximum_tail_rows,source_type='closed_sqlite_chain',
        source_observations=connection.source_observations,admitted_clock_observations=connection.admitted_clock_observations)
    audit['source_census']=connection.source_census if is_chain else manifest['source_census']
    (output/'audit.json').write_text(canonical(audit)+'\n');emit('complete')
    return audit

def compare(trainer,matrix,manifest,output):
    trainer=Path(trainer);proof=strict_json(trainer.with_suffix('.proof.json').read_text())
    if proof.get('schema')!='otc_static_trainer_transformation_v1' or proof.get('frozen_training_sha256')!=sha256(trainer):
        raise ValueError('Frozen trainer proof/source changed')
    # Recreate the entire permitted source transformation before executing the
    # supplied module. A self-edited digest/proof cannot authorize changed
    # thresholds, chronology, imports or admission code.
    data=strict_json(Path(manifest).read_text());metadata=data.get('metadata',{})
    plan_path=trainer.with_suffix('.plan.json');plan=validate_plan(plan_path)
    if plan['plan_sha256']!=metadata.get('compiler_plan_sha256'):raise ValueError('Comparison compiler plan differs from matrix')
    with tempfile.TemporaryDirectory(prefix='otc-static-replay-proof-') as folder:
        root=Path(folder);reg=root/'registration.json';reg.write_text(canonical(metadata.get('fresh_registration'))+'\n')
        expected=root/'training.py';compile_trainer(reg,plan_path,expected)
        if expected.read_bytes()!=trainer.read_bytes():raise ValueError('Trainer is not the exact deterministic frozen-source transformation')
    spec=importlib.util.spec_from_file_location('otc_frozen_fresh_trainer',trainer)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module.run_comparison(Path(matrix),Path(manifest),Path(output),'CPU')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('export','compare'))
    parser.add_argument('--output',required=True,type=Path)
    source=parser.add_mutually_exclusive_group();source.add_argument('--snapshot',type=Path);source.add_argument('--chain',type=Path)
    parser.add_argument('--registration',type=Path);parser.add_argument('--plan',type=Path)
    parser.add_argument('--trainer',type=Path);parser.add_argument('--matrix',type=Path);parser.add_argument('--manifest',type=Path)
    parser.add_argument('--synthetic-eval',action='store_true')
    parser.add_argument('--wait-chain',action='store_true')
    args=parser.parse_args()
    if args.action=='export':
        if args.snapshot is None and args.chain is None:parser.error('Export requires --snapshot or --chain')
        if args.wait_chain:
            if args.chain is None:parser.error('--wait-chain requires --chain')
            from .source_chain import wait_for_chain
            record=strict_json(args.registration.read_text());validate_registration(record)
            wait_for_chain(args.chain,record)
        result=export_matrix(args.chain or args.snapshot,args.registration,args.plan,args.output,synthetic_eval=args.synthetic_eval)
    else:result=compare(args.trainer,args.matrix,args.manifest,args.output)
    print(canonical({'status':result['status'],'promotable':False}))

if __name__=='__main__':main()
