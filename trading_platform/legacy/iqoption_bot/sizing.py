"""
Position sizing strategies.
Supports fixed amount, fixed percentage, fractional Kelly criterion,
and anti-martingale (increase after wins).
"""

from .models import SizingMethod
from .config import DEFAULT_PAYOUT


class PositionSizer:
    """
    Handles position sizing using various methods:
    - Fixed Amount: Always trade the same dollar amount
    - Fixed Percentage: Trade X% of current balance
    - Fractional Kelly: Use Kelly Criterion with a safety fraction
    - Anti-Martingale: Increase size after consecutive wins, reset after loss
    """

    def __init__(self, config: dict):
        raw_method = config.get('method', 'fixed').strip().lower()

        # Safe Enum casting, fallback to FIXED_AMOUNT if user config is invalid
        try:
            self.method = SizingMethod(raw_method)
        except ValueError:
            # Map shorthand 'fixed' to fixed_amount
            if raw_method == 'fixed':
                self.method = SizingMethod.FIXED_AMOUNT
            elif raw_method == 'percent':
                self.method = SizingMethod.FIXED_PERCENTAGE
            elif raw_method == 'kelly':
                self.method = SizingMethod.FRACTIONAL_KELLY
            else:
                self.method = SizingMethod.FIXED_AMOUNT

        self.fixed_amount = config.get('fixed_amount', 1.0)
        self.fixed_percentage = config.get('fixed_percentage', 0.01)  # 1%
        self.kelly_fraction = config.get('kelly_fraction', 0.25)  # 1/4 Kelly
        self.min_trade = config.get('min_trade', 1.0)
        self.max_trade = config.get('max_trade', 50.0)
        self.max_risk_percentage = config.get('max_risk_percentage', 0.02)  # Hard 2% cap

        # Anti-martingale state
        self._consecutive_wins = 0
        self._anti_mg_multiplier = config.get('anti_martingale_multiplier', 1.5)
        self._anti_mg_max_streak = config.get('anti_martingale_max_streak', 3)

    def calculate_size(self, balance: float, win_rate: float = 0.55,
                       payout: float = DEFAULT_PAYOUT,
                       strategy_win_rate: float = None) -> float:
        """
        Calculate position size based on configured method.

        Args:
            balance: Current account balance
            win_rate: Global historical win rate (0.0-1.0)
            payout: Broker payout rate (e.g., 0.80 = 80%)
            strategy_win_rate: Per-strategy win rate (used for Kelly if provided)

        Returns:
            Trade amount in dollars
        """
        # Use per-strategy win rate for Kelly if available
        effective_win_rate = strategy_win_rate if strategy_win_rate is not None else win_rate

        if self.method == SizingMethod.FIXED_AMOUNT:
            size = self.fixed_amount

        elif self.method == SizingMethod.FIXED_PERCENTAGE:
            size = balance * self.fixed_percentage

        elif self.method == SizingMethod.FRACTIONAL_KELLY:
            size = self._calculate_kelly(balance, effective_win_rate, payout)

        else:
            size = self.fixed_amount

        # A non-positive Kelly edge is an explicit no-trade decision, not a
        # value to be promoted to the broker minimum by the clamps below.
        if size <= 0:
            return 0.0

        # Apply constraints
        # 1. Ensure size is within [min_trade, max_trade]
        size = max(self.min_trade, size)
        size = min(self.max_trade, size)

        # 2. Apply hard 2% risk cap
        risk_limit = balance * self.max_risk_percentage
        if size > risk_limit:
            if risk_limit < self.min_trade:
                # SPECIAL EXCEPTION: If using FIXED_AMOUNT, we allow bypassing the risk limit
                # to meet the minimum trade size, provided the balance can actually cover it.
                if self.method == SizingMethod.FIXED_AMOUNT and balance >= self.fixed_amount:
                    size = self.fixed_amount
                else:
                    return 0.0
            else:
                size = risk_limit

        return round(float(size), 2)

    def _calculate_kelly(self, balance: float, win_rate: float,
                         payout: float) -> float:
        """
        Calculate Kelly Criterion position size.

        Kelly Formula: f* = (bp - q) / b
        Where:
            f* = fraction of bankroll to bet
            b = payout odds (e.g., 0.80)
            p = probability of winning
            q = probability of losing (1 - p)

        Fractional Kelly = f* × kelly_fraction

        A negative Kelly value means the estimated edge is negative.  In that
        case sizing returns zero so the execution layer can reject the trade.
        """
        p = win_rate
        q = 1 - p
        b = payout

        # Full Kelly
        if b <= 0:
            return 0.0

        kelly = (b * p - q) / b

        # If Kelly is negative, the estimated edge is negative — do not trade.
        if kelly <= 0:
            return 0.0

        # Apply fraction (e.g., 1/4 Kelly)
        fractional_kelly = kelly * self.kelly_fraction

        # Calculate dollar amount
        size = balance * fractional_kelly

        return size

    def record_outcome(self, result: str):
        """
        Track outcomes for anti-martingale sizing.

        Args:
            result: 'win', 'loss', or 'tie'
        """
        if result == 'win':
            self._consecutive_wins = min(self._consecutive_wins + 1, self._anti_mg_max_streak)
        elif result == 'loss':
            self._consecutive_wins = 0
        # ties don't change the streak

    def get_anti_martingale_multiplier(self) -> float:
        """
        Return the current anti-martingale size multiplier.
        Increases position after consecutive wins, resets after any loss.

        Multiplier chain:  1.0 → 1.5 → 2.25 → 3.375 (at max streak 3)
        """
        if self._consecutive_wins == 0:
            return 1.0
        return self._anti_mg_multiplier ** self._consecutive_wins

    def get_description(self) -> str:
        """Get human-readable description of sizing method."""
        if self.method == SizingMethod.FIXED_AMOUNT:
            return f"Fixed ${self.fixed_amount:.2f}"
        elif self.method == SizingMethod.FIXED_PERCENTAGE:
            return f"Fixed {self.fixed_percentage*100:.1f}% of balance"
        elif self.method == SizingMethod.FRACTIONAL_KELLY:
            fraction_name = {0.5: "½", 0.25: "¼", 0.125: "⅛"}.get(
                self.kelly_fraction, f"{self.kelly_fraction}"
            )
            return f"{fraction_name} Kelly Criterion (2% cap)"
        return "Unknown"
