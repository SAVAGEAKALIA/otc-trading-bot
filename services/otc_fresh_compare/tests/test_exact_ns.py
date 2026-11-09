"""Exact ordering and non-retroactive conflict regressions. No fit or I/O service."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contracts.otc_fresh_v1 import ASSETS,CONFIG,GRID_MS,canonical,digest
from services.otc_fresh_compare.export import NS_PER_MS,replay_decision
from services.otc_fresh_compare.tests.fixtures import DDL


def receipt_database(path,events):
    connection=sqlite3.connect(path)
    # Disposable synthetic inputs only. Collector/source durability is frozen.
    connection.execute('PRAGMA journal_mode=MEMORY')
    connection.execute('PRAGMA synchronous=OFF')
    connection.executescript(DDL)
    for sequence,(asset,kind,received_ns,value,identity) in enumerate(events,1):
        moment=received_ns//NS_PER_MS;frame='frame-'+identity
        source={'quote':'quote_samples','mood':'mood_samples','payout':'commission-stream'}[kind]
        row={'event_id':identity,'broker':'iqoption','asset':asset,'product':'turbo-option',
            'source':source,'kind':kind,'available_ms':moment,'event_ms':moment,
            'value':value,'clock_id':'receiver_utc','quality':'received'}
        lineage={'clock_status':'ok','received_at_ms':moment,'received_at_ns':received_ns}
        envelope={'frame_id':frame,'received_at_ms':moment,'received_at_ns':received_ns,
            'events':[{'observation':row,'lineage':lineage}]}
        connection.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)',
            (frame,'exact-fixture',sequence,moment,sequence,canonical(envelope),digest(envelope)))
        connection.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',
            (identity,frame,asset,kind,source,moment,canonical(row),canonical(lineage),'ok'))
    connection.commit();return connection


def decision_events(decision):
    ns=decision*NS_PER_MS;events=[]
    for index,asset in enumerate(ASSETS):
        events.extend([(asset,'quote',ns-1,'99',f'decision-{index}'),
            (asset,'payout',ns,'0.85',f'payout-{index}'),
            (asset,'mood',ns,'0.5',f'mood-{index}'),
            (asset,'quote',ns+100,'100',f'a-earliest-{index}'),
            (asset,'quote',ns+200,'101',f'z-later-{index}'),
            (asset,'quote',(decision+GRID_MS)*NS_PER_MS-1,'102',f'terminal-{index}')])
    return events


class ExactNanosecondGates(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='otc-exact-ns-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.decision=1794046080000
    def replay(self,events,name):
        connection=receipt_database(self.root/(name+'.sqlite'),events)
        try:return replay_decision(connection,self.decision)
        finally:connection.close()
    def test_distinct_ns_receipts_order_earliest_entry_and_terminal_without_ms_conflict(self):
        rows,details,stats=self.replay(decision_events(self.decision),'ordered')
        self.assertEqual(stats['conflicts'],[])
        self.assertTrue(all(row['status']=='resolved' and row['label']=='up' for row in rows))
        self.assertEqual([row['lineage']['modeled_strike'] for row in details],['a-earliest-0','a-earliest-1'])
        self.assertTrue(all(row['modeled_strike']=='100' for row in details))
        self.assertTrue(all(row['f_quote_age_ms']==1 for row in rows))
        # A floor-ms-only replay wrongly rejects distinct sequential receipts
        # as an event-time conflict instead of keeping their true order.
        from contracts.otc_v1 import Opportunity
        from services.otc_research.dataset import build_rows
        connection=receipt_database(self.root/'old.sqlite',decision_events(self.decision))
        try:
            import json
            original=[json.loads(raw) for raw, in connection.execute('SELECT observation_json FROM observations')]
        finally:connection.close()
        op=Opportunity('old','iqoption',ASSETS[0],'turbo-option','receiver_utc',self.decision,
            self.decision+GRID_MS,self.decision+2000,'hypothetical',None,0).as_record()
        with self.assertRaisesRegex(ValueError,'event-time value conflict'):build_rows(original,[op],CONFIG)
    def test_future_exact_conflicts_preserve_features_and_only_make_outcomes_unknown(self):
        events=decision_events(self.decision);base_rows,base,unused=self.replay(events,'base')
        for label,moment in [('entry',self.decision*NS_PER_MS+150),
            ('terminal',(self.decision+GRID_MS)*NS_PER_MS-1)]:
            additions=[(ASSETS[0],'quote',moment,value,label+str(index))
                for index,value in enumerate(('103','104'))]
            rows,details,stats=self.replay(events+additions,label)
            self.assertEqual(rows[0]['status'],'unresolved');self.assertIsNone(details[0]['label'])
            self.assertEqual(details[0]['features'],base[0]['features'])
            self.assertEqual(rows[1],base_rows[1]);self.assertEqual(len(stats['conflicts']),1)
            self.assertIn('conflicting_received_batch_at_outcome_cutoff',details[0]['reason_codes'])
            self.assertNotIn('conflicting_received_batch_at_feature_cutoff',details[0]['reason_codes'])


if __name__=='__main__':unittest.main()
