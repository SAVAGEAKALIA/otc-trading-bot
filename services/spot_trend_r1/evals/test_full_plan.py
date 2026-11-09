"""Whole-report and subprocess checks belong to the slower independent eval lane."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plan
SERVICE = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('D3_SOURCE_DIR', 'docs/research/crypto-r1-2026-10-31')).resolve()

class FullReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.preview = plan.read_json((SOURCE / 'spot_trend_preview.json').read_bytes())
        cls.result = plan.run(SOURCE)

    def test_source_and_output_hashes_and_repeatability(self):
        again = plan.run(SOURCE)
        self.assertEqual(plan.canonical(self.result), plan.canonical(again))
        body = deepcopy(self.result)
        recorded = body.pop('deterministic_body_sha256')
        self.assertEqual(recorded, plan.digest(plan.canonical(body)))
        self.assertEqual(self.result['requirements_sha256'], plan.digest(plan.canonical(self.result['requirements'])))
        raw_contract = (SERVICE / 'contracts' / 'protocol.json').read_bytes()
        self.assertEqual(self.result['provenance']['contract_sha256'], plan.digest(raw_contract))
        self.assertEqual(self.result['provenance']['contract_semantic_sha256'], plan.SUPPORTED_CONTRACT_SEMANTIC_SHA256)

    def test_saved_requirements_match_fresh_canonical_output(self):
        # Internal hashes alone cannot reject a self-consistent stale snapshot.
        # Compare every saved byte with the current code/contract/input result.
        saved = (SOURCE / 'd3_requirements.json').read_bytes()
        self.assertEqual(saved, plan.canonical(self.result),
                         'saved D3 evidence is stale, incomplete or noncanonical; regenerate and review it')


    def test_cli_path_independence(self):
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run([sys.executable, str(SERVICE / 'plan.py'), '--source-dir', str(SOURCE)],
                                     cwd=directory, check=True, capture_output=True)
        self.assertEqual(process.stdout, plan.canonical(self.result))

    def test_cli_accepts_policy_equivalent_layout_preserving_raw_provenance(self):
        import json

        def reverse_keys(value):
            if type(value) is dict:
                return {key: reverse_keys(value[key]) for key in reversed(list(value))}
            if type(value) is list:
                return [reverse_keys(child) for child in value]
            return value

        raw = json.dumps(reverse_keys(self.result['protocol']), indent=4, ensure_ascii=True).encode()
        with tempfile.TemporaryDirectory() as directory:
            reformatted = Path(directory) / 'equivalent-contract.json'
            reformatted.write_bytes(raw)
            process = subprocess.run([sys.executable, str(SERVICE / 'plan.py'), '--source-dir', str(SOURCE),
                                      '--contract', str(reformatted)], cwd=directory, check=True, capture_output=True)
        output = plan.read_json(process.stdout)
        self.assertEqual(output['provenance']['contract_sha256'], plan.digest(raw))
        self.assertNotEqual(output['provenance']['contract_sha256'], self.result['provenance']['contract_sha256'])
        self.assertEqual(output['provenance']['contract_semantic_sha256'], self.result['provenance']['contract_semantic_sha256'])
        original = deepcopy(self.result)
        for candidate in (output, original):
            candidate.pop('deterministic_body_sha256')
            candidate['provenance'].pop('contract_sha256')
        self.assertEqual(plan.canonical(output), plan.canonical(original))


    def test_entire_daily_grid_and_midnight_archives(self):
        reqs = self.result['requirements']
        marks = reqs['daily_independent_token_valuation']
        expected = plan.days(date(2026, 8, 3), date(2026, 11, 2))
        self.assertEqual([x['valuation_utc'][:10] for x in marks], [x.isoformat() for x in expected])
        self.assertEqual(len(reqs['daily_spot_valuation']), 2 * len(expected))
        for row in reqs['daily_spot_valuation']:
            day = date.fromisoformat(row['valuation_utc'][:10])
            self.assertEqual(row['archive_date'], (day - timedelta(days=1)).isoformat())
            self.assertTrue(row['window']['start_inclusive'])
            self.assertFalse(row['window']['end_inclusive'])
            self.assertEqual(row['window']['end_utc'], row['valuation_utc'])
        boundary = self.result['boundaries']
        self.assertGreater(boundary['ending_daily_mark_after_final_normal_decision_utc'], boundary['last_normal_decision_utc'])
        self.assertGreater(boundary['closing_valuation_utc'], boundary['terminal_deadline_utc'])
        self.assertEqual(boundary['terminal_decision_utc'], '2026-11-01T00:05:00.000Z')


    def test_schedule_is_conditional_candidates_never_pruned(self):
        result = self.result
        components = plan.validate_preview(self.preview)
        expected = sum(len(v['entry']) + len(v['exit']) for v in components.values())
        self.assertEqual(len(result['requirements']['conditional_order_execution']), expected)
        self.assertEqual(result['counts']['schedule_rows'], 6 * 90)
        self.assertTrue(all(x['actual_quantity'] is None for x in result['conditional_full_fill_schedule']))
        suppressed = [x for x in result['requirements']['conditional_order_execution'] if x['full_fill_projection_action'] == 'none']
        self.assertGreater(len(suppressed), 0)
        self.assertEqual(len(result['requirements']['terminal_execution']), 6)
        self.assertTrue(all(not row['fills_or_capacity_verified'] for row in result['quote_evidence']))


    def test_all_inventory_items_have_purpose_window_and_evidence(self):
        ids = []
        for purpose, rows in self.result['requirements'].items():
            for row in rows:
                self.assertEqual(row['purpose'], purpose)
                self.assertTrue(all(key in row for key in ('symbol', 'source_category', 'window', 'reason', 'scenario', 'source_reference', 'evidence_state', 'blockers', 'existing_local_evidence_can_satisfy')))
                ids.append(row['id'])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(self.result['r2_authorized'])
        self.assertIsNone(self.result['protocol']['capital_budget_usdt'])
