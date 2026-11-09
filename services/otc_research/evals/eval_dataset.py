"""Held-out deterministic scenarios and executable regression mutants.

No model calls or broker access. Synthetic edge checks verify accounting and
selection, not evidence of market predictability. Thresholds are declared here.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import types
import unittest

from services.otc_research import dataset, export
from services.otc_research.tests.dataset_fixtures import boundary_manifest, config, observation, observations, opportunity, payload
from services.otc_research.tests import test_dataset


SEED = 190237
THRESHOLDS = {"causality_failure_count": 0, "corruption_false_acceptance_count": 0,
              "boundary_corruption_false_acceptance_count": 0,
              "missing_outcome_retention": 1.0, "positive_fixture_admission": 1.0,
              "injected_direction_accuracy": 1.0, "null_direction_accuracy_min": 0.40,
              "null_direction_accuracy_max": 0.60, "mutants_killed_fraction": 1.0}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _market_fixture(injected):
    """220 independent windows, including 20 ties, with a known null/edge."""
    labels = [1] * 100 + [-1] * 100 + [0] * 20
    random.Random(SEED).shuffle(labels)
    events, opportunities = [], []
    for number, movement in enumerate(labels):
        decision = 10000 + 3000 * number
        feature = movement if injected else (1 if number % 2 else -1)
        direction = "call" if feature >= 0 else "put"
        op = opportunity(opportunity_id=f"window-{number:04}", decision_ms=decision, expiry_ms=decision + 600,
                         latest_entry_ms=decision + 100, acceptance_delay_ms=7, direction=direction,
                         expiry_basis="hypothetical")
        opportunities.append(op)
        events.extend([observation(f"{number}-old", "quote", decision - 200, "100"),
                       observation(f"{number}-current", "quote", decision - 25, "100"),
                       observation(f"{number}-payout", "payout", decision - 20, ".8"),
                       observation(f"{number}-mood", "mood", decision - 10, str((feature + 1) / 2)),
                       observation(f"{number}-entry", "quote", decision + 7, "100"),
                       observation(f"{number}-expiry", "quote", decision + 600, str(100 + movement))])
    return {"observations": events, "opportunities": opportunities, "config": config()}


def _fixture_metrics(input_data):
    result = dataset.build_rows(**input_data)
    rows = result["rows"]
    by_id = {op["opportunity_id"]: op for op in input_data["opportunities"]}
    directed = [row for row in rows if row["label"] in ("up", "down")]
    wins = sum((by_id[row["opportunity_id"]]["direction"] == "call") == (row["label"] == "up") for row in directed)
    return {"rows": len(rows), "resolved": result["counts"]["resolved"], "ties": result["counts"]["ties"],
            "direction_accuracy": wins / len(directed),
            "unit_proxy_return_sum": str(sum((Decimal(row["unit_pnl"]) for row in rows), Decimal(0))),
            "admission_fraction": result["counts"]["resolved"] / len(rows), "output_sha256": _hash(result)}


def _causality_trials():
    randomizer = random.Random(SEED + 1)
    failures = 0
    for number in range(100):
        source = payload()
        before = dataset.build_rows(**source)
        changed = deepcopy(source)
        for event in changed["observations"]:
            if event["available_ms"] > 1000:
                event["value"] = str(randomizer.randint(1, 10000)) if event["kind"] == "quote" else str(randomizer.randint(0, 100) / 100)
        for index in range(10):
            kind = randomizer.choice(["quote", "mood", "payout"])
            changed["observations"].append(observation(f"future-{number}-{index}", kind, 2100 + index,
                                                        str(randomizer.randint(1, 10000)) if kind == "quote" else str(randomizer.randint(0, 100) / 100), asset=f"unseen-{index}"))
        randomizer.shuffle(changed["observations"])
        after = dataset.build_rows(**changed)
        unchanged = (before["rows"][0]["features"] == after["rows"][0]["features"]
                     and before["counts"]["before_label_eligible"] == after["counts"]["before_label_eligible"])
        failures += not unchanged
    return {"trials": 100, "failures": failures}


def _corruption_trials():
    cases = []
    for field, value in [("available_ms", -1), ("event_ms", float("inf")), ("value", "-Infinity"),
                         ("value", "nan"), ("value", "sNaN"), ("value", " 1"), ("value", "1_0"),
                         ("clock_id", " "), ("source", ""), ("kind", "cash"), ("quality", "interpolated")]:
        corrupted = payload()
        corrupted["observations"][0][field] = value
        cases.append(corrupted)
    for field, value in [("expiry_ms", False), ("decision_ms", 1.5), ("direction", "long"), ("expiry_basis", "guessed"),
                         ("latest_entry_ms", 999), ("latest_entry_ms", 2000)]:
        corrupted = payload()
        corrupted["opportunities"][0][field] = value
        cases.append(corrupted)
    accepted = 0
    for case in cases:
        try:
            dataset.build_rows(**case)
        except dataset.ContractError:
            continue
        accepted += 1
    return {"trials": len(cases), "false_acceptances": accepted}


def _missing_outcomes():
    source = _market_fixture(True)
    deleted_ids = {f"{number}-expiry" for number in range(0, 220, 4)}
    source["observations"] = [event for event in source["observations"] if event["event_id"] not in deleted_ids]
    result = dataset.build_rows(**source)
    return {"expected_unresolved": len(deleted_ids), "actual_unresolved": result["counts"]["unresolved"],
            "before_label_eligible": result["counts"]["before_label_eligible"], "rows": len(result["rows"]),
            "retention_fraction": len(result["rows"]) / len(source["opportunities"])}


def _boundary_corruption_trials():
    """Held-out malformed source metadata must fail before allocating rows."""
    randomizer = random.Random(SEED + 19)
    cases = []
    for number in range(120):
        manifest = boundary_manifest()
        kind = randomizer.choice(['quote', 'mood', 'payout'])
        first = randomizer.randrange(1, 100000)
        last = randomizer.randrange(200000, 400000)
        mutation = number % 8
        endpoints = [(True, last), (first, False), (first + .5, last),
                     (str(first), last), (None, last), (last + 1, first),
                     (-first, last), (first, export.HISTORICAL_END_MS + number)][mutation]
        manifest['receipt_bounds'][kind] = dict(zip(('first_receipt_ms', 'last_receipt_ms'), endpoints))
        cases.append((f'{kind}-{number}', manifest))
    false_acceptances = []; unexpected_errors = []
    for name, manifest in cases:
        try:
            export.opportunities_for(manifest)
        except ValueError:
            continue
        except Exception as error:
            unexpected_errors.append({'case': name, 'type': type(error).__name__})
        else:
            false_acceptances.append(name)
    return {'trials': len(cases), 'false_acceptances': false_acceptances,
            'unexpected_errors': unexpected_errors}


def _boundary_old_behavior_mutant():
    """Execute the prior aggregation-first body against the actual regression."""
    source = Path(export.__file__).read_text()
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'opportunities_for')
    old_body = '''def opportunities_for(manifest):
    bounds = manifest['receipt_bounds']
    first = min(values['first_receipt_ms'] for values in bounds.values() if values['first_receipt_ms'] is not None)
    last = max(values['last_receipt_ms'] for values in bounds.values() if values['last_receipt_ms'] is not None)
    start = ((first + 119999) // 120000) * 120000
    if first < 0 or last < first or last >= HISTORICAL_END_MS:
        raise ValueError('Source is outside registered historical scope')
    rows = []
    for decision in range(start, last + 1, 120000):
        for asset in ASSETS:
            rows.append(Opportunity(f'{asset}@{decision}', 'iqoption', asset, 'turbo-option',
                                    'receiver_utc', decision, decision + 120000,
                                    decision + 2000, 'hypothetical', None, 0).as_record())
    return rows
'''
    lines = source.splitlines(keepends=True)
    mutated = ''.join(lines[:function.lineno - 1]) + old_body + ''.join(lines[function.end_lineno:])
    namespace = types.ModuleType('export_mutant_aggregate_bounds')
    namespace.__package__ = 'services.otc_research'
    sys.modules[namespace.__name__] = namespace
    try:
        exec(compile(mutated, '<mutant:aggregate_bounds>', 'exec'), namespace.__dict__)
        admitted = {}
        for name, kind, first, last in [('boolean_first', 'quote', True, 250000),
                                        ('masked_reverse', 'mood', 360000, 0)]:
            manifest = boundary_manifest()
            manifest['receipt_bounds'][kind].update(first_receipt_ms=first, last_receipt_ms=last)
            admitted[name] = len(namespace.opportunities_for(manifest))
        test_dataset.opportunities_for = namespace.opportunities_for
        suite = unittest.TestSuite([test_dataset.ExportBoundaryTests('test_noninteger_receipt_endpoints_rejected'),
                                   test_dataset.ExportBoundaryTests('test_per_source_reverse_and_scope_bounds_rejected_before_allocation')])
        captured = io.StringIO()
        result = unittest.TextTestRunner(stream=captured).run(suite)
        return {'mutant': 'aggregate_bounds_before_source_validation',
                'regression': 'ExportBoundaryTests receipt endpoint rejection',
                'killed': not result.wasSuccessful() and all(count > 0 for count in admitted.values()),
                'old_false_admission_rows': admitted,
                'failure_count': len(result.failures), 'error_count': len(result.errors)}
    finally:
        test_dataset.opportunities_for = export.opportunities_for
        del sys.modules[namespace.__name__]


def _mutant_trials():
    original_source = Path(dataset.__file__).read_text()
    payout_line = '    payout = index.asof(opportunity.scope, opportunity.asset, "payout", decision)'
    mutants = [
        ("payout_floor", payout_line,
         payout_line + '\n    payout = payout or Observation("fabricated", opportunity.broker, opportunity.asset, opportunity.product, "primary", "payout", decision, decision, Decimal("0.8"), opportunity.clock_id, "received")',
         "test_future_payout_cannot_fill_missing_payout_or_apply_floor"),
        ("label_filtered_market_universe", "    market = index.market_moods(opportunity)",
         '    market = [e for e in index.market_moods(opportunity) if any(q.asset == e.asset and q.kind == "quote" and q.available_ms > decision for s in index.streams.values() for q in s.events)]',
         "test_other_asset_future_quote_and_doji_do_not_change_market_mood"),
        ("drop_missing_outcomes", '    counts = {"total": len(rows)',
         '    rows = [row for row in rows if row["status"] == "resolved"]\n    counts = {"total": len(rows)',
         "test_missing_settlement_is_retained_after_selection"),
        ("drop_ties", '    counts = {"total": len(rows)',
         '    rows = [row for row in rows if row["label"] != "tie"]\n    counts = {"total": len(rows)',
         "test_tie_is_retained_and_refunded_or_explicitly_lost"),
        ("permit_pre_entry_source_quote", 'if event.event_ms >= earliest\n                            and event.available_ms - event.event_ms <= self.config.max_age["quote"]]',
         'if event.available_ms - event.event_ms <= self.config.max_age["quote"]]',
         "test_entry_deadlines_and_source_event_time"),
        ("future_terminal_backfill", "if event.event_ms == expiry:", "if event.event_ms >= expiry:",
         "test_exact_expiry_only_without_interpolation"),
        ("ignore_settlement_receipt_bound", "expiry + self.config.settlement_wait)", "expiry + 1000000)",
         "test_exact_expiry_only_without_interpolation"),
        ("source_time_as_visibility", "self.receipts = tuple(e.available_ms for e in self.events)",
         "self.receipts = tuple(e.event_ms for e in self.events)",
         "test_recent_source_event_with_future_receipt_is_invisible"),
        ("oldest_tick_in_receipt_batch", "event = max(batch, key=lambda item: (item.event_ms, item.event_id))",
         "event = min(batch, key=lambda item: (item.event_ms, item.event_id))",
         "test_batch_entry_newest_tick_and_invalid_fraction_bounds"),
        ("admit_impossible_entry_cutoff", 'if not times["decision_ms"] <= times["latest_entry_ms"] < times["expiry_ms"]:',
         'if False:',
         "test_entry_deadlines_and_source_event_time"),
    ]
    verdicts = []
    for name, old, new, test_name in mutants:
        if original_source.count(old) != 1:
            raise RuntimeError(f"mutant {name} replacement is not unique")
        namespace = types.ModuleType(f"dataset_mutant_{name}")
        sys.modules[namespace.__name__] = namespace
        try:
            exec(compile(original_source.replace(old, new), f"<mutant:{name}>", "exec"), namespace.__dict__)
            test_dataset.build_rows = namespace.build_rows
            suite = unittest.TestSuite([test_dataset.DatasetTests(test_name)])
            captured = io.StringIO()
            result = unittest.TextTestRunner(stream=captured).run(suite)
            # A removed row can cause IndexError in a test that expects it;
            # syntax errors/import failures never count, because compilation
            # happened before running the actual behavioral regression test.
            killed = not result.wasSuccessful()
            verdicts.append({"mutant": name, "regression": test_name, "killed": killed,
                             "failure_count": len(result.failures), "error_count": len(result.errors)})
        finally:
            test_dataset.build_rows = dataset.build_rows
            del sys.modules[namespace.__name__]
    return verdicts


def evaluate():
    injected = _fixture_metrics(_market_fixture(True))
    null = _fixture_metrics(_market_fixture(False))
    causal = _causality_trials()
    corrupted = _corruption_trials()
    missing = _missing_outcomes()
    mutants = _mutant_trials()
    boundary_corrupted = _boundary_corruption_trials()
    mutants.append(_boundary_old_behavior_mutant())
    checks = {"causality": causal["failures"] == 0, "corruptions": corrupted["false_acceptances"] == 0,
              "outcome_gaps_retained": missing["retention_fraction"] == 1 and missing["actual_unresolved"] == missing["expected_unresolved"],
              "positive_admission": injected["admission_fraction"] == 1,
              "injected_edge": injected["direction_accuracy"] == 1,
              "null": 0.4 <= null["direction_accuracy"] <= 0.6,
              "tie_retention": injected["ties"] == null["ties"] == 20,
              "boundary_corruptions": not boundary_corrupted['false_acceptances'] and not boundary_corrupted['unexpected_errors'],
              "mutation_regressions": all(item["killed"] for item in mutants)}
    return {"passed": all(checks.values()), "checks": checks, "thresholds": THRESHOLDS, "seed": SEED,
            "injected": injected, "null": null, "causality": causal, "corruptions": corrupted,
            "outcome_gaps": missing, "mutants": mutants,
            "boundary_corruptions": boundary_corrupted,
            "export_sha256": hashlib.sha256(Path(export.__file__).read_bytes()).hexdigest(),
            "dataset_sha256": hashlib.sha256(Path(dataset.__file__).read_bytes()).hexdigest(),
            "evidence_class": "synthetic_received_price_proxy", "market_profit_claim": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate()
    serialized = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(serialized)
    print(serialized, end="")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
