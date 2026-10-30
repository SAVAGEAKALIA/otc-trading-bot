import pytest
from decimal import Decimal
from trading_platform.risk.micro_live_policy import MicroLiveRiskPolicy
from trading_platform.domain.money import Money

def test_micro_live_policy_allows_valid_order():
    policy = MicroLiveRiskPolicy()
    assert policy.check_order_intent(Money(Decimal("10.00"), "USD"), venue="weex") is True

def test_micro_live_policy_rejects_non_usd():
    policy = MicroLiveRiskPolicy()
    with pytest.raises(ValueError, match="only permits USD"):
        policy.check_order_intent(Money(Decimal("10.00"), "EUR"), venue="weex")

def test_micro_live_policy_rejects_excess_notional():
    policy = MicroLiveRiskPolicy(max_notional_usd=Decimal("20.00"))
    with pytest.raises(ValueError, match="exceeds micro-live cap"):
        policy.check_order_intent(Money(Decimal("50.00"), "USD"), venue="weex")

def test_micro_live_policy_rejects_withdrawals():
    policy = MicroLiveRiskPolicy()
    with pytest.raises(PermissionError, match="Withdrawals are hard-disabled"):
        policy.check_withdrawal_allowed()
