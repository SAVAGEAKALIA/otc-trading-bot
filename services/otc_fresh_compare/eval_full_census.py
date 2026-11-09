"""Held-out canonical census and handoff attacks; no model or external calls."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import sqlite3

from contracts.otc_fresh_v1 import ASSETS,GRID_MS,canonical,digest,strict_json
from services.otc_fresh_compare.export import boundary,validate_source_scope
from services.otc_fresh_compare.source_chain import SourceChain
from services.otc_fresh_compare.tests.fixtures import registration
from services.otc_fresh_compare.tests.test_chain import focused_chain
from services.otc_fresh_compare.tests.test_full_census import (
    NS_PER_MS,mutate_archive,old_sql_census_admits,rewrite_envelope,
    seal_snapshot,single_source,
)


def evaluate(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);checks={};cases=[]
    seed=output/'seed';seed.mkdir();record,reg,plan=registration(seed,start='2026-11-21T04:00:00Z')
    for asset in ASSETS:
        for kind in ('quote','mood','payout'):
            for mode in ('lineage_ns','missing_event','sql_identity'):
                label=asset+'-'+kind+'-'+mode;root=output/label;root.mkdir()
                snapshot,connection=single_source(root,record,asset=asset,kind=kind)
                if mode=='lineage_ns':
                    envelope=strict_json(connection.execute('SELECT envelope_json FROM receipts').fetchone()[0])
                    envelope['events'][0]['lineage']['received_at_ns']+=711
                    connection.execute('UPDATE observations SET lineage_json=?',(canonical(envelope['events'][0]['lineage']),))
                    connection.execute('UPDATE receipts SET envelope_json=?,envelope_sha256=?',(canonical(envelope),digest(envelope)))
                elif mode=='missing_event':rewrite_envelope(connection,lambda e:e.update(events=[]))
                else:connection.execute("UPDATE observations SET event_id='sql-only-heldout-identity'")
                connection.commit();old_admitted=old_sql_census_admits(connection,record)
                seal_snapshot(snapshot,connection,record);blocked=False;error=None
                try:
                    result=boundary(snapshot,reg,plan,record['end_ms']);result[0].close()
                except ValueError as exc:blocked=True;error=str(exc)
                checks[label+'_old_sql_only_mutant_admits']=old_admitted
                checks[label+'_fully_rehashed_source_blocked']=blocked
                cases.append({'case':label,'old_sql_only_admitted':old_admitted,'blocked':blocked,'error':error,'snapshot':str(snapshot)})
    for mode in ('prestart','end','bool_ns','missing_ns','bad_sequence'):
        root=output/('empty-'+mode);root.mkdir();snapshot,connection=single_source(root,record,events=False)
        def mutate(envelope):
            if mode=='prestart':envelope.update(received_at_ms=record['start_ms']-1,received_at_ns=(record['start_ms']-1)*NS_PER_MS)
            elif mode=='end':envelope.update(received_at_ms=record['end_ms'],received_at_ns=record['end_ms']*NS_PER_MS)
            elif mode=='bool_ns':envelope['received_at_ns']=True
            elif mode=='missing_ns':envelope.pop('received_at_ns')
            else:envelope['sequence']=False
        rewrite_envelope(connection,mutate);old_admitted=old_sql_census_admits(connection,record)
        seal_snapshot(snapshot,connection,record);blocked=False;error=None
        try:
            result=boundary(snapshot,reg,plan,record['end_ms']);result[0].close()
        except ValueError as exc:blocked=True;error=str(exc)
        checks['empty_'+mode+'_old_sql_only_mutant_admits']=old_admitted
        checks['empty_'+mode+'_fully_rehashed_source_blocked']=blocked
        cases.append({'case':'empty-'+mode,'old_sql_only_admitted':old_admitted,'blocked':blocked,'error':error})
    root=output/'valid-census';root.mkdir();snapshot,connection=single_source(root,record,asset=ASSETS[1],kind='mood')
    first=connection.execute('SELECT received_at_ms FROM receipts').fetchone()[0]
    for sequence in range(2,514):
        frame='valid-empty-'+str(sequence);moment=first+sequence
        envelope={'frame_id':frame,'session_id':'owned','sequence':sequence,'received_at_ms':moment,
            'received_at_ns':moment*NS_PER_MS+711,'monotonic_ns':sequence,'events':[],'health':None}
        connection.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',
            (frame,'owned',sequence,moment,sequence,canonical(envelope),digest(envelope)))
    moment=record['end_ms']-1;envelope={'frame_id':'valid-empty-tail','session_id':'owned','sequence':514,
        'received_at_ms':moment,'received_at_ns':moment*NS_PER_MS+999999,'monotonic_ns':514,'events':[],'health':None}
    connection.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',
        ('valid-empty-tail','owned',514,moment,514,canonical(envelope),digest(envelope)));connection.commit()
    counts={'receipts':connection.execute('SELECT count(*) FROM receipts').fetchone()[0],
        'observations':connection.execute('SELECT count(*) FROM observations').fetchone()[0]}
    census=validate_source_scope(connection,record)
    checks['valid_all_receipts_including_empty_are_counted']=census['checked_receipts']==counts['receipts']
    checks['valid_all_observations_are_counted']=census['checked_observations']==counts['observations']
    checks['valid_census_zero_violations']=census['violations']==0
    checks['more_than_one_sql_fetch_batch_of_empty_receipts_checked']=census['checked_receipts']>512
    checks['valid_census_keeps_one_streamed_envelope_bound']=census['streamed_envelopes_at_once']==1
    checks['valid_exact_last_ns_before_global_end_checked']=census['maximum_received_at_ns']==record['end_ms']*NS_PER_MS-1
    seal_snapshot(snapshot,connection,record);result=boundary(snapshot,reg,plan,record['end_ms']);result[0].close()
    checks['valid_empty_tail_fractional_ns_boundary_admitted']=True
    cases.append({'case':'valid-census','census':census,'sql_counts':counts})
    for mode in ('backward_open','backward_receipt','valid_exact_ms_and_lag'):
        root=output/('handoff-'+mode);root.mkdir();chain_record,chain_reg,chain_plan,mono,chain,cutoff=focused_chain(root)
        if mode=='backward_open':
            mutate_archive(chain,root,1,lambda c:c.execute("UPDATE sessions SET at_ms=? WHERE transition='open'",(cutoff-7,)))
        elif mode=='backward_receipt':
            def mutate(connection):
                moment=cutoff-2*GRID_MS
                connection.execute("UPDATE sessions SET at_ms=? WHERE transition='open'",(moment,))
                frame,raw=connection.execute('SELECT frame_id,envelope_json FROM receipts LIMIT 1').fetchone()
                envelope=strict_json(raw);envelope.update(received_at_ms=moment,received_at_ns=moment*NS_PER_MS+17)
                for entry in envelope['events']:
                    entry['observation'].update(available_ms=moment,event_ms=moment)
                    entry['lineage'].update(received_at_ms=moment,received_at_ns=moment*NS_PER_MS+17)
                    connection.execute('UPDATE observations SET available_ms=?,observation_json=?,lineage_json=? WHERE event_id=?',
                        (moment,canonical(entry['observation']),canonical(entry['lineage']),entry['observation']['event_id']))
                connection.execute('UPDATE receipts SET received_at_ms=?,envelope_json=?,envelope_sha256=? WHERE frame_id=?',
                    (moment,canonical(envelope),digest(envelope),frame))
            mutate_archive(chain,root,1,mutate)
        else:
            data=strict_json(chain.read_text())
            for item in data['segments']:item['closed_at_ms']+=17
            chain.write_text(canonical(data)+'\n')
        reader=SourceChain(chain,chain_record,chain_record['end_ms']+17);blocked=False;error=None
        try:reader.close()
        except ValueError as exc:blocked=True;error=str(exc)
        finally:reader.abort()
        checks['handoff_'+mode]=(not blocked) if mode=='valid_exact_ms_and_lag' else blocked
        cases.append({'case':'handoff-'+mode,'blocked':blocked,'error':error,'chain':str(chain)})
    result={'schema':'otc_full_canonical_census_eval_v1','pass':all(checks.values()),'checks':checks,
        'threshold':'every fully rehashed canonical/inventory attack rejects; owned handoffs monotone; valid census exact',
        'fixtures':'held-out two assets, three kinds and shifted UTC schedule; no fitting or external calls',
        'network_calls':0,'broker_calls':0,'fit_calls':0}
    (output/'cases.json').write_text(canonical(cases)+'\n');(output/'eval.json').write_text(canonical(result)+'\n')
    print(canonical(result));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    raise SystemExit(0 if evaluate(args.output)['pass'] else 1)
