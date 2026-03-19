"""
Session and risk management.
Guards against excessive losses and enforces trading limits.
"""

from datetime import datetime
from typing import Tuple


class SessionManager:
    """
    Guards the account against session-level ruin.
    Enforces daily stop-loss, profit targets, and streak cooling.
    """

    def __init__(self, config: dict):
        self.max_daily_loss = abs(config.get('max_daily_loss', 50.0))  # e.g., $50
        self.max_consecutive_losses = config.get('max_consecutive_losses', 3)
        self.profit_target = config.get('daily_profit_target', 100.0)

        # Session State
        self.session_pnl = 0.0
        self.consecutive_losses = 0
        self.trades_taken = 0
        self.is_active = True
        self.stop_reason = ""
        self.session_start = datetime.now()

        # Notification callback (set by bot for Telegram alerts)
        self.notification_callback = None

    def set_max_daily_loss(self, amount: float):
        """Set max daily loss limit."""
        self.max_daily_loss = abs(float(amount))
        print(f"⚙️ Max Daily Loss limit set to ${self.max_daily_loss:.2f}")

    def set_max_consecutive_losses(self, count: int):
        """Set max consecutive losses limit."""
        self.max_consecutive_losses = max(1, int(count))
        print(f"⚙️ Max Consecutive Losses limit set to {self.max_consecutive_losses}")

    def set_profit_target(self, amount: float):
        """Set daily profit target."""
        self.profit_target = abs(float(amount))
        print(f"⚙️ Daily Profit Target set to ${self.profit_target:.2f}")

    def check_trade_allowed(self) -> Tuple[bool, str]:
        """Call this BEFORE submitting a trade."""
        if not self.is_active:
            return False, self.stop_reason

        if self.session_pnl <= -self.max_daily_loss:
            self._stop_session(f"Hit Max Daily Loss (-${self.max_daily_loss})")
            return False, self.stop_reason

        if self.consecutive_losses >= self.max_consecutive_losses:
            self._stop_session(f"Hit Max Consecutive Losses ({self.consecutive_losses})")
            return False, self.stop_reason

        if self.session_pnl >= self.profit_target:
            self._stop_session(f"Hit Profit Target (+${self.profit_target})")
            return False, self.stop_reason

        return True, "OK"

    def register_result(self, profit: float):
        """Call this AFTER a trade closes."""
        self.session_pnl += profit
        self.trades_taken += 1

        if profit > 0:
            self.consecutive_losses = 0
        elif profit < 0:
            self.consecutive_losses += 1

        # Log status
        print(f"   📉 Session PnL: ${self.session_pnl:.2f} | Streak: {self.consecutive_losses}L")

    def _stop_session(self, reason: str):
        self.is_active = False
        self.stop_reason = reason
        print(f"\n🛑 SESSION STOPPED: {reason}")

        # Send Telegram notification
        if self.notification_callback:
            try:
                import asyncio
                msg = (
                    f"🛑 *Session Stopped*\n\n"
                    f"Reason: {reason}\n"
                    f"PnL: ${self.session_pnl:.2f}\n"
                    f"Trades: {self.trades_taken}\n\n"
                    f"Use `/reset` to start a new session."
                )
                asyncio.create_task(self.notification_callback(msg))
            except Exception as e:
                print(f"⚠️ Could not send session stop notification: {e}")

    def reset_session(self):
        """Reset session for a new trading day."""
        self.session_pnl = 0.0
        self.consecutive_losses = 0
        self.trades_taken = 0
        self.is_active = True
        self.stop_reason = ""
        self.session_start = datetime.now()
        print("🔄 Session reset for new trading day")

    def get_session_stats(self) -> dict:
        """Get current session statistics."""
        duration = datetime.now() - self.session_start
        return {
            "pnl": self.session_pnl,
            "trades": self.trades_taken,
            "consecutive_losses": self.consecutive_losses,
            "is_active": self.is_active,
            "stop_reason": self.stop_reason,
            "duration_minutes": duration.total_seconds() / 60
        }

    def print_session_status(self):
        """Print current session status."""
        stats = self.get_session_stats()
        status = "🟢 ACTIVE" if stats['is_active'] else f"🔴 STOPPED: {stats['stop_reason']}"
        print(f"\n📊 SESSION STATUS: {status}")
        print(f"   PnL: ${stats['pnl']:.2f}")
        print(f"   Trades: {stats['trades']}")
        print(f"   Consecutive Losses: {stats['consecutive_losses']}")
        print(f"   Duration: {stats['duration_minutes']:.1f} minutes")

