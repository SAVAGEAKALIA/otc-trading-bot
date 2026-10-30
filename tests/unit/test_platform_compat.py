from datetime import UTC, datetime
from decimal import Decimal

from trading_platform.legacy.iqoption_bot.models import TradeRequest, TradeSignal
from trading_platform.legacy.iqoption_bot.platform_compat import LegacyTradeRequestAdapter
from trading_platform.domain.orders import BinaryDirection


def test_legacy_request_translation_preserves_execution_semantics() -> None:
    request = TradeRequest(
        signal=TradeSignal("EURUSD-op", "call", 2),
        ai_confidence=0.73,
        source="scanner",
        strategy_used="ml_gate_v1",
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)

    candidate = LegacyTradeRequestAdapter.to_otc_candidate(
        request,
        stake=Decimal("5"),
        payout_ratio=Decimal("0.84"),
        estimated_win_probability=Decimal("0.61"),
        decision_at=now,
    )

    assert candidate.normalized_asset == "EURUSD-OTC"
    assert candidate.direction is BinaryDirection.CALL
    assert candidate.duration_minutes == 2
    assert candidate.stake == Decimal("5")
    assert candidate.payout_ratio == Decimal("0.84")
    assert candidate.confidence == Decimal("0.73")
    assert candidate.strategy_id == "ml_gate_v1"


def test_legacy_translation_generates_stable_signal_id_for_replay() -> None:
    request = TradeRequest(TradeSignal("EURUSD-OTC", "put", 1), source="telegram")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    arguments = dict(
        stake=Decimal("1"),
        payout_ratio=Decimal("0.80"),
        estimated_win_probability=None,
        decision_at=now,
    )

    first = LegacyTradeRequestAdapter.to_otc_candidate(request, **arguments)
    second = LegacyTradeRequestAdapter.to_otc_candidate(request, **arguments)

    assert first.signal_id == second.signal_id
