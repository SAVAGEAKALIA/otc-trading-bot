"""Audit spent source fields without manufacturing missing execution evidence."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3
import time


def hash_file(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            value.update(block)
    return value.hexdigest()


def audit(source, output):
    source,output=Path(source),Path(output)
    output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((source/'manifest.json').read_text())
    observations=source/'observations.jsonl'
    lineage=source/'source_lineage.jsonl'
    if hash_file(observations)!=manifest['observations_sha256'] or hash_file(lineage)!=manifest['source_lineage_sha256']:
        raise ValueError('Spent canonical source changed')
    counts=Counter()
    for path,label in ((observations,'observation'),(lineage,'lineage')):
        with path.open() as stream:
            for line in stream:
                record=json.loads(line)
                counts[label+'_rows']+=1
                if label=='observation':
                    counts[record['kind']+'_observations']+=1
                for field in ('session_id','received_at_ns','offered_expiries_ms','offer_state',
                              'accepted_strike','accepted_expiry_ms','settlement_cash_return'):
                    counts[label+'_present_'+field]+=field in record
    snapshot=Path('/tmp/binary-training/resume-data/source_snapshot.sqlite')
    connection=sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True)
    tables={row[0]:[column[0] for column in connection.execute('SELECT name FROM pragma_table_info(?)',(row[0],))]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    connection.close()
    start=int(datetime(2026,7,31,tzinfo=timezone.utc).timestamp())*1000
    end=int(datetime(2026,8,21,tzinfo=timezone.utc).timestamp())*1000
    opportunities=(end-start)//120_000*2
    failures=['No physical receiver-session identity in canonical quote lineage',
              'No explicit open/negative offer state or offered expiry list',
              'No accepted strikes/expiries or broker cash settlements',
              'Receiver availability is milliseconds; finer receipt order is unobserved']
    report={'schema':'otc_new_strategy_historical_admission_v1',
            'status':'BLOCKED_FOR_ECONOMIC_EVIDENCE', 'started_at_ms':time.time_ns()//1_000_000,
            'audit_code_sha256':hash_file(Path(__file__)),
            'source_manifest_sha256':hash_file(source/'manifest.json'),
            'source_id':manifest['source_id'], 'source_sha256_reference':manifest['source_sha256'],
            'canonical_observations_sha256':manifest['observations_sha256'],
            'canonical_lineage_sha256':manifest['source_lineage_sha256'], 'canonical_hashes_verified':True,
            'counts':dict(sorted(counts.items())), 'raw_schema':tables,
            'historical_population':{'start_ms':start,'end_ms':end,'grid_ms':120_000,
                                     'assets':['EURUSD-OTC','GBPUSD-OTC'],'opportunities':opportunities},
            'policies':{'4':'leader_burst_flat_target_v1','5':'three_step_burst_fade_v1'},
            'opportunities_not_economically_scored':opportunities,
            'mean_unit_return':None, 'accepted_cash_return':None, 'edge_claim':False,
            'reasons':failures,'missing_fields_synthesized':False,
            'current_fresh_cohort_accessed':False,'orders':0,'broker_calls':0}
    (output/'admission.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    report=audit(**vars(parser.parse_args()))
    print(json.dumps({key:report[key] for key in ('status','counts','mean_unit_return','opportunities_not_economically_scored','reasons')},sort_keys=True))
