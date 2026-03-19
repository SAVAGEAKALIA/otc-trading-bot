"""
Main trading bot application.
Orchestrates all components and handles Telegram integration.
"""

import asyncio
import threading
from datetime import datetime
from typing import Optional, List

from .config import DEFAULT_TIMEZONE
from .models import TradeSignal, TradeRequest
from .sizing import PositionSizer
from .analytics import MarketAnalyzer
from .ai_analyzer import AIAnalyzer
from .trade_logger import AtomicTradeLogger
from .session import SessionManager
from .parser import SignalParser
from .worker import APIWorker
from .patterns import PatternAnalyzer
from .commands import CommandHandler
from .telegram_interface import TelegramInterface

# Suppress threading errors from iqoptionapi library
import logging
logging.getLogger('iqoptionapi').setLevel(logging.CRITICAL)


def _suppress_thread_exception(args):
    """Suppress known iqoptionapi threading errors."""
    exc_str = str(args.exc_value)
    if any(x in exc_str for x in ["'underlying'", "KeyError", "digital"]):
        return
    import traceback
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

threading.excepthook = _suppress_thread_exception


class OTCTradingBot:
    """
    Main trading bot with async architecture.

    Features:
    - Telegram signal listening
    - Single API worker for thread safety
    - Fractional Kelly position sizing
    - AI-powered analysis (optional)
    - Pattern analysis (candlestick patterns)
    - Real-time trade monitoring
    - Comprehensive logging
    """

    def __init__(self, config: dict):
        self.config = config
        self.iq_api = None
        self.api_worker: Optional[APIWorker] = None
        self.market_analyzer: Optional[MarketAnalyzer] = None
        self.pattern_analyzer: Optional[PatternAnalyzer] = None
        self.ai_analyzer: Optional[AIAnalyzer] = None
        self.trade_logger: Optional[AtomicTradeLogger] = None
        self.position_sizer: Optional[PositionSizer] = None
        self.signal_parser: Optional[SignalParser] = None
        self.session_manager: Optional[SessionManager] = None
        self.scheduled_trades: List[asyncio.Task] = []
        self.is_running = False

        # Command handler (extracted module)
        self.commands = CommandHandler(self)
        
        # Telegram interface (extracted module)
        self.telegram = TelegramInterface(self)

        # Bot Control State
        self.paused = False
        self.pause_reason = ""
        self.dry_run = False
        self.started_at = datetime.now()
        self.signals_received = 0
        self.signals_skipped = 0

        # Self-bot Telegram ID
        self.my_telegram_id = None

        # Telegram Signal Toggle
        self.telegram_signals_enabled = True

        # Admin IDs
        self.admin_ids = config.get('admin_ids', [])
        self.control_chat_id = config.get('control_chat_id', None)

    def is_admin(self, user_id: int) -> bool:
        """Check if a user has administrative privileges."""
        if not user_id:
            return False
        return user_id in self.admin_ids

    def connect_iq_option(self) -> bool:
        """Connect to IQ Option API."""
        import logging

        # Suppress known iqoptionapi errors that don't affect binary trading
        logging.getLogger('iqoptionapi').setLevel(logging.CRITICAL)

        from iqoptionapi.stable_api import IQ_Option

        print("🔌 Connecting to IQ Option...")

        try:
            self.iq_api = IQ_Option(
                self.config['iq_email'],
                self.config['iq_password']
            )

            # Set timeout for connection
            check, reason = self.iq_api.connect()

            if check:
                balance = self.iq_api.get_balance()
                print(f"✅ Connected successfully!")
                print(f"   Balance: ${balance:.2f}")
                self.iq_api.change_balance(self.config['account_type'])
                print(f"   Account: {self.config['account_type']}")

                # Note: Digital option thread errors are normal and don't affect binary trading
                print(f"   ℹ️ Note: 'digital_underlying' errors are harmless (we use binary options)")

                return True
            else:
                print(f"❌ Connection Failed: {reason}")
                return False

        except Exception as e:
            print(f"❌ Connection Error: {e}")
            return False

    def initialize_components(self):
        """Initialize all bot components."""
        self.market_analyzer = MarketAnalyzer()
        self.pattern_analyzer = PatternAnalyzer()

        self.ai_analyzer = AIAnalyzer(
            self.config.get('ai_api_key', ''),
            self.config.get('ai_enabled', False),
            self.config.get('confidence_threshold', 0.7)
        )

        self.trade_logger = AtomicTradeLogger(
            self.config.get('log_file', 'trade_log.json')
        )

        self.position_sizer = PositionSizer(
            self.config.get('position_sizing', {})
        )

        self.signal_parser = SignalParser(
            self.config.get('default_duration', 2),
            self.config.get('signal_timezone', DEFAULT_TIMEZONE)
        )

        session_config = {
            'max_daily_loss': self.config.get('max_daily_loss', 50.0),
            'max_consecutive_losses': self.config.get('max_consecutive_losses', 3),
            'daily_profit_target': self.config.get('daily_profit_target', 100.0)
        }
        self.session_manager = SessionManager(session_config)
        self.session_manager.notification_callback = self.telegram.send_notification

        # Martingale configuration
        martingale_config = {
            'enabled': self.config.get('martingale_enabled', False),
            'max_steps': self.config.get('martingale_max_steps', 3),
            'multiplier': self.config.get('martingale_multiplier', 2.0),
            'duration': self.config.get('martingale_duration', 2),
        }

        self.api_worker = APIWorker(
            self.iq_api,
            self.trade_logger,
            self.position_sizer,
            self.market_analyzer,
            self.session_manager,
            notification_callback=self.telegram.send_notification,
            martingale_config=martingale_config,
            confidence_min=0.80,  # raised from 0.65 to mirror simulate_phase_19 results (54% WR target)
            config=self.config
        )

        # Configure gatekeeper and MTF settings
        self.api_worker.use_gatekeeper = self.config.get('gatekeeper_enabled', False)
        self.api_worker.gatekeeper_strict_mode = self.config.get('gatekeeper_strict_mode', True)
        self.api_worker.mtf_enabled = self.config.get('mtf_enabled', True)
        self.api_worker.mtf_15m_enabled = self.config.get('mtf_15m_enabled', False)
        self.api_worker.mtf_5m_enabled = self.config.get('mtf_5m_enabled', True)
        self.api_worker.mtf_2m_enabled = self.config.get('mtf_2m_enabled', True)

        self.api_worker.gatekeeper_telegram.set_mtf_enabled(
            enabled=self.config.get('mtf_enabled', True),
            include_5m=self.config.get('mtf_5m_enabled', True),
            include_15m=self.config.get('mtf_15m_enabled', True),
            include_2m=self.config.get('mtf_2m_enabled', True)
        )
        self.api_worker.gatekeeper_scanner.set_mtf_enabled(
            enabled=self.config.get('mtf_enabled', True),
            include_5m=self.config.get('mtf_5m_enabled', True),
            include_15m=self.config.get('mtf_15m_enabled', True),
            include_2m=self.config.get('mtf_2m_enabled', True)
        )

        # Update data provider MTF setting
        self.api_worker.data_provider.set_mtf_enabled(self.config.get('mtf_enabled', True))

        # Configure scanner settings via the OTCScanner object
        from .scanner import ScannerTradeMode, ScannerProfile

        self.api_worker.scanner.config.enabled = self.config.get('scanner_enabled', False)
        self.api_worker.scanner.config.interval = self.config.get('scanner_interval')
        self.api_worker.scanner.config.confidence_min = self.config.get('scanner_confidence_min')

        scanner_mode = self.config.get('scanner_trade_mode', 'single')
        self.api_worker.scanner.config.trade_mode = ScannerTradeMode(scanner_mode)

        # Professional filter settings
        scanner_profile = self.config.get('scanner_profile')
        self.api_worker.scanner.config.profile = ScannerProfile(scanner_profile)

        self.api_worker.scanner.config.top_n_pairs = self.config.get('scanner_top_n_pairs')
        self.api_worker.scanner.config.close_window_sec = self.config.get('scanner_close_window_sec')
        self.api_worker.scanner.config.min_confluence = self.config.get('scanner_min_confluence')
        self.api_worker.scanner.config.autostop_on_session_block = self.config.get('scanner_autostop_on_session_block')
        self.api_worker.scanner.config.wait_for_pullback = self.config.get('scanner_wait_for_pullback', False)

        # Allowed volatility (comma-separated string -> list)
        vol_str = self.config.get('scanner_allowed_volatility', 'normal,low,high,extreme')
        self.api_worker.scanner.config.allowed_volatility = [v.strip() for v in vol_str.split(',') if v.strip()]

        # Duration settings (Map default duration and dynamic toggle)
        self.api_worker.scanner.config.fixed_duration = self.config.get('default_duration', 2)
        self.api_worker.scanner.config.dynamic_timeframe = self.config.get('scanner_dynamic_timeframe', True)
        self.api_worker.scanner.config.scanner_ml_enabled = self.config.get('scanner_ml_enabled', False)
        self.api_worker.scanner.config.scanner_strategy = self.config.get('scanner_strategy', 'indicators')

    async def handle_command(self, event, command: str, args: str) -> str:
        """Delegate to CommandHandler (extracted to commands.py)."""
        return await self.commands.handle(event, command, args)

    # ==========================================
    # MAIN RUN LOOP
    # ==========================================

    async def run(self):
        """Main async run loop."""
        print("\n" + "=" * 60)
        print("🤖 OTC TRADING BOT v2.5")
        print("=" * 60)

        if not self.connect_iq_option():
            return

        self.initialize_components()

        print(f"\n⚙️ CONFIGURATION")
        print(f"   Account Type: {self.config['account_type']}")
        print(f"   Position Sizing: {self.position_sizer.get_description()}")

        await self.telegram.start()

        print(f"\n🎧 Bot listening for signals...")
        print(f"   Channel: {self.config['channel_name']}")

        self.is_running = True

        try:
            startup_msg = f"🤖 *OTC Bot Started!*\nBalance: ${self.iq_api.get_balance():.2f}"
            await self.telegram.send_notification(startup_msg)

            await asyncio.gather(
                self.api_worker.start(),
                self.telegram.run_until_disconnected()
            )

        except KeyboardInterrupt:
            print("\n🛑 Bot stopped by user")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the bot."""
        self.is_running = False

        for task in self.scheduled_trades:
            if not task.done():
                task.cancel()

        if self.api_worker:
            await self.api_worker.stop()

        await self.telegram.disconnect()

        print("\n👋 Goodbye!")

    def start(self):
        """Entry point - starts the async event loop."""
        try:
            asyncio.run(self.run())
        except KeyboardInterrupt:
            print("\n🛑 Bot stopped by user")
