"""Free gate checks for immutable OTC boundaries."""
import unittest
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, ROUND_DOWN, ROUND_UP, localcontext
from contracts.otc_v1 import Observation, Opportunity, Settlement


class ContractTests(unittest.TestCase):
    def observation(self):
        return Observation('q1', 'iqoption', 'EURUSD-OTC', 'turbo-option', 'quotes', 'quote', 250, 200, '1.12', 'receiver_utc')

    def test_immutable_receipt_is_distinct_from_source(self):
        row = self.observation()
        self.assertEqual((row.available_ms, row.event_ms), (250, 200))
        with self.assertRaises(FrozenInstanceError):
            row.available_ms = 0
        self.assertEqual(row.as_record()['value'], '1.12')

    def test_unknown_availability_stays_unknown(self):
        row = replace(self.observation(), quality='bucket_only', available_ms=None)
        self.assertIsNone(row.as_record()['available_ms'])

    def test_reject_invalid_units_time_and_nonfinite(self):
        for changes in ({'value': 'NaN'}, {'value': 'Infinity'}, {'value': '-1'}, {'value': '0'},
                        {'event_ms': True}, {'available_ms': 199}, {'kind': 'other'},
                        {'kind': 'payout', 'value': '85'}, {'kind': 'mood', 'value': '1.1'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.observation(), **changes)

    def test_proxy_never_becomes_accepted_trade(self):
        row = Opportunity('o1','iqoption','EURUSD-OTC','turbo-option','receiver_utc',1000,5000,2000,'hypothetical','call')
        for changes in ({'evidence_class':'practice_accepted'}, {'latest_entry_ms':5000}, {'acceptance_delay_ms':True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(row, **changes)
        self.assertIsNone(replace(row, direction=None).as_record()['direction'])

    def test_cash_fee_and_nonstandard_tie_preserved(self):
        row = Settlement('b1','practice','broker_api','win','10','18','0.1','USD',9000,'raw1')
        self.assertEqual(row.unit_return, Decimal('.79'))
        self.assertEqual(replace(row, outcome='tie', gross_return='5').unit_return, Decimal('-.51'))
        self.assertEqual(row.as_record()['evidence_id'],'raw1')
        for changes in ({'source':'quote_proxy'}, {'outcome':'unresolved'}, {'outcome':'loss'}, {'stake':'0'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(row, **changes)

    def test_cash_ratio_ignores_caller_decimal_context(self):
        row = Settlement('b1','practice','broker_api','tie','3','1','0','USD',9000,'raw1')
        expected=Decimal('-0.6666666666666666666666666666666667')
        for rounding in (ROUND_DOWN,ROUND_UP):
            with localcontext() as ctx:
                ctx.prec=2;ctx.rounding=rounding
                self.assertEqual(row.unit_return,expected)


if __name__ == '__main__': unittest.main()
