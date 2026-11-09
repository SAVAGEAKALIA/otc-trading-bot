"""Fast deterministic admission and policy regressions; no model fitting."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.otc_research.training import (
    ASSETS, COLUMNS, FEATURES, LIMITS, MANIFEST_SCHEMA, Record, choose_policy,
    enforce_output_path, expected_returns, load_inputs,
    partition, partition_purged, policy_decisions, proper_scores, temperature_probs, run_comparison,
    strict_json,
)


def record(key='a', asset=ASSETS[0], decision=None, status='resolved', label='up', payout=.84):
    decision = LIMITS['policy'][0] + 1000 if decision is None else decision
    return Record(key, asset, decision, decision + 120000, status, label, payout,
                  tuple(0.1 for _ in FEATURES), 'received_price_proxy')


class TrainingGate(unittest.TestCase):
    def test_training_columns_use_the_shared_boundary(self):
        from contracts.otc_v1 import training_schema
        self.assertIs(COLUMNS,training_schema.COLUMNS)
        self.assertIs(FEATURES,training_schema.FEATURES)
        self.assertIs(ASSETS,training_schema.ASSETS)
        self.assertEqual(MANIFEST_SCHEMA,training_schema.MANIFEST_SCHEMA)

    def test_legal_json_numeric_overflow_rejected_at_any_depth(self):
        for value in ['{"metadata":{"value":1e10000}}',
                      '{"metadata":{"nested":[-1e10000]}}',
                      '{"metadata":{"nested":[{"value":1e10000}]}}']:
            with self.subTest(value=value),self.assertRaises(ValueError):strict_json(value)
        self.assertEqual(strict_json('{"metadata":{"decimal":"1e10000","finite":1e10}}'),
                         {'metadata':{'decimal':'1e10000','finite':1e10}})

    def test_output_guard_rejects_bare_repository_before_creating_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'HEAD').write_text('ref: refs/heads/main\n')
            (root/'objects').mkdir();(root/'refs').mkdir()
            with self.assertRaises(ValueError):enforce_output_path(root/'models')
            self.assertFalse((root/'models').exists())
            outside=root.parent/(root.name+'-outside')
            try:
                self.assertEqual(enforce_output_path(outside),outside.resolve())
            finally:
                outside.rmdir()

    def test_admission_failure_has_status_and_measured_phase_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'missing.csv';manifest=root/'missing.json';output=root/'run'
            with patch('builtins.print'),self.assertRaises(OSError):run_comparison(source,manifest,output)
            status=json.loads((output/'report.json').read_text())
            self.assertEqual(status['status'],'BLOCKED')
            self.assertFalse(status['promotable'])
            progress=[json.loads(line) for line in (output/'progress.log').read_text().splitlines()]
            self.assertEqual(progress[-1]['phase'],'failed')
            self.assertEqual(progress[-1]['completed_phases'],0)
            self.assertIsNone(progress[-1]['estimated_seconds_remaining'])

    def test_output_guard_rejects_other_repositories_and_worktrees(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for marker in ['directory','file']:
                repository=root/marker;repository.mkdir()
                if marker=='directory':
                    (repository/'.git').mkdir();(repository/'.git/HEAD').write_text('ref: refs/heads/main\n')
                else:(repository/'.git').write_text('gitdir: /tmp/example')
                with self.assertRaises(ValueError):enforce_output_path(repository/'models')
                self.assertFalse((repository/'models').exists())

    def test_negative_policies_abstain_instead_of_selecting_least_bad(self):
        variants=[{'threshold':threshold,'support_pass':True,
                   'selective':{'worst_case_mean_unit_return':score}}
                  for threshold,score in [(0,-.2),(.03,-.1),(.05,-.3)]]
        self.assertIsNone(choose_policy(variants))
        variants[1]['selective']['worst_case_mean_unit_return']=.1
        self.assertEqual(choose_policy(variants)['threshold'],.03)

    def test_boundary_purge_is_global(self):
        end = LIMITS['train'][1]
        self.assertEqual(partition(end), 'early')
        self.assertTrue(partition_purged(record(decision=end-120000)))
        self.assertFalse(partition_purged(record(decision=end-120001)))

    def test_tie_probability_is_not_a_win(self):
        call, put = expected_returns((.4, .3, .3), .8)
        self.assertAlmostEqual(call, .02)
        self.assertAlmostEqual(put, -.16)

    def test_unresolved_blocks_both_assets_and_stays_in_population(self):
        one=record(key='a', status='unresolved', label='')
        two=record(key='b', asset=ASSETS[1], decision=one.decision_ms+1000)
        decisions, summary=policy_decisions([two,one],[(.8,.1,.1),(.8,.1,.1)],0)
        by_id={row['opportunity_id']:row for row in decisions}
        self.assertTrue(by_id['a']['accepted'])
        self.assertIsNone(by_id['a']['proxy_unit_return'])
        self.assertEqual(by_id['b']['reason'],'position_open')
        self.assertEqual(summary['population'],2)
        self.assertEqual(summary['accepted_unresolved'],1)
        self.assertEqual(summary['worst_case_mean_unit_return'],-1)

    def test_position_tie_breaker_uses_asset_then_id(self):
        a=record('z',ASSETS[0]);b=record('a',ASSETS[1])
        decisions,_=policy_decisions([b,a],[(.8,.1,.1)]*2,0)
        self.assertEqual([r['opportunity_id'] for r in decisions if r['accepted']],['z'])

    def test_tie_refund_and_ineligible_are_counted(self):
        a=record(label='tie');b=record('b',decision=a.expiry_ms,status='ineligible',label='',payout=None)
        decisions,summary=policy_decisions([a,b],[(.8,.1,.1)]*2,0)
        self.assertEqual(decisions[0]['proxy_unit_return'],0)
        self.assertEqual(summary['accepted_ties'],1)
        self.assertEqual(summary['population'],2)
        self.assertEqual(summary['accepted'],1)
        self.assertEqual(decisions[1]['reason'],'ineligible')

    def test_temperature_keeps_three_classes(self):
        result=temperature_probs([[.8,.1,.1]],2)[0]
        self.assertEqual(len(result),3)
        self.assertAlmostEqual(sum(result),1)
        self.assertLess(result[0],.8)
        scores=proper_scores(['up','tie'],[(1,0,0),(0,0,1)])
        self.assertEqual(scores['brier'],0)
        self.assertLess(scores['log_loss'],1e-12)

    def test_admission_positive_and_corruptions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'data.csv';manifest=root/'manifest.json'
            row=dict(zip(COLUMNS,['x',ASSETS[0],LIMITS['train'][1]-240000,LIMITS['train'][1]-120000,'resolved','tie',.84,0,.5,.5,.84,1,1,1,'received_price_proxy']))
            def write(changes=None,extra=False):
                data={**row,**(changes or {})};columns=list(COLUMNS)
                if extra: columns.append('future_close');data['future_close']=1
                with source.open('w',newline='') as handle:
                    writer=csv.DictWriter(handle,fieldnames=columns);writer.writeheader();writer.writerow(data)
                digest=hashlib.sha256(source.read_bytes()).hexdigest()
                manifest.write_text(json.dumps({'schema':MANIFEST_SCHEMA,
                    'expiry_basis':'hypothetical','product_mapping':'explicit_assumed','clock':'receiver_utc',
                    'feature_availability':'receiver_receipt_lte_decision',
                    'outcome_basis':'last_received_quote_at_or_before_expiry',
                    'evidence_classes':['received_price_proxy'],'input_sha256':digest,
                    'source_lineage':[{'source_id':'test-observations','sha256':digest,
                                       'kind':'received_quote_observations','clock':'receiver_utc'}]}))
            write();records,_=load_inputs(source,manifest);self.assertEqual(records[0].label,'tie')
            for changes in [{'label':'win'},{'status':'unresolved','label':'up'},{'expiry_ms':row['decision_ms']},{'f_mood_age_ms':-1},{'f_return_lookback':'NaN'},{'asset':'UNKNOWN'},
                            {'f_quote_age_ms':''},{'f_mood_age_ms':''},{'f_payout_age_ms':''},
                            {'f_quote_age_ms':row['decision_ms']+1},{'f_quote_age_ms':1e100},
                            {'f_quote_age_ms':5001},{'f_mood_age_ms':60001},
                            {'f_payout_age_ms':600001},{'f_mood_age_ms':1.5},
                            {'evidence_class':'future_interpolated_candle_close'}]:
                write(changes)
                with self.assertRaises(ValueError):load_inputs(source,manifest)
            for changes in [{'schema':'unsupported_dataset_v999'},
                            {'feature_availability':'source_event_time_even_if_received_later'},
                            {'source_lineage':[]},{'promotable':True},{'metadata':{'bad':float('nan')}}]:
                write();data=json.loads(manifest.read_text());data.update(changes);manifest.write_text(json.dumps(data))
                with self.assertRaises(ValueError):load_inputs(source,manifest)
            write({'f_own_mood':'','f_market_mood':'','f_mood_age_ms':''})
            self.assertIsNone(load_inputs(source,manifest)[0][0].features[1])
            write(extra=True)
            with self.assertRaises(ValueError):load_inputs(source,manifest)
            write();manifest.write_text('{}')
            with self.assertRaises(ValueError):load_inputs(source,manifest)


if __name__=='__main__':
    unittest.main()
