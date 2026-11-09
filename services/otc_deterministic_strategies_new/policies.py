"""Frozen slots4/5. Every selection depends only on receipts at/before decision."""
from __future__ import annotations
from decimal import Decimal
from .contracts import Clock, Context, Decision, Offer, Pattern, Quote

ASSETS = ('EURUSD-OTC', 'GBPUSD-OTC')
POLICIES = ('leader_burst_flat_target_v1', 'three_step_burst_fade_v1')
NS_PER_MS = 1_000_000
LOOKBACK_NS = 60_000 * NS_PER_MS
QUOTE_MAX_AGE_NS = 5_000 * NS_PER_MS
PATTERN_MAX_SPAN_NS = 5_000 * NS_PER_MS
CLOCK_MAX_AGE_NS = 60_000 * NS_PER_MS
OFFER_MAX_AGE_NS = 600_000 * NS_PER_MS
MAX_CLOCK_OFFSET_MS = 15_000
PAYOUT_FLOOR = Decimal('0.80')
MAX_PAYOUT = Decimal('2')
MIN_EXPIRY_REMAINING_NS = 90_000 * NS_PER_MS
MAX_EXPIRY_REMAINING_NS = 150_000 * NS_PER_MS
TRIAL_SLOTS = {'leader_burst_flat_target_v1': 4, 'three_step_burst_fade_v1': 5}


def _integer(value):
    return type(value) is int and value >= 0


def _positive_decimal(value):
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _known_policy(policy, asset, decision_ns):
    if policy not in POLICIES or asset not in ASSETS or not _integer(decision_ns):
        raise ValueError('Unknown policy/asset or invalid integer receiver decision')


def _tail(quotes, asset, decision_ns):
    """Causal four-quote tail; future payload never participates in validation."""
    eligible = []
    for row in quotes:
        if not isinstance(row, Quote) or not _integer(row.received_at_ns):
            return (), 'invalid_quote_receipt'
        if row.received_at_ns > decision_ns or row.asset != asset:
            continue
        if row.received_at_ns < max(0, decision_ns - LOOKBACK_NS):
            continue
        eligible.append(row)
    eligible.sort(key=lambda q: q.received_at_ns)
    unique = []
    seen = {}
    timestamps = {}
    for row in eligible:
        if (not _positive_decimal(row.price) or not _integer(row.source_at_ms)
                or not isinstance(row.event_id, str) or not row.event_id
                or not isinstance(row.session_id, str) or not row.session_id
                or type(row.clock_offset_ms) is not int
                or abs(row.clock_offset_ms) > MAX_CLOCK_OFFSET_MS
                or row.clock_ok is not True):
            return (), 'invalid_quote_evidence'
        age_ns = row.received_at_ns + row.clock_offset_ms * NS_PER_MS - row.source_at_ms * NS_PER_MS
        if not 0 <= age_ns <= QUOTE_MAX_AGE_NS:
            return (), 'unavailable_quote_source_clock'
        if row.event_id in seen:
            if seen[row.event_id] != row:
                return (), 'conflicting_quote_identity'
            continue
        if row.received_at_ns in timestamps:
            # Distinct simultaneous events have no provable order, even if values agree.
            return (), 'ambiguous_quote_order'
        seen[row.event_id] = row
        timestamps[row.received_at_ns] = row
        unique.append(row)
    if len(unique) < 4:
        return (), 'insufficient_four_quote_history'
    tail = tuple(unique[-4:])
    if decision_ns - tail[-1].received_at_ns > QUOTE_MAX_AGE_NS:
        return (), 'stale_quote'
    if tail[-1].received_at_ns - tail[0].received_at_ns > PATTERN_MAX_SPAN_NS:
        return (), 'pattern_exceeds_five_seconds'
    if len({q.session_id for q in tail}) != 1:
        return (), 'pattern_crosses_session'
    if any(b.source_at_ms <= a.source_at_ms for a, b in zip(tail, tail[1:])):
        return (), 'source_not_strictly_advancing'
    return tail, None


def _three_step_direction(tail):
    changes = [(b.price > a.price) - (b.price < a.price) for a, b in zip(tail, tail[1:])]
    return changes[0] if changes[0] and len(set(changes)) == 1 else 0


def pattern_signal(policy, asset, decision_ns, quotes):
    """Mechanism diagnostic only. A Pattern is never sufficient to submit an order."""
    _known_policy(policy, asset, decision_ns)
    target, failure = _tail(quotes, asset, decision_ns)
    if failure:
        return Pattern(policy, asset, decision_ns, None, failure)
    if policy == 'three_step_burst_fade_v1':
        movement = _three_step_direction(target)
        if not movement:
            return Pattern(policy, asset, decision_ns, None, 'no_three_step_burst')
        return Pattern(policy, asset, decision_ns, 'put' if movement > 0 else 'call',
                       'three_step_burst_fade', tuple(q.event_id for q in target))
    leader_asset = next(name for name in ASSETS if name != asset)
    leader, failure = _tail(quotes, leader_asset, decision_ns)
    if failure:
        return Pattern(policy, asset, decision_ns, None, 'leader_' + failure)
    if target[-1].session_id != leader[-1].session_id:
        return Pattern(policy, asset, decision_ns, None, 'paired_pattern_crosses_session')
    if len({q.event_id for q in (*target, *leader)}) != 8:
        return Pattern(policy, asset, decision_ns, None, 'paired_quote_identity_conflict')
    movement = _three_step_direction(leader)
    if not movement:
        return Pattern(policy, asset, decision_ns, None, 'leader_no_three_step_burst')
    if leader[-1].received_at_ns >= target[-1].received_at_ns:
        return Pattern(policy, asset, decision_ns, None, 'leader_not_strictly_received_before_target')
    if leader[-1].source_at_ms > target[-1].source_at_ms:
        return Pattern(policy, asset, decision_ns, None, 'leader_source_ahead_of_target')
    if target[0].received_at_ns < leader[0].received_at_ns:
        return Pattern(policy, asset, decision_ns, None, 'target_flat_window_precedes_burst')
    if len({q.price for q in target}) != 1:
        return Pattern(policy, asset, decision_ns, None, 'target_already_moved')
    return Pattern(policy, asset, decision_ns, 'call' if movement > 0 else 'put',
                   'leader_burst_flat_target', tuple(q.event_id for q in (*target, *leader)))


def _latest(rows, decision_ns, kind):
    admitted = []
    for row in rows:
        if not isinstance(row, kind) or not _integer(row.received_at_ns):
            return None, 'invalid_' + kind.__name__.lower() + '_receipt'
        if row.received_at_ns <= decision_ns:
            admitted.append(row)
    if not admitted:
        return None, 'missing_' + kind.__name__.lower()
    latest_ns = max(row.received_at_ns for row in admitted)
    latest = [row for row in admitted if row.received_at_ns == latest_ns]
    if any(row != latest[0] for row in latest[1:]):
        return None, 'conflicting_' + kind.__name__.lower()
    return latest[0], None


def decide(policy, context):
    """Return an order proposal or abstention. Transport/risk is a separate root service."""
    if not isinstance(context, Context):
        raise ValueError('Typed immutable Context required')
    _known_policy(policy, context.asset, context.decision_ns)

    def abstain(reason):
        return Decision(policy, context.asset, context.decision_ns, None, reason)

    clock, failure = _latest(context.clocks, context.decision_ns, Clock)
    if failure:
        return abstain(failure)
    if (clock.healthy is not True or not _integer(clock.broker_at_receipt_ms)
            or context.decision_ns - clock.received_at_ns > CLOCK_MAX_AGE_NS
            or abs(clock.broker_at_receipt_ms * NS_PER_MS - clock.received_at_ns) > MAX_CLOCK_OFFSET_MS * NS_PER_MS):
        return abstain('unsupported_broker_clock')
    offer_rows = []
    offer_identities = {}
    for row in context.offers:
        if not isinstance(row, Offer) or not _integer(row.received_at_ns):
            return abstain('invalid_offer_receipt')
        if row.received_at_ns <= context.decision_ns and row.asset == context.asset:
            if isinstance(row.event_id, str) and row.event_id in offer_identities and offer_identities[row.event_id] != row:
                return abstain('contradictory_offer_identity')
            if isinstance(row.event_id, str):
                offer_identities[row.event_id] = row
            offer_rows.append(row)
    offer, failure = _latest(offer_rows, context.decision_ns, Offer)
    if failure:
        return abstain(failure)
    if context.decision_ns - offer.received_at_ns > OFFER_MAX_AGE_NS:
        return abstain('stale_offer')
    if offer.state != 'open':
        return abstain('offer_not_explicitly_open')
    if (offer.product != 'turbo-option' or type(offer.requested_duration_minutes) is not int
            or offer.requested_duration_minutes != 2 or not isinstance(offer.event_id, str)
            or not offer.event_id or type(offer.offered_expiries_ms) is not tuple
            or not offer.offered_expiries_ms or any(not _integer(x) for x in offer.offered_expiries_ms)
            or len(set(offer.offered_expiries_ms)) != len(offer.offered_expiries_ms)):
        return abstain('unsupported_offer_contract')
    if (not _positive_decimal(offer.payout_fraction)
            or not PAYOUT_FLOOR <= offer.payout_fraction <= MAX_PAYOUT):
        return abstain('payout_below_floor_or_unknown')
    if (not _integer(context.proposed_expiry_ms)
            or context.proposed_expiry_ms not in offer.offered_expiries_ms):
        return abstain('expiry_not_in_received_offer')
    broker_now_ns = clock.broker_at_receipt_ms * NS_PER_MS + context.decision_ns - clock.received_at_ns
    remaining_ns = context.proposed_expiry_ms * NS_PER_MS - broker_now_ns
    if not MIN_EXPIRY_REMAINING_NS <= remaining_ns <= MAX_EXPIRY_REMAINING_NS:
        return abstain('expiry_outside_two_minute_offer_window')
    pattern = pattern_signal(policy, context.asset, context.decision_ns, context.quotes)
    if pattern.direction is None:
        return abstain(pattern.reason)
    return Decision(policy, context.asset, context.decision_ns, pattern.direction, pattern.reason,
                    context.proposed_expiry_ms, offer.payout_fraction, pattern.quote_ids, offer.event_id)


def unit_return(direction, entry, terminal, payout, *, unresolved=False):
    """Conservative unit quote-proxy accounting; actual cash settlement supersedes it."""
    if direction not in ('call', 'put') or not _positive_decimal(payout) or payout > MAX_PAYOUT:
        raise ValueError('Known direction and finite positive payout required')
    if type(unresolved) is not bool:
        raise ValueError('unresolved must be bool')
    if unresolved:
        return Decimal('-1')
    if not _positive_decimal(entry) or not _positive_decimal(terminal):
        raise ValueError('Resolved prices must be finite positive Decimal values')
    if entry == terminal:
        return Decimal('0')
    win = (terminal > entry) == (direction == 'call')
    return payout if win else Decimal('-1')
