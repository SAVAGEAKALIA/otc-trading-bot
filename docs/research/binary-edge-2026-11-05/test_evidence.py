"""Gate tests for investigative accounting and retained source counterexamples."""
import math
import json
import sys
import types
from unittest.mock import patch
import os
from pathlib import Path
import tempfile
import unittest
from evidence import (edge_function,expectancy,expiry_cases,iid_sample_size,
                      payout_probe,raw_archive_audit,unit_return)

# Root copies this bundle to docs/research/binary-edge-2026-11-05 before running.
REPO=Path(os.environ.get("BINARY_EVIDENCE_REPO",Path(__file__).resolve().parents[3]))


class AccountingTests(unittest.TestCase):
    def test_net_profit_payout_not_total_refund(self):
        self.assertAlmostEqual(unit_return('win',.8),.8)
        self.assertEqual(unit_return('loss',.8),-1)
        self.assertAlmostEqual(expectancy(.55,.8),-.01)
        self.assertAlmostEqual(expectancy(1/1.8,.8),0)

    def test_contract_ties_refunds_and_costs(self):
        self.assertEqual(unit_return('tie',.8),0)
        self.assertAlmostEqual(unit_return('tie',.8,tie_refund=.5,cost=.01),-.51)
        self.assertAlmostEqual(expectancy(.54,.8,p_tie=.02),-.008)
        self.assertAlmostEqual(expectancy(.54,.8,p_tie=.02,tie_refund=0,cost=.01),-.038)

    def test_unresolved_and_nonfinite_inputs_fail(self):
        for outcome,payout in [('unknown',.8),('win',0),('win',math.nan),('loss',math.inf)]:
            with self.subTest(outcome=outcome,payout=payout),self.assertRaises(ValueError):
                unit_return(outcome,payout)
        with self.assertRaises(ValueError):
            expectancy(.9,.8,p_tie=.2)

    def test_educational_power_monotonicity(self):
        rows=[iid_sample_size(.85,e) for e in (.01,.03,.05)]
        self.assertGreater(rows[0]['approximate_independent_trades'],rows[1]['approximate_independent_trades'])
        self.assertGreater(rows[1]['approximate_independent_trades'],rows[2]['approximate_independent_trades'])
        self.assertAlmostEqual(rows[1]['p_alternative'],1.03/1.85)
        self.assertEqual(rows[0]['alpha_one_sided'],.05)
        self.assertEqual(rows[0]['power'],.8)
        with self.assertRaises(ValueError):
            iid_sample_size(.85,0)

    def test_missing_raw_is_not_checked(self):
        self.assertEqual(raw_archive_audit(None)['status'],'NOT_CHECKED')
        with tempfile.TemporaryDirectory() as d:
            r=raw_archive_audit(Path(d))
        self.assertEqual(r['status'],'NOT_CHECKED')
        self.assertEqual(len(r['missing']),3)


    def test_unavailable_or_absent_parquet_is_not_checked(self):
        fake_pandas=types.ModuleType('pandas')
        def unavailable_reader(path):
            raise ImportError('No parquet engine installed')
        fake_pandas.read_parquet=unavailable_reader
        reports={
            'run1/results.json': {'any_edge': False, 'results': [{
                'strategy': 'fixture', 'tf_sec': 120, 'holdout_wins': 6,
                'holdout_trades': 10, 'holdout_roi': .11}]},
            'run2/tournament_results.json': {'any_candidate': False, 'results': []},
            'round3/crowd_results.json': {'results': {'lightgbm': {'candidate': False}}},
        }
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name, value in reports.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(value))
            (root/'round3/trades_lightgbm.parquet').write_bytes(b'fixture')
            with patch.dict(sys.modules, {'pandas': fake_pandas}):
                result=raw_archive_audit(root)
                (root/'round3/trades_lightgbm.parquet').unlink()
                absent=raw_archive_audit(root)
        self.assertEqual(result['status'],'REPORTS_CHECKED')
        self.assertEqual(result['parquet']['status'],'NOT_CHECKED')
        self.assertEqual(result['parquet']['rows'],[])
        self.assertEqual(result['parquet']['reason'],'Parquet reader unavailable')
        self.assertEqual(absent['parquet']['status'],'NOT_CHECKED')
        self.assertEqual(absent['parquet']['rows'],[])
        self.assertEqual(len(absent['parquet']['missing']),3)


class SourceProbeTests(unittest.TestCase):
    def test_current_source_false_pass_and_fixed_payout_control(self):
        audit,source=edge_function(REPO)
        probe=payout_probe(audit)
        self.assertTrue(probe['helper_clears'])
        self.assertTrue(probe['false_positive'])
        self.assertAlmostEqual(probe['actual_mean_unit_pnl'],-.07)
        self.assertEqual(len(source['sha256']),64)
        fixed=payout_probe(audit,.55,.55)
        self.assertFalse(fixed['helper_clears'])
        self.assertAlmostEqual(fixed['actual_mean_unit_pnl'],-.07)

    def test_archived_same_timestamp_clock_shift(self):
        cases,source=expiry_cases(REPO)
        self.assertEqual([c['holding_seconds'] for c in cases],[91.,151.])
        self.assertEqual(cases[0]['supplied_utc'],cases[1]['supplied_utc'])
        self.assertEqual(len(source['commit']),40)


if __name__=='__main__':
    unittest.main()
