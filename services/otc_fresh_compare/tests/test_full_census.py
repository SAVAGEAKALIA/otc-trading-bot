"""Whole-source canonical census and owned-handoff regressions, without fitting."""
from __future__ import annotations

import copy
import gzip
from pathlib import Path
import sqlite3
import tempfile
import unittest

from contracts.otc_fresh_v1 import ASSETS,GRID_MS,canonical,digest,sha256,strict_json
from services.otc_fresh_compare import export
from services.otc_fresh_compare.source_chain import SourceChain
from services.otc_fresh_compare.tests.fixtures import DDL,registration
from services.otc_fresh_compare.tests.test_chain import focused_chain

NS_PER_MS=1000000


def old_sql_census_admits(connection,record):
    """Literal former SQL-only admission, independent of the repaired guard."""
    start,end=record['start_ms'],record['end_ms']
    sessions=connection.execute("SELECT count(*) FROM sessions WHERE typeof(at_ms)!='integer' OR at_ms<? OR transition NOT IN ('open','close') OR (transition='open' AND at_ms>=?)",(start,end)).fetchone()[0]
    receipts=connection.execute("SELECT count(*) FROM receipts r WHERE typeof(r.received_at_ms)!='integer' OR r.received_at_ms<? OR r.received_at_ms>=? OR NOT EXISTS (SELECT 1 FROM sessions s JOIN sessions c ON c.session_id=s.session_id AND c.transition='close' WHERE s.session_id=r.session_id AND s.transition='open' AND s.at_ms<=r.received_at_ms AND c.at_ms>=r.received_at_ms)",(start,end)).fetchone()[0]
    observations=connection.execute("SELECT count(*) FROM observations o LEFT JOIN receipts r ON r.frame_id=o.frame_id WHERE o.asset IS NULL OR o.kind IS NULL OR o.asset NOT IN ('EURUSD-OTC','GBPUSD-OTC') OR o.kind NOT IN ('quote','mood','payout') OR typeof(o.available_ms)!='integer' OR o.available_ms<? OR o.available_ms>=? OR r.frame_id IS NULL OR o.available_ms!=r.received_at_ms",(start,end)).fetchone()[0]
    return not (sessions or receipts or observations)


def single_source(root,record,*,events=True,asset=ASSETS[0],kind='quote',clock_status='ok',memory=False):
    """One small physical source at a time, with a receipt far from first decision."""
    snapshot=Path(root)/'snapshot';snapshot.mkdir()
    connection=sqlite3.connect(':memory:' if memory else snapshot/'receipts.sqlite')
    connection.executescript(DDL)
    connection.execute('INSERT INTO registration VALUES (1,?,?)',(canonical(record),digest(record)))
    for transition,moment in [('open',record['start_ms']),('close',record['end_ms'])]:
        connection.execute('INSERT INTO sessions VALUES (?,?,?,?)',('owned',transition,moment,'{}'))
    moment=record['start_ms']+43*GRID_MS+90000;identity='census-event';frame='census-frame'
    source={'quote':'quote_samples','mood':'mood_samples','payout':'commission-stream'}[kind]
    value={'quote':'100','mood':'0.5','payout':'0.85'}[kind]
    row={'event_id':identity,'broker':'iqoption','asset':asset,'product':'turbo-option',
        'source':source,'kind':kind,'available_ms':moment,'event_ms':moment,
        'value':value,'clock_id':'receiver_utc','quality':'received'}
    lineage={'clock_status':clock_status,'received_at_ms':moment,'received_at_ns':moment*NS_PER_MS}
    envelope={'frame_id':frame,'session_id':'owned','sequence':1,'received_at_ms':moment,
        'received_at_ns':moment*NS_PER_MS,'monotonic_ns':1,
        'events':[{'observation':row,'lineage':lineage}] if events else [],'health':None}
    connection.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',(frame,'owned',1,moment,1,canonical(envelope),digest(envelope)))
    if events:
        connection.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',
            (identity,frame,asset,kind,source,moment,canonical(row),canonical(lineage),clock_status))
    connection.commit();return snapshot,connection


def rewrite_envelope(connection,mutate):
    frame,raw=connection.execute('SELECT frame_id,envelope_json FROM receipts LIMIT 1').fetchone()
    envelope=strict_json(raw);mutate(envelope)
    connection.execute('UPDATE receipts SET envelope_json=?,envelope_sha256=? WHERE frame_id=?',(canonical(envelope),digest(envelope),frame))
    connection.commit();return envelope


def seal_snapshot(snapshot,connection,record):
    observed=connection.execute('SELECT count(*) FROM observations').fetchone()[0]
    admitted=connection.execute("SELECT count(*) FROM observations WHERE clock_status='ok'").fetchone()[0]
    connection.commit();connection.close();reg=Path(snapshot)/'registration.json';reg.write_text(canonical(record)+'\n')
    manifest={'schema':'fresh_otc_export_v1','registration_sha256':record['registration_sha256'],
        'code_sha256':record['code_sha256'],'config_sha256':record['config_sha256'],
        'observation_count':observed,'admissible_clock_observation_count':admitted,'unclosed_sessions':0,
        'hashes':{'receipts.sqlite':sha256(Path(snapshot)/'receipts.sqlite'),'registration.json':sha256(reg)}}
    manifest['manifest_sha256']=digest(manifest);(Path(snapshot)/'manifest.json').write_text(canonical(manifest)+'\n')


def mutate_archive(chain_path,root,index,mutate):
    chain=strict_json(Path(chain_path).read_text());segment=chain['segments'][index];archive=Path(segment['path'])
    raw=Path(root)/('mutation-'+str(index)+'.sqlite')
    with gzip.open(archive,'rb') as source,raw.open('wb') as output:
        while True:
            block=source.read(1048576)
            if not block:break
            output.write(block)
    connection=sqlite3.connect(raw)
    try:mutate(connection);connection.commit()
    finally:connection.close()
    with raw.open('rb') as source,archive.open('wb') as output,gzip.GzipFile(fileobj=output,mode='wb',mtime=0) as compressed:
        while True:
            block=source.read(1048576)
            if not block:break
            compressed.write(block)
    segment.update(compressed_sha256=sha256(archive),sqlite_sha256=sha256(raw),sqlite_bytes=raw.stat().st_size)
    Path(chain_path).write_text(canonical(chain)+'\n')


class FullCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=tempfile.TemporaryDirectory(prefix='otc-full-census-seed-')
        cls.record,cls.reg,cls.plan=registration(Path(cls.seed.name))
    @classmethod
    def tearDownClass(cls):cls.seed.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='otc-full-census-case-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def assert_blocked_census(self,connection):
        self.assertTrue(old_sql_census_admits(connection,self.record),'regression does not kill the old SQL-only guard')
        with self.assertRaises(ValueError):export.validate_source_scope(connection,self.record)
    def test_unselected_fully_rehashed_empty_receipt_prestart_blocks_before_full_export(self):
        snapshot,connection=single_source(self.root,self.record,events=False)
        rewrite_envelope(connection,lambda e:e.update(received_at_ms=self.record['start_ms']-1,received_at_ns=(self.record['start_ms']-1)*NS_PER_MS))
        self.assertTrue(old_sql_census_admits(connection,self.record));seal_snapshot(snapshot,connection,self.record)
        output=self.root/'would-export-10080'
        with self.assertRaises(ValueError):export.export_matrix(snapshot,self.reg,self.plan,output,now_ms=self.record['end_ms'])
        self.assertFalse(output.exists(),'invalid unselected source reached the grid exporter')
    def test_every_empty_receipt_hash_identity_and_exact_clock_is_checked(self):
        mutations={'frame':lambda e:e.update(frame_id='canonical-other'),
            'session':lambda e:e.update(session_id='canonical-other'),
            'sequence':lambda e:e.update(sequence=2),
            'monotonic':lambda e:e.update(monotonic_ns=2),
            'canonical_ms':lambda e:e.update(received_at_ms=e['received_at_ms']+1),
            'canonical_ns':lambda e:e.update(received_at_ns=e['received_at_ns']+NS_PER_MS),
            'boolean_ms':lambda e:e.update(received_at_ms=True),
            'boolean_ns':lambda e:e.update(received_at_ns=True),
            'missing_ns':lambda e:e.pop('received_at_ns')}
        for label,mutate in mutations.items():
            root=self.root/label;root.mkdir();snapshot,connection=single_source(root,self.record,events=False,memory=True)
            try:
                rewrite_envelope(connection,mutate)
                with self.subTest(case=label):self.assert_blocked_census(connection)
            finally:connection.close()
        root=self.root/'hash';root.mkdir();snapshot,connection=single_source(root,self.record,events=False,memory=True)
        try:
            connection.execute('UPDATE receipts SET envelope_sha256=?',('f'*64,));connection.commit()
            self.assert_blocked_census(connection)
        finally:connection.close()
    def test_unselected_observation_canonical_and_lineage_match_sql_and_receipt(self):
        for mode in ('canonical_asset','canonical_clock','lineage_ms','lineage_ns','lineage_status'):
            root=self.root/mode;root.mkdir();snapshot,connection=single_source(root,self.record,memory=True)
            try:
                envelope=strict_json(connection.execute('SELECT envelope_json FROM receipts').fetchone()[0]);entry=envelope['events'][0]
                if mode=='canonical_asset':entry['observation']['asset']=ASSETS[1]
                elif mode=='canonical_clock':entry['observation']['event_ms']-=1
                elif mode=='lineage_ms':entry['lineage']['received_at_ms']+=1
                elif mode=='lineage_ns':entry['lineage']['received_at_ns']+=1
                else:entry['lineage']['clock_status']='clock_fault'
                connection.execute('UPDATE observations SET observation_json=?,lineage_json=?',(canonical(entry['observation']),canonical(entry['lineage'])))
                connection.execute('UPDATE receipts SET envelope_json=?,envelope_sha256=?',(canonical(envelope),digest(envelope)));connection.commit()
                with self.subTest(case=mode):self.assert_blocked_census(connection)
            finally:connection.close()
    def test_receipt_event_inventory_is_exact_even_outside_selected_windows(self):
        for mode in ('missing','extra','duplicate','sql_only_identity'):
            root=self.root/mode;root.mkdir();snapshot,connection=single_source(root,self.record,memory=True)
            try:
                def mutate(envelope):
                    if mode=='missing':envelope['events']=[]
                    elif mode=='extra':
                        entry=copy.deepcopy(envelope['events'][0]);entry['observation']['event_id']='unindexed-extra'
                        envelope['events'].append(entry)
                    elif mode=='duplicate':envelope['events'].append(copy.deepcopy(envelope['events'][0]))
                rewrite_envelope(connection,mutate)
                if mode=='sql_only_identity':connection.execute("UPDATE observations SET event_id='canonical-not-sql'");connection.commit()
                with self.subTest(case=mode):self.assert_blocked_census(connection)
            finally:connection.close()
    def test_raw_record_caps_apply_before_deserializing_unselected_payloads(self):
        for mode in ('envelope','observation','lineage'):
            root=self.root/mode;root.mkdir();snapshot,connection=single_source(root,self.record,memory=True)
            try:
                envelope=strict_json(connection.execute('SELECT envelope_json FROM receipts').fetchone()[0])
                if mode=='envelope':envelope['padding']='x'*(export.MAX_ENVELOPE_BYTES+1)
                else:
                    entry=envelope['events'][0];entry[mode]['padding']='x'*(export.MAX_RECORD_BYTES+1)
                    if mode=='observation':connection.execute('UPDATE observations SET observation_json=?',(canonical(entry[mode]),))
                    else:connection.execute('UPDATE observations SET lineage_json=?',(canonical(entry[mode]),))
                connection.execute('UPDATE receipts SET envelope_json=?,envelope_sha256=?',(canonical(envelope),digest(envelope)));connection.commit()
                self.assertTrue(old_sql_census_admits(connection,self.record))
                with self.subTest(case=mode),self.assertRaisesRegex(ValueError,'budget|byte|size|cap'):export.validate_source_scope(connection,self.record)
            finally:connection.close()
    def test_valid_empty_and_fault_receipts_are_counted_with_zero_violations(self):
        for label,events,status in [('empty',False,'ok'),('fault',True,'clock_fault')]:
            root=self.root/label;root.mkdir();snapshot,connection=single_source(root,self.record,events=events,clock_status=status,memory=True)
            try:
                summary=export.validate_source_scope(connection,self.record)
                self.assertEqual(summary['checked_receipts'],1);self.assertEqual(summary['checked_observations'],int(events))
                self.assertEqual(summary['violations'],0)
            finally:connection.close()
    def test_empty_receipt_event_record_count_is_bounded_before_inventory_parse(self):
        from services.otc_fresh_compare.census import MAX_EVENTS_PER_RECEIPT
        snapshot,connection=single_source(self.root,self.record,events=False,memory=True)
        try:
            rewrite_envelope(connection,lambda e:e.update(events=[{}]*(MAX_EVENTS_PER_RECEIPT+1)))
            self.assertTrue(old_sql_census_admits(connection,self.record))
            with self.assertRaisesRegex(ValueError,'record cap'):export.validate_source_scope(connection,self.record)
        finally:connection.close()
    def test_later_owned_session_open_before_previous_close_rejects(self):
        record,reg,plan,db,chain,cutoff=focused_chain(self.root)
        mutate_archive(chain,self.root,1,lambda c:c.execute("UPDATE sessions SET at_ms=? WHERE transition='open'",(cutoff-1,)))
        reader=SourceChain(chain,record,record['end_ms'])
        try:
            with self.assertRaises(ValueError):reader.close()
        finally:reader.abort()
    def test_later_backward_receipts_cannot_silently_miss_prior_decisions(self):
        record,reg,plan,db,chain,cutoff=focused_chain(self.root)
        def mutate(connection):
            moment=cutoff-3*GRID_MS
            connection.execute("UPDATE sessions SET at_ms=? WHERE transition='open'",(moment,))
            frame,raw=connection.execute('SELECT frame_id,envelope_json FROM receipts LIMIT 1').fetchone()
            envelope=strict_json(raw);envelope.update(received_at_ms=moment,received_at_ns=moment*NS_PER_MS)
            for entry in envelope['events']:
                entry['observation'].update(available_ms=moment,event_ms=moment)
                entry['lineage'].update(received_at_ms=moment,received_at_ns=moment*NS_PER_MS)
                connection.execute('UPDATE observations SET available_ms=?,observation_json=?,lineage_json=? WHERE event_id=?',
                    (moment,canonical(entry['observation']),canonical(entry['lineage']),entry['observation']['event_id']))
            connection.execute('UPDATE receipts SET received_at_ms=?,envelope_json=?,envelope_sha256=? WHERE frame_id=?',
                (moment,canonical(envelope),digest(envelope),frame))
        mutate_archive(chain,self.root,1,mutate)
        reader=SourceChain(chain,record,record['end_ms'])
        try:
            with self.assertRaises(ValueError):reader.close()
        finally:reader.abort()
    def test_exact_ms_handoff_and_producer_metadata_lag_remain_valid(self):
        record,reg,plan,db,chain,cutoff=focused_chain(self.root)
        data=strict_json(chain.read_text())
        for item in data['segments']:item['closed_at_ms']+=9
        chain.write_text(canonical(data)+'\n');reader=SourceChain(chain,record,record['end_ms']+9)
        try:
            reader.close();self.assertEqual(reader.decoded,2)
        finally:reader.abort()


if __name__=='__main__':unittest.main()
