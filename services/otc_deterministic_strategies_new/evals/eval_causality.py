"""Held-input perturbation and exact accounting, with no real return claim."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import random
import time
from ..policies import POLICIES, decide, unit_return
from ..tests.test_policies import fixture


def evaluate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    checks = 0
    rng = random.Random(4005009)
    for policy in POLICIES:
        context = fixture(policy)
        expected = decide(policy, context)
        assert expected.direction is not None
        for index in range(1000):
            future = tuple(replace(context.quotes[-1], received_at_ns=context.decision_ns+rng.randrange(1, 10**10),
                                   source_at_ms=True, event_id=f'future-{index}-{j}', price=Decimal('NaN'), clock_ok=False)
                           for j in range(4))
            order = list(context.quotes+future)
            rng.shuffle(order)
            assert decide(policy, replace(context, quotes=tuple(order))) == expected
            checks += 1
            negative = replace(context.offers[-1], received_at_ns=context.decision_ns,
                               event_id=f'closed-{index}', state='closed', payout_fraction=None)
            assert decide(policy, replace(context, offers=context.offers+(negative,))).direction is None
            checks += 1
    for _ in range(1000):
        payout = Decimal(rng.randrange(1, 20001))/Decimal(10000)
        entry = Decimal(1000)
        up = Decimal(1001)
        down = Decimal(999)
        assert unit_return('call', entry, up, payout) == payout
        assert unit_return('call', entry, down, payout) == -1
        assert unit_return('put', entry, down, payout) == payout
        assert unit_return('put', entry, up, payout) == -1
        assert unit_return('call', entry, entry, payout) == 0
        assert unit_return('call', None, None, payout, unresolved=True) == -1
        checks += 6
        context = fixture('three_step_burst_fade_v1')
        quote = context.quotes[0]
        overrun = replace(quote, received_at_ns=quote.received_at_ns+rng.randrange(1,1_000_000),
                          source_at_ms=quote.source_at_ms-5_000)
        assert decide('three_step_burst_fade_v1', replace(context, quotes=(overrun,)+context.quotes[1:])).direction is None
        exact = replace(quote, source_at_ms=quote.source_at_ms-5_000)
        assert decide('three_step_burst_fade_v1', replace(context, quotes=(exact,)+context.quotes[1:])).direction == 'put'
        checks += 2
        for policy in POLICIES:
            candidate=fixture(policy)
            base=candidate.clocks[0]
            for sign in (-1,1):
                exact=replace(base,broker_at_receipt_ms=base.broker_at_receipt_ms+sign*15_000)
                assert decide(policy,replace(candidate,clocks=(exact,))).direction is not None
                excess=replace(exact,received_at_ns=base.received_at_ns-sign*rng.randrange(1,1_000_000))
                result=decide(policy,replace(candidate,clocks=(excess,)))
                assert result.direction is None and result.reason=='unsupported_broker_clock'
                checks+=2
    report = {'schema':'otc_deterministic_new_causal_eval_v1', 'passed':True,
              'checks':checks, 'threshold':1.0, 'seed':4005009,
              'wall_seconds':time.monotonic()-started, 'policy_ids':list(POLICIES),
              'future_model_outcomes_used':False, 'broker_calls':0, 'orders':0,
              'economic_edge_measured':False, 'accepted_contract_evidence':False}
    (output/'eval.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return report


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    print(json.dumps(evaluate(parser.parse_args().output),sort_keys=True))
