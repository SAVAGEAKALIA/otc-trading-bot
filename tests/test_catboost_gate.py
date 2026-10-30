import unittest

import numpy as np
import pandas as pd

from trading_platform.legacy.iqoption_bot.strategies.ml_catboost_gate_strategy import (
    MLCatBoostGateStrategy,
)


class FakeEngineer:
    def generate_features(self, frame, is_training=False):
        return pd.DataFrame([{"log_return_1": 0.01}])


class FakeContext:
    def __init__(self, payout=0.80):
        self.payout = payout

    def snapshot(self, asset, decision_time_ms):
        return {
            "payout_fraction": self.payout,
            "payout_missing": 0.0,
            "quote_missing": 0.0,
            "mood_missing": 0.0,
        }


class FakeModel:
    def predict(self, frame, prediction_type=None):
        return np.asarray([1.5])


class FakeCalibrator:
    def predict_proba(self, raw):
        return np.asarray([[0.30, 0.70]])


def configured_gate(payout=0.80):
    gate = object.__new__(MLCatBoostGateStrategy)
    gate.engineer = FakeEngineer()
    gate.context_provider = FakeContext(payout)
    gate.model = FakeModel()
    gate.calibrator = FakeCalibrator()
    gate.metadata = {
        "offline_deployment_approved": True,
        "calibration_id": "candidate-gate-cal-v1",
    }
    gate.disabled_reason = ""
    gate.threshold = 0.65
    gate.numeric_features = [
        "log_return_1", "strategy_score", "direction_sign"
    ]
    gate.categorical_features = ["asset", "direction", "strategy"]
    gate.feature_order = gate.numeric_features + gate.categorical_features
    return gate


class CatBoostGateTests(unittest.TestCase):
    def evaluate(self, gate, direction="put", minimum_payout=0.75):
        return gate.evaluate_candidate(
            asset="EURUSD-OP",
            direction=direction,
            strategy="Indicators",
            candles=[
                {
                    "timestamp": 1_700_000_000,
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.05,
                }
            ],
            strategy_score=70.0,
            strategy_confidence=0.70,
            confluence=2,
            duration_minutes=2,
            regime="normal",
            trend_5m="down",
            trend_15m="down",
            minimum_payout=minimum_payout,
            minimum_expected_value=0.01,
        )

    def test_gate_accepts_existing_put_without_changing_direction(self):
        result = self.evaluate(configured_gate(), direction="put")
        self.assertTrue(result.available)
        self.assertTrue(result.accepted)
        self.assertAlmostEqual(result.probability, 0.70)
        self.assertAlmostEqual(result.expected_value, 0.26)
        self.assertEqual(result.calibration_id, "candidate-gate-cal-v1")

    def test_gate_rejects_low_payout_even_with_probability_edge(self):
        result = self.evaluate(
            configured_gate(payout=0.60), minimum_payout=0.75
        )
        self.assertFalse(result.accepted)
        self.assertTrue(any("below minimum" in item for item in result.warnings))


if __name__ == "__main__":
    unittest.main()
