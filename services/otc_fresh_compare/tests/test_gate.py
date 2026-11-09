import ast
import copy
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contracts.otc_fresh_v1 import ASSETS,CONFIG,DAY_MS,GRID_MS,canonical,digest,sha256,strict_json,validate_registration
from services.otc_fresh_compare.compiler import ROOT,compile_trainer,model_ast
from services.otc_fresh_compare.export import boundary,replay_decision
from services.otc_fresh_compare.tests.fixtures import registration,collector_boundary
from services.otc_research import training
from services.otc_fresh_compare.tests.test_exact_ns import ExactNanosecondGates

class CoreGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_temp=tempfile.TemporaryDirectory(prefix='otc-gate-frozen-input-')
        cls.seed_root=Path(cls.seed_temp.name)
        cls.seed_record,cls.seed_reg,cls.seed_plan=registration(cls.seed_root)
    @classmethod
    def tearDownClass(cls):cls.seed_temp.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='otc-fresh-core-gate-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.record=copy.deepcopy(self.seed_record)
        self.reg=self.root/'registration.json';self.reg.write_bytes(self.seed_reg.read_bytes())
        self.plan=self.root/'plan.json';self.plan.write_bytes(self.seed_plan.read_bytes())
    def mutated(self,change):
        candidate=copy.deepcopy(self.record);change(candidate)
        candidate['registration_sha256']=digest({k:v for k,v in candidate.items() if k!='registration_sha256'})
        return candidate
    def test_exact_seven_day_grid_and_historical_scope_unchanged(self):
        limits=validate_registration(self.record)
        self.assertEqual([end-start for _,start,end in limits],[3*DAY_MS,DAY_MS,DAY_MS,DAY_MS,DAY_MS])
        self.assertEqual(7*DAY_MS//GRID_MS*len(ASSETS),10080)
        self.assertEqual(training.partition(training.epoch_ms('2026-08-14')),'policy')
        with self.assertRaises(ValueError):training.partition(self.record['start_ms'])
        original=strict_json((ROOT/'original-source-lock.json').read_text())
        self.assertTrue(all(sha256(ROOT/name)==value for name,value in original['files'].items()))
    def test_boolean_late_shifted_reordered_gapped_and_config_registration_rejected(self):
        changes=[lambda r:r.update(start_ms=True),lambda r:r.update(registered_at_ms=r['start_ms'],created_ms=r['start_ms']),
            lambda r:r.update(end_ms=r['end_ms']+GRID_MS),lambda r:r['phases'].reverse(),
            lambda r:r['phases'][1].update(start_ms=r['phases'][1]['start_ms']+GRID_MS),
            lambda r:r['config']['max_age_ms'].update(quote=True),
            lambda r:r['research_code_files'].update({'services/otc_research/training.py':'f'*64})]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):validate_registration(self.mutated(change))
    def test_nested_json_overflow_and_python310_streaming_digest(self):
        path=self.root/'data';path.write_bytes(b'fresh-core')
        import hashlib
        self.assertEqual(sha256(path),hashlib.sha256(b'fresh-core').hexdigest())
        for value in ('NaN','Infinity','-Infinity','1e10000','-1e10000'):
            with self.subTest(value=value),self.assertRaises(ValueError):strict_json('{"nested":['+value+']}')
    def test_static_compiler_uses_literal_limits_and_preserves_model_ast(self):
        target=self.root/'training.py';proof=compile_trainer(self.reg,self.plan,target)
        node=next(node for node in ast.parse(target.read_text()).body if isinstance(node,ast.Assign) and any(isinstance(name,ast.Name) and name.id=='LIMITS' for name in node.targets))
        self.assertTrue(all(isinstance(value,ast.Constant) for bounds in node.value.values for value in bounds.elts))
        self.assertEqual(model_ast(target.read_text()),model_ast((ROOT/'services/otc_research/training.py').read_text()))
        self.assertFalse(proof['runtime_global_rebinding']);self.assertNotIn('file_digest',target.read_text())
        ast.parse(target.read_text(),feature_version=(3,10))
    def test_redeclared_hash_cannot_authorize_a_changed_frozen_procedure(self):
        from services.otc_fresh_compare.export import compare
        target=self.root/'training.py';compile_trainer(self.reg,self.plan,target)
        text=target.read_text();self.assertIn('THRESHOLDS = (0.0, 0.03, 0.05)',text)
        target.write_text(text.replace('THRESHOLDS = (0.0, 0.03, 0.05)','THRESHOLDS = (0.0, 0.01, 0.02)'))
        proof=strict_json(target.with_suffix('.proof.json').read_text());proof['frozen_training_sha256']=sha256(target)
        target.with_suffix('.proof.json').write_text(canonical(proof)+'\n')
        plan=strict_json(self.plan.read_text());manifest=self.root/'manifest.json'
        manifest.write_text(canonical({'metadata':{'fresh_registration':self.record,'compiler_plan_sha256':plan['plan_sha256']}})+'\n')
        with self.assertRaisesRegex(ValueError,'exact deterministic'):compare(target,self.root/'unused.csv',manifest,self.root/'unused-run')
    def test_first_decision_replays_original_builder_and_future_features_never_enter(self):
        snapshot=collector_boundary(self.root,self.record,first_only=True)
        connection,record,plan,manifest,raw=boundary(snapshot,self.reg,self.plan,self.record['end_ms'])
        try:rows,details,count=replay_decision(connection,self.record['start_ms'])
        finally:connection.close()
        self.assertEqual(len(rows),2);self.assertTrue(all(row['status']=='unresolved' for row in rows))
        self.assertTrue(all(row['features']['return_lookback_missing'] for row in details))
        self.assertEqual([row['opportunity_id'] for row in rows],[f'{asset}@{self.record["start_ms"]}' for asset in ASSETS])
    def test_immutable_receipt_source_and_unfinished_collection_rejected(self):
        snapshot=collector_boundary(self.root,self.record,first_only=True)
        with self.assertRaises(ValueError):boundary(snapshot,self.reg,self.plan,self.record['end_ms']-1)
        with (snapshot/'receipts.sqlite').open('ab') as stream:stream.write(b'changed')
        with self.assertRaises(ValueError):boundary(snapshot,self.reg,self.plan,self.record['end_ms'])
    def test_receipt_envelope_change_and_byte_budget_block_before_features(self):
        snapshot=collector_boundary(self.root,self.record,first_only=True)
        conn=sqlite3.connect(snapshot/'receipts.sqlite')
        conn.execute("UPDATE receipts SET envelope_sha256=? WHERE frame_id=(SELECT min(frame_id) FROM receipts)",('f'*64,));conn.commit()
        with self.assertRaisesRegex(ValueError,'envelope'):replay_decision(conn,self.record['start_ms'])
        conn.close()
    def test_fractional_millisecond_receipt_cannot_be_a_decision_feature(self):
        snapshot=collector_boundary(self.root,self.record,first_only=True);conn=sqlite3.connect(snapshot/'receipts.sqlite')
        identity,frame,raw,meta_raw=conn.execute("SELECT event_id,frame_id,observation_json,lineage_json FROM observations WHERE asset=? AND kind='quote' ORDER BY available_ms LIMIT 1",(ASSETS[0],)).fetchone()
        meta=strict_json(meta_raw);meta['received_at_ns']=self.record['start_ms']*1000000+1
        envelope=strict_json(conn.execute('SELECT envelope_json FROM receipts WHERE frame_id=?',(frame,)).fetchone()[0])
        envelope['received_at_ns']=meta['received_at_ns'];envelope['events'][0]['lineage']=meta
        conn.execute('UPDATE observations SET lineage_json=? WHERE event_id=?',(canonical(meta),identity))
        conn.execute('UPDATE receipts SET envelope_json=?,envelope_sha256=? WHERE frame_id=?',(canonical(envelope),digest(envelope),frame));conn.commit()
        rows,details,stats=replay_decision(conn,self.record['start_ms'])
        self.assertEqual(rows[0]['status'],'ineligible');self.assertIsNone(details[0]['lineage']['decision_quote'])
        # Literal old behavior uses the floor-ms canonical row and admits the
        # one-nanosecond future quote. The regression depends on real rejection.
        from services.otc_research.dataset import build_rows
        from contracts.otc_v1 import Opportunity
        originals=[strict_json(value) for value, in conn.execute('SELECT observation_json FROM observations')]
        op=Opportunity(f'{ASSETS[0]}@{self.record["start_ms"]}','iqoption',ASSETS[0],'turbo-option','receiver_utc',self.record['start_ms'],self.record['start_ms']+GRID_MS,self.record['start_ms']+2000,'hypothetical',None,0).as_record()
        old=build_rows(originals,[op],CONFIG)['rows'][0]
        self.assertIsNotNone(old['features']);self.assertEqual(old['lineage']['decision_quote'],identity)
        conn.close()
    def test_complete_conflicting_receipt_batch_is_reported_and_not_selected(self):
        snapshot=collector_boundary(self.root,self.record,first_only=True);conn=sqlite3.connect(snapshot/'receipts.sqlite')
        row=list(conn.execute("SELECT * FROM observations WHERE asset=? AND kind='quote' ORDER BY available_ms LIMIT 1",(ASSETS[0],)).fetchone())
        original=strict_json(row[6]);original['event_id']='conflicting-event';original['value']='102'
        meta=strict_json(row[7]);row[0]='conflicting-event';row[1]='conflicting-frame';row[6]=canonical(original)
        envelope={'frame_id':row[1],'session_id':'synthetic','sequence':999999,'received_at_ms':row[5],
            'received_at_ns':row[5]*1000000,'events':[{'observation':original,'lineage':meta}],'health':None}
        conn.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',(row[1],'synthetic',999999,row[5],999999,canonical(envelope),digest(envelope)))
        conn.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',row);conn.commit()
        rows,details,stats=replay_decision(conn,self.record['start_ms'])
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['status'],'ineligible')
        self.assertEqual(len(stats['conflicts']),1);self.assertEqual(len(stats['conflicts'][0]['event_ids']),2)
        self.assertIn('conflicting_received_batch_at_feature_cutoff',details[0]['reason_codes'])
        conn.close()
        from unittest.mock import patch
        from services.otc_fresh_compare import export
        conn=sqlite3.connect(snapshot/'receipts.sqlite')
        with patch.object(export,'MAX_WINDOW_BYTES',1),self.assertRaisesRegex(ValueError,'byte memory budget'):
            replay_decision(conn,self.record['start_ms'])
        conn.close()

if __name__=='__main__':unittest.main()
