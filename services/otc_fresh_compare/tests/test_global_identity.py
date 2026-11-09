"""Whole-source session and identity regressions using disjoint synthetic archives."""
from __future__ import annotations

import gzip
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from contracts.otc_fresh_v1 import ASSETS,DAY_MS,GRID_MS,canonical,digest,sha256,strict_json
from services.otc_fresh_compare import export
from services.otc_fresh_compare.source_chain import SourceChain
from services.otc_fresh_compare.tests.fixtures import DDL,registration
from services.otc_fresh_compare.tests.test_full_census import single_source,seal_snapshot

NS_PER_MS=1000000


def session_cases(record):
    """Malformed SQL fields and pair cardinalities, including SQL NULL 3VL."""
    start=record['start_ms']
    return {
        'orphan_null_transition':('INSERT INTO sessions VALUES (?,?,?,?)',('orphan',None,start,'{}')),
        'owned_null_transition':('INSERT INTO sessions VALUES (?,?,?,?)',('owned',None,start,'{}')),
        'orphan_empty_transition':('INSERT INTO sessions VALUES (?,?,?,?)',('orphan','',start,'{}')),
        'orphan_blob_transition':('INSERT INTO sessions VALUES (?,?,?,?)',('orphan',sqlite3.Binary(b'open'),start,'{}')),
        'orphan_null_identity':('INSERT INTO sessions VALUES (?,?,?,?)',(None,'open',start,'{}')),
        'orphan_empty_identity':('INSERT INTO sessions VALUES (?,?,?,?)',('','open',start,'{}')),
        'paired_empty_identity':("INSERT INTO sessions SELECT ?,?,?,'{}' UNION ALL SELECT ?,?,?,'{}'",('','open',start,'','close',record['end_ms'])),
        'orphan_blob_identity':('INSERT INTO sessions VALUES (?,?,?,?)',(sqlite3.Binary(b'orphan'),'open',start,'{}')),
        'null_time':("UPDATE sessions SET at_ms=NULL WHERE transition='close'",()),
        'null_detail':("UPDATE sessions SET detail_json=NULL WHERE transition='open'",()),
        'empty_detail':("UPDATE sessions SET detail_json='' WHERE transition='open'",()),
        'blob_detail':("UPDATE sessions SET detail_json=? WHERE transition='open'",(sqlite3.Binary(b'{}'),)),
        'noncanonical_detail':("UPDATE sessions SET detail_json='{ }' WHERE transition='open'",()),
        'nonobject_detail':("UPDATE sessions SET detail_json='[]' WHERE transition='open'",()),
        'duplicate_open':('INSERT INTO sessions VALUES (?,?,?,?)',('owned','open',start,'{}')),
        'duplicate_close':('INSERT INTO sessions VALUES (?,?,?,?)',('owned','close',record['end_ms'],'{}')),
        'missing_open':("DELETE FROM sessions WHERE transition='open'",()),
        'missing_close':("DELETE FROM sessions WHERE transition='close'",()),
        'reversed_pair':("UPDATE sessions SET at_ms=? WHERE transition='close'",(start-1,)),
    }


def make_identity_chain(root,record,*,mode='valid',shards=3,asset=ASSETS[0],kind='quote'):
    """At most one small builder database and one optional reference DB per loop.

    Each shard owns a distinct closed physical session. A late-shard collision
    lies days outside the replay tail. Boundary modes put two observations at
    the same exact UTC instant in adjacent independently owned archives.
    """
    root=Path(root);root.mkdir(parents=True,exist_ok=True);segments=root/'segments';segments.mkdir()
    start,end=record['start_ms'],record['end_ms']
    cuts=[start+index*DAY_MS for index in range(shards)]+[end]
    assert cuts[-2]<end
    mono_path=root/'reference.sqlite';mono=sqlite3.connect(mono_path)
    # Test fixtures are disposable and deterministic, never collector writes.
    mono.execute('PRAGMA journal_mode=MEMORY');mono.execute('PRAGMA synchronous=OFF');mono.executescript(DDL)
    mono.execute('INSERT INTO registration VALUES (1,?,?)',(canonical(record),digest(record)))
    items=[];records=[]
    source={'quote':'quote_samples','mood':'mood_samples','payout':'commission-stream'}[kind]
    value={'quote':'100','mood':'0.5','payout':'0.85'}[kind]
    for index in range(shards):
        raw=segments/f'closed-{index}.sqlite';connection=sqlite3.connect(raw)
        connection.execute('PRAGMA journal_mode=MEMORY');connection.execute('PRAGMA synchronous=OFF');connection.executescript(DDL)
        connection.execute('INSERT INTO registration VALUES (1,?,?)',(canonical(record),digest(record)))
        session=f'owned-{index:03d}'
        if mode in ('session','sequence') and index==shards-1:session='owned-000'
        for transition,moment in [('open',cuts[index]),('close',cuts[index+1])]:
            row=(session,transition,moment,'{}');connection.execute('INSERT INTO sessions VALUES (?,?,?,?)',row)
            mono.execute('INSERT INTO sessions VALUES (?,?,?,?)',row)
        if mode=='null_transition' and index==shards-1:
            connection.execute('INSERT INTO sessions VALUES (?,?,?,?)',('unused-orphan',None,cuts[index],'{}'))
        boundary=mode in ('boundary_valid','identical_event')
        moment=(cuts[1] if index in (0,1) else cuts[index]+17*GRID_MS+90000) if boundary else cuts[index]+17*GRID_MS+90000
        identity=f'global-event-{index}';frame=f'global-frame-{index}';sequence=1
        if mode in ('event','contradictory_event','quarantined_event') and index==shards-1:identity='global-event-0'
        if mode=='identical_event' and index==1:identity='global-event-0'
        if mode=='frame' and index==shards-1:frame='global-frame-0'
        clock_status='quarantined' if mode=='quarantined_event' else 'ok'
        row={'event_id':identity,'broker':'iqoption','asset':asset,'product':'turbo-option','source':source,
             'kind':kind,'available_ms':moment,'event_ms':moment,'value':value,
             'clock_id':'receiver_utc','quality':'received'}
        if mode=='contradictory_event' and index==shards-1:row['value']='101.5' if kind=='quote' else '0.7'
        lineage={'clock_status':clock_status,'received_at_ms':moment,'received_at_ns':moment*NS_PER_MS}
        envelope={'frame_id':frame,'session_id':session,'sequence':sequence,'received_at_ms':moment,
                  'received_at_ns':moment*NS_PER_MS,'monotonic_ns':sequence,
                  'events':[{'observation':row,'lineage':lineage}],'health':None}
        receipt=(frame,session,sequence,moment,sequence,canonical(envelope),digest(envelope))
        observation=(identity,frame,asset,kind,source,moment,canonical(row),canonical(lineage),clock_status)
        connection.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',receipt)
        connection.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',observation)
        records.append({'shard':index,'session':session,'event':identity,'frame':frame,'received_at_ms':moment,
                        'observation':row,'lineage':lineage,'envelope':envelope})
        # An empty receipt remains in the inventory even when no replay selects it.
        empty_frame='empty-frame-0' if mode=='empty_frame' and index==shards-1 else f'empty-frame-{index}'
        empty_sequence=1 if mode=='local_sequence' and index==shards-1 else 2
        empty_moment=moment-1 if boundary and index==0 else moment+1
        empty={'frame_id':empty_frame,'session_id':session,'sequence':empty_sequence,'received_at_ms':empty_moment,
               'received_at_ns':empty_moment*NS_PER_MS,'monotonic_ns':empty_sequence,'events':[],'health':None}
        empty_receipt=(empty_frame,session,empty_sequence,empty_moment,empty_sequence,canonical(empty),digest(empty))
        connection.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',empty_receipt)
        # Invalid modes intentionally cannot form a globally unique monolith.
        if mode in ('valid','boundary_valid'):
            mono.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',receipt)
            mono.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',empty_receipt)
            mono.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',observation)
        connection.commit();connection.close()
        archive=raw.with_suffix('.sqlite.gz')
        with raw.open('rb') as source_file,archive.open('wb') as target,gzip.GzipFile(fileobj=target,mode='wb',mtime=0) as compressed:
            shutil.copyfileobj(source_file,compressed,1024*1024)
        items.append({'path':str(archive),'compressed_sha256':sha256(archive),'sqlite_sha256':sha256(raw),
                      'sqlite_bytes':raw.stat().st_size,'closed_at_ms':cuts[index+1]})
        raw.unlink()
    mono.commit();mono.close()
    chain={'schema':'fresh_otc_source_chain_v1','registration_sha256':record['registration_sha256'],
           'complete':True,'segments':items}
    path=root/'source-chain.json';path.write_text(canonical(chain)+'\n')
    (root/'receipt-evidence.json').write_text(canonical(records)+'\n')
    return path,mono_path,cuts,records


def admit_chain(path,record,*,prime=False):
    reader=SourceChain(path,record,record['end_ms'])
    try:
        if prime:export.replay_decision(reader,record['start_ms']+17*GRID_MS)
        reader.close()
        return {'decoded':reader.decoded,'census':reader.source_census}
    finally:reader.abort()


class GlobalIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=tempfile.TemporaryDirectory(prefix='otc-global-identity-seed-')
        cls.record,cls.reg,cls.plan=registration(Path(cls.seed.name))
    @classmethod
    def tearDownClass(cls):cls.seed.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='otc-global-identity-case-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def test_every_session_field_and_exact_pair_cardinality_rejects(self):
        for mode,(sql,params) in session_cases(self.record).items():
            root=self.root/mode;root.mkdir();_,connection=single_source(root,self.record,memory=True)
            try:
                connection.execute(sql,params);connection.commit()
                with self.subTest(mode=mode),self.assertRaises(ValueError):export.validate_source_scope(connection,self.record)
            finally:connection.close()
    def test_null_orphan_transition_rejects_before_immutable_snapshot_export(self):
        snapshot,connection=single_source(self.root,self.record)
        connection.execute('INSERT INTO sessions VALUES (?,?,?,?)',('unused-orphan',None,self.record['start_ms'],'{}'))
        seal_snapshot(snapshot,connection,self.record);output=self.root/'matrix'
        with self.assertRaises(ValueError):export.export_matrix(snapshot,self.reg,self.plan,output,now_ms=self.record['end_ms'])
        self.assertFalse(output.exists())
    def test_unused_distant_shards_reject_global_and_local_identity_reuse(self):
        for mode in ('session','sequence','frame','empty_frame','event','contradictory_event','quarantined_event','identical_event','local_sequence','null_transition'):
            path,_,_,records=make_identity_chain(self.root/mode,self.record,mode=mode)
            if mode!='identical_event':
                self.assertGreater(records[-1]['received_at_ms']-records[0]['received_at_ms'],600000)
            with self.subTest(mode=mode),self.assertRaises(ValueError):admit_chain(path,self.record,prime=True)
    def test_distinct_same_ms_boundary_matches_whole_source_reference(self):
        path,mono_path,cuts,_=make_identity_chain(self.root,self.record,mode='boundary_valid')
        mono=sqlite3.connect(mono_path.as_uri()+'?mode=ro&immutable=1',uri=True);reader=SourceChain(path,self.record,self.record['end_ms'])
        try:
            for moment in (cuts[1]-GRID_MS,cuts[1],cuts[1]+GRID_MS):
                self.assertEqual(export.replay_decision(reader,moment),export.replay_decision(mono,moment))
            reader.close();self.assertEqual(reader.decoded,3)
            self.assertEqual(reader.source_census['checked_receipts'],6)
            self.assertEqual(reader.source_census['checked_observations'],3)
            self.assertEqual(reader.source_census['violations'],0)
        finally:mono.close();reader.abort()
    def test_metadata_ledger_is_bounded_and_removed_after_abort_and_late_failure(self):
        path,_,_,_=make_identity_chain(self.root/'abort',self.record)
        reader=SourceChain(path,self.record,self.record['end_ms'])
        export.replay_decision(reader,self.record['start_ms']+17*GRID_MS)
        ledger=reader.identity_ledger_path
        self.assertIsInstance(ledger,Path);self.assertTrue(ledger.is_file())
        evidence=reader.source_census['global_identity_ledger']
        self.assertEqual(evidence['storage'],'temporary_sqlite')
        self.assertEqual(evidence['policy'],'owned_disjoint_shards_no_identity_reuse')
        self.assertLessEqual(evidence['maximum_key_batch_rows'],evidence['key_batch_row_cap'])
        self.assertLessEqual(evidence['maximum_key_batch_bytes'],evidence['key_batch_byte_cap'])
        self.assertLessEqual(evidence['maximum_database_bytes'],evidence['database_byte_cap'])
        self.assertLessEqual(evidence['maximum_temporary_bytes'],evidence['temporary_byte_cap'])
        self.assertFalse(evidence['cleanup_completed'])
        reader.abort();self.assertFalse(ledger.exists());self.assertIsNone(reader.identity_ledger_path)
        self.assertTrue(evidence['cleanup_completed']);reader.abort();reader.close()
        path,_,_,_=make_identity_chain(self.root/'failure',self.record,mode='contradictory_event')
        reader=SourceChain(path,self.record,self.record['end_ms']);export.replay_decision(reader,self.record['start_ms']+17*GRID_MS)
        ledger=reader.identity_ledger_path
        with self.assertRaises(ValueError):reader.close()
        self.assertFalse(ledger.exists());self.assertIsNone(reader.identity_ledger_path)
        self.assertTrue(reader.source_census['global_identity_ledger']['cleanup_completed'])
        self.assertIsNone(reader.temporary);self.assertTrue(reader.closed);reader.abort()

    def test_ledger_row_byte_database_caps_and_global_sequence_index(self):
        from services.otc_fresh_compare import identity_ledger as module
        source=sqlite3.connect(':memory:');self.addCleanup(source.close);source.executescript(DDL)
        # A direct constraint test independently reaches (session, sequence),
        # which valid whole-source census would reject earlier via session ID.
        source.execute('INSERT INTO receipts VALUES (?,?,?,0,0,?,?)',('frame-a','owned',1,'{}','x'))
        ledger=module.IdentityLedger();self.addCleanup(ledger.close);ledger.admit(source)
        source.execute('DELETE FROM receipts');source.execute('INSERT INTO receipts VALUES (?,?,?,0,0,?,?)',('frame-b','owned',1,'{}','x'))
        with self.assertRaisesRegex(ValueError,'reused'):ledger.admit(source)
        self.assertEqual(ledger.audit['checked_frame_ids'],1)
        self.assertEqual(ledger.connection.execute('SELECT count(*) FROM frame_ids').fetchone()[0],1)
        ledger.close()
        source.execute('DELETE FROM receipts')
        source.executemany('INSERT INTO receipts VALUES (?,?,?,0,0,?,?)',
            [(str(index)+'x'*1500,'s'*1500,index,'{}','x') for index in range(100)])
        with patch.object(module,'KEY_BATCH_BYTE_CAP',4000),patch.object(module,'KEY_BATCH_ROW_CAP',2):
            ledger=module.IdentityLedger()
            try:
                ledger.admit(source)
                self.assertEqual(ledger.audit['maximum_key_batch_rows'],1)
                self.assertLessEqual(ledger.audit['maximum_key_batch_bytes'],4000)
            finally:ledger.close()
        with patch.object(module,'KEY_BATCH_BYTE_CAP',100):
            ledger=module.IdentityLedger()
            try:
                with self.assertRaisesRegex(ValueError,'byte cap'):ledger.admit(source)
                self.assertEqual(ledger.audit['segments_checked'],0)
            finally:ledger.close()
        with patch.object(module,'DATABASE_BYTE_CAP',128*1024):
            ledger=module.IdentityLedger()
            try:
                with self.assertRaisesRegex(ValueError,'bounded metadata|disk byte cap'):ledger.admit(source)
                self.assertEqual(ledger.audit['segments_checked'],0)
                self.assertEqual(ledger.connection.execute('SELECT count(*) FROM frame_ids').fetchone()[0],0)
            finally:ledger.close()


if __name__=='__main__':unittest.main()
