"""Fixed fresh chronology. All time/source checks are deterministic and portable."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

DAY_MS = 86400000
GRID_MS = 120000
ASSETS = ('EURUSD-OTC', 'GBPUSD-OTC')
PHASES = (('training','train',3),('early','early',1),('calibration','calibration',1),
          ('policy','policy',1),('diagnostic','diagnostic_test',1))
CONFIG = {'source_priority': {'quote':['quote_samples'], 'mood':['mood_samples'],
                             'payout':['commission-stream','init-snapshot']},
          'max_age_ms':{'quote':5000,'mood':60000,'payout':600000},
          'max_entry_wait_ms':2000,'max_settlement_wait_ms':0,'lookback_ms':60000,
          'tie_rule':'full_refund','terminal_policy':'last_received_before'}

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def sha256(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def strict_json(text):
    def floating(value):
        parsed=float(value)
        if not math.isfinite(parsed):raise ValueError('Nonfinite JSON number')
        return parsed
    return json.loads(text,parse_float=floating,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON constant')))

def exact_ms(value,name):
    if type(value) is not int or value<0:raise ValueError(name+' must be exact nonnegative UTC milliseconds')
    return value

def iso(value):
    seconds,milliseconds=divmod(exact_ms(value,'time'),1000)
    return datetime.fromtimestamp(seconds,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+f'.{milliseconds:03d}Z'

def hashes(value,name):
    if not isinstance(value,dict) or not value:raise ValueError(name+' needs a nonempty source lock')
    for key,fingerprint in value.items():
        if not isinstance(key,str) or Path(key).is_absolute() or '..' in Path(key).parts:
            raise ValueError(name+' contains unsafe source name')
        if not isinstance(fingerprint,str) or not re.fullmatch('[0-9a-f]{64}',fingerprint):
            raise ValueError(name+' needs exact lowercase SHA256')
    return value

def validate_registration(record):
    if not isinstance(record,dict):raise ValueError('Fresh registration must be an object')
    unlocked=dict(record);lock=unlocked.pop('registration_sha256',None)
    if lock!=digest(unlocked):raise ValueError('Registration digest changed')
    start=exact_ms(record.get('start_ms'),'start_ms');end=exact_ms(record.get('end_ms'),'end_ms')
    created=exact_ms(record.get('registered_at_ms'),'registered_at_ms')
    if exact_ms(record.get('created_ms'),'created_ms')!=created or created>=start:
        raise ValueError('Registration must be frozen before collection start')
    if start%GRID_MS or end!=start+7*DAY_MS:raise ValueError('Fresh cohort must be exactly seven days on the UTC 120s grid')
    expected={'schema':'fresh_otc_receipts_v1','scope':'exploratory_development_received_price_proxy',
        'assets':list(ASSETS),'active_ids':{'76':ASSETS[0],'81':ASSETS[1]},'product':'turbo-option',
        'quote_product_basis':'explicit_assumed','grid_ms':GRID_MS,'hypothetical_expiry_ms':GRID_MS,
        'split_basis':'registered_utc_independent_of_label_coverage',
        'registration_policy':'fixed7d_train3d_early1d_calibration1d_policy1d_diagnostic1d',
        'accepted_contract_evidence':False,'capital_promotion':False,'start_utc':iso(start),'end_utc':iso(end)}
    if any(type(record.get(name)) is not type(value) or record.get(name)!=value for name,value in expected.items()):
        raise ValueError('Fresh registration scope/configuration changed')
    if canonical(record.get('config'))!=canonical(CONFIG) or record.get('config_sha256')!=digest(CONFIG):
        raise ValueError('Original feature/entry/expiry/tie configuration changed')
    phases=[];partitions={};cursor=start
    for phase,name,days in PHASES:
        following=cursor+days*DAY_MS
        phases.append({'phase':phase,'start_ms':cursor,'end_ms':following,'start_utc':iso(cursor),'end_utc':iso(following)})
        partitions[name]={'start_ms':cursor,'end_ms':following}
        cursor=following
    # Canonical comparison preserves strict types; the list preserves ordering.
    if canonical(record.get('phases'))!=canonical(phases) or canonical(record.get('partitions'))!=canonical(partitions):
        raise ValueError('Fresh chronology was reordered, gapped or changed')
    for key,digest_key in [('code_files','code_sha256'),('research_code_files','research_code_sha256')]:
        if record.get(digest_key)!=digest(hashes(record.get(key),key)):raise ValueError(key+' digest changed')
    sources={'collector':record['code_files'],'research':record['research_code_files']}
    if record.get('source_hashes')!=sources or record.get('source_sha256')!=digest(sources):
        raise ValueError('Collector/research source lock changed')
    return tuple((name,partitions[name]['start_ms'],partitions[name]['end_ms']) for _,name,_ in PHASES)

def validate_manifest_lock(manifest,spec):
    metadata=manifest.get('metadata')
    if not isinstance(metadata,dict):raise ValueError('Fresh matrix metadata is required')
    record=metadata.get('fresh_registration')
    limits=validate_registration(record)
    if record['registration_sha256']!=spec['registration_sha256'] or [list(item) for item in limits]!=spec['limits']:
        raise ValueError('Matrix chronology differs from the frozen static trainer')
    if metadata.get('compiler_plan_sha256')!=spec['compiler_plan_sha256']:
        raise ValueError('Matrix transformation plan differs from frozen trainer')
    if metadata.get('original_training_sha256')!=spec['original_training_sha256']:
        raise ValueError('Matrix original model source differs from frozen trainer')
    if metadata.get('fresh_confirmation') is not False or metadata.get('capital_permission') is not False:
        raise ValueError('Fresh development cannot authorize capital or confirmation claims')
    if metadata.get('expected_opportunities')!=7*DAY_MS//GRID_MS*len(ASSETS):
        raise ValueError('Fresh matrix must retain the fixed two-asset grid')
    return record
