import pytest

from trading_platform.legacy.iqoption_bot.scanner import ScannerSignal
from trading_platform.legacy.iqoption_bot.strategy_engine import StrategyEngine
from trading_platform.legacy.iqoption_bot.strategies.base import BaseStrategy, StrategyResult
from trading_platform.legacy.iqoption_bot.worker import APIWorker


class FixedStrategy(BaseStrategy):
    def __init__(self, name, probability=None, calibration_id=None):
        super().__init__(name)
        self.probability = probability
        self.calibration_id = calibration_id

    def analyze(self, candles, **kwargs):
        return StrategyResult(
            score=80,
            direction="call",
            confidence=0.8,
            reasons=["fixed"],
            warnings=[],
            should_trade=True,
            calibrated_win_probability=self.probability,
            calibration_id=self.calibration_id,
        )


def test_strategy_result_requires_probability_and_id_together() -> None:
    with pytest.raises(ValueError, match="appear together"):
        StrategyResult(
            score=80,
            direction="call",
            confidence=0.8,
            reasons=[],
            warnings=[],
            should_trade=True,
            calibrated_win_probability=0.72,
        )


def test_single_strategy_decision_preserves_calibrated_probability() -> None:
    engine = StrategyEngine()
    engine.register(FixedStrategy("ML", 0.72, "cal-v1"))

    decision = engine.evaluate_single("ML", candles=[])

    assert decision.calibrated_win_probability == 0.72
    assert decision.calibration_id == "cal-v1"


def test_multi_strategy_vote_drops_model_calibration() -> None:
    engine = StrategyEngine()
    engine.register(FixedStrategy("ML", 0.72, "cal-v1"))
    engine.register(FixedStrategy("Rule"))

    decision = engine.evaluate(candles=[], min_agreement=2)

    assert decision.should_trade
    assert decision.calibrated_win_probability is None
    assert decision.calibration_id is None


@pytest.mark.asyncio
async def test_worker_copies_scanner_provenance_into_trade_request() -> None:
    captured = []
    worker = APIWorker.__new__(APIWorker)
    worker.notification_callback = None

    async def submit(request, source):
        captured.append(request)

    worker.submit_trade = submit
    signal = ScannerSignal(
        asset="EURUSD-OTC",
        direction="call",
        confidence=0.72,
        score=72,
        confluence=1,
        risk_level="normal",
        reason="model",
        notes=[],
        strategy_used="ML_CatBoost_Directional",
        calibrated_win_probability=0.72,
        calibration_id="cal-v1",
    )

    await worker._handle_scanner_signal(signal)

    assert captured[0].calibrated_win_probability == 0.72
    assert captured[0].calibration_version == "cal-v1"
