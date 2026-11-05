import unittest

from fee_ladder import fee_cases


class FeeLadderTest(unittest.TestCase):
    def setUp(self):
        self.cases = fee_cases({'results': {'BTCUSDT': {'rows': [
            {'funding_bps': '12'}, {'funding_bps': '12.01'}, {'funding_bps': '17.9604'}
        ]}}})

    def test_public_vip_zero_all_taker(self):
        row = next(r for r in self.cases if (r['tier'], r['policy']) == ('VIP 0', 'TTTT'))
        self.assertEqual(row['roundtrip_fee_bps'], '31.0')
        self.assertEqual(row['qualifying_proxy_windows']['BTCUSDT'], 0)

    def test_asymmetric_execution_and_strict_gate(self):
        rows = {r['policy']: r for r in self.cases if r['tier'] == 'Supreme VIP'}
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows['MMMM']['qualifying_proxy_windows']['BTCUSDT'], 2)
        self.assertEqual(rows['MTMM']['qualifying_proxy_windows']['BTCUSDT'], 1)
        self.assertEqual(rows['MMTM']['qualifying_proxy_windows']['BTCUSDT'], 0)
