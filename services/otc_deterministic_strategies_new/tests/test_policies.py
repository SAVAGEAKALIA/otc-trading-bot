from dataclasses import replace
from decimal import Decimal
import unittest
from ..contracts import Clock, Context, Offer, Quote
from ..policies import POLICIES, decide, pattern_signal, unit_return

D = 1_000_000 * 1_000_000
A, B = 'EURUSD-OTC', 'GBPUSD-OTC'
FADE, LEAD = 'three_step_burst_fade_v1', 'leader_burst_flat_target_v1'


def quotes(asset=A, prices=('1', '1.001', '1.002', '1.003'), offset_ns=0):
    return tuple(Quote(asset, D - (4 - i) * 1_000_000_000 + offset_ns,
                       (D - (4 - i) * 1_000_000_000 + offset_ns) // 1_000_000,
                       Decimal(price), f'{asset}-{i}', 'physical-session', 0, True)
                 for i, price in enumerate(prices))


def fixture(policy=FADE):
    clock = Clock(D - 1_000_000_000, (D - 1_000_000_000) // 1_000_000, True)
    offer = Offer(A, D - 1_000_000_000, 'offer-1', 'open', 'turbo-option', 2,
                  (D // 1_000_000 + 120_000,), Decimal('.83'))
    rows = quotes() if policy == FADE else (
        quotes(A, ('1', '1', '1', '1'), 100_000_000) + quotes(B))
    return Context(A, D, offer.offered_expiries_ms[0], rows, (offer,), (clock,))


class Policies(unittest.TestCase):
    def test_three_step_fade_and_reverse(self):
        context = fixture()
        decision = decide(FADE, context)
        self.assertEqual(decision.direction, 'put')
        self.assertEqual(decision.expiry_ms, context.proposed_expiry_ms)
        self.assertEqual(decision.payout_fraction, Decimal('.83'))
        self.assertEqual(decision.offer_id, 'offer-1')
        self.assertEqual(len(decision.quote_ids), 4)
        down = replace(context, quotes=quotes(prices=('1.003', '1.002', '1.001', '1')))
        self.assertEqual(decide(FADE, down).direction, 'call')

    def test_leader_burst_target_flat(self):
        self.assertEqual(decide(LEAD, fixture(LEAD)).direction, 'call')

    def test_future_payload_and_closed_offer_do_not_change_decision(self):
        for policy in POLICIES:
            context = fixture(policy)
            future = replace(context.quotes[0], received_at_ns=D + 1, price=Decimal('NaN'), clock_ok=False)
            future_offer = replace(context.offers[0], received_at_ns=D + 1, state='closed', payout_fraction=None)
            future_clock = replace(context.clocks[0], received_at_ns=D + 1, healthy=False)
            mutated = replace(context, quotes=context.quotes + (future,),
                              offers=context.offers + (future_offer,), clocks=context.clocks + (future_clock,))
            self.assertEqual(decide(policy, context), decide(policy, mutated))

    def test_negative_offer_overrides_still_fresh_old_payout(self):
        context = fixture()
        closed = replace(context.offers[0], received_at_ns=D, event_id='offer-closed', state='closed')
        self.assertEqual(decide(FADE, replace(context, offers=context.offers + (closed,))).reason,
                         'offer_not_explicitly_open')

    def test_unknown_missing_or_stale_offer_abstains(self):
        context = fixture()
        for modified in (replace(context, offers=()),
                         replace(context, offers=(replace(context.offers[0], state='unknown'),)),
                         replace(context, offers=(replace(context.offers[0], received_at_ns=D-600_000_000_001),))):
            self.assertIsNone(decide(FADE, modified).direction)

    def test_offer_and_clock_conflicts_abstain(self):
        context = fixture()
        offer = replace(context.offers[0], event_id='simultaneous-other-offer', payout_fraction=Decimal('.90'))
        self.assertEqual(decide(FADE, replace(context, offers=context.offers+(offer,))).reason, 'conflicting_offer')
        clock = replace(context.clocks[0], broker_at_receipt_ms=context.clocks[0].broker_at_receipt_ms+1)
        self.assertEqual(decide(FADE, replace(context, clocks=context.clocks+(clock,))).reason, 'conflicting_clock')

    def test_payout_floor_nan_unknown_and_bool(self):
        context = fixture()
        for value in (None, Decimal('NaN'), Decimal('Infinity'), Decimal('.799999'), Decimal('2.1'), True):
            self.assertIsNone(decide(FADE, replace(context, offers=(replace(context.offers[0], payout_fraction=value),))).direction)
        minimum = replace(context.offers[0], payout_fraction=Decimal('.80'))
        self.assertEqual(decide(FADE, replace(context, offers=(minimum,))).direction, 'put')

    def test_clock_age_offset_health_and_type(self):
        context = fixture()
        for clock in (replace(context.clocks[0], healthy=False),
                      replace(context.clocks[0], received_at_ns=D-60_000_000_001),
                      replace(context.clocks[0], broker_at_receipt_ms=True),
                      replace(context.clocks[0], broker_at_receipt_ms=D//1_000_000+20_000)):
            self.assertIsNone(decide(FADE, replace(context, clocks=(clock,))).direction)

    def test_both_signed_clock_limits_use_exact_receiver_nanoseconds(self):
        for policy in POLICIES:
            context=fixture(policy)
            base=context.clocks[0]
            for sign in (-1,1):
                for overrun in (0,1):
                    received=base.received_at_ns-sign*overrun
                    broker=base.broker_at_receipt_ms+sign*15_000
                    clock=replace(base,received_at_ns=received,broker_at_receipt_ms=broker)
                    self.assertEqual(broker*1_000_000-received,sign*(15_000_000_000+overrun))
                    result=decide(policy,replace(context,clocks=(clock,)))
                    if overrun:
                        self.assertIsNone(result.direction)
                        self.assertEqual(result.reason,'unsupported_broker_clock')
                    else:
                        self.assertIsNotNone(result.direction)

    def test_expiry_requires_received_offer_and_registered_duration(self):
        context = fixture()
        for expiry in (True, context.proposed_expiry_ms+1):
            self.assertIsNone(decide(FADE, replace(context, proposed_expiry_ms=expiry)).direction)
        for offer in (replace(context.offers[0], requested_duration_minutes=True),
                      replace(context.offers[0], requested_duration_minutes=1),
                      replace(context.offers[0], product='binary-option'),
                      replace(context.offers[0], offered_expiries_ms=(True,)),
                      replace(context.offers[0], offered_expiries_ms=())):
            self.assertIsNone(decide(FADE, replace(context, offers=(offer,))).direction)

    def test_offer_expiry_window_exact_bounds(self):
        context = fixture()
        for remaining, allowed in ((89_999, False), (90_000, True), (150_000, True), (150_001, False)):
            expiry = D//1_000_000 + remaining
            offer = replace(context.offers[0], offered_expiries_ms=(expiry,))
            self.assertEqual(decide(FADE, replace(context, proposed_expiry_ms=expiry, offers=(offer,))).direction is not None, allowed)

    def test_zero_or_mixed_moves_abstain(self):
        context = fixture()
        for prices in (('1', '1', '1.1', '1.2'), ('1', '1.1', '1', '1.1'), ('1', '1', '1', '1')):
            self.assertIsNone(decide(FADE, replace(context, quotes=quotes(prices=prices))).direction)

    def test_quote_future_source_clock_gap_session_nan(self):
        context = fixture()
        mutations = (replace(context.quotes[-1], price=Decimal('NaN')),
                     replace(context.quotes[-1], source_at_ms=D//1_000_000+1),
                     replace(context.quotes[-1], clock_offset_ms=True),
                     replace(context.quotes[-1], clock_ok=False),
                     replace(context.quotes[-1], session_id='new-session'),
                     replace(context.quotes[-1], event_id=''),
                     replace(context.quotes[-1], received_at_ns=True))
        for quote in mutations:
            self.assertIsNone(decide(FADE, replace(context, quotes=context.quotes[:-1]+(quote,))).direction)
        older = tuple(replace(q, received_at_ns=q.received_at_ns-6_000_000_000,
                              source_at_ms=q.source_at_ms-6_000) for q in context.quotes)
        self.assertIsNone(decide(FADE, replace(context, quotes=older)).direction)
        span = (replace(context.quotes[0], received_at_ns=D-6_000_000_001,
                        source_at_ms=(D-6_000_000_001)//1_000_000),)+context.quotes[1:]
        self.assertIsNone(decide(FADE, replace(context, quotes=span)).direction)

    def test_quote_duplicate_identity_or_same_timestamp_conflict(self):
        context = fixture()
        identical = context.quotes+(context.quotes[-1],)
        self.assertEqual(decide(FADE, context), decide(FADE, replace(context, quotes=identical)))
        contradictory = replace(context.quotes[-1], price=Decimal('2'))
        self.assertIsNone(decide(FADE, replace(context, quotes=context.quotes+(contradictory,))).direction)
        simultaneous = replace(context.quotes[-1], event_id='another-event')
        self.assertIsNone(decide(FADE, replace(context, quotes=context.quotes+(simultaneous,))).direction)

    def test_source_cache_and_input_order(self):
        context = fixture()
        cached = replace(context.quotes[-1], source_at_ms=context.quotes[-2].source_at_ms)
        self.assertIsNone(decide(FADE, replace(context, quotes=context.quotes[:-1]+(cached,))).direction)
        self.assertEqual(decide(FADE, context), decide(FADE, replace(context, quotes=tuple(reversed(context.quotes)))))

    def test_fractional_source_age_cannot_be_truncated_into_freshness(self):
        context = fixture()
        quote = replace(context.quotes[0], received_at_ns=context.quotes[0].received_at_ns+1,
                        source_at_ms=context.quotes[0].source_at_ms-5_000)
        self.assertEqual(decide(FADE, replace(context, quotes=(quote,)+context.quotes[1:])).reason,
                         'unavailable_quote_source_clock')

    def test_leader_must_precede_target_and_target_must_stay_flat(self):
        context = fixture(LEAD)
        leader = context.quotes[-4:]
        target = context.quotes[:4]
        same_batch = tuple(replace(q, received_at_ns=q.received_at_ns-100_000_000,
                                   source_at_ms=q.source_at_ms-100) for q in target)+leader
        self.assertIsNone(decide(LEAD, replace(context, quotes=same_batch)).direction)
        moved = target[:-1]+(replace(target[-1], price=Decimal('1.1')),)+leader
        self.assertIsNone(decide(LEAD, replace(context, quotes=moved)).direction)
        ahead = target+leader[:-1]+(replace(leader[-1], source_at_ms=target[-1].source_at_ms+1),)
        self.assertIsNone(decide(LEAD, replace(context, quotes=ahead)).direction)

    def test_paired_sessions_and_global_quote_ids_must_agree(self):
        context = fixture(LEAD)
        rows = context.quotes
        copied = rows[:-1]+(replace(rows[-1], event_id=rows[0].event_id),)
        self.assertEqual(decide(LEAD, replace(context, quotes=copied)).reason, 'paired_quote_identity_conflict')
        reconnected = rows[:4]+tuple(replace(q, session_id='another-physical-session') for q in rows[4:])
        self.assertEqual(decide(LEAD, replace(context, quotes=reconnected)).reason, 'paired_pattern_crosses_session')

    def test_contradictory_reused_offer_identity_abstains(self):
        context=fixture()
        reused=replace(context.offers[0], received_at_ns=D, payout_fraction=Decimal('.90'))
        self.assertEqual(decide(FADE, replace(context, offers=context.offers+(reused,))).reason,
                         'contradictory_offer_identity')

    def test_invalid_policy_and_context_raise(self):
        with self.assertRaises(ValueError):
            decide('tuned-extra-variant', fixture())
        with self.assertRaises(ValueError):
            decide(FADE, {})
        with self.assertRaises(ValueError):
            decide(FADE, replace(fixture(), decision_ns=True))

    def test_mechanism_is_not_order_proposal(self):
        context = fixture()
        pattern = pattern_signal(FADE, A, D, context.quotes)
        self.assertEqual(pattern.role, 'preoffer_mechanism_only')
        self.assertFalse(hasattr(pattern, 'expiry_ms'))
        self.assertIsNone(decide(FADE, replace(context, offers=())).direction)

    def test_per_contract_returns_ties_and_full_unknown_loss(self):
        self.assertEqual(unit_return('call', Decimal('1'), Decimal('1.1'), Decimal('.55')), Decimal('.55'))
        self.assertEqual(unit_return('call', Decimal('1'), Decimal('.9'), Decimal('.95')), Decimal('-1'))
        self.assertEqual(unit_return('put', Decimal('1'), Decimal('1'), Decimal('.83')), Decimal('0'))
        self.assertEqual(unit_return('put', None, None, Decimal('.83'), unresolved=True), Decimal('-1'))
        # Variable payout/outcome covariance must be retained row by row.
        rows = [unit_return('call', Decimal('1'), Decimal('2'), Decimal('.55'))]*6
        rows += [unit_return('call', Decimal('1'), Decimal('.5'), Decimal('.95'))]*4
        self.assertEqual(sum(rows)/Decimal(len(rows)), Decimal('-.07'))


if __name__ == '__main__':
    unittest.main()
