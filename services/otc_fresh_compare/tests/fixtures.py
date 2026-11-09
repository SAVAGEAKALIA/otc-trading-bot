"""Deterministic synthetic receipts only. No collector transport or broker calls."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import random
import sqlite3
from contracts.otc_fresh_v1 import ASSETS,GRID_MS,canonical,digest,sha256
from services.otc_fresh_compare.compiler import ROOT,freeze_plan

PROTOCOL=Path(__file__).with_name('collector_protocol.py')
spec=importlib.util.spec_from_file_location('otc_existing_collector_protocol',PROTOCOL)
protocol=importlib.util.module_from_spec(spec);spec.loader.exec_module(protocol)

def registration(root,start='2026-11-14T00:00:00Z'):
    plan=root/'plan.json';freeze_plan(plan)
    record=protocol.make_registration(start,now_ms=protocol.parse_start(start)-86400000,
        root=PROTOCOL.parent,research_source_root=ROOT)
    path=root/'registration.json';path.write_text(canonical(record)+'\n')
    return record,path,plan

DDL='''
CREATE TABLE registration(singleton INTEGER PRIMARY KEY,record_json TEXT,record_sha256 TEXT);
CREATE TABLE sessions(session_id TEXT,transition TEXT,at_ms INTEGER,detail_json TEXT);
CREATE TABLE receipts(frame_id TEXT PRIMARY KEY,session_id TEXT,sequence INTEGER,received_at_ms INTEGER,monotonic_ns INTEGER,envelope_json TEXT,envelope_sha256 TEXT);
CREATE TABLE observations(event_id TEXT PRIMARY KEY,frame_id TEXT,asset TEXT,kind TEXT,source TEXT,available_ms INTEGER,observation_json TEXT,lineage_json TEXT,clock_status TEXT);
CREATE TABLE health(health_id TEXT,session_id TEXT,at_ms INTEGER,code TEXT,detail_json TEXT);
CREATE INDEX observations_causal ON observations(available_ms);
'''

def collector_boundary(root,record,*,positive=True,gap_every=0,seed=90137,first_only=False):
    folder=root/'snapshot';folder.mkdir();database=folder/'receipts.sqlite';connection=sqlite3.connect(database)
    # Pure synthetic fixture construction only. Production recorder durability
    # stays untouched; these disposable inputs need no journal/fsync.
    connection.execute('PRAGMA journal_mode=MEMORY')
    connection.execute('PRAGMA synchronous=OFF')
    connection.executescript(DDL)
    connection.execute('INSERT INTO registration VALUES (1,?,?)',(canonical(record),digest(record)))
    for transition,moment in [('open',record['start_ms']),('close',record['end_ms'])]:
        connection.execute('INSERT INTO sessions VALUES (?,?,?,?)',('synthetic',transition,moment,'{}'))
    rng=random.Random(seed);count=(record['end_ms']-record['start_ms'])//GRID_MS
    pattern=[99.0,100.0,101.0,101.0,100.0,99.0,99.0]
    prices={asset:([pattern[index%len(pattern)] for index in range(count+1)] if positive
        else [float(rng.choice((99,100,101))) for index in range(count+1)]) for asset in ASSETS}
    sequence=0
    def add(moment,asset,kind,value):
        nonlocal sequence
        sequence+=1;frame=f'replay-frame-{sequence}';identity=f'replay-event-{sequence}'
        source={'quote':'quote_samples','mood':'mood_samples','payout':'commission-stream'}[kind]
        row={'event_id':identity,'broker':'iqoption','asset':asset,'product':'turbo-option',
             'source':source,'kind':kind,'available_ms':moment,'event_ms':moment,
             'value':str(value),'clock_id':'receiver_utc','quality':'received'}
        lineage={'clock_status':'ok','received_at_ms':moment,'received_at_ns':moment*1000000,'source_event_ms':moment,
                 'fixture':'synthetic-core-replay','quote_product_basis':'explicit_assumed'}
        envelope={'frame_id':frame,'session_id':'synthetic','sequence':sequence,'received_at_ms':moment,
                  'received_at_ns':moment*1000000,
                  'monotonic_ns':sequence,'events':[{'observation':row,'lineage':lineage}],'health':None}
        connection.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',
            (frame,'synthetic',sequence,moment,sequence,canonical(envelope),digest(envelope)))
        connection.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',
            (identity,frame,asset,kind,source,moment,canonical(row),canonical(lineage),'ok'))
    for index in range(1 if first_only else count):
        moment=record['start_ms']+index*GRID_MS
        for asset in ASSETS:
            current=prices[asset][index];following=prices[asset][index+1]
            if not gap_every or index%gap_every:
                add(moment,asset,'quote',current)
                add(moment+60000,asset,'quote',100.0)
            # The interval's latent regime is chosen before its receipts; it
            # drives both observed mood and the following quote in the recipe.
            latent=(1,1,0,-1,-1,0,0)[index%7]
            mood=(.9 if latent>0 else .1 if latent<0 else .5) if positive else rng.random()
            add(moment,asset,'mood',mood);add(moment,asset,'payout',.85)
    # Complete the final expiry while retaining the original last-before policy.
    if not first_only:
        for asset in ASSETS:add(record['end_ms']-1,asset,'quote',prices[asset][-1])
    connection.commit();observed=connection.execute('SELECT count(*) FROM observations').fetchone()[0]
    connection.close()
    (folder/'registration.json').write_text(canonical(record)+'\n')
    manifest={'schema':'fresh_otc_export_v1','registration_sha256':record['registration_sha256'],
        'code_sha256':record['code_sha256'],'config_sha256':record['config_sha256'],
        'observation_count':observed,'admissible_clock_observation_count':observed,'unclosed_sessions':0,
        'hashes':{'receipts.sqlite':sha256(database),'registration.json':sha256(folder/'registration.json')},
        'source_clock':'receiver_utc','quote_product_basis':'explicit_assumed',
        'evidence_class':'received_price_proxy','research_scope':'exploratory_development'}
    manifest['manifest_sha256']=digest(manifest)
    (folder/'manifest.json').write_text(canonical(manifest)+'\n')
    return folder
