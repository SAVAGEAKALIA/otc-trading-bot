"""Sequential closed gzip SQLite images with bounded cross-shard receipt tails."""
from __future__ import annotations
import gzip
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from contracts.otc_fresh_v1 import ASSETS,canonical,digest,sha256,strict_json

CHAIN_KEYS={'schema','registration_sha256','complete','segments'}
SEGMENT_KEYS={'path','compressed_sha256','sqlite_sha256','sqlite_bytes','closed_at_ms'}
SCOPE="asset IN ('EURUSD-OTC','GBPUSD-OTC') AND kind IN ('quote','mood','payout')"
SELECT="SELECT o.observation_json,o.lineage_json,o.clock_status,r.received_at_ms,o.available_ms,o.asset,o.kind,o.source,o.event_id,r.frame_id,r.envelope_json,r.envelope_sha256 FROM observations o JOIN receipts r ON r.frame_id=o.frame_id WHERE o.asset IN ('EURUSD-OTC','GBPUSD-OTC') AND o.kind IN ('quote','mood','payout') AND o.available_ms BETWEEN ? AND ? ORDER BY o.available_ms,o.event_id"
CLOSURE_ARCHIVE_GRACE_MS=60*60*1000

def chain_wait_state(path,registration,now_ms):
    """Frozen workflow deadline; no opportunity or partition dates can move."""
    if type(now_ms) is not int:raise ValueError('Chain wait clock needs integer UTC milliseconds')
    end=registration['end_ms'];deadline=end+CLOSURE_ARCHIVE_GRACE_MS;path=Path(path)
    if path.exists():
        chain=strict_json(path.read_text())
        if not isinstance(chain,dict) or set(chain)!=CHAIN_KEYS or chain['schema']!='fresh_otc_source_chain_v1' or chain['registration_sha256']!=registration['registration_sha256'] or type(chain['complete']) is not bool:
            raise ValueError('Chain wait source must have the exact registered schema')
        if chain['complete']:
            if now_ms<end:raise ValueError('Completed chain published before registered end')
            return {'status':'READY','eta_seconds':0,'archive_deadline_ms':deadline}
    if now_ms<end:return {'status':'WAITING_REGISTERED_END','eta_seconds':(end-now_ms)/1000,'archive_deadline_ms':deadline}
    if now_ms>=deadline:return {'status':'BLOCKED','reason':'incomplete_chain_after_closure_archive_grace','eta_seconds':None,'archive_deadline_ms':deadline}
    return {'status':'WAITING_ARCHIVE','eta_seconds':None,'archive_deadline_ms':deadline}

def wait_for_chain(path,registration,*,clock_ms=None,sleep=None,progress_path=None):
    """Local filesystem wait, bounded by the immutable end plus one hour."""
    clock_ms=(lambda:time.time_ns()//1000000) if clock_ms is None else clock_ms
    sleep=time.sleep if sleep is None else sleep;previous=None;last_emit=None
    progress_path=Path(progress_path) if progress_path is not None else Path('/tmp')/('fresh-otc-chain-wait-'+registration['registration_sha256'][:12])/'progress.log'
    progress_path.parent.mkdir(parents=True,exist_ok=True)
    if not progress_path.exists():print('tail -f '+str(progress_path),flush=True)
    while True:
        now=clock_ms();state=chain_wait_state(path,registration,now)
        if state['status']!=previous or last_emit is None or now-last_emit>=300000:
            progress=min(100,max(0,(now-registration['start_ms'])/(registration['end_ms']-registration['start_ms'])*100))
            line=canonical({'event':'Fresh OTC closed archive wait','now_ms':now,'percent_done':progress,
                'percent_basis':'registered collection clock; archive state reported separately',**state})
            print(line,flush=True)
            with progress_path.open('a') as stream:stream.write(line+'\n')
            previous=state['status'];last_emit=now
        if state['status']=='READY':return state
        if state['status']=='BLOCKED':raise ValueError('BLOCKED: incomplete chain after fixed one-hour closure/archive grace')
        deadline=registration['end_ms'] if state['status']=='WAITING_REGISTERED_END' else state['archive_deadline_ms']
        sleep(min(60,(deadline-now)/1000))

class Cursor:
    def __init__(self,value=None,rows=()):self.value=value;self.rows=rows;self.offset=0
    def fetchone(self):return (self.value,)
    def fetchmany(self,size):
        result=self.rows[self.offset:self.offset+size];self.offset+=len(result);return result

def serialized_bytes(row):return sum(len(row[index].encode()) for index in (0,1,10))

class SourceChain:
    def __init__(self,path,registration,now_ms):
        self.path=Path(path).resolve(strict=True);self.raw=self.path.read_bytes();self.chain=strict_json(self.raw)
        if not isinstance(self.chain,dict) or set(self.chain)!=CHAIN_KEYS or self.chain['schema']!='fresh_otc_source_chain_v1':
            raise ValueError('Source chain must have the exact registered schema')
        if self.chain['registration_sha256']!=registration['registration_sha256'] or self.chain['complete'] is not True:
            raise ValueError('Source chain is unregistered or unfinished')
        if type(now_ms) is not int or now_ms<registration['end_ms']:raise ValueError('Registered collection has not ended')
        self.segments=self.chain['segments'];self.registration=registration
        if not isinstance(self.segments,list) or not self.segments:raise ValueError('Source chain needs closed segments')
        previous=registration['start_ms'];parent=None;seen=set()
        for segment in self.segments:
            if not isinstance(segment,dict) or set(segment)!=SEGMENT_KEYS:raise ValueError('Source segment fields differ from contract')
            path=Path(segment['path']) if isinstance(segment['path'],str) else Path('.')
            if not path.is_absolute() or path.parent.name!='segments' or not str(path).endswith('.sqlite.gz') or path.is_symlink() or not path.is_file() or path.resolve()!=path:
                raise ValueError('Source segments require regular absolute .sqlite.gz files in one segments directory')
            if parent is None:parent=path.parent
            if path.parent!=parent or str(path) in seen:raise ValueError('Source segment path is duplicated or outside the chain')
            seen.add(str(path))
            for field in ('compressed_sha256','sqlite_sha256'):
                if not isinstance(segment[field],str) or not re.fullmatch('[0-9a-f]{64}',segment[field]):raise ValueError('Source segment needs exact SHA256')
            if type(segment['sqlite_bytes']) is not int or segment['sqlite_bytes']<=0:raise ValueError('Source SQLite size must be positive integer bytes')
            if type(segment['closed_at_ms']) is not int or segment['closed_at_ms']<=previous or segment['closed_at_ms']>now_ms:
                raise ValueError('Source segments must be closed in strictly increasing order')
            previous=segment['closed_at_ms']
        if previous<registration['end_ms']:raise ValueError('Final source segment closed before the fixed cohort ended')
        self.index=-1;self.connection=None;self.temporary=None;self.tail=[];self.window_key=None
        self.window=[];self.window_bytes=0;self.maximum_tail_rows=0;self.decoded=0;self.closed=False
        self.source_observations=0;self.admitted_clock_observations=0
        self.session_closed_ms=None
        self.source_census={'checked_sessions':0,'checked_receipts':0,'checked_observations':0,
            'violations':0,'segments_checked':0,'maximum_envelope_bytes':0,'maximum_record_bytes':0,
            'maximum_events_per_receipt':0,'streamed_envelopes_at_once':1,
            'minimum_received_at_ns':None,'maximum_received_at_ns':None}
        from .identity_ledger import IdentityLedger
        self.identity_ledger=IdentityLedger()
        self.source_census['global_identity_ledger']=self.identity_ledger.audit

    @property
    def identity_ledger_path(self):return self.identity_ledger.path

    def _release(self):
        if self.connection is not None:self.connection.close();self.connection=None
        if self.temporary is not None:self.temporary.cleanup();self.temporary=None

    def _open_next(self):
        self._release();self.index+=1;segment=self.segments[self.index]
        if sha256(segment['path'])!=segment['compressed_sha256']:raise ValueError('Compressed source segment changed')
        from .export import MAX_WINDOW_BYTES,validate_source_scope
        if shutil.disk_usage(tempfile.gettempdir()).free<segment['sqlite_bytes']+MAX_WINDOW_BYTES:
            raise ValueError('Insufficient temporary disk for one verified SQLite shard')
        self.temporary=tempfile.TemporaryDirectory(prefix='otc-closed-shard-')
        decoded=Path(self.temporary.name)/'receipts.sqlite';size=0
        try:
            with gzip.open(segment['path'],'rb') as stream,decoded.open('wb') as output:
                while True:
                    block=stream.read(1024*1024)
                    if not block:break
                    size+=len(block)
                    if size>segment['sqlite_bytes']:raise ValueError('Decoded source segment exceeds registered size')
                    output.write(block)
            if size!=segment['sqlite_bytes'] or sha256(decoded)!=segment['sqlite_sha256']:
                raise ValueError('Decoded SQLite source hash/size changed')
            connection=sqlite3.connect(decoded.as_uri()+'?mode=ro&immutable=1',uri=True)
            self.connection=connection;connection.execute('PRAGMA query_only=ON')
            if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Source shard integrity failed')
            stored=connection.execute('SELECT record_json,record_sha256 FROM registration WHERE singleton=1').fetchone()
            if stored is None or strict_json(stored[0])!=self.registration or stored[1]!=digest(self.registration):
                raise ValueError('Source shard global registration changed')
            unclosed=connection.execute("SELECT count(*) FROM sessions s WHERE s.transition='open' AND NOT EXISTS(SELECT 1 FROM sessions c WHERE c.session_id=s.session_id AND c.transition='close')").fetchone()[0]
            last=connection.execute("SELECT max(at_ms) FROM sessions WHERE transition='close'").fetchone()[0]
            if unclosed or type(last) is not int or last>segment['closed_at_ms']:
                raise ValueError('Source shard is unfinished or its closure evidence changed')
            invalid_sessions=connection.execute("SELECT count(*) FROM sessions WHERE typeof(at_ms)!='integer' OR at_ms<0 OR at_ms>? OR transition NOT IN ('open','close')",(segment['closed_at_ms'],)).fetchone()[0]
            reversed_sessions=connection.execute("SELECT count(*) FROM sessions s WHERE s.transition='open' AND NOT EXISTS(SELECT 1 FROM sessions c WHERE c.session_id=s.session_id AND c.transition='close' AND c.at_ms>=s.at_ms)").fetchone()[0]
            if invalid_sessions or reversed_sessions or (self.session_closed_ms is not None and last<=self.session_closed_ms):
                raise ValueError('Source shard session chronology changed')
            if self.index==len(self.segments)-1 and last<self.registration['end_ms']:
                raise ValueError('Final source session closed before the fixed cohort ended')
            scope=validate_source_scope(connection,self.registration,min_session_open_ms=self.session_closed_ms)
            self.identity_ledger.admit(connection)
            for field in ('checked_sessions','checked_receipts','checked_observations'):
                self.source_census[field]+=scope[field]
            for field in ('maximum_envelope_bytes','maximum_record_bytes','maximum_events_per_receipt'):
                self.source_census[field]=max(self.source_census[field],scope[field])
            for field in ('envelope_byte_cap','record_byte_cap','events_per_receipt_cap'):
                self.source_census[field]=scope[field]
            self.source_census['segments_checked']+=1
            lower=scope['minimum_received_at_ns'];upper=scope['maximum_received_at_ns']
            if lower is not None:
                current=self.source_census['minimum_received_at_ns']
                self.source_census['minimum_received_at_ns']=lower if current is None else min(current,lower)
                current=self.source_census['maximum_received_at_ns']
                self.source_census['maximum_received_at_ns']=upper if current is None else max(current,upper)
            self.session_closed_ms=last
            outside=connection.execute("SELECT count(*) FROM observations WHERE asset IS NULL OR kind IS NULL OR asset NOT IN ('EURUSD-OTC','GBPUSD-OTC') OR kind NOT IN ('quote','mood','payout') OR typeof(available_ms)!='integer'").fetchone()[0]
            if outside:raise ValueError('Source shard contains observations outside the fixed scope')
            self.source_observations+=connection.execute('SELECT count(*) FROM observations').fetchone()[0]
            self.admitted_clock_observations+=connection.execute("SELECT count(*) FROM observations WHERE clock_status='ok'").fetchone()[0]
            self.decoded+=1
        except BaseException:
            self.abort();raise

    def _raw(self,earliest,latest):
        from .export import MAX_WINDOW_ROWS,MAX_WINDOW_BYTES,FETCH_BATCH
        count=self.connection.execute('SELECT count(*) FROM observations WHERE '+SCOPE+' AND available_ms BETWEEN ? AND ?',(earliest,latest)).fetchone()[0]
        size=self.connection.execute("SELECT coalesce(sum(length(CAST(o.observation_json AS BLOB))+length(CAST(o.lineage_json AS BLOB))+length(CAST(r.envelope_json AS BLOB))),0) FROM observations o JOIN receipts r ON r.frame_id=o.frame_id WHERE o.asset IN ('EURUSD-OTC','GBPUSD-OTC') AND o.kind IN ('quote','mood','payout') AND o.available_ms BETWEEN ? AND ?",(earliest,latest)).fetchone()[0]
        if count>MAX_WINDOW_ROWS or size>MAX_WINDOW_BYTES:raise ValueError('Source shard window exceeds bounded memory budget')
        result=[];cursor=self.connection.execute(SELECT,(earliest,latest))
        while True:
            batch=cursor.fetchmany(FETCH_BATCH)
            if not batch:break
            result.extend(batch)
        if len(result)!=count:raise ValueError('Source shard observation has no matching receipt')
        return result

    def _prepare(self,earliest,latest):
        key=(earliest,latest)
        if self.window_key==key:return
        if self.window_key is not None and earliest<self.window_key[0]:raise ValueError('Source-chain replay must move forward')
        self.window_key=key
        self.window=[]
        self.tail=[row for row in self.tail if row[4]>=earliest]
        if self.index<0:self._open_next()
        # The next shard can contain an exact boundary-ms receipt. Read it when
        # expiry equals closure as well, preserving the complete receipt batch.
        while self.index+1<len(self.segments) and latest>=self.session_closed_ms:
            maximum=self.connection.execute('SELECT max(available_ms) FROM observations').fetchone()[0]
            previous=self._raw(earliest,maximum) if maximum is not None else []
            self.tail.extend(previous);self._check_budget(self.tail)
            self.maximum_tail_rows=max(self.maximum_tail_rows,len(self.tail));self._open_next()
        current=self._raw(earliest,latest)
        tail=[row for row in self.tail if earliest<=row[4]<=latest]
        self._check_budget([*tail,*current])
        self.window=sorted([*tail,*current],key=lambda row:(row[4],row[8]));self.window_bytes=sum(serialized_bytes(row) for row in self.window)

    @staticmethod
    def _check_budget(rows):
        from .export import MAX_WINDOW_ROWS,MAX_WINDOW_BYTES
        if len(rows)>MAX_WINDOW_ROWS or sum(serialized_bytes(row) for row in rows)>MAX_WINDOW_BYTES:
            raise ValueError('Merged source-chain window exceeds bounded memory budget')

    def execute(self,sql,params=()):
        if self.closed:raise ValueError('Source-chain reader is closed')
        if len(params)<2:raise ValueError('Unsupported source-chain query')
        self._prepare(params[0],params[1])
        if sql.startswith('SELECT count(*) FROM observations WHERE available_ms'):
            return Cursor(len(self.window))
        if sql.startswith('SELECT coalesce(sum('):return Cursor(self.window_bytes)
        if sql.startswith('SELECT count(*) FROM observations o JOIN receipts'):
            return Cursor(sum(len(row[0].encode())>params[2] or len(row[1].encode())>params[3] or len(row[10].encode())>params[4] for row in self.window))
        if sql.startswith('SELECT o.observation_json,'):return Cursor(rows=self.window)
        raise ValueError('Unsupported source-chain query')

    def assert_stable(self):
        if self.path.read_bytes()!=self.raw or any(sha256(item['path'])!=item['compressed_sha256'] for item in self.segments):
            raise ValueError('Source chain or closed archive changed during replay')

    def close(self):
        if self.closed:return
        try:
            # Even a source shard with no selected windows remains verified.
            while self.index+1<len(self.segments):self._open_next()
            self.assert_stable()
        finally:self.abort()

    def abort(self):
        try:self._release()
        finally:
            self.identity_ledger.close();self.closed=True;self.tail=[];self.window=[]
