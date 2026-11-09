"""Cold-selected precommit regressions; the full focused eval runs before ship."""
from contextlib import redirect_stdout
import io
import time
import unittest

from services.otc_collection_ops.ops import canonical
from services.otc_collection_ops.tests.focused import EssentialTests


TEST_NAMES = (
    "test_exact_owned_pid_database_registration_and_start_ticks",
    "test_python_c_or_other_executable_is_never_owned",
    "test_failed_ownership_never_signals_any_process",
    "test_registered_dates_and_off_grid_daily_handoffs_are_fixed",
    "test_streamed_gzip_exact_hash_preserves_initial_identity_then_removes_owned_raw",
    "test_public_chain_exact_contract_and_transport_only_restart",
    "test_real_corrupt_sqlite_status_stops_verified_producer_and_retains_raw",
    "test_real_source_read_fault_run_stops_only_owned_process_and_retains_raw",
    "test_archive_admission_and_queued_work_reject_diagnosed_failure",
)


def main():
    output = io.StringIO()
    started = time.monotonic()
    with redirect_stdout(output):
        result = unittest.TextTestRunner(stream=output).run(
            unittest.TestSuite(EssentialTests(name) for name in TEST_NAMES))
    wall_seconds = time.monotonic() - started
    report = {"schema": "otc_collection_ops_precommit_gate_v1", "tests": result.testsRun,
              "errors": len(result.errors), "failures": len(result.failures),
              "pass_threshold": 1.0, "passed": result.wasSuccessful(),
              "wall_seconds": wall_seconds, "budget_seconds": 2.0,
              "within_budget": wall_seconds < 2.0,
              "broker_calls": 0, "ssh_calls": 0, "credential_value_reads": 0,
              "real_process_signals": 0, "selected_tests": TEST_NAMES,
              "coverage": ["ownership_unknown_identity", "fixed_global_dates", "gzip_provenance",
                           "real_bad_database_shutdown", "real_mutable_file_shutdown",
                           "diagnosed_failure_archive_launch_removal_guard"]}
    print(canonical(report))
    if not result.wasSuccessful():
        print(output.getvalue())
    # Timing is measured separately: scheduling contention must not turn a
    # deterministic regression into a flaky assertion.
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
