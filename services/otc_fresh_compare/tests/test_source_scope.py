"""Whole-source scope must reject even fully rehashed out-of-cohort rows."""
from pathlib import Path
import gzip
import sqlite3
import tempfile
import unittest
from contracts.otc_fresh_v1 import canonical,digest,sha256,strict_json
from services.otc_fresh_compare.export import boundary
from services.otc_fresh_compare.tests.fixtures import registration,collector_boundary
from services.otc_fresh_compare.tests.test_chain import focused_chain
from services.otc_fresh_compare.source_chain import SourceChain

class ScopeTests(unittest.TestCase):
    def test_rehashed_prestart_end_or_postclose_receipts_block(self):
        for mode in ('prestart','end','postclose'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);record,reg,plan=registration(root)
                snapshot=collector_boundary(root,record,first_only=True)
                db=snapshot/'receipts.sqlite';conn=sqlite3.connect(db)
                if mode=='postclose':
                    conn.execute("UPDATE sessions SET at_ms=? WHERE transition='close'",(record['start_ms']+1,))
                    conn.execute('INSERT INTO sessions VALUES(?,?,?,?)',('later','open',record['start_ms'],'{}'))
                    conn.execute('INSERT INTO sessions VALUES(?,?,?,?)',('later','close',record['end_ms'],'{}'))
                else:
                    moment=record['start_ms']-1 if mode=='prestart' else record['end_ms']
                    frame,raw,envelope_sha=conn.execute('SELECT frame_id,envelope_json,envelope_sha256 FROM receipts LIMIT 1').fetchone()
                    envelope=strict_json(raw);envelope['received_at_ms']=moment;envelope['received_at_ns']=moment*1000000
                    event=envelope['events'][0];event['observation'].update(available_ms=moment,event_ms=moment)
                    event['lineage'].update(received_at_ms=moment,received_at_ns=moment*1000000)
                    conn.execute('UPDATE receipts SET received_at_ms=?,envelope_json=?,envelope_sha256=? WHERE frame_id=?',(moment,canonical(envelope),digest(envelope),frame))
                    conn.execute('UPDATE observations SET available_ms=?,observation_json=?,lineage_json=? WHERE frame_id=?',(moment,canonical(event['observation']),canonical(event['lineage']),frame))
                conn.commit();conn.close()
                manifest_path=snapshot/'manifest.json';manifest=strict_json(manifest_path.read_text());manifest.pop('manifest_sha256')
                manifest['hashes']['receipts.sqlite']=sha256(db);manifest['manifest_sha256']=digest(manifest)
                manifest_path.write_text(canonical(manifest)+'\n')
                with self.assertRaises(ValueError):
                    result=boundary(snapshot,reg,plan,record['end_ms'])
                    result[0].close()
    def test_rehashed_chain_censuses_unused_prestart_and_postclose_rows(self):
        for mode in ('prestart','postclose'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);record,reg,plan,db,chain_path,cutoff=focused_chain(root)
                chain=strict_json(chain_path.read_text());segment=chain['segments'][0];archive=Path(segment['path'])
                raw=root/'attack.sqlite';raw.write_bytes(gzip.decompress(archive.read_bytes()));conn=sqlite3.connect(raw)
                if mode=='postclose':
                    last=conn.execute('SELECT max(received_at_ms) FROM receipts').fetchone()[0]
                    conn.execute("UPDATE sessions SET at_ms=? WHERE transition='close'",(last-1,))
                else:
                    moment=record['start_ms']-1
                    frame,encoded=conn.execute('SELECT frame_id,envelope_json FROM receipts LIMIT 1').fetchone()
                    envelope=strict_json(encoded);envelope['received_at_ms']=moment;envelope['received_at_ns']=moment*1000000
                    event=envelope['events'][0];event['observation'].update(available_ms=moment,event_ms=moment)
                    event['lineage'].update(received_at_ms=moment,received_at_ns=moment*1000000)
                    conn.execute('UPDATE receipts SET received_at_ms=?,envelope_json=?,envelope_sha256=? WHERE frame_id=?',(moment,canonical(envelope),digest(envelope),frame))
                    conn.execute('UPDATE observations SET available_ms=?,observation_json=?,lineage_json=? WHERE frame_id=?',(moment,canonical(event['observation']),canonical(event['lineage']),frame))
                conn.commit();conn.close();archive.write_bytes(gzip.compress(raw.read_bytes(),mtime=0))
                segment.update(compressed_sha256=sha256(archive),sqlite_sha256=sha256(raw),sqlite_bytes=raw.stat().st_size)
                chain_path.write_text(canonical(chain)+'\n');reader=SourceChain(chain_path,record,record['end_ms'])
                try:
                    with self.assertRaises(ValueError):reader.close()
                finally:reader.abort()
    def test_future_declared_source_closure_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            record,reg,plan,db,chain_path,cutoff=focused_chain(Path(folder))
            chain=strict_json(chain_path.read_text());chain['segments'][-1]['closed_at_ms']=record['end_ms']+10000
            chain_path.write_text(canonical(chain)+'\n')
            with self.assertRaises(ValueError):SourceChain(chain_path,record,record['end_ms']+1000)

if __name__=='__main__':unittest.main()
