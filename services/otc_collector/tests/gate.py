"""Deterministic gate runner with a persisted elapsed-time budget result."""
import argparse
import io
from pathlib import Path
import time
import unittest
from services.otc_collector.protocol import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    start = time.perf_counter()
    suite = unittest.defaultTestLoader.discover("services/otc_collector/tests", top_level_dir=".")
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output).run(suite)
    elapsed = time.perf_counter() - start
    report = {"schema": "fresh_collector_gate_v1", "tests": result.testsRun, "errors": len(result.errors),
              "failures": len(result.failures), "elapsed_seconds": elapsed, "budget_seconds": 2,
              "tests_passed": result.wasSuccessful(), "budget_passed": elapsed < 2}
    if args.output:
        path = Path(args.output).resolve()
        if not path.is_relative_to(Path("/tmp")):
            raise ValueError("evidence must be under /tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical(report) + "\n")
    print(canonical(report))
    if not result.wasSuccessful():
        print(output.getvalue())
    return 0 if result.wasSuccessful() and elapsed < 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
