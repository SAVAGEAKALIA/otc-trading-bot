"""Fixed future weekend protocol. Registration does not start collection."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time

START=datetime(2026,11,16,tzinfo=timezone.utc)
DAYS=(('training',21),('early',7),('calibration',7),('policy',7),('diagnostic',7))
GRID_MS=120000
ASSETS=['EURUSD-OTC','GBPUSD-OTC']

def canonical(r):return json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(r):return hashlib.sha256(canonical(r).encode()).hexdigest()
def ms(d):return int(d.timestamp())*1000

def stages():
    cursor=START;result=[]
    for name,days in DAYS:
        end=cursor+timedelta(days=days)
        weekends=[]
        day=cursor
        while day<end:
            if day.weekday()==5:weekends.append({'start_ms':ms(day),'end_ms':ms(day+timedelta(days=2))})
            day+=timedelta(days=1)
        result.append({'name':name,'start_ms':ms(cursor),'end_ms':ms(end),'weekends':weekends,
                       'start_utc':cursor.isoformat().replace('+00:00','Z'),'end_utc':end.isoformat().replace('+00:00','Z'),
                       'scheduled_opportunities':((ms(end)-ms(cursor))//GRID_MS)*len(ASSETS)})
        cursor=end
    return result

def register(now_ms=None):
    now_ms=time.time_ns()//1000000 if now_ms is None else now_ms
    if type(now_ms) is not int or not 0<=now_ms<ms(START-timedelta(hours=6)):
        raise ValueError('source-lock deadline passed; do not retrospectively register')
    phases=stages()
    r={'schema':'otc_weekend_development_protocol_v2','registered_ms':now_ms,
       'assets':ASSETS,'product':'turbo-option','start_ms':phases[0]['start_ms'],'end_ms':phases[-1]['end_ms'],
       'grid_ms':GRID_MS,'hypothetical_expiry_ms':GRID_MS,'stages':phases,
       'source_lock_deadline_ms':ms(START-timedelta(hours=6)),
       'source_references':{'collector':'027864a33475ca1e548652c3fc492e85662068af26a01258d33b700c939d153c',
                            'comparison':'a40109f868b28c3c5493018b447995a0bcb0c3efcfc32752cfdb5831293300ba'},
       'collection_deployed':False,'scheduler_deployed':False,'comparison_executable_ready':False,
       'readiness':'Requires a separately locked v2 calendar registration parser/compiler before the deadline. Existing seven-day validation rejects this schema.',
       'outcome_basis':'received_quote_proxy_not_accepted_contract', 'capital_promotion':False,
       'policy':'Original logistic/CatBoost families, three thresholds, training-only preprocessing, early-only stopping, calibration-only temperature, policy-only choice; global position, selected unknowns full loss.',
       'exclusions':'Retain every scheduled row; causal disabled/suspended or unavailable offers abstain, stale payouts/quote gaps remain visible; purge overlapping labels at stage boundaries; no replacement weekends.',
       'scheduled_opportunities':sum(s['scheduled_opportunities'] for s in phases),
       'storage_scenario':{'quotes_per_day':1000000,'raw_bytes_per_quote_including_receipts_and_indexes':6144,
                           'days':49,'raw_bytes':1000000*6144*49,'compression_ratio_measured':False,
                           'admission':'Daily rotation plus verified off-host archive retention required. Do not assume seven-week archives fit existing free disk.'}}
    r['registration_sha256']=digest(r)
    return r

def validate(r):
    if not isinstance(r,dict):raise ValueError('protocol object required')
    expected=register(r.get('registered_ms'))
    if canonical(r)!=canonical(expected):raise ValueError('fixed protocol or digest changed')
    return True

if __name__=='__main__':
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    r=register();validate(r);Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(canonical({'registration_sha256':r['registration_sha256'],'opportunities':r['scheduled_opportunities'],'collection_deployed':False,'start_utc':r['stages'][0]['start_utc'],'end_utc':r['stages'][-1]['end_utc']}))
