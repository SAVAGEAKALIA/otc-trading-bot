from decimal import Decimal
from typing import Mapping, Any
from trading_platform.domain.money import Money

class MicroLiveRiskPolicy:
    """
    Phase 15 Micro-Live Risk Policy.
    Wraps standard risk policies with systemic micro-live safeguards.
    """
    def __init__(self, max_daily_loss_usd: Decimal = Decimal("50.00"), max_notional_usd: Decimal = Decimal("20.00")):
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_notional_usd = max_notional_usd
        self.current_daily_loss_usd = Decimal("0.00")
        self.withdrawals_enabled = False

    def check_order_intent(self, notional: Money, venue: str) -> bool:
        """
        Validates whether the order intent violates micro-live constraints.
        Returns True if safe, raises ValueError if unsafe.
        """
        if notional.currency != "USD":
            raise ValueError("Micro-live phase only permits USD base denomination.")
        
        if notional.amount > self.max_notional_usd:
            raise ValueError(f"Order notional {notional.amount} exceeds micro-live cap {self.max_notional_usd}")
            
        if self.current_daily_loss_usd >= self.max_daily_loss_usd:
            raise ValueError(f"Daily loss cap {self.max_daily_loss_usd} exceeded. Trading halted.")
            
        return True
        
    def check_withdrawal_allowed(self) -> bool:
        """
        Ensures withdrawals are fundamentally disabled during micro-live.
        """
        if not self.withdrawals_enabled:
            raise PermissionError("Withdrawals are hard-disabled in the Micro-Live phase.")
        return True
