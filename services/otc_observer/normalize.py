"""Normalize received observations for an explicitly hypothetical price experiment."""
from __future__ import annotations
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json


def normalize_rows(rows, kind, *, product='turbo-option', assets=None, clock_limit_ms=15_000):
    """Canonicalize simultaneous receipt batches before treating receipt as event time.

    Price rows have no product field. Their product assignment is a recorded experiment
    assumption, never broker-contract evidence. Original timestamps remain in lineage.
    """
    if kind not in {'quote', 'mood', 'payout'}:
        raise ValueError('Unknown observation kind')
    if type(clock_limit_ms) is not int or clock_limit_ms < 0:
        raise ValueError('Clock limit must be a nonnegative integer')
    counts=Counter(); batches=defaultdict(list); lineage={}
    for raw in rows:
        counts['input']+=1
        asset=raw.get('broker_asset')
        if not isinstance(asset, str) or not asset.strip() or asset != asset.strip():
            counts['missing_asset_identity']+=1; continue
        if assets is not None and asset not in assets:
            counts['outside_asset_scope']+=1; continue
        if kind!='quote' and raw.get('instrument_type')!=product:
            counts['wrong_product']+=1; continue
        received=raw.get('received_at_ms'); offset=raw.get('clock_offset_ms')
        if not isinstance(received,int) or isinstance(received,bool) or received<0:
            counts['missing_receipt']+=1; continue
        if not isinstance(offset,int) or isinstance(offset,bool) or abs(offset)>clock_limit_ms:
            counts['clock_quarantine']+=1; continue
        value=raw.get({'quote':'mid','mood':'call_fraction','payout':'payout_fraction'}[kind])
        try:
            number=Decimal(str(value))
        except InvalidOperation:
            counts['invalid_value']+=1; continue
        if not number.is_finite() or (kind=='quote' and number<=0) or (kind=='mood' and not 0<=number<=1) or (kind=='payout' and not 0<=number<=2):
            counts['invalid_value']+=1; continue
        original=raw.get('source_event_ms') if kind=='quote' else raw.get('observed_bucket_ms')
        if not isinstance(original,int) or isinstance(original,bool) or original < 0:
            counts['missing_source_identity']+=1; continue
        if kind=='quote' and not 0<=received-original<=clock_limit_ms:
            counts['quote_source_age_quarantine']+=1; continue
        source=raw.get('source') if kind=='payout' else {'quote':'quote_samples','mood':'mood_samples'}[kind]
        if not isinstance(source,str) or not source or source != source.strip():
            counts['missing_source_identity']+=1; continue
        try:
            raw_json = json.dumps(raw, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            counts['invalid_row_identity']+=1; continue
        item={'raw':raw,'value':str(number),'source_stamp':original,'source':source}
        batches[(asset,source,received)].append(item)
    events=[]
    for (asset,source,received),batch in sorted(batches.items()):
        # A websocket batch can contain several source ticks. Only its newest tick
        # was the current quote once the batch arrived. No invented intra-batch time.
        newest=max(x['source_stamp'] for x in batch)
        latest=[x for x in batch if x['source_stamp']==newest]
        if len({Decimal(x['value']) for x in latest})>1:
            counts['conflicting_batch_rows']+=len(batch); continue
        item=min(latest,key=lambda x:json.dumps(x['raw'],sort_keys=True))
        counts['batch_rows_collapsed']+=len(batch)-1
        raw=item['raw']
        identity=f'{kind}|{asset}|{product}|{source}|{newest}|{received}'
        event_id=hashlib.sha256(identity.encode()).hexdigest()
        events.append({'event_id':event_id,'broker':'iqoption','asset':asset,'product':product,'source':source,
                       'kind':kind,'available_ms':received,'event_ms':received,'value':item['value'],
                       'clock_id':'receiver_utc','quality':'received'})
        lineage[event_id]={'table':{'quote':'quote_samples','mood':'mood_samples','payout':'payout_samples'}[kind],
                           'broker_asset':asset,'raw_source_or_bucket_ms':newest,'received_at_ms':received,
                           'clock_offset_ms':raw['clock_offset_ms'],'source':source,
                           'raw_sha256':hashlib.sha256(json.dumps(raw,sort_keys=True,allow_nan=False).encode()).hexdigest(),
                           'product_basis':'explicit_assumed' if kind=='quote' else 'recorded'}
    counts['output']=len(events)
    return events,dict(sorted(counts.items())),lineage


def availability_audit(opportunities, payout_events, lineage):
    """Match legacy bucket and receipt joins on the same receiver-clock decisions.

    This measures unsafe availability on this explicit experiment grid only, not the
    prevalence in a previously published study with a different decision population.
    """
    from bisect import bisect_right
    groups=defaultdict(list)
    for event in payout_events:
        meta=lineage[event['event_id']]
        # Translate the recorded bucket with THAT snapshot's recorded offset. Never
        # use this reconstructed grouping key as availability in the repaired join.
        bucket_local=meta['raw_source_or_bucket_ms']-meta['clock_offset_ms']
        groups[(event['asset'],event['product'],event['source'])].append((bucket_local,event))
    indexes={key:sorted(rows,key=lambda x:(x[0],x[1]['event_id'])) for key,rows in groups.items()}
    keys={key:[row[0] for row in rows] for key,rows in indexes.items()}
    rows=[]
    for op in opportunities:
        key=(op['asset'],op['product'],'init-snapshot')
        values=indexes.get(key,[]); pos=bisect_right(keys.get(key,[]),op['decision_ms'])-1
        old=values[pos][1] if pos>=0 else None
        if old is None or op['decision_ms']-values[pos][0]>600_000:
            old=None
        rows.append({'opportunity_id':op['opportunity_id'],'legacy_event_id':None if old is None else old['event_id'],
                     'future_receipt_used_by_legacy_join':None if old is None else old['available_ms']>op['decision_ms']})
    known=[row for row in rows if row['legacy_event_id'] is not None]
    return {'scope':'matched_receiver_clock_experiment_grid','decisions':len(rows),'legacy_joined':len(known),
            'future_join_count':sum(row['future_receipt_used_by_legacy_join'] for row in known),
            'unmeasurable_or_unjoined':len(rows)-len(known),'rows':rows}
