import asyncio
import threading
from datetime import datetime
from typing import Optional, List

from telethon import TelegramClient, events

from .data_provider import get_completed_candles
from .models import TradeSignal, TradeRequest

class TelegramInterface:
    """
    Handles all Telegram interactions, including commands and signal processing.
    """

    def __init__(self, bot):
        self.bot = bot
        self.client: Optional[TelegramClient] = None
        self.is_running = False

    async def start(self):
        """Initialize and start the Telegram client."""
        telegram_session = self.bot.config.get('telegram_session', 'otc_session')
        self.client = TelegramClient(
            telegram_session,
            self.bot.config['api_id'],
            self.bot.config['api_hash'],
            connection_retries=10,
            auto_reconnect=True
        )

        self._setup_event_handlers()
        
        await self.client.start()
        self.is_running = True
        
        me = await self.client.get_me()
        self.bot.my_telegram_id = me.id
        if self.bot.my_telegram_id not in self.bot.admin_ids:
            self.bot.admin_ids.append(self.bot.my_telegram_id)
            
        print(f"\n🎮 Telegram Interface ready. User ID: {self.bot.my_telegram_id}")

    def _setup_event_handlers(self):
        """Setup Telegram event handlers."""
        
        @self.client.on(events.NewMessage(outgoing=True))
        async def self_command_handler(event):
            message = event.message.message or ""
            if not message.startswith('/'):
                return
            parts = message[1:].split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            print(f"\n🎮 Command: /{command} {args}")
            
            # Delegate to bot's command handler
            response = await self.bot.handle_command(event, command, args)
            
            try:
                await self.client.send_message('me', response, parse_mode='md')
            except Exception:
                await self.client.send_message('me', response.replace('*', ''))

        @self.client.on(events.NewMessage(chats=self.bot.config['channel_name']))
        async def signal_handler(event):
            message = event.message.message or ""
            if not message:
                return

            if not self.bot.telegram_signals_enabled:
                return
            
            signal_keywords = ["TRADE NOW", "DIRECTION", "OTC", "BUY", "SELL", "CALL", "PUT"]
            if any(kw in message.upper() for kw in signal_keywords):
                print(f"\n📩 Trade signal detected")
                task = asyncio.create_task(self.process_signal(message))
                self.bot.scheduled_trades.append(task)

    async def send_notification(self, message: str):
        """Send notification to Saved Messages (self-bot)."""
        if not self.bot.config.get('send_notifications', True):
            return

        if self.client and self.is_running:
            try:
                await self.client.send_message('me', message, parse_mode='md')
            except Exception:
                try:
                    await self.client.send_message('me', message.replace('*', '').replace('_', ''))
                except Exception:
                    pass

    async def process_signal(self, message_text: str):
        """Process a trading signal from Telegram."""
        self.bot.signals_received += 1

        if self.bot.paused:
            self.bot.signals_skipped += 1
            print(f"   ⏸️ Signal skipped (bot paused)")
            return

        try:
            try:
                available_assets = await self.bot.api_worker.get_available_assets()
            except Exception:
                available_assets = {}
                
            signal = self.bot.signal_parser.parse(message_text, available_assets)

            if not signal:
                print("   ⚠️ Could not parse signal from message")
                return

            print(f"\n{'=' * 50}")
            print(f"🚀 NEW SIGNAL RECEIVED")
            print(f"   Asset: {signal.asset}")
            print(f"   Direction: {signal.direction.upper()}")
            print(f"   Duration: {signal.duration}M")
            print(f"{'=' * 50}")

            allowed, reason = self.bot.session_manager.check_trade_allowed()
            if not allowed:
                print(f"⛔ Trade blocked by Session Manager: {reason}")
                return

            if signal.entry_time:
                await self._schedule_trade(signal)
            else:
                await self._execute_signal(signal)

        except Exception as e:
            print(f"   ❌ Error processing signal: {e}")
            import traceback
            traceback.print_exc()

    async def _schedule_trade(self, signal: TradeSignal):
        """Schedule a trade to execute at the specified entry time."""
        now = datetime.now(self.bot.signal_parser.timezone)
        wait_seconds = (signal.entry_time - now).total_seconds()

        if wait_seconds < -90:
            print(f"   ⚠️ Entry time passed. Skipping.")
            return
        elif wait_seconds < 0:
            wait_seconds = 0
        else:
            print(f"   ⏰ Scheduled in {wait_seconds:.0f}s")

        if wait_seconds > 0:
            await asyncio.sleep(max(0, wait_seconds - 0.5))  # 0.5s lead time for API latency

        allowed, reason = self.bot.session_manager.check_trade_allowed()
        if not allowed:
            print(f"⛔ Trade blocked: {reason}")
            return

        if self.bot.paused:
            self.bot.signals_skipped += 1
            return

        await self._execute_signal(signal)

    async def _execute_signal(self, signal: TradeSignal):
        """Execute a trading signal."""
        if self.bot.dry_run:
            print(f"\n🧪 DRY RUN: Would execute {signal.asset} {signal.direction.upper()}")
            return

        print(f"\n📊 Analyzing market for {signal.asset}...")

        candles = await self.bot.api_worker.get_market_data(
            signal.asset.replace("-OTC", ""),
            timeframe=120,
            candle_count=50
        )

        indicators = None
        completed_candles = get_completed_candles(candles) if candles else []
        if completed_candles:
            indicators = self.bot.market_analyzer.calculate_indicators(completed_candles, symbol=signal.asset)
            if indicators:
                print(f"   RSI: {indicators['rsi']}, Trend: {indicators['trend']}")

        trade_request = TradeRequest(
            signal=signal,
            ai_confidence=1.0,
            reasoning="Signal execution"
        )

        await self.bot.api_worker.submit_trade(trade_request, source="telegram")

    async def disconnect(self):
        """Disconnect the Telegram client."""
        if self.client:
            await self.client.disconnect()
            self.is_running = False

    async def run_until_disconnected(self):
        """Run the client until disconnected."""
        if self.client:
            await self.client.run_until_disconnected()
