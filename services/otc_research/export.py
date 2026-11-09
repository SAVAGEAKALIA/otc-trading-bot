"""Create a causal training matrix from the observer's immutable JSONL boundary."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from contracts.otc_v1 import Observation, Opportunity
from contracts.otc_v1.training_schema import ASSETS, FEATURES, COLUMNS, MANIFEST_SCHEMA
from .dataset import build_rows

CONFIG = {'source_priority': {'quote': ['quote_samples'], 'mood': ['mood_samples'],
                              'payout': ['commission-stream', 'init-snapshot']},
          'max_age_ms': {'quote': 5000, 'mood': 60000, 'payout': 600000},
          'max_entry_wait_ms': 2000, 'max_settlement_wait_ms': 0,
          'lookback_ms': 60000, 'tie_rule': 'full_refund', 'terminal_policy': 'last_received_before'}
HISTORICAL_END_MS = int(datetime.fromisoformat('2026-08-21').replace(tzinfo=timezone.utc).timestamp() * 1000)
BOUND_TABLES = {'quote': 'quote_samples', 'mood': 'mood_samples', 'payout': 'payout_samples'}


def validated_receipt_bounds(manifest):
    """Validate each source before aggregate bounds can allocate a grid."""
    if not isinstance(manifest, dict):
        raise ValueError('Observer manifest must be an object')
    required = {'schema': 'otc_receiver_observation_export_v1', 'status': 'DONE',
                'source_stable': True, 'clock': 'receiver_utc', 'promotable': False,
                'product': 'turbo-option', 'quote_product_mapping': 'explicit_assumed'}
    if any(type(manifest.get(key)) is not type(value) or manifest.get(key) != value
           for key, value in required.items()) or manifest.get('assets') != list(ASSETS):
        raise ValueError('Unsupported or incomplete observer boundary')
    bounds = manifest.get('receipt_bounds')
    inventory = manifest.get('inventory')
    if not isinstance(bounds, dict) or set(bounds) != set(BOUND_TABLES):
        raise ValueError('Receipt bounds must contain exactly quote, mood and payout')
    if not isinstance(inventory, dict) or set(inventory) != set(BOUND_TABLES.values()):
        raise ValueError('Source inventory must contain exactly the registered tables')
    nonempty = []
    for kind, table in BOUND_TABLES.items():
        value = bounds[kind]
        census = inventory[table]
        if not isinstance(value, dict) or set(value) != {'first_receipt_ms', 'last_receipt_ms'}:
            raise ValueError(f'{kind}: receipt endpoints must have the exact registered fields')
        count = census.get('rows_in_scope') if isinstance(census, dict) else None
        if type(count) is not int or count < 0:
            raise ValueError(f'{kind}: inventory row count must be a nonnegative integer')
        first, last = value['first_receipt_ms'], value['last_receipt_ms']
        if first is None and last is None:
            if count != 0:
                raise ValueError(f'{kind}: nonempty source cannot have empty receipt bounds')
            continue
        if count == 0 or type(first) is not int or type(last) is not int:
            raise ValueError(f'{kind}: nonempty receipt endpoints must be integer milliseconds')
        if not 0 <= first <= last < HISTORICAL_END_MS:
            raise ValueError(f'{kind}: source is outside registered historical scope')
        nonempty.append((first, last))
    return nonempty


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strict_json(value):
    def invalid(constant):
        raise ValueError('Nonfinite JSON is forbidden')
    def finite_float(text):
        number = float(text)
        if not math.isfinite(number):
            raise ValueError('Nonfinite JSON number is forbidden')
        return number
    return json.loads(value, parse_constant=invalid, parse_float=finite_float)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def load_boundary(snapshot):
    """Verify observer-export bytes and shared immutable observation schema."""
    manifest_bytes = (snapshot / 'manifest.json').read_bytes()
    manifest = strict_json(manifest_bytes)
    validated_receipt_bounds(manifest)
    for name in ('observations', 'source_lineage'):
        if sha256(snapshot / (name + '.jsonl')) != manifest.get(name + '_sha256'):
            raise ValueError(f'{name} boundary hash differs')
    observations = []
    with (snapshot / 'observations.jsonl').open() as stream:
        for line in stream:
            row = strict_json(line)
            Observation(**row)
            if row['asset'] not in ASSETS or row['clock_id'] != 'receiver_utc' or row['product'] != 'turbo-option':
                raise ValueError('Observation scope differs from registered source')
            observations.append(row)
    if sha256(snapshot / 'observations.jsonl') != manifest['observations_sha256'] or (snapshot / 'manifest.json').read_bytes() != manifest_bytes:
        raise ValueError('Observation boundary changed during loading')
    return observations, manifest


def opportunities_for(manifest):
    bounds = validated_receipt_bounds(manifest)
    if not bounds:
        return []
    first = min(value[0] for value in bounds)
    last = max(value[1] for value in bounds)
    # July/August archive is spent diagnostic data. UTC boundaries are fixed,
    # and do not follow resolved-label availability or an asset outcome filter.
    start = ((first + 119999) // 120000) * 120000
    rows = []
    for decision in range(start, last + 1, 120000):
        for asset in ASSETS:
            row = Opportunity(f'{asset}@{decision}', 'iqoption', asset, 'turbo-option',
                              'receiver_utc', decision, decision + 120000,
                              decision + 2000, 'hypothetical', None, 0).as_record()
            rows.append(row)
    return rows


def canonical_rows(dataset, opportunities, observations):
    by_id = {row['opportunity_id']: row for row in opportunities}
    events = {row['event_id']: row for row in observations}
    output = []
    for row in dataset['rows']:
        op = by_id[row['opportunity_id']]; features = row['features']
        value = {'opportunity_id': row['opportunity_id'], 'asset': op['asset'],
                 'decision_ms': row['decision_ms'], 'expiry_ms': row['expiry_ms'],
                 'status': row['status'], 'label': row['label'] or '',
                 'payout': '' if features is None else features['payout'],
                 'evidence_class': 'received_price_proxy'}
        value.update({name: '' for name in FEATURES})
        if features is not None:
            for name, key in [('f_return_lookback', 'return_lookback'), ('f_own_mood', 'own_mood'),
                              ('f_market_mood', 'market_mood'), ('f_payout', 'payout'),
                              ('f_quote_age_ms', 'quote_age_ms'), ('f_payout_age_ms', 'payout_age_ms')]:
                value[name] = '' if features[key] is None else features[key]
            # One age column certifies every contributing mood observation,
            # including other assets when the target mood is absent.
            mood_ids = set(row['lineage']['market_mood'])
            if row['lineage']['own_mood']:
                mood_ids.add(row['lineage']['own_mood'])
            ages = [row['decision_ms'] - events[event_id]['available_ms'] for event_id in mood_ids]
            value['f_mood_age_ms'] = max(ages) if ages else ''
        output.append(value)
    return output


def legacy_availability(opportunities, observations, source_lineage):
    """Matched payout bucket join versus actual receipt on the same fixed grid."""
    from bisect import bisect_right
    from collections import defaultdict
    by_id = {event['event_id']: event for event in observations if event['kind'] == 'payout'}
    groups = defaultdict(list)
    for row in source_lineage:
        event = by_id.get(row['event_id'])
        if event is None or event['source'] != 'init-snapshot':
            continue
        bucket = row['raw_source_or_bucket_ms'] - row['clock_offset_ms']
        groups[event['asset']].append((bucket, event['event_id'], event['available_ms']))
    indexes = {key: sorted(value) for key, value in groups.items()}
    keys = {key: [row[0] for row in value] for key, value in indexes.items()}
    matched = []; joined = future = 0
    for opportunity in opportunities:
        asset = opportunity['asset']; decision = opportunity['decision_ms']
        values = indexes.get(asset, []); position = bisect_right(keys.get(asset, []), decision) - 1
        old = values[position] if position >= 0 else None
        if old is not None and decision - old[0] > 600000:
            old = None
        if old is not None:
            joined += 1; future += old[2] > decision
        matched.append({'opportunity_id': opportunity['opportunity_id'],
                        'legacy_event_id': old[1] if old else None,
                        'legacy_used_future_receipt': None if old is None else old[2] > decision})
    return {'scope': 'same_receiver_clock_grid_after_raw_clock_quarantine', 'decisions': len(opportunities),
            'legacy_joined': joined, 'legacy_future_join_count': future,
            'repaired_future_join_count': 0, 'matched_rows': matched}


def export_matrix(snapshot: Path, output: Path):
    snapshot = snapshot.resolve(strict=True); output = output.resolve()
    if output == snapshot or snapshot in output.parents:
        raise ValueError('Matrix output must be separate from immutable observations')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Matrix export output must be new or empty')
    output.mkdir(parents=True, exist_ok=True)
    def emit(phase, **values):
        record = {'event': 'OTC matrix export', 'phase': phase,
                  'timestamp_utc': datetime.now(timezone.utc).isoformat(), **values}
        line = json.dumps(record, sort_keys=True, allow_nan=False)
        print(line, flush=True)
        with (output / 'progress.log').open('a') as stream:
            stream.write(line + '\n')
    registered = {'schema': 'otc_proxy_dataset_registration_v1', 'assets': list(ASSETS),
                  'decision_grid_ms': 120000, 'horizon_seconds': 120, 'acceptance_delay_ms': 0,
                  'entry_cutoff_after_decision_ms': 2000, 'config': CONFIG, 'promotable': False}
    registered['code_sha256'] = {'export': sha256(Path(__file__)),
                                   'dataset': sha256(Path(__file__).with_name('dataset.py'))}
    write_json(output / 'registration.json', registered)
    emit('loading_hash_verified_boundary', percent=None, eta_seconds=None)
    observations, source_manifest = load_boundary(snapshot)
    opportunities = opportunities_for(source_manifest)
    emit('building', observations=len(observations), opportunities=len(opportunities), percent=None, eta_seconds=None)
    dataset = build_rows(observations, opportunities, CONFIG)
    rows = canonical_rows(dataset, opportunities, observations)
    with (output / 'matrix.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS); writer.writeheader(); writer.writerows(rows)
    with (output / 'decision_lineage.jsonl').open('w') as stream:
        for row in dataset['rows']:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
    source_lineage = []
    with (snapshot / 'source_lineage.jsonl').open() as stream:
        for line in stream:
            row = strict_json(line)
            if row['table'] == 'payout_samples':
                source_lineage.append(row)
    old = legacy_availability(opportunities, observations, source_lineage)
    event_receipts = {event['event_id']: event['available_ms'] for event in observations}
    old['repaired_future_join_count'] = sum(
        event_receipts[row['lineage']['payout']] > row['decision_ms']
        for row in dataset['rows'] if row['lineage']['payout'] is not None)
    feature_future_references = 0
    for row in dataset['rows']:
        lineage = row['lineage']
        references = [lineage[key] for key in ('decision_quote', 'payout', 'lookback_quote', 'own_mood') if lineage[key] is not None]
        references.extend(lineage['market_mood'])
        feature_future_references += sum(event_receipts[event_id] > row['decision_ms'] for event_id in references)
    with (output / 'availability_comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['opportunity_id', 'legacy_event_id', 'legacy_used_future_receipt']);writer.writeheader();writer.writerows(old.pop('matched_rows'))
    audit = {'schema': 'otc_proxy_audit_v1', 'source_sha256': source_manifest['source_sha256'],
             'counts': dataset['counts'], 'normalization_counts': source_manifest['normalization_counts'],
             'source_inventory': source_manifest['inventory'], 'availability_comparison': old,
             'measured_future_feature_references': feature_future_references,
             'label_counts': dict(Counter(row['label'] for row in rows)),
             'reason_counts': dict(Counter(reason for row in dataset['rows'] for reason in row['reason_codes'])),
             'accepted_contract_count': None, 'cash_return_count': None, 'actual_win_rate': None,
             'missing_contract_reason': 'No accepted broker strikes, binding expiry offers or authoritative cash settlements in source',
             'fresh_confirmation': False, 'promotable': False}
    write_json(output / 'audit.json', audit)
    manifest = {'schema': MANIFEST_SCHEMA, 'expiry_basis': 'hypothetical',
                'product_mapping': 'explicit_assumed', 'clock': 'receiver_utc',
                'feature_availability': 'receiver_receipt_lte_decision',
                'outcome_basis': 'last_received_quote_at_or_before_expiry',
                'input_sha256': sha256(output / 'matrix.csv'), 'promotable': False,
                'horizon_seconds': 120, 'assets': list(ASSETS), 'evidence_classes': ['received_price_proxy'],
                'source_lineage': [{'source_id': source_manifest['source_id'], 'sha256': source_manifest['source_sha256'],
                                   'kind': 'received_quote_observations', 'clock': 'receiver_utc'}],
                'metadata': {'registration': registered, 'observer_manifest_sha256': sha256(snapshot / 'manifest.json'),
                             'observation_sha256': source_manifest['observations_sha256'],
                             'raw_lineage_sha256': source_manifest['source_lineage_sha256'],
                             'decision_lineage_sha256': sha256(output / 'decision_lineage.jsonl'),
                             'audit_sha256': sha256(output / 'audit.json')}}
    if sha256(snapshot / 'source_lineage.jsonl') != source_manifest['source_lineage_sha256']:
        raise ValueError('Source lineage changed during matrix export')
    write_json(output / 'manifest.json', manifest)
    emit('complete', **dataset['counts'], promotable=False, percent=100.0, eta_seconds=0)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); export_matrix(args.snapshot, args.output)


if __name__ == '__main__':
    main()
