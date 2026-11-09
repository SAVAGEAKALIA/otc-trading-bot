"""New files must pass Git whitespace checks before they are staged."""
from pathlib import Path
import sys
import unittest

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
from delivery import additions_patch, check_patch


class DeliveryTests(unittest.TestCase):
    def test_untracked_eof_blank_line_is_rejected(self):
        patch = additions_patch({'new_module.py': b'value = 1\n\n'})
        with self.assertRaisesRegex(ValueError, 'blank line at EOF'):
            check_patch(patch)

    def test_regression_eval_source_passes_before_staging(self):
        name = 'evals/test_full_plan.py'
        check_patch(additions_patch({name: (SERVICE / name).read_bytes()}))

if __name__ == '__main__':
    unittest.main()
