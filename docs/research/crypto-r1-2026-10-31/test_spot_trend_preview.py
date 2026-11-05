from decimal import Decimal
import unittest

from spot_trend_preview import conditions


def bar(high, low, close):
    return tuple(map(Decimal, (close, high, low, close)))


class SpotTrendPreviewTest(unittest.TestCase):
    def test_signal_bar_does_not_define_its_own_threshold(self):
        history = [bar('10', '8', '9'), bar('11', '7', '10')]
        self.assertEqual(conditions(history + [bar('14', '9', '12')], 2, 2, 1), (True, False))
        self.assertEqual(conditions(history + [bar('10', '5', '6')], 2, 2, 1), (False, True))

    def test_equality_and_warmup(self):
        history = [bar('10', '8', '9'), bar('11', '7', '10')]
        for close in ('11', '7'):
            self.assertEqual(conditions(history + [bar('14', '5', close)], 2, 2, 1), (False, False))
        with self.assertRaises(ValueError):
            conditions(history, 1, 2, 1)
