"""
Connection Management Module — Handles API connection monitoring and reconnection.

Extracted from worker.py to reduce the god object. Contains:
- Connection monitoring loop
- Reconnection with exponential backoff
- Connection state tracking
"""

import time
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .worker import APIWorker

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Monitors and maintains the IQ Option API connection."""

    def __init__(self, worker: "APIWorker"):
        self._w = worker

        # Connection state
        self.is_connected = True
        self.reconnect_lock = asyncio.Lock()
        self.last_reconnect_attempt = 0
        self.reconnect_cooldown = 5  # Minimum seconds between reconnect attempts
        self.connection_errors = 0  # Track consecutive connection errors

    def get_status(self) -> dict:
        """Get current connection status information."""
        return {
            'is_connected': self.is_connected,
            'connection_errors': self.connection_errors,
            'pending_signals': len(self._w.pending_signals),
            'active_trades': len(self._w.active_trades),
            'queue_size': self._w.trade_queue.qsize()
        }

    def check_connection(self) -> bool:
        """Check connection status and update state if disconnected."""
        try:
            if not self._w.api.check_connect():
                self.is_connected = False
                self._w.is_connected = False
                return False
            return True
        except Exception:
            self.is_connected = False
            self._w.is_connected = False
            return False

    async def maintain_connection(self):
        """Background task to ensure API connection stays alive."""
        print("🔌 Connection monitor started")
        check_interval = 5  # Check every 5 seconds initially
        max_check_interval = 30  # Max 30 seconds between checks

        while self._w.running:
            try:
                loop = asyncio.get_event_loop()

                async with self.reconnect_lock:
                    try:
                        is_connected = await loop.run_in_executor(
                            None,
                            self._w.api.check_connect
                        )
                    except Exception as e:
                        error_str = str(e).lower()
                        if 'closed' in error_str or 'connection' in error_str:
                            is_connected = False
                        else:
                            is_connected = False
                            print(f"⚠️ Connection check failed: {e}")

                    if not is_connected:
                        self.is_connected = False
                        self._w.is_connected = False
                        self.connection_errors += 1

                        # Respect cooldown between reconnection attempts
                        time_since_last = time.time() - self.last_reconnect_attempt
                        if time_since_last < self.reconnect_cooldown:
                            await asyncio.sleep(self.reconnect_cooldown - time_since_last)

                        print(f"\n⚠️ Connection lost! Attempting reconnect (attempt #{self.connection_errors})...")
                        self.last_reconnect_attempt = time.time()

                        try:
                            reconnect_result = await asyncio.wait_for(
                                loop.run_in_executor(None, self._w.api.connect),
                                timeout=30
                            )

                            if isinstance(reconnect_result, tuple):
                                reconnected = reconnect_result[0]
                            else:
                                reconnected = bool(reconnect_result)

                            if reconnected:
                                print("✅ Reconnected successfully!")
                                self.is_connected = True
                                self._w.is_connected = True
                                self.connection_errors = 0
                                check_interval = 5
                                self.reconnect_cooldown = 5

                                try:
                                    balance = await loop.run_in_executor(None, self._w.api.get_balance)
                                    print(f"   Balance: ${balance:.2f}")

                                    # Re-initialize asset cache after reconnection
                                    self._w.asset_resolver.initialize_cache()
                                except Exception:
                                    pass

                                # Process any queued signals
                                await self._w._process_pending_signals()

                                # Notify about reconnection
                                if self._w.notification_callback:
                                    try:
                                        await self._w.notification_callback(
                                            "🔌 *Reconnected to IQ Option*\nBot is now actively trading again."
                                        )
                                    except Exception:
                                        pass
                            else:
                                # Exponential backoff for failed reconnections
                                backoff = min(60, self.reconnect_cooldown * (2 ** min(self.connection_errors, 4)))
                                print(f"❌ Reconnection failed. Retrying in {backoff:.0f}s...")
                                self.reconnect_cooldown = backoff

                        except asyncio.TimeoutError:
                            print(f"⚠️ Reconnection timed out. Retrying in {self.reconnect_cooldown}s...")
                        except Exception as e:
                            print(f"⚠️ Reconnection error: {e}")

                    else:
                        # Connection is good
                        if not self.is_connected:
                            print("✅ Connection restored!")
                            self.is_connected = True
                            self._w.is_connected = True
                            self.connection_errors = 0
                            await self._w._process_pending_signals()

                        self.is_connected = True
                        self._w.is_connected = True
                        self.reconnect_cooldown = 5
                        check_interval = min(check_interval + 1, max_check_interval)

                await asyncio.sleep(check_interval)

            except Exception as e:
                error_str = str(e)
                if not any(x in error_str for x in ["'underlying'", "KeyError", "digital", "Expecting value"]):
                    print(f"⚠️ Connection monitor error: {e}")
                self.is_connected = False
                self._w.is_connected = False
                check_interval = 5
                await asyncio.sleep(5)
