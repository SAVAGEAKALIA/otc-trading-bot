"""Gate regression: caller edits must never poison a later same-process plan."""
import os
from pathlib import Path
import sys
import unittest

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
import plan

SOURCE = Path(os.environ.get('D3_SOURCE_DIR', 'docs/research/crypto-r1-2026-10-31')).resolve()


class OutputOwnershipTests(unittest.TestCase):
    def test_returned_report_mutation_does_not_change_next_plan(self):
        module = plan
        inputs = {path: path.read_bytes() for path in
                  [SOURCE / name for name in plan.SOURCE_HASHES]
                  + [SERVICE / 'contracts' / 'protocol.json']}
        earlier = plan.run(SOURCE)
        expected = plan.canonical(earlier)
        requirements = earlier['requirements']
        window = requirements['daily_spot_valuation'][0]['window']
        blockers = requirements['daily_spot_valuation'][0]['blockers']
        window['start_utc'] = 'caller-edited boundary'
        window['annotations'] = [{'notes': ['local note', {'tags': ['review']}]}]
        window['annotations'][0]['notes'][1]['tags'].append('caller-added')
        blockers.append('caller-added blocker')
        requirements['conditional_order_execution'][0]['window']['end_inclusive'] = False
        requirements['terminal_execution'][0]['blockers'].clear()
        requirements['actual_fill_outcomes_and_reconciliation'].append({'notes': ['caller-only row']})
        requirements['unresolved_continuation'][0]['window']['end_condition'] = 'caller annotation'
        requirements['caller_annotations'] = [{'notes': ['private review']}]
        self.assertNotEqual(plan.canonical(earlier), expected, 'probe must actually mutate the returned report')

        # The already-imported module is deliberately reused; no reload or cache
        # clear may conceal cross-call ownership of mutable windows or lists.
        fresh = plan.run(SOURCE)
        self.assertIs(plan, module)
        self.assertEqual(plan.canonical(fresh), expected)
        self.assertIsNot(fresh['requirements'], requirements)
        self.assertIsNot(fresh['requirements']['daily_spot_valuation'][0]['window'], window)
        self.assertIsNot(fresh['requirements']['daily_spot_valuation'][0]['blockers'], blockers)
        for path, raw in inputs.items():
            self.assertEqual(path.read_bytes(), raw, 'the caller may mutate output, never source bytes')


if __name__ == '__main__':
    unittest.main()
