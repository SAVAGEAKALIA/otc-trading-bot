import pytest

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.interfaces.telegram_auth import OperatorRole, authorize


def test_viewers_are_read_only():
    authorize(OperatorRole.VIEWER, TradingEnvironment.TESTNET, "status")
    with pytest.raises(PermissionError): authorize(OperatorRole.VIEWER, TradingEnvironment.TESTNET, "pause")


def test_live_enable_is_never_a_telegram_action():
    with pytest.raises(PermissionError): authorize(OperatorRole.ADMIN, TradingEnvironment.LIVE, "live_enable")
