"""
IQ Option API worker.
Single-threaded worker that handles all IQ Option API calls safely.

Refactored: Result checking, martingale, connection, and asset resolution
have been extracted into focused modules. This file contains the core
trade orchestration logic.
"""

import time
import asyncio
import logging
import uuid
from typing import Optional, Dict, Any, Tuple, List

# Suppress known iqoptionapi errors
logging.getLogger('iqoptionapi').setLevel(logging.CRITICAL)

from .models import TradeRequest, TradeSignal
from .config import DEFAULT_PAYOUT
from .trade_logger import TradeLogger
from .sizing import PositionSizer
from .analytics import MarketAnalyzer, SignalGatekeeper
from .session import SessionManager
from .patterns import PatternAnalyzer
from .data_provider import MarketDataProvider, MTFBundle
from .scanner import OTCScanner, ScannerSignal, ScannerConfig, ScannerTradeMode
from .result_checker import ResultChecker
from .martingale import MartingaleManager
from .connection import ConnectionManager
from .asset_resolver import AssetResolver
from .trade_queue import PriorityTradeQueue
from .confidence_tracker import ConfidenceTracker


class APIWorker:
    """Single worker that handles all IQ Option API calls."""

    def __init__(self, iq_api, trade_logger: TradeLogger,
                 position_sizer: PositionSizer, market_analyzer: MarketAnalyzer,
                 session_manager: Optional[SessionManager] = None,
                 notification_callback=None,
                 martingale_config: Optional[Dict] = None,
                 confidence_min: float = 0.80, # NEW: Match simulation results
                 config: Optional[Dict] = None):  # NEW: Accept main config
        self.api = iq_api
        self.logger = trade_logger
        self.sizer = position_sizer
        self.analyzer = market_analyzer
        self.session_manager = session_manager
        self.notification_callback = notification_callback
        self.trade_queue: PriorityTradeQueue = PriorityTradeQueue()
        self.pending_execution_count = 0  # Fix race condition in single-mode
        self.submission_lock = asyncio.Lock()  # Atomic lock for submitting trades
        self.active_trades: Dict[int, dict] = {}
        self.running = False
        self.payout_rate = DEFAULT_PAYOUT
        
        # Store main config (fallback to empty dict if None)
        self.config = config or {}

        # --- Extracted modules ---
        self.martingale = MartingaleManager(self, martingale_config)
        self.asset_resolver = AssetResolver(self)
        self.result_checker = ResultChecker(self)
        self.connection_mgr = ConnectionManager(self)

        # Convenience aliases (backward compat for direct access)
        self.martingale_enabled = self.martingale.enabled
        self.martingale_max_steps = 0
        
        # Session PnL tracking for result verification
        self.cumulative_pnl = 0.0
        self.martingale_multiplier = self.martingale.multiplier
        self.martingale_duration = self.martingale.duration
        self.active_martingale_series = self.martingale.active_series

        # Signal filtering components
        # CRITICAL: Use centralized config as source of truth
        self.gatekeeper_mode_telegram = self.config.get("gatekeeper_mode_telegram", "relaxed")
        self.gatekeeper_mode_scanner = self.config.get("gatekeeper_mode_scanner", "normal")
        
        # Gatekeepers initialization moved down to include ML db
        


        self.confidence_tracker = ConfidenceTracker()
        self.pattern_analyzer = PatternAnalyzer()
        
        # REMOVED: Redundant hardcoded overrides that caused issues
        # self.gatekeeper_mode_telegram = 'relaxed'
        # self.gatekeeper_mode_scanner = 'very_relaxed'

        # Market data provider for centralized candle fetching (OTC only)
        self.data_provider = MarketDataProvider(
            iq_api,
            mtf_enabled=True,
            connection_checker=self.connection_mgr.check_connection
        )

        # Initialize Phase 3 Fingerprint Database
        from .fingerprint import RollingMemoryDB
        self.fingerprint_db = RollingMemoryDB()
        
        self.ml_enabled = self.config.get("ml_enabled", False) if self.config else False
        
        self.gatekeeper_telegram = SignalGatekeeper(
            mode=self.gatekeeper_mode_telegram,
            ml_enabled=self.ml_enabled,
            fingerprint_db=self.fingerprint_db
        )
        self.gatekeeper_scanner = SignalGatekeeper(
            mode=self.gatekeeper_mode_scanner,
            ml_enabled=self.ml_enabled,
            fingerprint_db=self.fingerprint_db
        )

        # Config for gatekeeper (can be overridden)
        self.use_gatekeeper = False
        self.gatekeeper_strict_mode = True
        self.martingale_gatekeeper_enabled = False  # NEW: Default to bypassing gatekeeper for martingale steps
        # Force default to avoid configuration bleed
        if martingale_config and martingale_config.get('gatekeeper_enabled'):
             self.martingale_gatekeeper_enabled = True

        # Phase 10: Dedicated Martingale Gatekeeper for Classic Recovery
        # Uses very_relaxed mode since recovery is already committed
        self.martingale_gatekeeper = SignalGatekeeper(mode="very_relaxed")

        # MTF (Multi-Timeframe) config
        self.mtf_enabled = True
        self.mtf_2m_enabled = True
        self.mtf_5m_enabled = True
        self.mtf_15m_enabled = True

        # OTC Scanner
        self.scanner = OTCScanner(
            api=iq_api,
            data_provider=self.data_provider,
            analyzer=market_analyzer,
            pattern_analyzer=self.pattern_analyzer,
            gatekeeper=self.gatekeeper_scanner,  # Use dedicated scanner gatekeeper
        )
        # Assign the worker's fingerprint db to the scanner
        self.scanner.fingerprint_db = self.fingerprint_db

        # Inject Martingale strategy context into the scanner (for delayed pullback logic)
        if hasattr(self, 'martingale'):
            self.scanner.active_martingale_series = self.martingale.active_series
            self.scanner.martingale_enabled = getattr(self.martingale, 'enabled', False)
            self.scanner.martingale_max_steps = getattr(self.martingale, 'max_steps', 3)
            self.scanner.martingale_multiplier = getattr(self.martingale, 'multiplier', 2.0)
        
        self.scanner.martingale_wait_for_pullback = self.config.get('martingale_wait_for_pullback', False) if self.config else False
        
        # Apply the confidence threshold from bot.py
        self.scanner.set_confidence(confidence_min)
        
        # Phase 11: Reanalyzer deprecated, removed initialization
        
        self.scanner.on_signal = self._handle_scanner_signal
        self.scanner.can_trade_callback = self.can_place_trade
        self.scanner.is_connected_callback = lambda: self.is_connected
        self.scanner.get_otc_pairs_callback = self.get_cached_otc_pairs

        # Connection state (synced by ConnectionManager)
        self.is_connected = True
        self.pending_signals: list = []

        # Balance tracking for multi-trade result checking
        self.last_known_balance = 0.0
        self.balance_check_lock = asyncio.Lock()

        # Scanner auto-stop state
        self.scanner_autostop_notified = False

        # Initialize asset cache via extracted module
        self.asset_resolver.initialize_cache()

    def _initialize_asset_cache(self):
        """Delegate to AssetResolver."""
        self.asset_resolver.initialize_cache()

    def get_cached_otc_pairs(self) -> List[str]:
        """Delegate to AssetResolver."""
        return self.asset_resolver.get_cached_otc_pairs()

    def set_session_limits(self, key: str, value: float):
        """Delegate session limit updates."""
        if not self.session_manager:
            return

        if key == 'max_loss':
            self.session_manager.set_max_daily_loss(value)
        elif key == 'max_streak':
            self.session_manager.set_max_consecutive_losses(int(value))
        elif key == 'profit_target':
            self.session_manager.set_profit_target(value)

    # ==========================================
    # MARTINGALE CONTROL METHODS
    # ==========================================

    def set_martingale_enabled(self, enabled: bool):
        """Delegate to MartingaleManager."""
        self.martingale.set_enabled(enabled)
        self.martingale_enabled = enabled

    def set_martingale_params(self, key: str, value: float):
        """Delegate parameter updates to MartingaleManager."""
        if key == 'steps':
            self.martingale.set_max_steps(int(value))
        elif key == 'multiplier':
            self.martingale.set_multiplier(float(value))
        elif key == 'duration':
            self.martingale.set_duration(int(value))

    def get_martingale_status(self) -> dict:
        """Delegate to MartingaleManager."""
        return self.martingale.get_status()

    def _generate_series_id(self) -> str:
        """Delegate to MartingaleManager."""
        return self.martingale.generate_series_id()

    def _get_asset_id(self, asset_name: str) -> Optional[int]:
        """Delegate to AssetResolver."""
        return self.asset_resolver.get_asset_id(asset_name)

    async def start(self):
        """Start the API worker with delegated module loops."""
        self.running = True
        tasks = [
            self._process_trades(),
            self.result_checker.check_results_loop(),
            self.connection_mgr.maintain_connection(),
            self._idle_telemetry_loop()
        ]
        if self.scanner.config.enabled:
            tasks.append(self.scanner.start())
        await asyncio.gather(*tasks)

    async def stop(self):
        """Stop the API worker."""
        self.running = False
        await self.scanner.stop()

    async def _idle_telemetry_loop(self):
        """Send a heartbeat notification every 30 minutes including market health."""
        while self.running:
            await asyncio.sleep(1800)  # 30 minutes
            if not self.running:
                break
                
            # Check components
            is_scanning = self.scanner.config.enabled and getattr(self.scanner, 'running', False)
            trade_allowed, reason = self.session_manager.check_trade_allowed() if self.session_manager else (True, "Active")
            stale_pct = getattr(self.scanner, 'stagnation_percent', 0.0)
            
            # Format time for heartbeat
            try:
                import pytz
                from datetime import datetime
                tz_name = self.config.get('signal_timezone', 'Africa/Lagos') if self.config else 'Africa/Lagos'
                tz = pytz.timezone(tz_name)
                now_str = datetime.now(tz).strftime('%I:%M %p')
            except ImportError:
                from datetime import datetime
                now_str = datetime.now().strftime('%I:%M %p')
                
            # Build message
            status_msg = (
                f"📡 *Heartbeat Update ({now_str})*\n\n"
                f"Scanner: `{'ON' if is_scanning else 'OFF'}`\n"
                f"Session: `{'Active' if trade_allowed else 'Blocked'}`\n"
                f"Health: `{stale_pct:.0f}% Stagnant`\n"
                f"Status: `{reason}`"
            )
            
            # Add alert if market is notably stale
            if stale_pct > 30:
                status_msg += "\n\n⚠️ *Stale Market Warning*: High density of flat OTC pairs detected."

            if self.notification_callback:
                try:
                    asyncio.create_task(self.notification_callback(status_msg))
                except Exception:
                    pass

    # ==========================================
    # GATEKEEPER CONTROL METHODS
    # ==========================================

    def set_gatekeeper_mode_telegram(self, mode: str):
        """Set gatekeeper mode for Telegram signals."""
        valid_modes = ['strict', 'normal', 'relaxed', 'very_relaxed']
        if mode in valid_modes:
            self.gatekeeper_mode_telegram = mode
            self.gatekeeper_telegram.set_mode(mode)
            print(f"🔍 Gatekeeper mode (Telegram): {mode.upper()}")
        else:
            print(f"⚠️ Invalid gatekeeper mode: {mode}")

    def set_gatekeeper_mode_scanner(self, mode: str):
        """Set gatekeeper mode for Scanner signals."""
        valid_modes = ['strict', 'normal', 'relaxed', 'very_relaxed']
        if mode in valid_modes:
            self.gatekeeper_mode_scanner = mode
            self.gatekeeper_scanner.set_mode(mode)
            print(f"🔍 Gatekeeper mode (Scanner): {mode.upper()}")
        else:
            print(f"⚠️ Invalid gatekeeper mode: {mode}")

    def get_gatekeeper_status(self) -> Dict[str, Any]:
        """Get gatekeeper status for both signal sources."""
        settings = self.gatekeeper_telegram.get_current_settings()
        stats = self.gatekeeper_telegram.get_stats()
        return {
            'enabled': self.use_gatekeeper,
            'mode_telegram': self.gatekeeper_mode_telegram,
            'mode_scanner': self.gatekeeper_mode_scanner,
            'martingale_gatekeeper': self.martingale_gatekeeper_enabled,
            'mtf_enabled': self.mtf_enabled,
            'mtf_2m_enabled': self.mtf_2m_enabled,
            'mtf_5m_enabled': self.mtf_5m_enabled,
            'mtf_15m_enabled': self.mtf_15m_enabled,
            'min_confluence': settings.get('min_confluence', 2),
            'loss_streak_cooldown': settings.get('loss_streak_cooldown', 5),
            'stats': stats,
        }

    # ==========================================
    # SCANNER CONTROL METHODS (delegate to OTCScanner)
    # ==========================================

    def set_scanner_enabled(self, enabled: bool):
        """Enable or disable the OTC scanner."""
        self.scanner.set_enabled(enabled)
        if enabled and self.running and not self.scanner.running:
            # Start scanner loop if worker is already running
            asyncio.create_task(self.scanner.start())

    def set_scanner_interval(self, seconds: int):
        """Set scanner interval in seconds (min 30s)."""
        self.scanner.set_interval(seconds)

    def set_scanner_trade_mode(self, mode: str):
        """Set scanner trade mode: 'single' or 'multi'."""
        self.scanner.set_trade_mode(mode)

    def set_scanner_confidence(self, confidence: float):
        """Set minimum confidence threshold (0.0-1.0)."""
        self.scanner.set_confidence(confidence)

    def set_scanner_ml(self, enabled: bool):
        """Enable or disable the ML Probability Engine."""
        self.scanner.set_ml_enabled(enabled)

    def set_scanner_adaptive(self, enabled: bool):
        """Enable or disable Volatility-Adaptive Thresholding."""
        self.scanner.set_adaptive_enabled(enabled)

    def get_scanner_status(self) -> Dict[str, Any]:
        """Get scanner status information."""
        status = self.scanner.get_status()
        status['active_trades'] = len(self.active_trades)
        return status

    def can_place_trade(self, from_scanner: bool = True) -> Tuple[bool, str]:
        """
        Check if a new trade can be placed based on scanner trade mode.

        Returns (allowed, reason) tuple.

        Rules:
        - Session Manager blocked: always block + auto-disable scanner
        - Scanner OFF: always allow (Telegram signals work normally)
        - Telegram signals bypass scanner's single-trade restriction
        - Single Mode: blocks if active trades or pending signals exist
        """
        if not self.is_connected:
            return False, "Not connected to API"

        # Check session limits
        if self.session_manager:
            allowed, reason = self.session_manager.check_trade_allowed()
            if not allowed:
                # Auto-stop scanner if configured
                if self.scanner.config.enabled and self.scanner.config.autostop_on_session_block:
                    self._auto_stop_scanner(reason)
                return False, reason

        if not self.scanner.config.enabled:
            # Scanner is OFF - Telegram signals work normally
            self.scanner_autostop_notified = False  # Reset for next time scanner is enabled
            return True, "Scanner off - normal mode"

        # Telegram signals bypass scanner's single-trade restriction
        if not from_scanner:
            return True, "Telegram signal - bypasses single-trade mode"

        if self.scanner.config.trade_mode == ScannerTradeMode.MULTI:
            return True, "Multi-trade mode"

        # Single trade mode - check for active trades OR queued trades (scanner only)
        if self.active_trades:
            return False, f"Single-trade mode: {len(self.active_trades)} trade(s) active"

        # Fix race condition: Check if there are pending trades in the queue that haven't become active yet
        # We check BOTH the queue size AND the explicit reservation counter
        if not self.trade_queue.empty():
             return False, f"Single-trade mode: {self.trade_queue.qsize()} trade(s) pending execution"
             
        if self.pending_execution_count > 0:
             return False, f"Single-trade mode: {self.pending_execution_count} trade(s) being processed"

        # Also check for active martingale series that are RECOVERING (step > 0).
        # Step-0 series are just tracking stubs for fresh trades and must NOT
        # block scanner signals — otherwise single mode goes permanently dead.
        recovering_series = {
            sid: s for sid, s in self.active_martingale_series.items()
            if s.get('step', 0) > 0
        }
        if recovering_series:
            return False, f"Single-trade mode: {len(recovering_series)} martingale recovery series active"

        return True, "No active trades"

    def _auto_stop_scanner(self, reason: str):
        """
        Automatically stop the scanner when session manager blocks trading.
        Sends notification once per session block.
        """
        if self.scanner_autostop_notified:
            return  # Already notified

        self.scanner.set_enabled(False)
        self.scanner_autostop_notified = True

        print(f"\n🛑 SCANNER AUTO-STOPPED")
        print(f"   Reason: {reason}")
        print(f"   Scanner will remain disabled until manually re-enabled.")

        # Send notification
        if self.notification_callback:
            try:
                import asyncio
                asyncio.create_task(self.notification_callback(
                    f"🛑 *Scanner Auto-Stopped*\n\nReason: {reason}\n\nScanner disabled to protect capital. "
                    f"Review `/status` and use `/reset` to start a new session."
                ))
            except Exception:
                pass

    async def _handle_scanner_signal(self, signal: ScannerSignal):
        """
        Handle a signal discovered by the OTC scanner.

        Converts ScannerSignal to TradeRequest and submits for execution.
        """
        print(f"\n{'=' * 50}")
        print(f"🔍 SCANNER SIGNAL FOUND")
        print(f"   Asset: {signal.asset}")
        print(f"   Direction: {signal.direction.upper()}")
        print(f"   Confidence: {signal.confidence:.0%}")
        print(f"   Score: {abs(signal.score):.0f}")
        print(f"   Confluence: {signal.confluence}")
        print(f"   Duration: {signal.recommended_duration}m")
        print(f"   {signal.mtf_summary}")
        if signal.notes:
            print(f"   Reasoning: {', '.join(signal.notes)}")
        print(f"{'=' * 50}")

        # Create trade signal
        trade_signal = TradeSignal(
            asset=signal.asset,
            direction=signal.direction,
            duration=signal.recommended_duration,
        )

        # Create trade request
        request = TradeRequest(
            signal=trade_signal,
            ai_confidence=signal.confidence,
            reasoning=f"Scanner: {signal.reason}",
            skip_gatekeeper=True,  # Scanner already ran gatekeeper
            source="scanner",  # Explicitly mark as scanner source
            indicators=signal.indicators_2m,
            indicators_5m=signal.indicators_5m,
            indicators_15m=signal.indicators_15m,
            candles=signal.candles,
            score=signal.score,
            martingale_step=signal.martingale_step,
            martingale_amount=signal.martingale_amount,
            martingale_series_id=signal.martingale_series_id,
            strategy_used=signal.strategy_used,
            # Sprint 4: Analytical metadata
            quality_score=signal.quality_score,
            regime=signal.regime,
        )

        # Send notification
        if self.notification_callback:
            try:
                await self.notification_callback(signal.to_notification())
            except Exception:
                pass

        # Submit trade
        await self.submit_trade(request, source="scanner")

    async def submit_trade(self, request: TradeRequest, source: str = "telegram"):
        """Submit a trade request to the queue."""
        
        # Check if scanner source
        from_scanner = (source.lower() == "scanner")
        
        # Smart Signal Analysis
        is_martingale = (request.martingale_step > 0)
        reanalyzer_on = self.config.get("martingale_reanalyzer_enabled", True) if is_martingale else True
        
        # Allow Martingale re-analysis if enabled in config
        if not from_scanner and not request.signal.entry_time and (not is_martingale or reanalyzer_on):
            prefix = "🔄 Martingale Recovery" if is_martingale else "🧠 Smart Signal"
            print(f"\n{prefix} Analysis on {request.signal.asset} ({request.signal.direction.upper()})...")
            try:
                # 1. Fetch latest candles
                mtf_bundle = await self.data_provider.get_mtf_bundle(request.signal.asset)
                if not mtf_bundle or not mtf_bundle.entry_tf:
                    raise Exception("Failed to fetch fresh MTF data")
                
                # 2. Calculate indicators for all timeframes
                indicators_2m = self.scanner.analyzer.calculate_indicators(
                    mtf_bundle.entry_tf.candles, 
                    symbol=request.signal.asset
                )
                
                indicators_5m = None
                if mtf_bundle.mid_tf and mtf_bundle.mid_tf.is_valid:
                    indicators_5m = self.scanner.analyzer.calculate_indicators(
                        mtf_bundle.mid_tf.candles, 
                        symbol=request.signal.asset
                    )
                    
                indicators_15m = None
                if mtf_bundle.high_tf and mtf_bundle.high_tf.is_valid:
                    indicators_15m = self.scanner.analyzer.calculate_indicators(
                        mtf_bundle.high_tf.candles, 
                        symbol=request.signal.asset
                    )
                
                # 3. Evaluate using Strategy Engine
                pattern_analysis = self.pattern_analyzer.analyze(mtf_bundle.entry_tf.candles) if self.pattern_analyzer else None
                
                # Retrieve active strategies. For martingale, use the EXACT SAME strategy that initiated the series.
                strat_used = getattr(request, 'strategy_used', '')
                active_strats = [strat_used] if strat_used else getattr(self.config, 'active_strategies', [])

                # Telegram/martingale signals use min_agreement=1 (external conviction)
                smart_min_agreement = 1 if not from_scanner else self.scanner.config.min_agreement

                engine_decision = self.scanner.strategy_engine.evaluate(
                    mtf_bundle.entry_tf.candles,
                    symbol=request.signal.asset,
                    indicators_2m=indicators_2m,
                    indicators_5m=indicators_5m,
                    indicators_15m=indicators_15m,
                    pattern_analysis=pattern_analysis,
                    active_strategies=active_strats,
                    min_agreement=smart_min_agreement
                )
            
                # Store for gatekeeper/fingerprinting
                request.engine_decision = engine_decision
            
                # 4. Handle flips or rejects
                if engine_decision.should_trade and engine_decision.direction != request.signal.direction:
                    if self.config.get("martingale_reanalyzer_flip_enabled", True):
                        print(f"   🔄 SMART FLIP: {request.signal.direction.upper()} -> {engine_decision.direction.upper()}")
                        request.signal.direction = engine_decision.direction
                        request.reasoning += f" [SmartFlip: Strategy strongly prefers {engine_decision.direction.upper()}]"
                        
                        if self.notification_callback:
                            try:
                                msg = (f"🧠 *{prefix} Analysis*\n"
                                       f"Asset: {request.signal.asset}\n"
                                       f"Action: 🔄 SMART FLIP\n"
                                       f"Result: {request.signal.direction.upper()}\n"
                                       f"Reason: Strategy score {engine_decision.score:.1f}")
                                await self.notification_callback(msg)
                            except Exception: pass
                    else:
                        print(f"   ⚠️ Flip suggested to {engine_decision.direction.upper()} but MARTINGALE_REANALYZER_FLIP_ENABLED is False.")
                elif not engine_decision.should_trade:
                    # Strategy expects no trade
                    print(f"   🚫 SMART REJECT: Strategy Engine found no edge (Score: {engine_decision.score:.1f})")
                    if self.notification_callback:
                        try:
                            msg = (f"🧠 *{prefix} Analysis*\n"
                                   f"Asset: {request.signal.asset}\n"
                                   f"Action: 🚫 SMART REJECT\n"
                                   f"Reason: Strategy Engine Score {engine_decision.score:.1f}")
                            await self.notification_callback(msg)
                        except Exception: pass
                    
                    if is_martingale and request.martingale_series_id:
                        self.martingale.finalize_series(request.martingale_series_id, f"smart_reject: Strategy Engine Score {engine_decision.score}")
                    return

            except Exception as e:
                print(f"   ⚠️ Martingale Engine re-analysis failed: {e}")


        # Check trade mode — Telegram signals bypass single-trade restriction
        # CRITICAL FIX: Use lock to prevent race condition between multiple scanner signals
        async with self.submission_lock:
            can_trade, reason = self.can_place_trade(from_scanner=from_scanner)
            if not can_trade:
                 source = "Scanner" if from_scanner else "Telegram"
                 print(f"   ⛔ {source} trade blocked: {reason}")
                 if self.notification_callback:
                     try:
                         asyncio.create_task(self.notification_callback(
                             f"⛔ *Trade Blocked*\n\nSource: {source}\nAsset: {request.signal.asset}\nReason: {reason}"
                         ))
                     except: pass
                 return

            # Increment counter to reserve slot immediately (Fix for Single Scan Mode race condition)
            if from_scanner:
                 self.pending_execution_count += 1
                 print(f"   🔒 Reserved execution slot. Pending: {self.pending_execution_count}")


        # Queue signal if disconnected
        if not self.is_connected:
            signal_info = {
                'request': request,
                'queued_at': time.time(),
                'max_age': 120
            }
            self.pending_signals.append(signal_info)
            print(f"   ⏳ Signal queued (IQ disconnected): {request.signal.asset} {request.signal.direction}")
            return

        # Source is available in this scope (from submit_trade arguments)
        await self.trade_queue.put(request, source=source)


    async def _process_pending_signals(self):
        """Process any queued signals after reconnection.

        Drops signals that:
        1. Are older than max_age (default 2 minutes)
        2. Have entry_time that has already passed by more than MAX_LATE_SECONDS
        """
        if not self.pending_signals:
            return

        from datetime import datetime, timezone

        print(f"\n📋 Processing {len(self.pending_signals)} queued signal(s)...")
        current_time = time.time()
        now = datetime.now()

        processed = 0
        expired = 0
        dropped_late = 0

        MAX_LATE_SECONDS = 30  # Drop signals if entry time passed by more than 60s

        while self.pending_signals:
            signal_info = self.pending_signals.pop(0)
            request = signal_info['request']
            age = current_time - signal_info['queued_at']

            # Check 1: Signal too old (queued for more than max_age)
            if age > signal_info['max_age']:
                print(f"   ⏰ Signal expired ({age:.0f}s old): {request.signal.asset}")
                expired += 1
                continue

            # Check 2: Entry time has passed
            if request.signal.entry_time:
                entry_time = request.signal.entry_time

                # Handle timezone-aware vs naive datetimes
                if entry_time.tzinfo is not None:
                    try:
                        now_tz = datetime.now(entry_time.tzinfo)
                    except:
                        now_tz = now
                else:
                    now_tz = now

                time_diff = (now_tz - entry_time).total_seconds() if hasattr(entry_time, 'tzinfo') else (now - entry_time).total_seconds()

                if time_diff > MAX_LATE_SECONDS:
                    print(f"   ⏰ Entry time passed ({time_diff:.0f}s late): {request.signal.asset} @ {entry_time.strftime('%I:%M %p') if entry_time else 'N/A'}")
                    dropped_late += 1
                    continue
                elif time_diff > 0:
                    print(f"   ⚠️ Entry time was {time_diff:.0f}s ago, still within tolerance")

            # Check 3: Respect Trade Mode (Single/Multi) - CRITICAL FIX
            # If we are in single mode and just queued a signal, we must block subsequent ones.
            # We must re-check can_place_trade because logic might have changed or we just queued one.
            from_scanner = (request.source == "scanner")
            can_trade, reason = self.can_place_trade(from_scanner=from_scanner)
            
            if not can_trade:
                 print(f"   ⛔ Signal dropped (Trade Mode/Busy): {request.signal.asset} ({reason})")
                 continue

            # Increment count if from scanner (matches submit_trade logic)
            if from_scanner:
                 self.pending_execution_count += 1

            # Signal is valid - re-submit to queue
            # Source for re-queued trades remains same as original request
            source = getattr(request, 'source', 'telegram')
            await self.trade_queue.put(request, source=source)
            processed += 1
            print(f"   ✅ Re-queued: {request.signal.asset} {request.signal.direction}")

        total_dropped = expired + dropped_late
        if processed > 0 or total_dropped > 0:
            print(f"   📊 Re-queued: {processed}, Expired: {expired}, Late: {dropped_late}")

    async def _process_trades(self):
        """Process trades from the queue."""
        while self.running:
            try:
                try:
                    request = await asyncio.wait_for(
                        self.trade_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                await self._execute_trade(request)
                # PHASE 20: Safe task completion
                try:
                    self.trade_queue.task_done()
                except: pass

            except Exception as e:
                print(f"⚠️ Trade processor error: {e}")

    async def _execute_trade(self, request: TradeRequest):
        """Execute a single trade."""
        signal = request.signal
        is_martingale = request.martingale_step > 0

        # ---- SMART MARTINGALE PULLBACK HALT ----
        # If this is a recovery step AND we want to wait for pullbacks, we STOP execution here.
        # The martingale manager already registered the active series.
        # We just need to skip placing a real market order right now, letting the scanner
        # pick up the slack when the next valid pullback occurs.
        if is_martingale and self.config.get("martingale_wait_for_pullback", True):
            # We must only do this if it's coming from the automatic martingale manager schedule,
            # NOT if it's the scanner finally triggering the delayed trade.
            # If `skip_gatekeeper` is False, it was natively autogenerated by the martingale sequence.
            if request.skip_gatekeeper is False and signal.entry_time is None:
                 print(f"   ⏱️ Martingale Step {request.martingale_step} parked.")
                 print(f"      Waiting for next valid {signal.asset} {signal.direction.upper()} scanner pullback.")
                 return

        # ---- PHASE 10: DEPRECATED LEGACY GATEKEEPER ----
        # Removed: SmartReanalyzer in submit_trade now handles this with better logic.

        step_label = f" [M{request.martingale_step}]" if is_martingale else ""
        print(f"\n💰 Executing trade{step_label}...")

        try:
            # Check if entry time has passed (for scheduled trades) - skip for martingale
            MAX_LATE_SECONDS = 60
            if signal.entry_time and not is_martingale:
                from datetime import datetime
                now = datetime.now(signal.entry_time.tzinfo) if signal.entry_time.tzinfo else datetime.now()
                time_diff = (now - signal.entry_time).total_seconds()

                if time_diff > MAX_LATE_SECONDS:
                    print(f"   ⏰ TRADE DROPPED: Entry time passed by {time_diff:.0f}s")
                    print(f"      Asset: {signal.asset} {signal.direction.upper()}")
                    print(f"      Entry was: {signal.entry_time.strftime('%I:%M %p')}")
                    print(f"      Current: {now.strftime('%I:%M %p')}")
                    return

            # Check connection before executing
            if not self.is_connected:
                print(f"   ⚠️ IQ Option disconnected - queueing trade for later")
                signal_info = {
                    'request': request,
                    'queued_at': time.time(),
                    'max_age': 120
                }
                self.pending_signals.append(signal_info)
                return

            loop = asyncio.get_event_loop()
            validated_asset = await self._validate_and_get_asset(signal.asset)
            if not validated_asset:
                print(f"❌ Asset {signal.asset} is not available for trading right now")
                return

            trade_asset = validated_asset

            # ============================================
            # SESSION MANAGER CHECK (for martingale too)
            # ============================================
            if self.session_manager and is_martingale:
                allowed, reason = self.session_manager.check_trade_allowed()
                if not allowed:
                    print(f"⛔ Martingale{step_label} blocked by Session Manager: {reason}")
                    # Clean up the series
                    if request.martingale_series_id:
                        self.martingale.finalize_series(request.martingale_series_id, "blocked")
                    return

            # ============================================
            # SIGNAL GATEKEEPER CHECK (applies to martingale too when enabled)
            # ============================================
            # Determine if we should skip gatekeeper
            should_run_gatekeeper = self.use_gatekeeper and not request.skip_gatekeeper

            decision = None
            indicators = None
            indicators_5m = None
            indicators_15m = None
            pattern_analysis = None
            mtf_bundle = None

            # Martingale Logic: Bypass unless explicitly enabled
            if is_martingale:
                if not self.martingale_gatekeeper_enabled:
                    print(f"   ⏩ Martingale Step {request.martingale_step}: Bypassing Gatekeeper (Safety Mode)")
                    should_run_gatekeeper = False
                else:
                    print(f"   🔍 Martingale Step {request.martingale_step}: Gatekeeper Checked (Enabled)")

            # Determine trade source and gatekeeper instance early
            trade_source = getattr(request, 'source', 'telegram')
            
            # PHASE 10.1: Martingale Routing Fix
            # If it's a martingale trade, we ALWAYS use the dedicated martingale gatekeeper
            # regardless of source (scanner or telegram).
            if is_martingale:
                 active_gatekeeper = self.martingale_gatekeeper
            elif trade_source == 'scanner':
                 active_gatekeeper = self.gatekeeper_scanner
            else:
                 active_gatekeeper = self.gatekeeper_telegram

            if should_run_gatekeeper:
                print(f"\n🔍 Signal Gatekeeper Analysis{step_label}...")
                print(f"   Using {'Scanner' if trade_source == 'scanner' else 'Telegram'} Gatekeeper (Source: {trade_source})")

                # PHASE 19: Data Fetch Retry Logic
                mtf_bundle = None
                max_retries = 1
                for attempt in range(max_retries):
                    # Fetch MTF bundle (Centralized candle fetching)
                    mtf_bundle = await self.data_provider.get_mtf_bundle(
                        signal.asset,
                        include_5m=self.mtf_enabled and self.mtf_5m_enabled,
                        include_15m=self.mtf_enabled and self.mtf_15m_enabled
                    )
                    
                    if mtf_bundle.entry_tf.is_valid:
                        if attempt > 0:
                            print(f"   ✅ Data Recovery: Fetched candles for {signal.asset} on attempt {attempt+1}")
                        break
                    
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 1.5
                        print(f"   ⚠️ Data Gap: {signal.asset} entry candles invalid. Retry {attempt+2}/{max_retries} in {wait_time}s...")
                        # Clear cache for this asset to force a fresh fetch
                        self.data_provider.clear_cache(signal.asset)
                        await asyncio.sleep(wait_time)
                
                if not mtf_bundle or not mtf_bundle.entry_tf.is_valid:
                    print(f"   ❌ CRITICAL: Entry timeframe candles for {signal.asset} failed after {max_retries} retries.")
                    if self.notification_callback:
                        await self.notification_callback(f"⚠️ *Data Fetch Failure*: Permanent gap for {signal.asset}. Trade aborted.")
                    return

                # Safe access guaranteed by check above
                assert mtf_bundle is not None
                print(f"   📊 {mtf_bundle.get_status_summary()}")

                # Calculate indicators for each available timeframe
                indicators = self.analyzer.calculate_indicators(mtf_bundle.entry_tf.candles, symbol=signal.asset)
                pattern_analysis = self.pattern_analyzer.analyze(
                    mtf_bundle.entry_tf.candles, signal.direction
                )

                if mtf_bundle.mid_tf and mtf_bundle.mid_tf.is_valid:
                    indicators_5m = self.analyzer.calculate_indicators(mtf_bundle.mid_tf.candles, symbol=signal.asset)
                elif self.mtf_5m_enabled:
                    print(f"   ⚠️ Warning: 5m MTF data missing for {signal.asset}")

                if mtf_bundle.high_tf and mtf_bundle.high_tf.is_valid:
                    indicators_15m = self.analyzer.calculate_indicators(mtf_bundle.high_tf.candles, symbol=signal.asset)
                elif self.mtf_15m_enabled:
                    print(f"   ⚠️ Warning: 15m MTF data missing for {signal.asset}")

                # 3. Handle Strategy Engine Evaluation (Requirement for Gatekeeper)
                engine_decision = getattr(request, 'engine_decision', None)
                
                # If no engine decision yet (Telegram signals skipping reanalyzer), evaluate now
                if not engine_decision:
                    # Retrieve active strategies
                    strat_used = getattr(request, 'strategy_used', '')
                    active_strats = [strat_used] if strat_used else getattr(self.config, 'active_strategies', [])

                    # For Telegram signals, use min_agreement=1 since the external signal
                    # IS the conviction — we just need any strategy to confirm direction.
                    # Scanner's min_agreement (2/3) only applies to scanner-sourced signals.
                    is_telegram = (trade_source != 'scanner')
                    tg_min_agreement = 1 if is_telegram else self.scanner.config.min_agreement

                    engine_decision = self.scanner.strategy_engine.evaluate(
                        mtf_bundle.entry_tf.candles,
                        symbol=signal.asset,
                        indicators_2m=indicators,
                        indicators_5m=indicators_5m,
                        indicators_15m=indicators_15m,
                        pattern_analysis=pattern_analysis,
                        active_strategies=active_strats,
                        min_agreement=tg_min_agreement
                    )
                    request.engine_decision = engine_decision

                # 4. Run gatekeeper decision with MTF context
                # Convert StrategyEngine decision (TradeDecision) to Gatekeeper input (SignalScore if needed)
                # They are compatible, so we just pass engine_decision
                
                # IMPORTANT: Scanner signals already pass strict MTF checks in scanner.py
                # Skip MTF re-check for scanner to avoid double-penalizing valid signals
                if trade_source == 'scanner' and not is_martingale:
                    decision = active_gatekeeper.decide(
                        self.analyzer,
                        indicators,
                        pattern_analysis,
                        signal.direction,
                        indicators_2m=indicators,
                        indicators_5m=None,   # Scanner already validated MTF
                        indicators_15m=None,  # Scanner already validated MTF
                        use_mhi=request.use_mhi,
                        mhi_strategy=request.mhi_strategy,
                        pre_calculated_score=engine_decision, # Pass the engine's quantitative score
                        raw_candles=mtf_bundle.entry_tf.candles if mtf_bundle.entry_tf.is_valid else None
                    )
                else:
                    decision = active_gatekeeper.decide(
                        self.analyzer,
                        indicators,
                        pattern_analysis,
                        signal.direction,
                        indicators_2m=indicators,
                        indicators_5m=indicators_5m,
                        indicators_15m=indicators_15m,
                        is_martingale=is_martingale,
                        use_mhi=request.use_mhi,
                        mhi_strategy=request.mhi_strategy,
                        pre_calculated_score=engine_decision, # Pass the engine's quantitative score
                        raw_candles=mtf_bundle.entry_tf.candles if mtf_bundle.entry_tf.is_valid else None
                    )

                # Print decision details
                print(active_gatekeeper.format_decision(decision))

                if not decision.accept:
                    if self.gatekeeper_strict_mode:
                        print(f"\n⛔ TRADE REJECTED BY GATEKEEPER{step_label}")
                        print(f"   Reason: {decision.reason}")

                        # Notify user about rejection
                        if self.notification_callback:
                            try:
                                msg = f"⛔ *Signal Rejected{step_label}*\n\nAsset: {signal.asset}\nDirection: {signal.direction.upper()}\n\n{decision.reason}"
                                if decision.notes:
                                    msg += f"\n\nDetails: {'; '.join(decision.notes[:3])}"
                                await self.notification_callback(msg)
                            except Exception: pass

                        # Clean up the series
                        if request.martingale_series_id:
                            self.martingale.finalize_series(request.martingale_series_id, "blocked")
                        return
                    else:
                        print(f"   ⚠️ Proceeding anyway (strict_mode=False)")
                else:
                    print(f"\n✅ SIGNAL APPROVED BY GATEKEEPER{step_label}")
                    print(f"   Score: {decision.score:.0f} | Confidence: {decision.confidence:.0%} | Confluence: {decision.confluence_count}")
            else:
                # RECOVER indicators from request if gatekeeper was skipped (Phase 3 Fingerprint Support)
                if hasattr(request, 'indicators') and request.indicators:
                    indicators = request.indicators
                    indicators_5m = getattr(request, 'indicators_5m', None)
                    indicators_15m = getattr(request, 'indicators_15m', None)
                    print(f"   🧠 recovered indicators from {trade_source} request for fingerprinting")

                # If we still don't have indicators, we must fetch them for the fingerprint
                if not indicators:
                    mtf_bundle = await self.data_provider.get_mtf_bundle(
                        signal.asset,
                        include_5m=self.mtf_enabled and self.mtf_5m_enabled,
                        include_15m=self.mtf_enabled and self.mtf_15m_enabled
                    )
                    print(f"   📊 {mtf_bundle.get_status_summary()}")

                    if mtf_bundle.entry_tf.is_valid:
                        indicators = self.analyzer.calculate_indicators(mtf_bundle.entry_tf.candles, symbol=signal.asset)
                    if mtf_bundle.mid_tf and mtf_bundle.mid_tf.is_valid:
                        indicators_5m = self.analyzer.calculate_indicators(mtf_bundle.mid_tf.candles, symbol=signal.asset)
                    if mtf_bundle.high_tf and mtf_bundle.high_tf.is_valid:
                        indicators_15m = self.analyzer.calculate_indicators(mtf_bundle.high_tf.candles, symbol=signal.asset)
                
                print(f"   ⏩ Bypassing Gatekeeper Analysis (Source: {trade_source})")

            # ============================================
            # DETERMINE TRADE AMOUNT
            # ============================================

            balance = await loop.run_in_executor(None, self.api.get_balance)
            win_rate = self.logger.get_win_rate()
            self.payout_rate = await self._get_payout(trade_asset)

            if self.payout_rate < 0.5:
                print(f"   ⚠️ Payout too low ({self.payout_rate*100:.0f}%), using default 80%")
                self.payout_rate = DEFAULT_PAYOUT

            # For martingale: use override amount, bypass position sizer
            if is_martingale and request.martingale_amount:
                amount = request.martingale_amount
                print(f"   🔁 Martingale Step {request.martingale_step}/{self.martingale_max_steps}")
                print(f"   💰 Martingale Amount: ${amount:.2f} (bypassing position sizer)")
            else:
                amount = self.sizer.calculate_size(balance, win_rate, self.payout_rate)

            # Use fixed duration for martingale
            trade_duration = self.martingale_duration if is_martingale else signal.duration

            print(f"   Asset: {trade_asset}")
            print(f"   Balance: ${balance:.2f}")
            print(f"   Win Rate: {win_rate*100:.1f}%")
            print(f"   Payout: {self.payout_rate*100:.0f}%")
            print(f"   Position Size: ${amount:.2f}")
            if is_martingale:
                print(f"   Duration: {trade_duration}M (martingale fixed)")

            # Check for zero amount (too risky)
            if amount <= 0:
                print(f"⛔ Trade skipped: Too risky for current balance (Amount: ${amount:.2f})")
                print(f"   Increase /sizing risk limit to allow higher percentage")
                if self.notification_callback:
                    try:
                        asyncio.create_task(self.notification_callback(
                            f"⛔ *Trade Skipped*\n\nAsset: {trade_asset}\nReason: Too risky for current balance (${balance:.2f})\n"
                            f"Trade amount would be below $1 broker minimum at current risk settings."
                        ))
                    except: pass
                if is_martingale and request.martingale_series_id:
                    self.martingale.finalize_series(request.martingale_series_id, "too_risky")
                return

            # Check balance for martingale amount
            if balance < amount:
                print(f"❌ Insufficient balance! Have: ${balance:.2f}, Need: ${amount:.2f}")
                if is_martingale and request.martingale_series_id:
                    self.martingale.finalize_series(request.martingale_series_id, "insufficient_balance")
                return

            # Connection check before trade
            try:
                is_connected = await loop.run_in_executor(None, self.api.check_connect)
                if not is_connected:
                    print(f"   ⚠️ Connection lost, reconnecting...")
                    reconnect_result = await loop.run_in_executor(None, self.api.connect)
                    if isinstance(reconnect_result, tuple) and not reconnect_result[0]:
                        print(f"❌ Could not reconnect before trade")
                        return
                    elif not reconnect_result:
                        print(f"❌ Could not reconnect before trade")
                        return
                    await asyncio.sleep(0.5)
            except Exception as e:
                print(f"   ⚠️ Connection check error: {e}")

            # Place the trade - use trade_duration for martingale support
            check, order_id = await self._place_trade(trade_asset, signal.direction, amount, trade_duration)

            if check:
                print(f"✅ Trade Placed!{step_label}")
                print(f"   Order ID: {order_id}")
                print(f"   Amount: ${amount:.2f}")

                new_balance = await loop.run_in_executor(None, self.api.get_balance)
                print(f"   New Balance: ${new_balance:.2f}")


                self.logger.log_trade(
                    signal.asset, signal.direction, trade_duration,
                    order_id, amount, request.ai_confidence, request.reasoning,
                    source=trade_source
                )

                # Generate or use existing series ID for martingale tracking
                series_id = request.martingale_series_id
                if not series_id and self.martingale_enabled:
                    series_id = self._generate_series_id()
                    # Initialize series tracking for new trades
                    self.active_martingale_series[series_id] = {
                        'base_amount': amount,
                        'cumulative_loss': 0.0,
                        'step': 0,
                        'asset': signal.asset,
                        'direction': signal.direction,
                    }

                expiry_time = time.time() + (trade_duration * 60) + 5  # 5 sec buffer after expiry
                result_deadline = expiry_time + 60  # 60 sec deadline for result (reduced from 120)

                # Get balance AFTER trade was placed (amount already deducted)
                try:
                    balance_after_trade = await loop.run_in_executor(None, self.api.get_balance)
                except:
                    balance_after_trade = balance - amount  # Estimate if can't fetch

                # Calculate context for robust result checking
                active_stakes_sum = sum(t['amount'] for t in self.active_trades.values())
                
                # Create Phase 3 Fingerprint
                fingerprint = None
                if indicators:
                    from .fingerprint import TradeFingerprint
                    # Helper for MTF trends
                    t2m = str(indicators.get("trend", "neutral"))
                    t5m = str(indicators_5m.get("trend", "neutral")) if indicators_5m else "neutral"
                    t15m = str(indicators_15m.get("trend", "neutral")) if indicators_15m else "neutral"
                    
                    # Score source: gatekeeper overrides signal score if it ran
                    fp_score = float(decision.score) if decision else float(getattr(request, 'score', 0.0))
                    
                    # ── Sprint 4: Compute analytical fields from candles ──
                    fp_body_expansion = None
                    fp_run_length = None
                    fp_candles = request.candles if request.candles else None
                    if fp_candles and len(fp_candles) >= 2:
                        try:
                            # Body expansion: last candle body / previous candle body
                            last_c = fp_candles[-1]
                            prev_c = fp_candles[-2]
                            last_body = abs(float(last_c.get('c', last_c.get('close', 0))) - float(last_c.get('o', last_c.get('open', 0))))
                            prev_body = abs(float(prev_c.get('c', prev_c.get('close', 0))) - float(prev_c.get('o', prev_c.get('open', 0))))
                            if prev_body > 1e-10:
                                fp_body_expansion = round(last_body / prev_body, 2)
                        except Exception:
                            pass
                        try:
                            # Run length: count consecutive same-direction candles from end
                            fp_run_length = 0
                            for rc in reversed(fp_candles):
                                rc_o = float(rc.get('o', rc.get('open', 0)))
                                rc_c = float(rc.get('c', rc.get('close', 0)))
                                rc_dir = 'call' if rc_c > rc_o else ('put' if rc_c < rc_o else 'neutral')
                                if rc_dir == signal.direction:
                                    fp_run_length += 1
                                else:
                                    break
                        except Exception:
                            fp_run_length = None

                    fp_source = getattr(request, 'source', 'telegram')
                    fp_quality_score = getattr(request, 'quality_score', None)
                    fp_regime = getattr(request, 'regime', None)
                    fp_adx = float(indicators.get("adx", 0.0))

                    fingerprint = TradeFingerprint(
                        asset=signal.asset,
                        direction=signal.direction,
                        action_time=time.time(),
                        duration=int(trade_duration),
                        rsi=float(indicators.get("rsi", 50.0)),
                        stoch_k=float(indicators.get("stoch_k", 50.0)),
                        stoch_d=float(indicators.get("stoch_d", 50.0)),
                        macd_hist=float(indicators.get("macd_histogram", 0.0)),
                        bb_position=float(indicators.get("bb_position", 0.5)),
                        volatility=str(indicators.get("volatility_regime", "normal")),
                        trend_2m=t2m,
                        trend_5m=t5m,
                        trend_15m=t15m,
                        score=fp_score,
                        candles=fp_candles,
                        strategy_used=getattr(request, 'strategy_used', '') or fp_source,
                        # Sprint 4: Analytical fields
                        source=fp_source,
                        quality_score=fp_quality_score,
                        regime=fp_regime,
                        body_expansion=fp_body_expansion,
                        run_length=fp_run_length,
                        adx=fp_adx,
                    )
                
                self.active_trades[order_id] = {
                    "fingerprint": fingerprint,
                    "asset": signal.asset,
                    "direction": signal.direction,
                    "amount": amount,
                    "placed_at": time.time(),
                    "expiry_time": expiry_time,
                    "result_deadline": result_deadline,
                    "balance_snapshot": balance_after_trade, # Initial snapshot
                    "after_trade_balance": balance_after_trade,
                    "active_stakes_at_placement": active_stakes_sum,
                    "started_with_pnl": getattr(self, "cumulative_pnl", 0.0),
                    "check_attempts": 0,
                    "balance_before": balance,  # Balance BEFORE trade (with amount)
                    "balance_after_trade": balance_after_trade,  # Balance AFTER trade (amount deducted)
                    "payout_rate": self.payout_rate,  # Store payout for win calculation
                    # Martingale tracking
                    "martingale_step": request.martingale_step,
                    "martingale_series_id": series_id,
                    "duration": trade_duration,
                    # Confidence calibration tracking
                    "confidence": request.ai_confidence,
                    "source": getattr(request, 'source', 'telegram'),
                    "strategy_used": getattr(request, 'strategy_used', ''),
                    "winning_strategy": getattr(request.engine_decision, 'winning_strategy', '') if getattr(request, 'engine_decision', None) else getattr(request, 'strategy_used', ''),
                    "agreeing_strategies": getattr(request.engine_decision, 'agreeing_strategies', []) if getattr(request, 'engine_decision', None) else [],
                }


                print(f"   ⏱️ Result will be checked in ~{trade_duration} min 5 sec")
                print(f"   📋 Active trades being monitored: {len(self.active_trades)}")

                if self.notification_callback:
                    try:
                        martingale_label = f" [M{request.martingale_step}]" if is_martingale else ""
                        msg = f"📈 *Trade Placed{martingale_label}*\n\nAsset: {signal.asset}\nDirection: {signal.direction.upper()}\nAmount: ${amount:.2f}\nDuration: {trade_duration}M\n\n⏱️ Result in ~{trade_duration} min"
                        if is_martingale:
                            msg += f"\n\n🔁 Martingale Step {request.martingale_step}/{self.martingale_max_steps}"
                        await self.notification_callback(msg)
                    except Exception:
                        pass
            else:
                # Trade failed - notify user
                error_msg = str(order_id) if order_id else "Unknown error"
                print(f"❌ Trade Failed{step_label}: {error_msg}")

                # Clean up martingale series on failure
                if is_martingale and request.martingale_series_id:
                    self.martingale.finalize_series(request.martingale_series_id, "trade_failed")

                # Send failure notification
                if self.notification_callback:
                    try:
                        msg = f"❌ *Trade Failed{step_label}*\n\nAsset: {signal.asset}\nDirection: {signal.direction.upper()}\nAmount: ${amount:.2f}\n\nError: {error_msg[:100]}"
                        await self.notification_callback(msg)
                    except Exception:
                        pass

        except Exception as e:
            import traceback
            print(f"⚠️ Trade execution error: {e}")
            traceback.print_exc()
        finally:
            # CRITICAL: Always decrement pending count for scanner trades,
            # even on early returns (entry time passed, disconnected, etc.)
            if request.source == "scanner" and self.pending_execution_count > 0:
                self.pending_execution_count -= 1
                print(f"   🔓 Released execution slot. Pending: {self.pending_execution_count}")


    async def _get_payout(self, asset: str) -> float:
        """Get current payout rate for asset."""
        try:
            loop = asyncio.get_event_loop()
            all_profit = await loop.run_in_executor(None, self.api.get_all_profit)

            if not all_profit:
                return DEFAULT_PAYOUT

            asset_keys_to_try = [
                asset,
                asset.replace("-OTC", ""),
                asset.lower(),
                asset.replace("-OTC", "").lower(),
            ]

            for key in asset_keys_to_try:
                if key in all_profit:
                    profit_data = all_profit[key]

                    if isinstance(profit_data, dict):
                        payout = profit_data.get('binary', profit_data.get('turbo', None))
                        if payout is None:
                            for v in profit_data.values():
                                if isinstance(v, (int, float)) and v > 1:
                                    payout = v
                                    break
                    elif isinstance(profit_data, (int, float)):
                        payout = profit_data
                    else:
                        continue

                    if payout is not None:
                        if 50 <= payout <= 100:
                            return payout / 100
                        elif 0.5 <= payout <= 1.0:
                            return payout
                        elif 1 < payout < 50:
                            return DEFAULT_PAYOUT

        except Exception as e:
            print(f"   ⚠️ Could not get payout: {e}")

        return DEFAULT_PAYOUT

    async def _validate_and_get_asset(self, asset: str) -> Optional[str]:
        """Delegate to AssetResolver."""
        return await self.asset_resolver.validate_and_get_asset(asset)

    async def _place_trade(self, asset: str, direction: str, amount: float, duration: int) -> Tuple[bool, Any]:
        """Delegate to AssetResolver."""
        return await self.asset_resolver.place_trade(asset, direction, amount, duration)

    async def _resolve_asset_name(self, asset: str) -> str:
        """Delegate to AssetResolver."""
        return await self.asset_resolver.resolve_asset_name(asset)

    # ==========================================
    # DELEGATED METHODS (thin wrappers)
    # ==========================================

    async def _check_results(self):
        """Delegate to ResultChecker."""
        await self.result_checker.check_results_loop()

    async def _handle_result(self, order_id, trade_info, result, profit, current_balance):
        """Delegate to ResultChecker."""
        await self.result_checker.handle_result(order_id, trade_info, result, profit, current_balance)

    # ==========================================
    # MARTINGALE DELEGATED METHODS
    # ==========================================

    # ==========================================
    # DATA & CONNECTION METHODS
    # ==========================================


    async def get_market_data(self, asset: str, timeframe: int = 120,
                               candle_count: int = 50):
        """Get market data via data provider."""
        return await self.data_provider.get_candles(asset, timeframe, candle_count)

    async def get_available_assets(self) -> dict:
        # Get available assets from IQ Option API
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.api.get_all_open_time)
        except Exception as e:
            print(f"⚠️ Could not get available assets: {e}")
            return {}

    def get_connection_status(self) -> dict:
        # Delegate connection status 
        return self.connection_mgr.get_status()

