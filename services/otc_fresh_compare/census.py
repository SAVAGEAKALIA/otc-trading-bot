"""Streaming admission of every stored receipt and its complete event inventory."""
from contracts.otc_fresh_v1 import ASSETS,CONFIG,canonical,digest,strict_json
from contracts.otc_v1 import Observation

NS_PER_MS=1000000
MAX_EVENTS_PER_RECEIPT=4096


def _json(raw,limit,what):
    if not isinstance(raw,str) or len(raw.encode('utf-8'))>limit:
        raise ValueError('Source census '+what+' exceeds deterministic byte cap')
    value=strict_json(raw)
    if not isinstance(value,dict) or canonical(value)!=raw:
        raise ValueError('Source census '+what+' is not a canonical JSON object')
    return value


def _integer(value,what):
    if type(value) is not int or value<0:raise ValueError('Source census '+what+' needs a nonnegative integer')


def validate_source_scope(connection,record,*,min_session_open_ms=None,record_bytes=65536,envelope_bytes=1048576):
    """One bounded envelope and one PK observation lookup at a time, no source list.

    Inventory equality is bidirectional: each unique envelope event has exactly
    one matching SQL observation, and their total equals the whole SQL census.
    This covers zero-event/quarantined frames and unselected observations too.
    """
    start,end=record['start_ms'],record['end_ms']
    if min_session_open_ms is not None:_integer(min_session_open_ms,'handoff boundary')
    for value in (record_bytes,envelope_bytes):
        if type(value) is not int or value<=0:raise ValueError('Source census byte caps need positive integers')
    sessions=connection.execute("SELECT count(*) FROM sessions WHERE session_id IS NULL OR typeof(session_id)!='text' OR length(CAST(session_id AS BLOB))=0 OR length(CAST(session_id AS BLOB))>? OR transition IS NULL OR typeof(transition)!='text' OR transition NOT IN ('open','close') OR typeof(at_ms)!='integer' OR at_ms<? OR (transition='open' AND at_ms>=?) OR detail_json IS NULL OR typeof(detail_json)!='text' OR length(CAST(detail_json AS BLOB))=0 OR length(CAST(detail_json AS BLOB))>?",(record_bytes,start,end,record_bytes)).fetchone()[0]
    pairs=connection.execute("SELECT count(*) FROM (SELECT session_id FROM sessions GROUP BY session_id HAVING count(*)!=2 OR count(CASE WHEN transition='open' THEN 1 END)!=1 OR count(CASE WHEN transition='close' THEN 1 END)!=1 OR min(CASE WHEN transition='close' THEN at_ms END)<min(CASE WHEN transition='open' THEN at_ms END))").fetchone()[0]
    receipts=connection.execute("SELECT count(*) FROM receipts r WHERE r.frame_id IS NULL OR typeof(r.frame_id)!='text' OR length(CAST(r.frame_id AS BLOB))=0 OR r.session_id IS NULL OR typeof(r.session_id)!='text' OR length(CAST(r.session_id AS BLOB))=0 OR length(CAST(r.frame_id AS BLOB))>? OR length(CAST(r.session_id AS BLOB))>? OR typeof(r.sequence)!='integer' OR r.sequence<0 OR typeof(r.monotonic_ns)!='integer' OR r.monotonic_ns<0 OR typeof(r.received_at_ms)!='integer' OR r.received_at_ms<? OR r.received_at_ms>=? OR NOT EXISTS (SELECT 1 FROM sessions s JOIN sessions c ON c.session_id=s.session_id AND c.transition='close' WHERE s.session_id=r.session_id AND s.transition='open' AND s.at_ms<=r.received_at_ms AND c.at_ms>=r.received_at_ms)",(record_bytes,record_bytes,start,end)).fetchone()[0]
    duplicate_frames=connection.execute('SELECT count(*) FROM (SELECT frame_id FROM receipts GROUP BY frame_id HAVING count(*)!=1)').fetchone()[0]
    duplicate_sequences=connection.execute('SELECT count(*) FROM (SELECT session_id,sequence FROM receipts GROUP BY session_id,sequence HAVING count(*)!=1)').fetchone()[0]
    observations=connection.execute("SELECT count(*) FROM observations o LEFT JOIN receipts r ON r.frame_id=o.frame_id WHERE o.event_id IS NULL OR typeof(o.event_id)!='text' OR length(CAST(o.event_id AS BLOB))=0 OR length(CAST(o.event_id AS BLOB))>? OR o.frame_id IS NULL OR typeof(o.frame_id)!='text' OR length(CAST(o.frame_id AS BLOB))=0 OR length(CAST(o.frame_id AS BLOB))>? OR o.asset IS NULL OR o.kind IS NULL OR o.asset NOT IN ('EURUSD-OTC','GBPUSD-OTC') OR o.kind NOT IN ('quote','mood','payout') OR typeof(o.available_ms)!='integer' OR o.available_ms<? OR o.available_ms>=? OR r.frame_id IS NULL OR o.available_ms!=r.received_at_ms",(record_bytes,record_bytes,start,end)).fetchone()[0]
    if sessions or pairs or receipts or observations or duplicate_frames or duplicate_sequences:
        raise ValueError('Source census contains records outside the registered cohort or physical session, or duplicate identities')
    if min_session_open_ms is not None:
        backward=connection.execute("SELECT count(*) FROM sessions WHERE transition='open' AND at_ms<?",(min_session_open_ms,)).fetchone()[0]
        backward_receipts=connection.execute('SELECT count(*) FROM receipts WHERE received_at_ms<?',(min_session_open_ms,)).fetchone()[0]
        if backward or backward_receipts:raise ValueError('Source census contains a backward physical shard handoff')
    oversized_receipts=connection.execute("SELECT count(*) FROM receipts WHERE typeof(envelope_json)!='text' OR length(CAST(envelope_json AS BLOB))>?",(envelope_bytes,)).fetchone()[0]
    oversized_observations=connection.execute("SELECT count(*) FROM observations WHERE typeof(observation_json)!='text' OR typeof(lineage_json)!='text' OR length(CAST(observation_json AS BLOB))>? OR length(CAST(lineage_json AS BLOB))>?",(record_bytes,record_bytes)).fetchone()[0]
    if oversized_receipts or oversized_observations:raise ValueError('Source census record exceeds deterministic byte cap')
    for detail, in connection.execute('SELECT detail_json FROM sessions'):
        _json(detail,record_bytes,'session detail')
    sql_receipts=connection.execute('SELECT count(*) FROM receipts').fetchone()[0]
    sql_observations=connection.execute('SELECT count(*) FROM observations').fetchone()[0]
    result={'checked_sessions':connection.execute('SELECT count(*) FROM sessions').fetchone()[0],
        'checked_receipts':0,'checked_observations':0,'violations':0,
        'maximum_envelope_bytes':0,'maximum_record_bytes':0,'maximum_events_per_receipt':0,
        'envelope_byte_cap':envelope_bytes,'record_byte_cap':record_bytes,
        'events_per_receipt_cap':MAX_EVENTS_PER_RECEIPT,'streamed_envelopes_at_once':1,
        'minimum_received_at_ns':None,'maximum_received_at_ns':None}
    cursor=connection.execute('SELECT frame_id,session_id,sequence,received_at_ms,monotonic_ns,envelope_json,envelope_sha256 FROM receipts')
    while True:
        stored=cursor.fetchone()
        if stored is None:break
        frame,session,sequence,moment,monotonic,raw,fingerprint=stored
        envelope=_json(raw,envelope_bytes,'envelope')
        required={'frame_id','session_id','sequence','received_at_ms','received_at_ns','events'}
        if not required<=set(envelope) or set(envelope)-required-{'monotonic_ns','health'}:
            raise ValueError('Source census receipt envelope fields changed')
        if digest(envelope)!=fingerprint or envelope['frame_id']!=frame or envelope['session_id']!=session:
            raise ValueError('Source census receipt envelope hash or identity changed')
        for key in ('sequence','received_at_ms','received_at_ns'):_integer(envelope[key],key)
        ns=envelope['received_at_ns']
        if envelope['sequence']!=sequence or envelope['received_at_ms']!=moment or ns//NS_PER_MS!=moment or not start*NS_PER_MS<=ns<end*NS_PER_MS:
            raise ValueError('Source census canonical receipt nanosecond clock or sequence differs from SQL/cohort')
        if 'monotonic_ns' in envelope:
            _integer(envelope['monotonic_ns'],'monotonic clock')
            if envelope['monotonic_ns']!=monotonic:raise ValueError('Source census monotonic receipt clock differs from SQL')
        events=envelope['events']
        if not isinstance(events,list) or len(events)>MAX_EVENTS_PER_RECEIPT:
            raise ValueError('Source census envelope event inventory exceeds deterministic record cap')
        identities=set()
        for item in events:
            if not isinstance(item,dict) or set(item)!={'observation','lineage'}:
                raise ValueError('Source census envelope event inventory fields changed')
            obs,meta=item['observation'],item['lineage']
            obs_raw=canonical(obs);meta_raw=canonical(meta)
            obs=_json(obs_raw,record_bytes,'observation');meta=_json(meta_raw,record_bytes,'lineage')
            try:event=Observation(**obs)
            except (TypeError,ValueError) as error:raise ValueError('Source census canonical observation is invalid') from error
            if event.asset not in ASSETS or event.broker!='iqoption' or event.product!='turbo-option' or event.clock_id!='receiver_utc' or event.source not in CONFIG['source_priority'][event.kind] or event.quality!='received':
                raise ValueError('Source census canonical observation scope changed')
            if event.available_ms!=moment or event.event_ms!=moment:
                raise ValueError('Source census canonical observation clock differs from receipt')
            for key in ('received_at_ms','received_at_ns'):_integer(meta.get(key),'lineage '+key)
            if meta['received_at_ms']!=moment or meta['received_at_ns']!=ns or not isinstance(meta.get('clock_status'),str) or not meta['clock_status']:
                raise ValueError('Source census lineage clock/status differs from receipt')
            if 'monotonic_ns' in meta:
                _integer(meta['monotonic_ns'],'lineage monotonic clock')
                if meta['monotonic_ns']!=monotonic:raise ValueError('Source census lineage monotonic clock differs from receipt')
            if event.event_id in identities:raise ValueError('Source census envelope has duplicate event inventory')
            identities.add(event.event_id)
            matches=connection.execute('SELECT event_id,frame_id,asset,kind,source,available_ms,observation_json,lineage_json,clock_status FROM observations WHERE event_id=?',(event.event_id,)).fetchmany(2)
            if len(matches)!=1:raise ValueError('Source census event inventory lacks one unique SQL observation')
            sql=matches[0]
            if sql[:6]!=(event.event_id,frame,event.asset,event.kind,event.source,moment) or sql[8]!=meta['clock_status']:
                raise ValueError('Source census observation SQL identity/clock/status differs from envelope')
            stored_obs=_json(sql[6],record_bytes,'stored observation');stored_meta=_json(sql[7],record_bytes,'stored lineage')
            if canonical(stored_obs)!=obs_raw or canonical(stored_meta)!=meta_raw:
                raise ValueError('Source census observation/lineage differs from envelope inventory')
            result['checked_observations']+=1
            result['maximum_record_bytes']=max(result['maximum_record_bytes'],len(obs_raw.encode()),len(meta_raw.encode()))
        result['checked_receipts']+=1
        result['maximum_envelope_bytes']=max(result['maximum_envelope_bytes'],len(raw.encode()))
        result['maximum_events_per_receipt']=max(result['maximum_events_per_receipt'],len(events))
        result['minimum_received_at_ns']=ns if result['minimum_received_at_ns'] is None else min(result['minimum_received_at_ns'],ns)
        result['maximum_received_at_ns']=ns if result['maximum_received_at_ns'] is None else max(result['maximum_received_at_ns'],ns)
    if result['checked_receipts']!=sql_receipts or result['checked_observations']!=sql_observations:
        raise ValueError('Source census whole-source observation inventory differs from receipt events')
    return result
