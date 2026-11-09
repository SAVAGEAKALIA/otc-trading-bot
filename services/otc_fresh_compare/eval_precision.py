"""Held-out raw-nanosecond and complete-batch attacks on the core source path."""
from __future__ import annotations
import argparse
from pathlib import Path
import sqlite3
from contracts.otc_fresh_v1 import ASSETS,CONFIG,GRID_MS,canonical,digest,strict_json
from contracts.otc_v1 import Opportunity
from services.otc_fresh_compare.export import replay_decision
from services.otc_fresh_compare.tests.fixtures import registration,collector_boundary
from services.otc_research.dataset import build_rows

def evaluate(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);checks={};cases=[]
    for asset in ASSETS:
        for kind in ('quote','mood','payout'):
            root=output/(asset+'-'+kind);root.mkdir();record,reg,plan=registration(root)
            snapshot=collector_boundary(root,record,first_only=True);conn=sqlite3.connect(snapshot/'receipts.sqlite')
            identity,frame,raw,meta_raw=conn.execute('SELECT event_id,frame_id,observation_json,lineage_json FROM observations WHERE asset=? AND kind=? ORDER BY available_ms LIMIT 1',(asset,kind)).fetchone()
            meta=strict_json(meta_raw);meta['received_at_ns']=record['start_ms']*1000000+999999
            envelope=strict_json(conn.execute('SELECT envelope_json FROM receipts WHERE frame_id=?',(frame,)).fetchone()[0])
            envelope['received_at_ns']=meta['received_at_ns'];envelope['events'][0]['lineage']=meta
            conn.execute('UPDATE observations SET lineage_json=? WHERE event_id=?',(canonical(meta),identity))
            conn.execute('UPDATE receipts SET envelope_json=?,envelope_sha256=? WHERE frame_id=?',(canonical(envelope),digest(envelope),frame));conn.commit()
            rows,details,stats=replay_decision(conn,record['start_ms'])
            ids=[]
            for detail in details:
                lineage=detail['lineage'];ids.extend(lineage[name] for name in ('decision_quote','payout','lookback_quote','own_mood') if lineage[name] is not None);ids.extend(lineage['market_mood'])
            label=asset+'_'+kind
            checks[label+'_fractional_future_receipt_not_referenced']=identity not in ids
            checks[label+'_opportunities_retained']=len(rows)==2
            originals=[strict_json(value) for value, in conn.execute('SELECT observation_json FROM observations')]
            op=Opportunity(f'{asset}@{record["start_ms"]}','iqoption',asset,'turbo-option','receiver_utc',record['start_ms'],record['start_ms']+GRID_MS,record['start_ms']+2000,'hypothetical',None,0).as_record()
            old=build_rows(originals,[op],CONFIG)['rows'][0]
            old_ids=list(old['lineage'].values());flat=[item for value in old_ids for item in (value if isinstance(value,list) else [value])]
            checks[label+'_old_ms_only_mutant_admits_future']=identity in flat
            cases.append({'asset':asset,'kind':kind,'raw_received_at_ns':meta['received_at_ns'],
                'decision_cutoff_ns':record['start_ms']*1000000,'canonical_floor_ms':record['start_ms'],
                'original_behavior_references_future':identity in flat,'fresh_behavior_references_future':identity in ids})
            conn.close()
    root=output/'conflicting-batch';root.mkdir();record,reg,plan=registration(root)
    snapshot=collector_boundary(root,record,first_only=True);conn=sqlite3.connect(snapshot/'receipts.sqlite')
    template=list(conn.execute("SELECT * FROM observations WHERE asset=? AND kind='quote' ORDER BY available_ms LIMIT 1",(ASSETS[0],)).fetchone())
    for index,value in enumerate(('102','103','104')):
        row=list(template);obs=strict_json(row[6]);obs['event_id']=f'conflict-{index}';obs['value']=value
        row[0]=obs['event_id'];row[1]=f'conflict-frame-{index}';row[6]=canonical(obs);meta=strict_json(row[7])
        envelope={'frame_id':row[1],'session_id':'synthetic','sequence':900000+index,
            'received_at_ms':row[5],'received_at_ns':row[5]*1000000,'events':[{'observation':obs,'lineage':meta}],'health':None}
        conn.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',(row[1],'synthetic',900000+index,row[5],900000+index,canonical(envelope),digest(envelope)))
        conn.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',row)
    conn.commit();rows,details,stats=replay_decision(conn,record['start_ms']);conn.close()
    checks['complete_four_event_batch_conflict_reported']=len(stats['conflicts'])==1 and len(stats['conflicts'][0]['event_ids'])==4
    checks['conflicting_batch_not_admitted']=rows[0]['status']=='ineligible'
    checks['conflicting_batch_preserves_other_asset']=len(rows)==2
    cases.append({'complete_conflicts':stats['conflicts'],'statuses':[row['status'] for row in rows]})
    verdict={'schema':'otc_fresh_precision_eval_v1','pass':all(checks.values()),'checks':checks,
        'cases':cases,'threshold':'all raw-nanosecond and complete-batch attacks must pass',
        'fixtures':'synthetic source replay only; no side services, credentials or broker calls'}
    (output/'eval.json').write_text(canonical(verdict)+'\n');print(canonical(verdict));return verdict

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    raise SystemExit(0 if evaluate(args.output)['pass'] else 1)
