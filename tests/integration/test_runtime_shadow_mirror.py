import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_platform.legacy.iqoption_bot.models import TradeRequest, TradeSignal
from trading_platform.legacy.iqoption_bot.platform_shadow import PlatformShadowMirror
from trading_platform.legacy.iqoption_bot.worker import APIWorker
from tests.calibration_fixtures import calibration_provenance


def request(probability=0.60) -> TradeRequest:
    return TradeRequest(
        signal=TradeSignal("EURUSD-OTC", "call", 2),
        ai_confidence=0.75,
        source="scanner",
        strategy_used="catboost_gate",
        calibrated_win_probability=probability,
        calibration_version="catboost-gate-v1",
        platform_decision_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_runtime_mirror_writes_approved_shadow_evidence(tmp_path) -> None:
    mirror = PlatformShadowMirror(
        f"sqlite+pysqlite:///{tmp_path / 'runtime-shadow.db'}",
        {
            "platform_shadow_max_stake": 10,
            "platform_shadow_min_payout": 0.7,
            "platform_shadow_min_expectancy": 0,
        },
    )
    try:
        mirror.repository.register_calibration_provenance(
            calibration_provenance(
                calibration_id="catboost-gate-v1",
                model_version="catboost-gate-v1",
            )
        )
        result = await mirror.mirror(
            request(),
            stake=Decimal("5"),
            payout_ratio=Decimal("0.84"),
            balance=Decimal("100"),
            active_exposure=Decimal("0"),
            open_order_count=0,
        )
        assert result.risk_decision.is_approved
        assert result.signal.model_version == "catboost-gate-v1"
        assert result.order is not None
        assert mirror.repository.signal_decision_count() == 1
        assert mirror.repository.order_count() == 1
        bound = mirror.bind_broker_order_id(result, 9001)
        assert bound.broker_order_id == "9001"
        assert mirror.bind_broker_order_id(result, 9001).broker_order_id == "9001"
    finally:
        mirror.close()


@pytest.mark.asyncio
async def test_runtime_mirror_reconciles_bound_broker_settlement(tmp_path) -> None:
    settled_at = datetime.now(UTC) + timedelta(minutes=3)

    class HistoryAPI:
        def get_position_history_v2(self, instrument_type, limit, offset, start, end):
            return True, {
                "positions": [
                    {
                        "id": [9001],
                        "win": "win",
                        "amount": 5,
                        "win_amount": 9.2,
                        "close_time": int(settled_at.timestamp()),
                    }
                ]
            }

    mirror = PlatformShadowMirror(
        f"sqlite+pysqlite:///{tmp_path / 'runtime-shadow-settlement.db'}",
        {},
        broker_api=HistoryAPI(),
    )
    try:
        mirror.repository.register_calibration_provenance(
            calibration_provenance(
                calibration_id="catboost-gate-v1",
                model_version="catboost-gate-v1",
            )
        )
        result = await mirror.mirror(
            request(),
            stake=Decimal("5"),
            payout_ratio=Decimal("0.84"),
            balance=Decimal("100"),
            active_exposure=Decimal("0"),
            open_order_count=0,
        )
        mirror.bind_broker_order_id(result, 9001)

        settlements = await mirror.reconcile_settlements(
            settled_at
        )

        assert len(settlements) == 1
        assert settlements[0].broker_order_id == "9001"
        assert mirror.repository.binary_settlement_count() == 1
    finally:
        mirror.close()


@pytest.mark.asyncio
async def test_runtime_mirror_records_missing_calibration_without_order(tmp_path) -> None:
    mirror = PlatformShadowMirror(
        f"sqlite+pysqlite:///{tmp_path / 'runtime-shadow.db'}", {}
    )
    try:
        result = await mirror.mirror(
            request(None),
            stake=Decimal("5"),
            payout_ratio=Decimal("0.84"),
            balance=Decimal("100"),
            active_exposure=Decimal("0"),
            open_order_count=0,
        )
        assert not result.risk_decision.is_approved
        assert result.order is None
        assert mirror.repository.signal_decision_count() == 1
    finally:
        mirror.close()


@pytest.mark.asyncio
async def test_runtime_mirror_rejects_request_delayed_in_legacy_queue(tmp_path) -> None:
    delayed = request()
    delayed.platform_decision_at = datetime.now(UTC) - timedelta(minutes=2)
    mirror = PlatformShadowMirror(
        f"sqlite+pysqlite:///{tmp_path / 'runtime-shadow.db'}", {}
    )
    try:
        result = await mirror.mirror(
            delayed,
            stake=Decimal("5"),
            payout_ratio=Decimal("0.84"),
            balance=Decimal("100"),
            active_exposure=Decimal("0"),
            open_order_count=0,
        )
        assert "signal is stale" in result.risk_decision.reasons
        assert result.order is None
    finally:
        mirror.close()


@pytest.mark.asyncio
async def test_worker_shadow_failure_cannot_propagate_to_legacy_path(caplog) -> None:
    class BrokenMirror:
        async def mirror(self, *args, **kwargs):
            raise RuntimeError("shadow database offline")

    worker = APIWorker.__new__(APIWorker)
    worker.platform_shadow_mirror = BrokenMirror()
    worker._platform_shadow_tasks = set()
    worker.active_trades = {}

    worker._schedule_platform_shadow(
        request(), amount=5.0, payout_rate=0.84, balance=100.0
    )
    await asyncio.gather(*tuple(worker._platform_shadow_tasks), return_exceptions=True)
    await asyncio.sleep(0)

    assert "legacy path unchanged" in caplog.text


@pytest.mark.asyncio
async def test_worker_binds_broker_id_after_shadow_order_is_ready() -> None:
    result = type("Result", (), {"order": object()})()

    class Mirror:
        def __init__(self):
            self.bound = []

        def bind_broker_order_id(self, shadow_result, broker_order_id):
            self.bound.append((shadow_result, broker_order_id))

    worker = APIWorker.__new__(APIWorker)
    worker.platform_shadow_mirror = Mirror()
    worker._platform_shadow_tasks = set()
    shadow_task = asyncio.create_task(asyncio.sleep(0, result=result))

    worker._schedule_platform_shadow_binding(shadow_task, 9001)
    await asyncio.gather(*tuple(worker._platform_shadow_tasks))

    assert worker.platform_shadow_mirror.bound == [(result, 9001)]
