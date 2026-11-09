"""Fast, dependency-free offer/balance regression gates."""
from dataclasses import replace
from decimal import Decimal
import unittest
from trading_platform.brokers.iqoption.practice_contract import Offer, offered_expiry, select_practice

class ContractGates(unittest.TestCase):
    def test_expiry_admission(self):
        now=1_794_206_400_000_000_000
        offer=Offer(1865,'USDNGN-OTC',True,False,Decimal('.85'),now//1_000_000_000+60,60,5,((now//1_000_000_000-3600,now//1_000_000_000+3600),),now)
        self.assertEqual(offered_expiry(offer,now,now),now//1_000_000_000+120)
        for bad in [replace(offer,enabled=False),replace(offer,suspended=True),replace(offer,received_ns=now-30_000_000_001),replace(offer,payout=Decimal('.79')),replace(offer,schedules=()),replace(offer,enabled=1)]:
            with self.assertRaises(ValueError):offered_expiry(bad,now,now)
    def test_practice_identity(self):
        b={'id':4,'type':4,'currency':'USD','amount':100}
        self.assertEqual(select_practice([b],1).balance_id,4)
        for rows in [[],[b,b],[{**b,'type':1}],[{**b,'type':True}],[{**b,'currency':'EUR'}],[{**b,'amount':'NaN'}]]:
            with self.assertRaises(ValueError):select_practice(rows,1)
if __name__=='__main__':unittest.main()
