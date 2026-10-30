import unittest

import numpy as np
import pandas as pd

from trading_platform.legacy.iqoption_bot.strategies.ml_catboost_directional_strategy import (
    MLDirectionalCatBoostStrategy,
)


class FakeEngineer:
    def generate_features(self, frame, is_training=False):
        return pd.DataFrame([{"log_return_1": 0.01}])


class FakeContext:
    def __init__(self, payout=0.80):
        self.payout = payout

    def enrich_candles(self, candles, symbol, timeframe):
        frame = pd.DataFrame(candles)
        frame["context_complete"] = 1.0
        frame["payout_fraction"] = self.payout
        return frame


class FakeModel:
    def predict(self, frame, prediction_type=None):
        return np.asarray([1.2])


class FakeCalibrator:
    def predict_proba(self, raw):
        return np.asarray([[0.30, 0.70]])


def configured_strategy(payout=0.80):
    strategy = object.__new__(MLDirectionalCatBoostStrategy)
    strategy.model = FakeModel()
    strategy.calibrator = FakeCalibrator()
    strategy.engineer = FakeEngineer()
    strategy.context_provider = FakeContext(payout)
    strategy.metadata = {
        "assets": ["EURUSD-OTC"],
        "offline_deployment_approved": False,
        "calibration_id": "directional-cal-v1",
    }
    strategy.disabled_reason = ""
    strategy.feature_order = ["log_return_1", "asset"]
    strategy.numeric_features = ["log_return_1"]
    strategy.categorical_features = ["asset"]
    strategy.threshold = 0.65
    return strategy


def candles():
    return [
        {
            "timestamp": 1_700_000_000 + index * 120,
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.05,
        }
        for index in range(65)
    ]


class DirectionalCatBoostTests(unittest.TestCase):
    def test_directional_model_can_propose_call_in_research_mode(self):
        result = configured_strategy().analyze(
            candles(), symbol="EURUSD-OP",
            ml_min_payout=0.75, ml_min_expected_value=0.02,
        )
        self.assertTrue(result.should_trade)
        self.assertEqual(result.direction, "call")
        self.assertAlmostEqual(result.confidence, 0.70)
        self.assertAlmostEqual(result.calibrated_win_probability, 0.70)
        self.assertEqual(result.calibration_id, "directional-cal-v1")
        self.assertTrue(any("research-only" in item for item in result.warnings))

    def test_directional_model_rejects_low_payout(self):
        result = configured_strategy(payout=0.60).analyze(
            candles(), symbol="EURUSD-OTC",
            ml_min_payout=0.75, ml_min_expected_value=0.02,
        )
        self.assertFalse(result.should_trade)
        self.assertTrue(any("below minimum" in item for item in result.warnings))


if __name__ == "__main__":
    unittest.main()
