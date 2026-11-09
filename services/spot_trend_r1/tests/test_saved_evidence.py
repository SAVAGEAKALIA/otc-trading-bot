"""Reject incomplete or stale saved requirements before a commit."""
import os
from pathlib import Path
import sys
import unittest

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
import plan

SOURCE = Path(os.environ.get("D3_SOURCE_DIR", "docs/research/crypto-r1-2026-10-31")).resolve()


class SavedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (SOURCE / "d3_requirements.json").read_bytes()
        cls.report = plan.read_json(cls.raw)

    def check_snapshot(self, raw):
        report = plan.read_json(raw)
        for flag in ("r2_authorized", "r2_freeze_ready", "returns_computed", "actual_fills_computed"):
            self.assertIs(report[flag], False)
        provenance = report["provenance"]
        self.assertEqual(provenance["planner_sha256"], plan.digest((SERVICE / "plan.py").read_bytes()))
        contract_raw = (SERVICE / "contracts/protocol.json").read_bytes()
        self.assertEqual(provenance["contract_sha256"], plan.digest(contract_raw))
        self.assertEqual(provenance["contract_semantic_sha256"], plan.SUPPORTED_CONTRACT_SEMANTIC_SHA256)
        self.assertEqual(provenance["input_sha256"],
                         {name: plan.digest((SOURCE / name).read_bytes()) for name in plan.SOURCE_HASHES})
        self.assertEqual(report["requirements_sha256"], plan.digest(plan.canonical(report["requirements"])))
        body = dict(report)
        recorded = body.pop("deterministic_body_sha256")
        self.assertEqual(recorded, plan.digest(plan.canonical(body)))

    def test_saved_requirements_integrity_and_current_provenance(self):
        self.check_snapshot(self.raw)

    def test_interrupted_or_incomplete_artifact_is_rejected(self):
        with self.assertRaises((ValueError, KeyError, AssertionError)):
            self.check_snapshot(self.raw[:len(self.raw) // 2])
        incomplete = dict(self.report)
        incomplete["requirements"] = dict(self.report["requirements"])
        incomplete["requirements"]["terminal_execution"] = self.report["requirements"]["terminal_execution"][:-1]
        with self.assertRaises(AssertionError):
            self.check_snapshot(plan.canonical(incomplete))

    def test_previous_code_or_permission_claim_is_rejected(self):
        for field, value in (("planner_sha256", "0" * 64), ("permission", True)):
            changed = dict(self.report)
            if field == "permission":
                changed["r2_authorized"] = value
            else:
                changed["provenance"] = dict(self.report["provenance"])
                changed["provenance"][field] = value
            with self.assertRaises(AssertionError):
                self.check_snapshot(plan.canonical(changed))


if __name__ == "__main__":
    unittest.main()
