"""
Martingale Strategy Module — Handles loss recovery via progressive betting.

Extracted from worker.py to reduce the god object. Contains:
- Series tracking and creation
- Loss handling and next-step scheduling
- Series finalization
"""

import asyncio
import uuid
import logging
from typing import Optional, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .worker import APIWorker

logger = logging.getLogger(__name__)


class MartingaleManager:
    """Manages martingale recovery series for the trading bot."""

    def __init__(self, worker: "APIWorker", config: Optional[Dict] = None):
        self._w = worker
        config = config or {}
        self.enabled = config.get('enabled', False)
        self.max_steps = config.get('max_steps', 3)
        self.multiplier = config.get('multiplier', 2.0)
        self.duration = config.get('duration', 2)

        # Track active series (series_id -> cumulative_loss)
        self.active_series: Dict[str, dict] = {}

    def set_enabled(self, enabled: bool):
        """Toggle martingale strategy on/off."""
        self.enabled = enabled
        print(f"🔁 Martingale {'enabled' if enabled else 'disabled'}")

    def set_max_steps(self, steps: int):
        """Set maximum martingale steps (1-10)."""
        self.max_steps = max(1, min(10, int(steps)))
        print(f"🔁 Martingale max steps set to {self.max_steps}")

    def set_multiplier(self, multiplier: float):
        """Set martingale multiplier (1.0-5.0)."""
        self.multiplier = max(1.0, min(5.0, float(multiplier)))
        print(f"🔁 Martingale multiplier set to {self.multiplier}x")

    def set_duration(self, duration: int):
        """Set fixed duration for martingale trades (1-15 min)."""
        self.duration = max(1, min(15, int(duration)))
        print(f"🔁 Martingale duration set to {self.duration}M")

    def get_status(self) -> dict:
        """Get current martingale status and configuration."""
        return {
            'enabled': self.enabled,
            'max_steps': self.max_steps,
            'multiplier': self.multiplier,
            'duration': self.duration,
            'active_series': len(self.active_series)
        }

    @staticmethod
    def generate_series_id() -> str:
        """Generate a unique ID for a martingale series."""
        return str(uuid.uuid4())[:8]

    async def handle_loss(self, trade_info: dict, series_id: Optional[str], notification_msg: str):
        """
        Handle a trade loss for martingale strategy.

        - If martingale disabled: do nothing
        - If at max steps: finalize series as lost
        - Otherwise: schedule next martingale step
        """
        if not self.enabled:
            return

        current_step = trade_info.get('martingale_step', 0)
        amount = trade_info['amount']
        # Extract source from trade info (default to telegram if missing)
        source = trade_info.get('source', 'telegram')

        # Create or update series tracking
        if not series_id:
            series_id = self.generate_series_id()
            self.active_series[series_id] = {
                'base_amount': amount,
                'cumulative_loss': amount,
                'step': current_step,
                'asset': trade_info['asset'],
                'direction': trade_info['direction'],
                'source': source,  # Store source correctly
                'strategy_used': trade_info.get('strategy_used', ''),
            }
        else:
            if series_id in self.active_series:
                self.active_series[series_id]['cumulative_loss'] += amount
                self.active_series[series_id]['step'] = current_step
                # Ensure source is preserved if missing (should be there from creation)
                if 'source' not in self.active_series[series_id]:
                     self.active_series[series_id]['source'] = source
                if 'strategy_used' not in self.active_series[series_id]:
                     self.active_series[series_id]['strategy_used'] = trade_info.get('strategy_used', '')

        # Check if we can do another step
        next_step = current_step + 1
        if next_step > self.max_steps:
            # Max steps reached - series lost
            print(f"   🔁 Martingale max steps ({self.max_steps}) reached - series ended")
            cumulative_loss = self.active_series.get(series_id, {}).get('cumulative_loss', amount)

            # Register the total series loss with session manager
            if self._w.session_manager:
                self._w.session_manager.register_result(-amount)

            if self._w.notification_callback:
                try:
                    msg = f"🔁 *Martingale Series Ended*\n\nMax steps reached ({self.max_steps})\nTotal Loss: -${cumulative_loss:.2f}"
                    await self._w.notification_callback(msg)
                except Exception:
                    pass

            self.finalize_series(series_id, "max_steps")
            return

        # Check session manager before scheduling next step
        if self._w.session_manager:
            # Register THIS step's loss now (before next step)
            self._w.session_manager.register_result(-amount)

            allowed, reason = self._w.session_manager.check_trade_allowed()
            if not allowed:
                print(f"   ⛔ Martingale step {next_step} blocked: {reason}")
                self.finalize_series(series_id, f"blocked: {reason}")
                return

        # Schedule next martingale step
        next_amount = amount * self.multiplier
        await self._schedule_trade(trade_info, series_id, next_step, next_amount)

    async def _schedule_trade(self, trade_info: dict, series_id: str, step: int, amount: float):
        """
        Schedule the next martingale recovery trade.
        """
        from .models import TradeSignal, TradeRequest

        print(f"\n🔁 SCHEDULING MARTINGALE STEP {step}/{self.max_steps}")
        print(f"   Asset: {trade_info['asset']} {trade_info['direction'].upper()}")
        print(f"   Amount: ${amount:.2f} ({self.multiplier}x previous)")
        print(f"   Duration: {self.duration}M (fixed)")
        
        # Retrieve source from active series (truth)
        series_data = self.active_series.get(series_id, {})
        source = series_data.get('source', 'telegram')
        strategy_used = series_data.get('strategy_used', '')

        signal = TradeSignal(
            asset=trade_info['asset'],
            direction=trade_info['direction'],
            duration=self.duration,
            entry_time=None  # Execute immediately
        )

        request = TradeRequest(
            signal=signal,
            ai_confidence=1.0,
            reasoning=f"Martingale step {step}/{self.max_steps}",
            martingale_step=step,
            score=trade_info.get('score', 0.0),
            martingale_amount=amount,
            martingale_series_id=series_id,
            source=source,  # Propagate source to worker
            strategy_used=strategy_used # Propagate underlying strategy
        )

        # Small delay before martingale trade
        await asyncio.sleep(2)

        # Submit to trade queue via submit_trade to trigger Smart Reanalysis
        await self._w.submit_trade(request, source="martingale")
        print(f"   ✅ Martingale trade submitted")

        # Send notification
        if self._w.notification_callback:
            try:
                cumulative = self.active_series.get(series_id, {}).get('cumulative_loss', 0)
                msg = f"🔁 *Martingale Step {step}*\n\nAsset: {trade_info['asset']}\nDirection: {trade_info['direction'].upper()}\nAmount: ${amount:.2f}\nDuration: {self.duration}M\n\nRecovering: ${cumulative:.2f} loss"
                await self._w.notification_callback(msg)
            except Exception:
                pass

    def finalize_series(self, series_id: str, reason: str):
        """
        Clean up a martingale series after it ends.
        """
        if series_id in self.active_series:
            series_data = self.active_series.pop(series_id)
            print(f"   🔁 Martingale series {series_id} finalized: {reason}")
            print(f"      Steps taken: {series_data.get('step', 0) + 1}")
            print(f"      Cumulative loss: ${series_data.get('cumulative_loss', 0):.2f}")
