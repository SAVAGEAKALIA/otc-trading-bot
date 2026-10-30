from datetime import UTC, datetime, timedelta

import pytest

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.interfaces.telegram_auth import OperatorRole
from trading_platform.interfaces.telegram_console import (
    CallbackTokenCodec,
    InMemoryAuditSink,
    TelegramOperatorConsole,
)


class Application:
    def __init__(self):
        self.calls = []

    async def execute_operator_action(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True}


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_console(*, lifetime=timedelta(minutes=2)):
    application = Application()
    audit = InMemoryAuditSink()
    clock = lambda: NOW
    codec = CallbackTokenCodec("test-secret", lifetime=lifetime, now=clock)
    return TelegramOperatorConsole(application, codec, audit, now=clock), application, audit, codec


@pytest.mark.asyncio
async def test_operator_callback_dispatches_through_application_and_audits():
    console, application, audit, codec = make_console()
    token = codec.issue(
        user_id="42", action="pause", parameters={"reason": "operator"}
    )
    assert len(token.encode("utf-8")) <= 64

    result = await console.handle_callback(
        user_id="42",
        role=OperatorRole.OPERATOR,
        environment=TradingEnvironment.TESTNET,
        token=token,
    )

    assert result == {"ok": True}
    assert application.calls[0]["action"] == "pause"
    assert audit.events[-1].outcome == "accepted"


@pytest.mark.asyncio
async def test_callback_is_bound_to_user_and_one_time():
    console, _, audit, codec = make_console()
    token = codec.issue(user_id="42", action="reconcile")

    with pytest.raises(PermissionError, match="another user"):
        await console.handle_callback(
            user_id="99", role=OperatorRole.OPERATOR,
            environment=TradingEnvironment.TESTNET, token=token,
        )
    await console.handle_callback(
        user_id="42", role=OperatorRole.OPERATOR,
        environment=TradingEnvironment.TESTNET, token=token,
    )
    with pytest.raises(RuntimeError, match="consumed"):
        await console.handle_callback(
            user_id="42", role=OperatorRole.OPERATOR,
            environment=TradingEnvironment.TESTNET, token=token,
        )
    assert any(event.outcome == "replayed" for event in audit.events)


@pytest.mark.asyncio
async def test_viewer_cannot_cancel_or_reduce_and_no_application_call_occurs():
    console, application, audit, codec = make_console()
    token = codec.issue(user_id="42", action="reduce_only")

    with pytest.raises(PermissionError):
        await console.handle_callback(
            user_id="42", role=OperatorRole.VIEWER,
            environment=TradingEnvironment.TESTNET, token=token,
        )

    assert application.calls == []
    assert audit.events[-1].outcome == "denied"


@pytest.mark.asyncio
async def test_expired_callback_is_rejected():
    current = [NOW]
    application = Application()
    audit = InMemoryAuditSink()
    codec = CallbackTokenCodec(
        "test-secret", lifetime=timedelta(seconds=1), now=lambda: current[0]
    )
    console = TelegramOperatorConsole(application, codec, audit, now=lambda: current[0])
    token = codec.issue(user_id="42", action="pause")
    current[0] += timedelta(seconds=2)

    with pytest.raises(TimeoutError, match="expired"):
        await console.handle_callback(
            user_id="42", role=OperatorRole.OPERATOR,
            environment=TradingEnvironment.TESTNET, token=token,
        )

    assert application.calls == []
    assert audit.events[-1].outcome == "expired"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["live_enable", "set_leverage", "set_risk", "arbitrary_order"])
async def test_forbidden_actions_are_denied_even_for_admin(action):
    console, application, _, codec = make_console()
    token = codec.issue(user_id="42", action=action)
    with pytest.raises(PermissionError, match="never authorized"):
        await console.handle_callback(
            user_id="42", role=OperatorRole.ADMIN,
            environment=TradingEnvironment.TESTNET, token=token,
        )
    assert application.calls == []
