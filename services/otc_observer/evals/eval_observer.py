"""Deterministic adversarial observer scenarios, with explicit pass thresholds."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile

from services.otc_observer.normalize import normalize_rows
from services.otc_observer.tests.test_export import fixture_database
from services.otc_observer.export import read_snapshot
from services.otc_research.export import export_matrix, strict_json


def evaluate():
    checks = {}
    raw = dict(broker_asset='EURUSD-OTC', source_event_ms=1000, received_at_ms=2000, clock_offset_ms=0, mid=100)
    for name, changes in [('future_source', {'source_event_ms': 2001}), ('unknown_clock', {'clock_offset_ms': None}),
                          ('old_source', {'source_event_ms': 0, 'received_at_ms': 15001}),
                          ('nonfinite_quote', {'mid': float('nan')}), ('missing_receipt', {'received_at_ms': None}),
                          ('nonfinite_metadata', {'metadata': float('inf')})]:
        changed = {**raw, **changes}
        checks[name + '_quarantined'] = not normalize_rows([changed], 'quote')[0]
    current = deepcopy(raw);current['source_event_ms'] = 1500;current['mid'] = 102
    events, _, lineage = normalize_rows([raw, current], 'quote')
    checks['whole_batch_newest_source_tick'] = len(events) == 1 and events[0]['value'] == '102'
    checks['true_receipt_kept'] = events[0]['available_ms'] == events[0]['event_ms'] == 2000
    checks['original_source_lineage_kept'] = lineage[events[0]['event_id']]['raw_source_or_bucket_ms'] == 1500
    conflicted = {**current, 'mid': 103}
    checks['conflicting_latest_batch_quarantined'] = not normalize_rows([current, conflicted], 'quote')[0]
    for value in ['NaN', 'Infinity', '1e10000']:
        try:
            strict_json('{"metadata":' + value + '}')
        except ValueError:
            checks['strict_json_' + value] = True
        else:
            checks['strict_json_' + value] = False
    with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
        root = Path(temporary); database = root / 'source.sqlite';fixture_database(database)
        read_snapshot(database, root / 'observations')
        audit = export_matrix(root / 'observations', root / 'matrix')
        checks['positive_full_export_admitted'] = audit['counts']['resolved'] == 2
        checks['all_grid_rows_and_unresolved_retained'] = audit['counts']['total'] == 4 and audit['counts']['unresolved'] == 2
        checks['actual_contract_claims_unavailable'] = audit['actual_win_rate'] is None and not audit['promotable']
        (root / 'observations/source_lineage.jsonl').write_text('corrupted\n')
        try:
            export_matrix(root / 'observations', root / 'corrupt-output')
        except ValueError:
            checks['lineage_hash_corruption_blocked'] = True
        else:
            checks['lineage_hash_corruption_blocked'] = False
    # Prove the causal normalizer distinguishes a late receipt from bucket time.
    payout = dict(broker_asset='EURUSD-OTC', instrument_type='turbo-option', source='init-snapshot', observed_bucket_ms=0,
                  received_at_ms=250000, clock_offset_ms=0, payout_fraction=.85)
    events, _, _ = normalize_rows([payout], 'payout')
    # Execute the historical availability defect, rather than merely asserting
    # a difference between two timestamps in the correct implementation.
    import services.otc_observer.normalize as normalizer
    source = Path(normalizer.__file__).read_text()
    before = "'kind':kind,'available_ms':received,'event_ms':received,'value':item['value'],"
    after = "'kind':kind,'available_ms':newest,'event_ms':newest,'value':item['value'],"
    if source.count(before) != 1:
        raise RuntimeError('Receipt mutant replacement is not unique')
    namespace = {}
    exec(compile(source.replace(before, after), '<bucket-time-mutant>', 'exec'), namespace)
    mutant_events, _, _ = namespace['normalize_rows']([payout], 'payout')
    checks['legacy_bucket_time_mutant_killed'] = events[0]['available_ms'] == 250000 and mutant_events[0]['available_ms'] != 250000
    return {'schema': 'otc_observer_eval_v1', 'pass': all(checks.values()), 'checks': checks,
            'thresholds': {'false_admissions': 0, 'positive_admitted_rows': 2, 'retained_population': 4},
            'market_profit_claim': False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--output', type=Path)
    args = parser.parse_args();report = evaluate()
    result = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if args.output:args.output.write_text(result)
    print(result, end='')
    raise SystemExit(0 if report['pass'] else 1)


if __name__ == '__main__':main()
