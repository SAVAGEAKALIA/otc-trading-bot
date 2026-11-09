import numpy as np
import pandas as pd

from trading_platform.legacy.iqoption_bot.strategies.ml_lstm_strategy import MLLSTMStrategy


class FakeEngineer:
    def generate_features(self, frame, is_training=False):
        return pd.DataFrame([{"feature": 0.1}, {"feature": 0.2}])


class FakeScaler:
    def transform(self, values):
        return values


class FakeInput:
    name = "features"


class FakeSession:
    def get_inputs(self):
        return [FakeInput()]

    def run(self, outputs, inputs):
        return [np.asarray([[2.0]], dtype=np.float32)]


def configured_strategy(calibration_id="lstm-cal-v1"):
    strategy = object.__new__(MLLSTMStrategy)
    strategy.ort_session = FakeSession()
    strategy.scaler = FakeScaler()
    strategy.disabled_reason = ""
    strategy.seq_length = 2
    strategy.warmup_candles = 0
    strategy.features = ["feature"]
    strategy.asset_features = []
    strategy.scale_idx = 1
    strategy.output_type = "logit"
    strategy.threshold = 0.60
    strategy.requires_market_context = False
    strategy.metadata = {}
    strategy.engineer = FakeEngineer()
    strategy.calibration_id = calibration_id
    return strategy


def test_lstm_signal_propagates_calibrated_probability_and_identity() -> None:
    result = configured_strategy().analyze(
        [{"close": 1.0}, {"close": 1.1}], symbol="EURUSD-OTC"
    )

    assert result.should_trade is True
    assert result.direction == "call"
    assert result.calibrated_win_probability == result.confidence
    assert result.calibration_id == "lstm-cal-v1"


def test_unprovenanced_lstm_signal_does_not_claim_calibration() -> None:
    result = configured_strategy(calibration_id=None).analyze(
        [{"close": 1.0}, {"close": 1.1}], symbol="EURUSD-OTC"
    )

    assert result.should_trade is True
    assert result.calibrated_win_probability is None
    assert result.calibration_id is None
