"""Seeded acceptance evaluation; no account calls or orders."""
import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import random
import unittest
from trading_platform.brokers.iqoption.practice_contract import Offer, offered_expiry, select_practice
from tests.unit.brokers.test_iqoption_practice import NOW, PracticeGates

def main():
    rng=random.Random(20261109)
    tested=0
    for _ in range(5000):
        broker=NOW+rng.randrange(-20_000_000_000,20_000_000_000)
        first=broker//60_000_000_000*60+60
        offer=Offer(1865,'USDNGN-OTC',True,False, __import__('decimal').Decimal('.85'),first,60,5,((first-3600,first+3600),),NOW)
        value=offered_expiry(offer,NOW,broker)
        assert value in [first+i*60 for i in range(5)]
        assert 90_000_000_000<=value*1_000_000_000-broker<=150_000_000_000
        tested+=2
        for bad in (replace(offer,enabled=False),replace(offer,suspended=True),replace(offer,received_ns=NOW-30_000_000_001),replace(offer,payout=__import__('decimal').Decimal('.79'))):
            try:offered_expiry(bad,NOW,broker)
            except ValueError:pass
            else:raise AssertionError('unsafe offer admitted')
            tested+=1
    with contextlib.redirect_stdout(io.StringIO()):
        result=unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(PracticeGates))
    report={'seed':20261109,'contract_checks':tested,'gates':result.testsRun,'failures':len(result.failures),'errors':len(result.errors), 'account_calls':0,'verified_edge':False,'pass':result.wasSuccessful()}
    print(json.dumps(report,sort_keys=True))
    if not report['pass']:raise SystemExit(1)
if __name__=='__main__':main()
