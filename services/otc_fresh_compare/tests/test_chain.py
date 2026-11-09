"""Focused source-chain/cutoff replay. No fit, transport or side tools."""
from __future__ import annotations
import copy
import gzip
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from contracts.otc_fresh_v1 import ASSETS,GRID_MS,canonical,digest,sha256,strict_json
from services.otc_fresh_compare.export import replay_decision
from services.otc_fresh_compare.source_chain import SourceChain,CLOSURE_ARCHIVE_GRACE_MS,chain_wait_state,wait_for_chain
from services.otc_fresh_compare.tests.fixtures import registration,collector_boundary

def focused_chain(root):
    record,reg,plan=registration(root);snapshot=collector_boundary(root,record,first_only=True)
    database=snapshot/'receipts.sqlite';conn=sqlite3.connect(database)
    cutoff=record['partitions']['early']['start_ms'];shift=cutoff-GRID_MS-record['start_ms']
    originals=list(conn.execute('SELECT * FROM observations'))
    conn.execute('DELETE FROM observations');conn.execute('DELETE FROM receipts')
    sequence=0
    def add(template,moment,identity,value=None):
        nonlocal sequence
        sequence+=1;row=list(template);obs=strict_json(row[6]);meta=strict_json(row[7])
        obs.update(event_id=identity,available_ms=moment,event_ms=moment)
        if value is not None:obs['value']=str(value)
        meta.update(received_at_ms=moment,received_at_ns=moment*1000000,source_event_ms=moment)
        frame='chain-frame-'+identity;row[0]=identity;row[1]=frame;row[5]=moment;row[6]=canonical(obs);row[7]=canonical(meta)
        envelope={'frame_id':frame,'session_id':'synthetic','sequence':sequence,'received_at_ms':moment,
            'received_at_ns':moment*1000000,'events':[{'observation':obs,'lineage':meta}],'health':None}
        conn.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',(frame,'synthetic',sequence,moment,sequence,canonical(envelope),digest(envelope)))
        conn.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',row)
    for index,template in enumerate(originals):
        moment=template[5]+shift;add(template,moment,'old-'+str(index))
        if template[3]!='payout' and not (template[2]==ASSETS[1] and template[3]=='mood'):
            for period in (1,2):add(template,moment+period*GRID_MS,f'new-{period}-{index}',100+period if template[3]=='quote' else None)
    mood=next(row for row in originals if row[2]==ASSETS[1] and row[3]=='mood')
    add(mood,cutoff-1,'previous-shard-recent-mood',.3)
    conn.commit();conn.close()
    segments=root/'segments';segments.mkdir();items=[]
    for index in (1,2):
        raw=segments/f'closed-{index}.sqlite';shutil.copyfile(database,raw)
        connection=sqlite3.connect(raw)
        # Disposable synthetic copies only, never live recorder settings.
        connection.execute('PRAGMA journal_mode=MEMORY')
        connection.execute('PRAGMA synchronous=OFF')
        if index==1:
            connection.execute('DELETE FROM observations WHERE available_ms>=?',(cutoff,));connection.execute('DELETE FROM receipts WHERE received_at_ms>=?',(cutoff,))
            connection.execute("UPDATE sessions SET at_ms=? WHERE transition='close'",(cutoff,));closed=cutoff
        else:
            connection.execute('DELETE FROM observations WHERE available_ms<?',(cutoff,));connection.execute('DELETE FROM receipts WHERE received_at_ms<?',(cutoff,));closed=record['end_ms']
            connection.execute("UPDATE sessions SET at_ms=? WHERE transition='open'",(cutoff,))
        # Equal-width identities keep serialized-input parity with the mono
        # fixture while modelling distinct physical producer sessions.
        session='shard-'+str(index).zfill(3)
        connection.execute('UPDATE sessions SET session_id=?',(session,))
        connection.execute('UPDATE receipts SET session_id=?',(session,))
        cursor=connection.execute('SELECT frame_id,envelope_json FROM receipts')
        for frame,encoded in cursor:
            envelope=strict_json(encoded);envelope['session_id']=session
            connection.execute('UPDATE receipts SET envelope_json=?,envelope_sha256=? WHERE frame_id=?',(canonical(envelope),digest(envelope),frame))
        connection.commit();connection.close()
        archive=raw.with_suffix('.sqlite.gz')
        with archive.open('wb') as output,gzip.GzipFile(fileobj=output,mode='wb',mtime=0) as compressed,raw.open('rb') as source:
            shutil.copyfileobj(source,compressed,1024*1024)
        items.append({'path':str(archive),'compressed_sha256':sha256(archive),'sqlite_sha256':sha256(raw),
                      'sqlite_bytes':raw.stat().st_size,'closed_at_ms':closed})
        raw.unlink()
    chain={'schema':'fresh_otc_source_chain_v1','registration_sha256':record['registration_sha256'],
           'complete':True,'segments':items}
    path=root/'source-chain.json';path.write_text(canonical(chain)+'\n')
    return record,reg,plan,database,path,cutoff

class ChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='otc-chain-focused-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.record,self.reg,self.plan,self.single,self.chain,self.cutoff=focused_chain(self.root)
    def test_source_chain_matches_monolithic_replay_across_fixed_cutoff(self):
        mono=sqlite3.connect(self.single.as_uri()+'?mode=ro&immutable=1',uri=True)
        shards=SourceChain(self.chain,self.record,self.record['end_ms'])
        try:
            for moment in (self.cutoff-GRID_MS,self.cutoff,self.cutoff+GRID_MS):
                left,details_left,stats_left=replay_decision(mono,moment)
                right,details_right,stats_right=replay_decision(shards,moment)
                self.assertEqual(left,right);self.assertEqual(details_left,details_right)
                self.assertEqual(stats_left,stats_right)
                if moment==self.cutoff:
                    self.assertTrue(all(row['f_return_lookback']!='' and row['payout']!='' for row in right))
                    self.assertIn('previous-shard-recent-mood',details_right[1]['lineage']['market_mood'])
            self.assertEqual(shards.decoded,2);self.assertGreater(shards.maximum_tail_rows,0)
        finally:mono.close();shards.close()
        self.assertIsNone(shards.temporary)
    def test_unfinished_wrong_registration_boolean_size_and_reordered_chain_rejected(self):
        original=strict_json(self.chain.read_text())
        changes=[lambda c:c.update(complete=False),lambda c:c.update(complete=1),
            lambda c:c.update(registration_sha256='f'*64),lambda c:c['segments'].reverse(),
            lambda c:c['segments'][0].update(sqlite_bytes=True),lambda c:c.update(ops_state={})]
        for change in changes:
            candidate=copy.deepcopy(original);change(candidate);self.chain.write_text(canonical(candidate)+'\n')
            with self.subTest(change=change),self.assertRaises(ValueError):SourceChain(self.chain,self.record,self.record['end_ms'])
        self.chain.write_text(canonical(original)+'\n')
        with self.assertRaises(ValueError):SourceChain(self.chain,self.record,self.record['end_ms']-1)
    def test_decoded_hash_and_compressed_source_change_rejected(self):
        value=strict_json(self.chain.read_text());value['segments'][0]['sqlite_sha256']='f'*64
        self.chain.write_text(canonical(value)+'\n');reader=SourceChain(self.chain,self.record,self.record['end_ms'])
        with self.assertRaises(ValueError):replay_decision(reader,self.cutoff-GRID_MS)
        reader.abort()
        value['segments'][0]['compressed_sha256']='e'*64;self.chain.write_text(canonical(value)+'\n')
        reader=SourceChain(self.chain,self.record,self.record['end_ms'])
        with self.assertRaises(ValueError):replay_decision(reader,self.cutoff-GRID_MS)
        reader.abort()
    def test_archive_wait_has_fixed_grace_unknown_eta_and_no_chronology_extension(self):
        original=strict_json(self.chain.read_text());end=self.record['end_ms']
        with self.assertRaisesRegex(ValueError,'before registered end'):chain_wait_state(self.chain,self.record,end-1)
        pending=copy.deepcopy(original);pending['complete']=False;self.chain.write_text(canonical(pending)+'\n')
        self.assertEqual(chain_wait_state(self.chain,self.record,end-1)['status'],'WAITING_REGISTERED_END')
        state=chain_wait_state(self.chain,self.record,end)
        self.assertEqual(state['status'],'WAITING_ARCHIVE');self.assertIsNone(state['eta_seconds'])
        deadline=end+CLOSURE_ARCHIVE_GRACE_MS
        self.assertEqual(chain_wait_state(self.chain,self.record,deadline-1)['status'],'WAITING_ARCHIVE')
        self.assertEqual(chain_wait_state(self.chain,self.record,deadline)['status'],'BLOCKED')
        clock=[deadline-1];sleeps=[]
        def sleep(seconds):sleeps.append(seconds);clock[0]+=round(seconds*1000)
        with self.assertRaisesRegex(ValueError,'fixed one-hour'):wait_for_chain(self.chain,self.record,clock_ms=lambda:clock[0],sleep=sleep,progress_path=self.root/'wait-progress.log')
        self.assertEqual(sleeps,[.001]);self.assertEqual(self.record['end_ms'],end)
        self.chain.write_text(canonical(original)+'\n')
        self.assertEqual(chain_wait_state(self.chain,self.record,end)['status'],'READY')
    def test_producer_closure_lag_keeps_actual_session_boundary_and_future_close_rejects(self):
        original=strict_json(self.chain.read_text());lagged=copy.deepcopy(original)
        for item in lagged['segments']:item['closed_at_ms']+=3
        self.chain.write_text(canonical(lagged)+'\n')
        mono=sqlite3.connect(self.single.as_uri()+'?mode=ro&immutable=1',uri=True)
        reader=SourceChain(self.chain,self.record,self.record['end_ms']+3)
        try:
            for decision in (self.cutoff-GRID_MS,self.cutoff,self.cutoff+GRID_MS):
                self.assertEqual(replay_decision(reader,decision),replay_decision(mono,decision))
        finally:mono.close();reader.close()
        # Archive metadata cannot declare producer closure before a session
        # actually closed, even though later producer metadata is legitimate.
        invalid=copy.deepcopy(original);invalid['segments'][0]['closed_at_ms']-=1
        self.chain.write_text(canonical(invalid)+'\n');reader=SourceChain(self.chain,self.record,self.record['end_ms'])
        with self.assertRaisesRegex(ValueError,'closure evidence'):replay_decision(reader,self.cutoff-GRID_MS)
        reader.abort()

if __name__=='__main__':unittest.main()
