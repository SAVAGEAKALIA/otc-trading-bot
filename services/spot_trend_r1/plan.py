"""Offline D3 requirements planner. Does not calculate historical fills or returns."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
from typing import Any

UTC = timezone.utc
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
LOOKBACKS = ((20, 10), (55, 20), (100, 50))
FIRST = date(2026, 8, 2)
LAST = date(2026, 10, 30)
WARMUP = date(2026, 4, 24)
DAY = timedelta(days=1)
HERE = Path(__file__).resolve().parent
SOURCE_HASHES = {
    'spot_trend_preview.json': 'e2549e960a204ad349303da6af6b8f038f06ef1470df84a11b46091f2a3cf762',
    'spot_quote_checks.json': '6751699552624146d83dbe3d7e3f5a5102fc4bc56df9a4d2627b10f4fa133927',
}
# Whole-contract pin, independent of the caller-selected file. A policy change
# needs a reviewed protocol/code version, not an edited JSON file alone.
SUPPORTED_CONTRACT_SEMANTIC_SHA256 = '53ff53bea7e8b0b13b7683133a2ab980dbf019483ce899a52f10a61cca612048'


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(raw: bytes) -> Any:
    def bad_constant(value):
        raise ValueError(f'nonfinite JSON constant: {value}')
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=bad_constant)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc(day: date, minute: int = 0) -> datetime:
    return datetime.combine(day, time(), UTC) + timedelta(minutes=minute)


def iso(stamp: datetime) -> str:
    return stamp.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def milliseconds(stamp: datetime) -> int:
    return int(stamp.timestamp()) * 1000 + stamp.microsecond // 1000


def parse_day(value: Any) -> date:
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is not None, 'invalid date format')
    return date.fromisoformat(value)


def days(first: date, last: date) -> list[date]:
    require(first <= last, 'reversed date window')
    return [first + DAY * i for i in range((last - first).days + 1)]


def rational(value: Any, positive: bool = False) -> Fraction:
    require(isinstance(value, (str, int)) and not isinstance(value, bool), 'exact rational string/integer required')
    try:
        number = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('invalid finite rational') from exc
    require(number > 0 if positive else number >= 0, 'invalid nonpositive or negative amount')
    return number


def is_int(value: Any) -> bool:
    return type(value) is int


def valid_hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def validate_contract(contract: dict) -> None:
    """Fail closed on every field, including nested additions, before lookup/use.

    JSON layout and object-key order have no meaning; array order and scalar
    types do. In particular bool/int and int/float equality cannot bypass the
    contract. The pin is never computed from a caller-selected contract file.
    """
    require(type(contract) is dict, 'supported contract must be a JSON object')

    def validate_json_types(value):
        if type(value) is dict:
            require(all(type(key) is str for key in value), 'contract keys must be strings')
            for child in value.values():
                validate_json_types(child)
        elif type(value) is list:
            for child in value:
                validate_json_types(child)
        else:
            require(value is None or type(value) in (str, int, bool), 'unsupported contract scalar/container type')

    validate_json_types(contract)
    require(digest(canonical(contract)) == SUPPORTED_CONTRACT_SEMANTIC_SHA256,
            'unsupported contract semantics; a policy/field change requires a reviewed protocol and code version')


def validate_preview(preview: dict) -> dict[tuple[str, int, int], dict]:
    require(preview['scope'] == 'historical threshold preview only' and preview['r2_freeze_ready'] is False, 'preview scope/promotion invalid')
    require((preview['warmup_start'], preview['signal_first'], preview['signal_last']) == (WARMUP.isoformat(), FIRST.isoformat(), LAST.isoformat()), 'preview date window mismatch')
    require(preview['decision_first'] == '2026-08-03T00:05:00Z' and preview['decision_last'] == '2026-10-31T00:05:00Z', 'preview decision grid mismatch')
    source = preview['source']
    require(source['start_utc'] == '2026-04-24T00:00:00+00:00' and source['end_exclusive_utc'] == '2026-10-31T00:00:00+00:00', 'provenance date mismatch')
    require(source['scope'] == 'public spot daily warmup feasibility, no strategy run', 'source scope mismatch')
    seen = set()
    for record in source['records']:
        symbol = record['symbol']
        require(symbol in SYMBOLS and symbol not in seen, 'missing/duplicate source symbol')
        seen.add(symbol)
        expected_url = f'https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval=D&start={milliseconds(utc(WARMUP))}&end={milliseconds(utc(LAST+DAY))-1}&limit=200'
        require(record['url'] == expected_url, 'source URL/identity mismatch')
        require(valid_hash(record['sha256']) and valid_hash(record['prior_sha256']), 'invalid source digest')
        require(is_int(record['rows']) and record['rows'] == 190 and record['overlap_rows'] == 90 and record['overlap_mismatches'] == [], 'unverified history grid/overlap')
        require(is_int(record['bytes']) and record['bytes'] > 0, 'source size invalid')
    require(seen == set(SYMBOLS), 'missing source symbol')
    require(set(preview['results']) == set(SYMBOLS), 'unexpected/missing result symbol')
    components = {}
    for symbol in SYMBOLS:
        for row in preview['results'][symbol]:
            require(is_int(row['entry_lookback']) and is_int(row['exit_lookback']), 'noninteger lookback')
            pair = (row['entry_lookback'], row['exit_lookback'])
            key = (symbol, *pair)
            require(pair in LOOKBACKS and key not in components, 'unknown/duplicate component')
            require(is_int(row['eligible_signal_days']) and row['eligible_signal_days'] == len(days(FIRST, LAST)), 'incomplete component grid')
            normalized = {}
            for kind in ('entry', 'exit'):
                raw_dates = row[f'{kind}_condition_dates']
                require(isinstance(raw_dates, list), 'condition dates must be list')
                values = [parse_day(x) for x in raw_dates]
                require(values == sorted(set(values)), 'unsorted/duplicate threshold dates')
                require(all(FIRST <= x <= LAST for x in values), 'threshold outside development grid')
                normalized[kind] = set(values)
            require(not normalized['entry'] & normalized['exit'], 'conflicting threshold conditions')
            components[key] = normalized
    require(set(components) == {(s, *p) for s in SYMBOLS for p in LOOKBACKS}, 'missing component')
    return components


def quote_in_window(event_ms: int, submission_ms: int) -> bool:
    return is_int(event_ms) and is_int(submission_ms) and submission_ms <= event_ms <= submission_ms + 60000


def valuation_in_window(event_ms: int, valuation_ms: int) -> bool:
    return is_int(event_ms) and is_int(valuation_ms) and valuation_ms - 60000 <= event_ms < valuation_ms


def available_before(event_ms: int, available_ms: int | None, cutoff_ms: int) -> bool:
    return is_int(event_ms) and is_int(available_ms) and is_int(cutoff_ms) and event_ms <= available_ms < cutoff_ms


def validate_quotes(quotes: dict, components: dict) -> dict[tuple[str, date], dict]:
    require(quotes['scope'] == 'archived exchange timestamp quote checks' and quotes['fills_simulated'] is False, 'quote scope/fill claim invalid')
    expected = {(key[0], d + DAY) for key, value in components.items() for kind in ('entry', 'exit') for d in value[kind]}
    found = {}
    for row in quotes['rows']:
        day = parse_day(row['decision_date'])
        key = row['symbol'], day
        require(key in expected and key not in found, 'unexpected/duplicate quote identity')
        require(row['status'] == 'observed' and valid_hash(row['archive_sha256']), 'unverified quote evidence')
        target = milliseconds(utc(day, 10))
        require(is_int(row['target_ms']) and row['target_ms'] == target, 'quote submission clock mismatch')
        require(quote_in_window(row['ts_ms'], target), 'quote outside exact executable window')
        require(is_int(row['offset_ms']) and row['offset_ms'] == row['ts_ms'] - target, 'quote offset mismatch')
        bid, ask, bid_size, ask_size = [rational(row[x], True) for x in ('bid', 'ask', 'bid_size', 'ask_size')]
        require(bid < ask and bid_size > 0 and ask_size > 0, 'invalid two-sided book')
        spread = rational(row['spread_bps'], True)
        computed = (ask - bid) / ((bid + ask) / 2) * 10000
        require(abs(spread - computed) <= Fraction(1, 10**25), 'spread value conflicts with quote')
        found[key] = row
    require(set(found) == expected and len(found) == 15, 'quote coverage incomplete')
    return found


def target_after(target: str, entry: bool, exit_: bool) -> str:
    require(target in ('flat', 'long') and type(entry) is bool and type(exit_) is bool, 'invalid signal state')
    require(not (entry and exit_), 'conflicting signal')
    return 'long' if entry else 'flat' if exit_ else target


def intended_action(base_quantity: Fraction, entry: bool, exit_: bool, terminal: bool = False) -> str:
    require(base_quantity >= 0, 'negative holding')
    target_after('flat', entry, exit_)
    if terminal:
        return 'sell' if base_quantity > 0 else 'none'
    if exit_ and base_quantity > 0:
        return 'sell'
    if entry and base_quantity == 0:
        return 'buy'
    return 'none'


@dataclass(frozen=True)
class Ledger:
    """Synthetic conservation checker only; no prices from history are supplied here."""
    cash: Fraction
    quantity: Fraction = Fraction(0)
    other: tuple[tuple[str, Fraction], ...] = ()
    fill_ids: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self):
        require(isinstance(self.cash, Fraction) and isinstance(self.quantity, Fraction), 'exact ledger balances required')
        require(self.cash >= 0 and self.quantity >= 0, 'negative ledger balance')
        require(len(dict(self.other)) == len(self.other), 'duplicate currency balance')
        require(all(currency not in ('USDT', 'BASE') and isinstance(amount, Fraction) and amount >= 0 for currency, amount in self.other), 'invalid cost-currency balance')


def apply_fill(ledger: Ledger, fill_id: str, side: str, gross_quantity: str, price: str,
               fee_currency: str, fee_amount: str) -> Ledger:
    """Apply one reconciled synthetic fill once. Unknown fee/depth/precision is not inferred."""
    require(isinstance(fill_id, str) and bool(fill_id) and fill_id not in ledger.fill_ids, 'missing or duplicate fill id')
    require(side in ('buy', 'sell'), 'invalid side')
    quantity, fill_price, fee = rational(gross_quantity, True), rational(price, True), rational(fee_amount)
    require(isinstance(fee_currency, str) and bool(fee_currency), 'fee denomination missing')
    direction = 1 if side == 'buy' else -1
    cash = ledger.cash - direction * quantity * fill_price
    base = ledger.quantity + direction * quantity
    other = dict(ledger.other)
    if fee_currency == 'USDT':
        cash -= fee
    elif fee_currency == 'BASE':
        base -= fee
    else:
        require(fee_currency in other, 'unfunded/unknown third-currency fee')
        other[fee_currency] -= fee
    require(cash >= 0 and base >= 0 and all(x >= 0 for x in other.values()), 'fill would borrow cash/base/cost currency')
    return Ledger(cash, base, tuple(sorted(other.items())), ledger.fill_ids | {fill_id})


def reconcile_components(ledgers: dict[str, Ledger]) -> dict:
    expected = {f'{symbol}:{entry}/{exit_}' for symbol in SYMBOLS for entry, exit_ in LOOKBACKS}
    require(set(ledgers) == expected, 'exactly six unique component ledgers required')
    symbols = {}
    for symbol in SYMBOLS:
        selected = [ledger for identity, ledger in ledgers.items() if identity.startswith(symbol + ':')]
        symbols[symbol] = {'cash_usdt': sum((x.cash for x in selected), Fraction(0)),
                           'base_quantity': sum((x.quantity for x in selected), Fraction(0))}
    return {'symbols': symbols, 'portfolio_cash_usdt': sum((x.cash for x in ledgers.values()), Fraction(0)),
            'other_balances': {currency: sum((dict(x.other).get(currency, Fraction(0)) for x in ledgers.values()), Fraction(0))
                               for currency in sorted({currency for x in ledgers.values() for currency, _ in x.other})}}


def terminal_state(ledgers: list[Ledger], outcomes_reconciled: bool) -> str:
    require(len(ledgers) == 6 and type(outcomes_reconciled) is bool, 'six component outcomes required')
    return 'flat_reconciled' if outcomes_reconciled and all(x.quantity == 0 for x in ledgers) else 'blocked_unresolved_continuation'


def time_window(start: datetime, end: datetime, end_inclusive: bool, *, available_cutoff: datetime | None = None) -> dict:
    value = {'start_utc': iso(start), 'start_inclusive': True, 'end_utc': iso(end), 'end_inclusive': end_inclusive}
    if available_cutoff is not None:
        value['available_at_strictly_before_utc'] = iso(available_cutoff)
    return value


def requirement(identity: str, purpose: str, symbol: str, source_category: str,
                window: dict | None, reason: str, scenario: str, source_reference: str,
                status: str, blockers: list[str], existing: bool | None = None, **extra) -> dict:
    return dict(id=identity, purpose=purpose, symbol=symbol, source_category=source_category,
                window=window, reason=reason, scenario=scenario, source_reference=source_reference,
                evidence_state=status, blockers=blockers, existing_local_evidence_can_satisfy=existing, **extra)


def build_plan(preview: dict, quotes: dict, contract: dict, provenance: dict) -> dict:
    validate_contract(contract)
    components = validate_preview(preview)
    observed = validate_quotes(quotes, components)
    signal_days = days(FIRST, LAST)
    decision_days = [d + DAY for d in signal_days]
    terminal_day = decision_days[-1] + DAY
    closing_day = terminal_day + DAY
    valuation_days = days(decision_days[0], closing_day)
    groups = {key: [] for key in ('signal_history', 'historical_availability', 'conditional_order_execution',
                                  'daily_spot_valuation', 'daily_independent_token_valuation', 'terminal_execution',
                                  'sizing_fees_precision', 'actual_fill_outcomes_and_reconciliation', 'unresolved_continuation')}
    component_rows, schedule = [], []
    for (symbol, entry, exit_), conditions in sorted(components.items()):
        identity = f'{symbol}:{entry}/{exit_}'
        component_rows.append({'id': identity, 'symbol': symbol, 'entry_lookback': entry, 'exit_lookback': exit_,
                               'initial_capital_fraction': {'numerator': 1, 'denominator': 6},
                               'initial_cash_usdt': None, 'initial_base_quantity': '0', 'actual_outcomes': 'unknown'})
        target, conditional_state = 'flat', 'flat'
        for day in signal_days:
            buy, sell = day in conditions['entry'], day in conditions['exit']
            next_target = target_after(target, buy, sell)
            action = intended_action(Fraction(conditional_state == 'long'), buy, sell)
            after = 'long' if action == 'buy' else 'flat' if action == 'sell' else conditional_state
            decision_day = day + DAY
            schedule.append(dict(component=identity, signal_bar_date=day.isoformat(), decision_utc=iso(utc(decision_day, 5)),
                                 entry_condition=buy, exit_condition=sell, signal_target_before=target,
                                 signal_target_after=next_target, state_before_if_all_prior_attempts_filled=conditional_state,
                                 conditional_action_if_all_prior_attempts_filled=action,
                                 state_after_if_all_attempts_fill=after, actual_quantity=None,
                                 assumption='all prior eligible instructions fully filled and fees/precision permitted the instruction'))
            target, conditional_state = next_target, after
            if buy or sell:
                candidate_action = 'buy' if buy else 'sell'
                rid = f'candidate:{identity}:{decision_day}:{candidate_action}'
                probe = observed[symbol, decision_day]
                groups['conditional_order_execution'].append(requirement(
                    rid, 'conditional_order_execution', symbol, 'spot_book_and_execution_evidence',
                    time_window(utc(decision_day, 10), utc(decision_day, 11), True),
                    'Fresh strict threshold condition: retain this window even if full-fill projection suppresses the action.',
                    'buy only if actual base is zero; sell only if actual base is positive; one attempt, cancel remainder at deadline',
                    f'spot_quote_checks.json#{symbol}/{decision_day}', 'quote_observed_execution_unverified',
                    ['historical_client_availability', 'depth_capacity', 'fees_precision_impact', 'actual_fill_outcome'], False,
                    component=identity, side=candidate_action, executable_side='ask' if buy else 'bid',
                    full_fill_projection_action=action, observed_event_ms=probe['ts_ms'],
                    quote_observation_satisfied=True, decision_utc=iso(utc(decision_day, 5))))
        terminal_rid = f'terminal:{identity}:{terminal_day}'
        groups['terminal_execution'].append(requirement(
            terminal_rid, 'terminal_execution', symbol, 'fresh_spot_sell_book_depth_and_fill',
            time_window(utc(terminal_day, 10), utc(terminal_day, 11), True),
            'User-selected terminal close, separate from ordinary signal exits; include every potentially held component.',
            'sell actual residual once if positive, including residual from partial or missed prior exits',
            f'public_spot_archive/{symbol}/{terminal_day}', 'local_coverage_unknown',
            ['fresh_terminal_bid', 'depth_capacity', 'fees_precision_impact', 'actual_fill_outcome'], None,
            component=identity, side='sell', executable_side='bid', decision_utc=iso(utc(terminal_day, 5)),
            state_if_all_normal_attempts_filled=conditional_state, archive_date=terminal_day.isoformat()))
    for symbol in SYMBOLS:
        record = next(x for x in preview['source']['records'] if x['symbol'] == symbol)
        for day in signal_days:
            decision = utc(day + DAY, 5)
            groups['signal_history'].append(requirement(
                f'history:{symbol}:{day}', 'signal_history', symbol, 'completed_daily_spot_candles',
                time_window(utc(day - DAY * 100), utc(day + DAY), False, available_cutoff=decision),
                'Signal close and complete prior 100 bars cover all fixed component lookbacks; signal bar excluded from each lookback.',
                'all three components; 20/10, 55/20, 100/50', 'spot_trend_preview.json#source/' + symbol,
                'contents_verified_by_frozen_preview_provenance', [], True,
                source_response_sha256=record['sha256'], signal_bar_date=day.isoformat(),
                decision_utc=iso(decision), availability_verified=False))
            groups['historical_availability'].append(requirement(
                f'availability:{symbol}:{day}', 'historical_availability', symbol, 'historical_publication_or_receipt_proof',
                time_window(utc(day - DAY * 100), decision, False, available_cutoff=decision),
                'Prove all signal/lookback record event_time and available_at precede the historical decision.',
                'all normal decisions, including flat days', 'spot_trend_preview.json#source/' + symbol,
                'historical_availability_unverified', ['available_at_not_demonstrated'], False,
                retrieved_at_is_not_available_at=True))
    for day in valuation_days:
        valuation = utc(day)
        window = time_window(valuation - timedelta(seconds=60), valuation, False, available_cutoff=valuation)
        for symbol in SYMBOLS:
            groups['daily_spot_valuation'].append(requirement(
                f'mark:{symbol}:{day}', 'daily_spot_valuation', symbol, 'fresh_spot_bid', window,
                'Conservative daily coverage for actual holdings and dust, including conditionally flat days.',
                'full window; no fill-based pruning', f'public_spot_archive/{symbol}/{day-DAY}',
                'local_coverage_unknown', ['fresh_preceding_bid_not_validated', 'historical_mark_availability'], None,
                valuation_utc=iso(valuation), archive_date=(day-DAY).isoformat(), mark_side='bid',
                point_validity='invalid_until_evidence_and_actual_holdings_reconciled'))
        groups['daily_independent_token_valuation'].append(requirement(
            f'mark:USDTUSD:{day}', 'daily_independent_token_valuation', 'USDTUSD', 'independent_token_usd_source', window,
            'Convert all D3 equity and unchanged-unit B0 with identical source and timestamp; include opening cash.',
            'every day regardless of holdings', 'independent_provider_not_yet_selected',
            'source_and_local_coverage_unknown', ['independent_provider_and_method', 'fresh_preceding_token_mark', 'historical_mark_availability'], None,
            valuation_utc=iso(valuation), source_calendar_date_utc=(day-DAY).isoformat(), shared_with='B0_USDT_HOLD',
            point_validity='invalid_until_evidence_reconciled'))
    for candidate in groups['conditional_order_execution'] + groups['terminal_execution']:
        groups['actual_fill_outcomes_and_reconciliation'].append(requirement(
            'outcome:' + candidate['id'], 'actual_fill_outcomes_and_reconciliation', candidate['symbol'], 'reconciled_execution_and_cost_ledger',
            candidate['window'], 'Actual instruction acceptance/rejection/cancel, partial/full fills, timestamps, fees and final cash/base balances are required; quote is not fill.',
            'conditional on eligible attempted instruction; explicit no-attempt reason otherwise', candidate['id'],
            'outcomes_unknown', ['no_actual_fill_outcomes', 'no_cost_currency_reconciliation'], False,
            component=candidate['component']))
    groups['sizing_fees_precision'].append(requirement(
        'account:facts', 'sizing_fees_precision', 'PORTFOLIO', 'verified_account_instrument_cost_configuration', None,
        'Fee-inclusive independent component sizing cannot be computed until capital, filters, fees and costs are known.',
        'before any execution or capital-denominated calculation', 'contracts/protocol.json#unknown_account_facts',
        'ACCOUNT_FACTS_PENDING', list(contract['unknown_account_facts']), False))
    groups['unresolved_continuation'].append(requirement(
        'continuation:terminal_failure', 'unresolved_continuation', 'BTCUSDT,ETHUSDT,USDTUSD', 'ongoing_daily_spot_bid_and_independent_token_marks',
        {'start_utc': iso(utc(closing_day + DAY)), 'start_inclusive': True, 'end_utc': None,
         'end_condition': 'all residual quantities resolved under separately authorized treatment and reconciled',
         'daily_utc': '00:00:00', 'observation_interval': '[valuation-60000ms, valuation)',
         'source_archive_date_rule': 'preceding UTC calendar day'},
        'Failed/partial terminal sale or unknown outcome preserves exposure beyond the planned endpoint.',
        'only if terminal flatness/reconciliation fails; no automatic trading retry', 'contracts/protocol.json#terminal',
        'conditional_unresolved_obligation', ['unknown_terminal_outcome', 'continuation_resolution_not_authorized'], None))
    requirements_flat = [row for key in sorted(groups) for row in groups[key]]
    for key in groups:
        groups[key].sort(key=lambda row: row['id'])
    counts = {key: len(value) for key, value in groups.items()}
    fullfill_actions = [r for r in schedule if r['conditional_action_if_all_prior_attempts_filled'] != 'none']
    blocker_counts = Counter(b for row in requirements_flat for b in row['blockers'])
    output = dict(schema_version=contract['schema_version'], status='DESCRIPTIVE_ONLY_REQUIREMENTS_READY_R2_BLOCKED',
                  r2_authorized=False, r2_freeze_ready=False, returns_computed=False, actual_fills_computed=False,
                  protocol=contract, provenance=provenance, components=component_rows,
                  boundaries=dict(opening_cash_valuation_utc=iso(utc(decision_days[0])),
                                  first_signal_bar=FIRST.isoformat(), last_signal_bar=LAST.isoformat(),
                                  first_decision_utc=iso(utc(decision_days[0], 5)), last_normal_decision_utc=iso(utc(decision_days[-1], 5)),
                                  ending_daily_mark_after_final_normal_decision_utc=iso(utc(terminal_day)),
                                  terminal_decision_utc=iso(utc(terminal_day, 5)), terminal_submission_utc=iso(utc(terminal_day, 10)),
                                  terminal_deadline_utc=iso(utc(terminal_day, 11)), closing_valuation_utc=iso(utc(closing_day))),
                  counts=dict(components=len(components), signal_days=len(signal_days), normal_decision_days=len(decision_days),
                              schedule_rows=len(schedule), conditional_fullfill_actions=len(fullfill_actions),
                              observed_unique_quote_windows=len(observed), daily_valuation_points=len(valuation_days),
                              requirements_by_purpose=counts),
                  conditional_full_fill_schedule=schedule,
                  quote_evidence=[dict(row, archive_url=f'https://quote-saver.bycsi.com/orderbook/spot/{row["symbol"]}/{row["decision_date"]}_{row["symbol"]}_ob200.data.zip',
                                       evidence='frozen_saved_prefix_replay_report', raw_archive_rehashed_here=False,
                                       full_day_semantic_validation=False, client_availability_verified=False,
                                       fills_or_capacity_verified=False) for _, row in sorted(observed.items())],
                  requirements=groups, blockers=[dict(reason=key, affected_requirements=value) for key, value in sorted(blocker_counts.items())],
                  closing_validity='blocked_until_flat_actual_balances_and_all_costs_and_marks_reconciled',
                  evidence_claim='Requirement inventory hash is not an R2 experiment lock. Unknown local coverage is not proven data absence.')
    output['requirements_sha256'] = digest(canonical(groups))
    output['deterministic_body_sha256'] = digest(canonical(output))
    return output


def run(source_dir: Path, contract_path: Path = HERE / 'contracts' / 'protocol.json') -> dict:
    contract_raw = contract_path.read_bytes()
    contract = read_json(contract_raw)
    validate_contract(contract)
    loaded = {}
    for name, expected in SOURCE_HASHES.items():
        raw = (source_dir / name).read_bytes()
        require(digest(raw) == expected, f'frozen source SHA256 mismatch: {name}')
        loaded[name] = read_json(raw)
    provenance = {'contract_file': 'contracts/protocol.json', 'contract_sha256': digest(contract_raw),
                  'contract_semantic_sha256': digest(canonical(contract)),
                  'planner_file': 'plan.py', 'planner_sha256': digest(Path(__file__).read_bytes()),
                  'input_sha256': dict(SOURCE_HASHES), 'source_scope': 'frozen saved reports; raw local archives not opened',
                  'hash_scope': 'deterministic requirements/config/code/input identities; not final R2 lock'}
    return build_plan(loaded['spot_trend_preview.json'], loaded['spot_quote_checks.json'], contract, provenance)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=Path('docs/research/crypto-r1-2026-10-31'))
    parser.add_argument('--contract', type=Path, default=HERE / 'contracts' / 'protocol.json')
    args = parser.parse_args()
    try:
        result = run(args.source_dir, args.contract)
    except (ValueError, KeyError, TypeError, OSError, RecursionError) as exc:
        parser.exit(2, f'INPUT_REJECTED: {exc}\n')
    print(canonical(result).decode(), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
