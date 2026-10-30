"""
OTC Trading Bot v2.0
====================
A robust Telegram signal trading bot for IQ Option with:
- Real-time trade monitoring
- Martingale strategy (up to 3 levels)
- AI-powered trade analysis (optional)
- Technical indicators (RSI, SMA, trend detection)
- Comprehensive trade logging

Author: Trading Bot
Version: 2.0
"""

import re
import time
import json
import asyncio
import os
from datetime import datetime
from threading import Thread, Lock
from typing import Optional, Tuple, Dict, Any, Callable
from telethon import TelegramClient, events
from trading_platform.vendor.iqoptionapi.iqoptionapi.stable_api import IQ_Option
import requests


# ==========================================
# 📊 MARKET ANALYZER
# ==========================================

class MarketAnalyzer:
    """Handles market data fetching and technical analysis."""

    def __init__(self, iq_api: IQ_Option):
        self.api = iq_api

    def get_market_data(self, asset: str, timeframe: int = 120, candle_count: int = 100) -> Optional[list]:
        """
        Fetch historical candles.

        Args:
            asset: Trading asset (e.g., 'EURUSD')
            timeframe: Candle timeframe in seconds (60=1M, 120=2M, 300=5M, 900=15M, 3600=1H)
            candle_count: Number of candles to fetch

        Returns:
            List of candle data or None on error
        """
        try:
            candles = self.api.get_candles(asset, timeframe, candle_count, time.time())
            return candles
        except Exception as e:
            print(f"⚠️ Error fetching candles: {e}")
            return None

    def calculate_indicators(self, candles: list) -> Optional[Dict[str, Any]]:
        """
        Calculate technical indicators from candle data.

        Returns:
            Dictionary with RSI, SMA, trend, support/resistance levels
        """
        if not candles or len(candles) < 20:
            return None

        closes = [c['close'] for c in candles]
        highs = [c['max'] for c in candles]
        lows = [c['min'] for c in candles]
        volumes = [c['volume'] for c in candles]

        # Simple Moving Averages
        sma_10 = sum(closes[-10:]) / 10
        sma_20 = sum(closes[-20:]) / 20

        # RSI Calculation (14-period)
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            diff = closes[-i] - closes[-i - 1]
            if diff > 0:
                gains.append(diff)
            else:
                losses.append(abs(diff))

        avg_gain = sum(gains) / 14 if gains else 0
        avg_loss = sum(losses) / 14 if losses else 0.001
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        # Trend detection
        trend = "bullish" if sma_10 > sma_20 else "bearish"

        # Momentum
        momentum = ((closes[-1] - closes[-10]) / closes[-10]) * 100 if closes[-10] != 0 else 0

        return {
            "current_price": closes[-1],
            "sma_10": round(sma_10, 5),
            "sma_20": round(sma_20, 5),
            "rsi": round(rsi, 2),
            "trend": trend,
            "momentum": round(momentum, 2),
            "recent_high": max(highs[-20:]),
            "recent_low": min(lows[-20:]),
            "avg_volume": sum(volumes[-10:]) / 10,
            "volatility": round((max(highs[-10:]) - min(lows[-10:])) / closes[-1] * 100, 2)
        }

    def get_trader_sentiment(self, asset: str) -> Optional[dict]:
        """Get trader sentiment (% buying calls vs puts)."""
        try:
            self.api.subscribe_strike_list(asset, 1)
            time.sleep(2)
            data = self.api.get_digital_current_profit(asset, 1)
            self.api.unsubscribe_strike_list(asset, 1)
            return data
        except Exception:
            return None

    def is_favorable_condition(self, indicators: dict, direction: str) -> Tuple[bool, str]:
        """
        Check if market conditions are favorable for the trade direction.

        Returns:
            Tuple of (is_favorable, reason)
        """
        if not indicators:
            return True, "No indicator data available"

        rsi = indicators.get('rsi', 50)
        trend = indicators.get('trend', 'unknown')

        # Check for overbought/oversold conditions
        if direction == "call":
            if rsi > 80:
                return False, f"RSI overbought ({rsi})"
            if trend == "bearish" and rsi > 60:
                return False, f"Bearish trend with high RSI ({rsi})"
            return True, f"Favorable for CALL (RSI: {rsi}, Trend: {trend})"
        else:  # put
            if rsi < 20:
                return False, f"RSI oversold ({rsi})"
            if trend == "bullish" and rsi < 40:
                return False, f"Bullish trend with low RSI ({rsi})"
            return True, f"Favorable for PUT (RSI: {rsi}, Trend: {trend})"


# ==========================================
# 🤖 AI ANALYZER
# ==========================================

class AIAnalyzer:
    """Handles AI-based trade analysis using OpenAI API."""

    def __init__(self, api_key: str, enabled: bool = True, confidence_threshold: float = 0.7):
        self.api_key = api_key
        self.enabled = enabled
        self.confidence_threshold = confidence_threshold

    def analyze(self, asset: str, direction: str, indicators: dict, sentiment: dict = None) -> Tuple[bool, float, str]:
        """
        Send market data to AI for trade decision.

        Returns:
            Tuple of (should_trade, confidence, reasoning)
        """
        if not self.enabled or not self.api_key or self.api_key == "your_openai_api_key":
            return True, 1.0, "AI disabled - executing signal directly"

        prompt = f"""
        You are a professional binary options trading analyst. Analyze this trade signal and market data.
        Be conservative - only recommend trades with clear technical confirmation.

        SIGNAL: {asset} - {direction.upper()}

        MARKET DATA:
        - Current Price: {indicators.get('current_price')}
        - RSI (14): {indicators.get('rsi')} (>70 overbought, <30 oversold)
        - SMA 10: {indicators.get('sma_10')}
        - SMA 20: {indicators.get('sma_20')}
        - Trend: {indicators.get('trend')}
        - Momentum: {indicators.get('momentum')}%
        - Volatility: {indicators.get('volatility')}%
        - Recent High: {indicators.get('recent_high')}
        - Recent Low: {indicators.get('recent_low')}

        RULES:
        - For CALL: RSI should not be >75, trend should not be strongly bearish
        - For PUT: RSI should not be <25, trend should not be strongly bullish
        - High volatility (>2%) increases risk

        Respond ONLY in this exact JSON format:
        {{"should_trade": true, "confidence": 0.75, "reasoning": "brief explanation"}}
        """

        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 150
                },
                timeout=15
            )

            result = response.json()

            if 'error' in result:
                print(f"⚠️ AI API Error: {result['error']}")
                return True, 0.5, "AI API error - proceeding with caution"

            content = result['choices'][0]['message']['content']

            # Clean and parse JSON
            content = content.strip()
            if content.startswith('```'):
                content = re.sub(r'^```json?\s*', '', content)
                content = re.sub(r'\s*```$', '', content)

            analysis = json.loads(content)
            return analysis['should_trade'], analysis['confidence'], analysis['reasoning']

        except json.JSONDecodeError as e:
            print(f"⚠️ AI JSON Parse Error: {e}")
            return True, 0.5, "AI response parse error - proceeding with caution"
        except Exception as e:
            print(f"⚠️ AI Error: {e}")
            return True, 0.5, "AI unavailable - proceeding with caution"


# ==========================================
# 📝 TRADE LOGGER
# ==========================================

class TradeLogger:
    """Handles trade logging, history, and statistics."""

    def __init__(self, log_file: str = "trade_log.json"):
        self.log_file = log_file
        self.trade_history = []
        self.lock = Lock()
        self._load_history()

    def _load_history(self):
        """Load existing trade history from file."""
        try:
            with open(self.log_file, "r") as f:
                self.trade_history = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.trade_history = []

    def log_trade(self, asset: str, direction: str, duration: int, order_id: int,
                  amount: float, martingale_level: int, ai_confidence: float, reasoning: str) -> dict:
        """Log a new trade."""
        trade = {
            "timestamp": datetime.now().isoformat(),
            "asset": asset,
            "direction": direction,
            "duration": duration,
            "order_id": order_id,
            "amount": amount,
            "martingale_level": martingale_level,
            "ai_confidence": ai_confidence,
            "reasoning": reasoning,
            "result": None,
            "profit": None
        }

        with self.lock:
            self.trade_history.append(trade)
            self._save()

        return trade

    def update_result(self, order_id: int, result: str, profit: float):
        """Update trade result after expiration."""
        with self.lock:
            for trade in self.trade_history:
                if trade['order_id'] == order_id:
                    trade['result'] = result
                    trade['profit'] = profit
                    break
            self._save()

    def _save(self):
        """Save trade history to file."""
        try:
            with open(self.log_file, "w") as f:
                json.dump(self.trade_history, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving trade log: {e}")

    def get_statistics(self) -> dict:
        """Calculate trading statistics."""
        if not self.trade_history:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_profit": 0}

        completed = [t for t in self.trade_history if t['result'] is not None]
        wins = len([t for t in completed if t['result'] == 'win'])
        losses = len([t for t in completed if t['result'] == 'lose'])
        total_profit = sum(t.get('profit', 0) or 0 for t in completed)

        return {
            "total": len(completed),
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / len(completed) * 100), 1) if completed else 0,
            "total_profit": round(total_profit, 2)
        }

    def print_statistics(self):
        """Print formatted statistics."""
        stats = self.get_statistics()
        print(f"\n📊 STATISTICS")
        print(f"   Total Trades: {stats['total']}")
        print(f"   Wins: {stats['wins']} | Losses: {stats['losses']}")
        print(f"   Win Rate: {stats['win_rate']}%")
        print(f"   Total Profit: ${stats['total_profit']:.2f}")


# ==========================================
# ⏱️ TRADE MONITOR
# ==========================================

class TradeMonitor:
    """Monitors active trades and handles martingale strategy."""

    def __init__(self, iq_api: IQ_Option, trade_logger: TradeLogger, martingale_config: dict):
        self.api = iq_api
        self.logger = trade_logger
        self.martingale_enabled = martingale_config.get('enabled', False)
        self.max_martingale_level = martingale_config.get('max_level', 3)
        self.martingale_multiplier = martingale_config.get('multiplier', 2.2)
        self.active_trades = {}
        self.lock = Lock()
        self.on_martingale_trigger: Optional[Callable] = None

    def monitor_trade(self, order_id: int, asset: str, direction: str,
                      duration: int, amount: float, martingale_level: int = 0):
        """Start monitoring a trade in a separate thread."""
        thread = Thread(
            target=self._monitor_thread,
            args=(order_id, asset, direction, duration, amount, martingale_level),
            daemon=True
        )

        with self.lock:
            self.active_trades[order_id] = {
                "asset": asset,
                "direction": direction,
                "duration": duration,
                "amount": amount,
                "martingale_level": martingale_level,
                "thread": thread
            }

        thread.start()

    def _monitor_thread(self, order_id: int, asset: str, direction: str,
                        duration: int, amount: float, martingale_level: int):
        """Monitor trade until completion."""
        level_str = f" [M{martingale_level}]" if martingale_level > 0 else ""
        print(f"\n⏱️ Monitoring trade {order_id}{level_str} ({duration}M)...")

        # Wait for trade to complete (duration in minutes + buffer)
        wait_time = (duration * 60) + 10
        start_time = time.time()

        while (time.time() - start_time) < wait_time:
            elapsed = time.time() - start_time
            remaining = wait_time - elapsed
            mins, secs = divmod(int(remaining), 60)
            print(f"   ⏳ {order_id}: {mins}:{secs:02d} remaining    ", end='\r')
            time.sleep(1)

        print(f"\n   ✅ Trade {order_id} expired. Checking result...")

        # Check result with retries
        result, profit = self._check_result(order_id)

        # Remove from active trades
        with self.lock:
            self.active_trades.pop(order_id, None)

        if result == "win":
            print(f"   🎉 WIN! Profit: +${profit:.2f}")
            self.logger.update_result(order_id, "win", profit)

        elif result == "lose":
            print(f"   😔 LOSS! Amount: -${amount:.2f}")
            self.logger.update_result(order_id, "lose", -amount)

            # Trigger martingale if enabled and within limits
            if self.martingale_enabled and martingale_level < self.max_martingale_level:
                self._trigger_martingale(asset, direction, duration, amount, martingale_level)
            elif martingale_level >= self.max_martingale_level:
                print(f"   ⛔ Max martingale level ({self.max_martingale_level}) reached. Stopping.")

        elif result == "tie":
            print(f"   🔄 TIE! Amount returned: ${amount:.2f}")
            self.logger.update_result(order_id, "tie", 0)

        else:
            print(f"   ⚠️ Unknown result: {result}")
            self.logger.update_result(order_id, "unknown", 0)

    def _check_result(self, order_id: int) -> Tuple[str, float]:
        """Check trade result with multiple retries."""
        max_attempts = 10

        for attempt in range(max_attempts):
            try:
                # Try different methods to check result
                result = self.api.check_win_v4(order_id)

                if result is not None:
                    if result > 0:
                        return "win", result
                    elif result < 0:
                        return "lose", abs(result)
                    else:
                        return "tie", 0

            except Exception as e:
                if attempt == max_attempts - 1:
                    print(f"   ⚠️ Final check attempt failed: {e}")

            time.sleep(2)

        return "unknown", 0

    def _trigger_martingale(self, asset: str, direction: str, duration: int,
                           previous_amount: float, current_level: int):
        """Trigger martingale trade after a loss."""
        new_level = current_level + 1
        new_amount = round(previous_amount * self.martingale_multiplier, 2)

        print(f"\n{'='*50}")
        print(f"🔄 MARTINGALE TRIGGERED - Level {new_level}/{self.max_martingale_level}")
        print(f"   Previous Amount: ${previous_amount:.2f}")
        print(f"   New Amount: ${new_amount:.2f} ({self.martingale_multiplier}x)")
        print(f"   Direction: {direction.upper()} (same as previous)")

        if self.on_martingale_trigger:
            # Small delay before martingale trade
            time.sleep(2)
            self.on_martingale_trigger(asset, direction, duration, new_amount, new_level)

    def get_active_count(self) -> int:
        """Get number of active trades being monitored."""
        with self.lock:
            return len(self.active_trades)


# ==========================================
# 📡 SIGNAL PARSER
# ==========================================

class SignalParser:
    """Handles parsing of trading signals from Telegram messages."""

    def __init__(self, iq_api: IQ_Option, default_duration: int = 2):
        self.api = iq_api
        self.default_duration = default_duration

        # Common asset mappings
        self.asset_aliases = {
            "EURUSD": ["EUR/USD", "EURUSD", "EUR-USD"],
            "GBPUSD": ["GBP/USD", "GBPUSD", "GBP-USD"],
            "USDJPY": ["USD/JPY", "USDJPY", "USD-JPY"],
            "AUDUSD": ["AUD/USD", "AUDUSD", "AUD-USD"],
            "USDCAD": ["USD/CAD", "USDCAD", "USD-CAD"],
            "EURGBP": ["EUR/GBP", "EURGBP", "EUR-GBP"],
            "EURJPY": ["EUR/JPY", "EURJPY", "EUR-JPY"],
            "GBPJPY": ["GBP/JPY", "GBPJPY", "GBP-JPY"],
        }

    def parse(self, message_text: str) -> Optional[Tuple[str, str, int]]:
        """
        Parse raw text into (Asset, Direction, Duration).

        Returns:
            Tuple of (asset, direction, duration_minutes) or None if parsing fails
        """
        text = message_text.upper()

        # Extract asset
        full_asset_match = re.search(r'([A-Z]{3})[/\-\s]?([A-Z]{3})', text)
        if not full_asset_match:
            return None

        raw_asset = full_asset_match.group(1) + full_asset_match.group(2)

        # Check if asset is available
        try:
            all_assets = self.api.get_all_open_time()
        except Exception as e:
            print(f"⚠️ Error getting asset list: {e}")
            return None

        # Try OTC first (available 24/7), then regular
        otc_asset = f"{raw_asset}-OTC"
        regular_asset = raw_asset

        final_asset = None

        # Check binary options
        if 'binary' in all_assets:
            if otc_asset in all_assets['binary'] and all_assets['binary'][otc_asset].get('open'):
                final_asset = otc_asset
            elif regular_asset in all_assets['binary'] and all_assets['binary'][regular_asset].get('open'):
                final_asset = regular_asset

        # Check turbo options as fallback
        if not final_asset and 'turbo' in all_assets:
            if otc_asset in all_assets['turbo'] and all_assets['turbo'][otc_asset].get('open'):
                final_asset = otc_asset
            elif regular_asset in all_assets['turbo'] and all_assets['turbo'][regular_asset].get('open'):
                final_asset = regular_asset

        if not final_asset:
            print(f"⚠️ Asset {raw_asset} / {otc_asset} is not available for trading")
            return None

        # Extract direction
        call_patterns = ["CALL", "BUY", "UP", "LONG", "⬆", "🟢", "🔼", "📈", "GREEN"]
        put_patterns = ["PUT", "SELL", "DOWN", "SHORT", "⬇", "🔴", "🔽", "📉", "RED"]

        direction = None
        if any(x in text for x in call_patterns):
            direction = "call"
        elif any(x in text for x in put_patterns):
            direction = "put"
        else:
            return None

        # Extract duration (default to configured duration)
        duration = self.default_duration

        # Match patterns like "2M", "2 MIN", "2 MINUTES", "M2"
        time_patterns = [
            r'(\d+)\s*(?:M(?:IN(?:UTES?)?)?)\b',  # 2M, 2MIN, 2MINUTES
            r'\b(?:M)\s*(\d+)\b',                   # M2
            r'(\d+)\s*(?:MINUTE)',                  # 2 MINUTE
            r'EXP(?:IRY)?[:\s]*(\d+)',             # EXPIRY: 2 or EXP 2
        ]

        for pattern in time_patterns:
            time_match = re.search(pattern, text)
            if time_match:
                duration = int(time_match.group(1))
                break

        # Validate duration (1-5 minutes for binary)
        duration = max(1, min(duration, 5))

        return final_asset, direction, duration


# ==========================================
# 🤖 MAIN TRADING BOT
# ==========================================

class OTCTradingBot:
    """
    Main trading bot that orchestrates all components.

    Features:
    - Telegram signal listening
    - IQ Option trade execution
    - AI-powered analysis (optional)
    - Martingale strategy (configurable levels)
    - Real-time trade monitoring
    - Comprehensive logging
    """

    def __init__(self, config: dict):
        self.config = config
        self.iq_api: Optional[IQ_Option] = None
        self.telegram_client: Optional[TelegramClient] = None
        self.market_analyzer: Optional[MarketAnalyzer] = None
        self.ai_analyzer: Optional[AIAnalyzer] = None
        self.trade_logger: Optional[TradeLogger] = None
        self.trade_monitor: Optional[TradeMonitor] = None
        self.signal_parser: Optional[SignalParser] = None
        self.is_running = False
        self.trade_lock = Lock()

    def connect_iq_option(self) -> bool:
        """Connect to IQ Option API."""
        print("🔌 Connecting to IQ Option...")

        try:
            self.iq_api = IQ_Option(
                self.config['iq_email'],
                self.config['iq_password']
            )
            check, reason = self.iq_api.connect()

            if check:
                balance = self.iq_api.get_balance()
                print(f"✅ Connected successfully!")
                print(f"   Balance: ${balance:.2f}")
                self.iq_api.change_balance(self.config['account_type'])
                print(f"   Account: {self.config['account_type']}")
                return True
            else:
                print(f"❌ Connection Failed: {reason}")
                return False

        except Exception as e:
            print(f"❌ Connection Error: {e}")
            return False

    def initialize_components(self):
        """Initialize all bot components."""
        self.market_analyzer = MarketAnalyzer(self.iq_api)

        self.ai_analyzer = AIAnalyzer(
            self.config.get('ai_api_key', ''),
            self.config.get('ai_enabled', False),
            self.config.get('confidence_threshold', 0.7)
        )

        self.trade_logger = TradeLogger(
            self.config.get('log_file', 'trade_log.json')
        )

        self.trade_monitor = TradeMonitor(
            self.iq_api,
            self.trade_logger,
            self.config.get('martingale', {'enabled': False})
        )
        self.trade_monitor.on_martingale_trigger = self._execute_martingale_trade

        self.signal_parser = SignalParser(
            self.iq_api,
            self.config.get('default_duration', 2)
        )

    def _execute_martingale_trade(self, asset: str, direction: str,
                                   duration: int, amount: float, martingale_level: int):
        """Execute a martingale trade (called by monitor after a loss)."""
        self._place_trade(
            asset, direction, duration, amount,
            martingale_level, skip_analysis=True
        )

    def _place_trade(self, asset: str, direction: str, duration: int,
                     amount: float, martingale_level: int = 0, skip_analysis: bool = False,
                     ai_confidence: float = 1.0, reasoning: str = ""):
        """Place a trade on IQ Option."""
        with self.trade_lock:
            try:
                # Check balance before trading
                current_balance = self.iq_api.get_balance()
                if current_balance < amount:
                    print(f"❌ Insufficient balance! Have: ${current_balance:.2f}, Need: ${amount:.2f}")
                    return

                check, order_id = self.iq_api.buy(amount, asset, direction, duration)

                if check:
                    level_str = f" [Martingale L{martingale_level}]" if martingale_level > 0 else ""
                    print(f"✅ Trade Placed!{level_str}")
                    print(f"   Order ID: {order_id}")
                    print(f"   Amount: ${amount:.2f}")
                    print(f"   New Balance: ${self.iq_api.get_balance():.2f}")

                    # Log trade
                    self.trade_logger.log_trade(
                        asset, direction, duration, order_id, amount,
                        martingale_level, ai_confidence,
                        reasoning if reasoning else ("Martingale" if martingale_level > 0 else "Signal")
                    )

                    # Start monitoring
                    self.trade_monitor.monitor_trade(
                        order_id, asset, direction, duration, amount, martingale_level
                    )
                else:
                    print(f"❌ Trade Failed: {order_id}")

            except Exception as e:
                print(f"⚠️ Trade Error: {e}")

    def execute_trade(self, asset: str, direction: str, duration: int):
        """Execute trade with optional AI validation and market analysis."""
        print(f"\n{'=' * 50}")
        print(f"🚀 NEW SIGNAL RECEIVED")
        print(f"   Asset: {asset}")
        print(f"   Direction: {direction.upper()}")
        print(f"   Duration: {duration}M")
        print(f"{'=' * 50}")

        indicators = None
        ai_confidence = 1.0
        reasoning = "Direct signal execution"

        # Market analysis
        print("\n📊 Fetching market data...")
        candles = self.market_analyzer.get_market_data(
            asset.replace("-OTC", ""),
            timeframe=120,  # 2-minute candles
            candle_count=50
        )

        if candles:
            indicators = self.market_analyzer.calculate_indicators(candles)
            if indicators:
                print(f"   Price: {indicators['current_price']}")
                print(f"   RSI: {indicators['rsi']}")
                print(f"   Trend: {indicators['trend']}")
                print(f"   Momentum: {indicators['momentum']}%")
                print(f"   Volatility: {indicators['volatility']}%")

                # Basic condition check
                is_favorable, condition_reason = self.market_analyzer.is_favorable_condition(
                    indicators, direction
                )
                print(f"   Condition: {condition_reason}")
        else:
            print("   ⚠️ Could not fetch market data")
            indicators = {"rsi": 50, "trend": "unknown", "current_price": 0}

        # AI Analysis (if enabled)
        if self.config.get('ai_enabled', False):
            print("\n🤖 AI Analysis...")
            should_trade, ai_confidence, reasoning = self.ai_analyzer.analyze(
                asset, direction, indicators
            )
            print(f"   Should Trade: {'Yes' if should_trade else 'No'}")
            print(f"   Confidence: {ai_confidence * 100:.0f}%")
            print(f"   Reasoning: {reasoning}")

            if not should_trade or ai_confidence < self.config.get('confidence_threshold', 0.7):
                threshold = self.config.get('confidence_threshold', 0.7) * 100
                print(f"\n❌ TRADE SKIPPED")
                print(f"   Confidence {ai_confidence * 100:.0f}% < Threshold {threshold:.0f}%")
                return

        # Execute trade
        print(f"\n💰 Executing trade...")
        self._place_trade(
            asset, direction, duration,
            self.config['trade_amount'],
            martingale_level=0,
            skip_analysis=False,
            ai_confidence=ai_confidence,
            reasoning=reasoning
        )

    def start(self):
        """Start the trading bot."""
        print("\n" + "=" * 60)
        print("🤖 OTC TRADING BOT v2.0")
        print("=" * 60)

        # Connect to IQ Option
        if not self.connect_iq_option():
            return

        # Initialize components
        self.initialize_components()

        # Print configuration
        print(f"\n⚙️ CONFIGURATION")
        print(f"   Account Type: {self.config['account_type']}")
        print(f"   Base Trade Amount: ${self.config['trade_amount']:.2f}")
        print(f"   Default Duration: {self.config.get('default_duration', 2)}M")
        print(f"   AI Analysis: {'Enabled' if self.config.get('ai_enabled') else 'Disabled'}")

        if self.config.get('ai_enabled'):
            print(f"   Confidence Threshold: {self.config.get('confidence_threshold', 0.7) * 100:.0f}%")

        martingale = self.config.get('martingale', {})
        if martingale.get('enabled'):
            print(f"   Martingale: Enabled")
            print(f"      Max Level: {martingale.get('max_level', 3)}")
            print(f"      Multiplier: {martingale.get('multiplier', 2.2)}x")

            # Calculate max risk
            base = self.config['trade_amount']
            mult = martingale.get('multiplier', 2.2)
            max_level = martingale.get('max_level', 3)
            total_risk = sum(base * (mult ** i) for i in range(max_level + 1))
            print(f"      Max Risk (all levels): ${total_risk:.2f}")
        else:
            print(f"   Martingale: Disabled")

        # Setup Telegram client
        self.telegram_client = TelegramClient(
            'otc_session',
            self.config['api_id'],
            self.config['api_hash']
        )

        @self.telegram_client.on(events.NewMessage(chats=self.config['channel_name']))
        async def handler(event):
            message = event.message.message
            print(f"\n📩 New message received:")
            print(f"   {message[:100]}{'...' if len(message) > 100 else ''}")

            data = self.signal_parser.parse(message)
            if data:
                asset, direction, duration = data
                self.execute_trade(asset, direction, duration)
            else:
                print("   ⚠️ Could not parse signal from message")

        print(f"\n🎧 Bot is now listening for signals...")
        print(f"   Channel: {self.config['channel_name']}")
        print(f"   Press Ctrl+C to stop\n")

        self.is_running = True

        try:
            self.telegram_client.start()
            self.telegram_client.run_until_disconnected()
        except KeyboardInterrupt:
            print("\n\n🛑 Bot stopped by user")
            self.stop()

    def stop(self):
        """Stop the bot and print statistics."""
        self.is_running = False

        if self.trade_logger:
            self.trade_logger.print_statistics()

        if self.telegram_client:
            self.telegram_client.disconnect()

        print("\n👋 Goodbye!")


# ==========================================
# 🚀 ENTRY POINT
# ==========================================

if __name__ == "__main__":
    # ========================================
    # ⚙️ BOT CONFIGURATION
    # ========================================
    config = {
        # Telegram API (get from my.telegram.org)
        "api_id": int(os.environ.get("TG_API_ID", "0")),
        "api_hash": os.environ.get("TG_API_HASH", ""),
        "channel_name": int(os.environ.get("TG_CHANNEL_ID", "0")),

        # IQ Option Credentials
        "iq_email": os.environ.get("IQ_EMAIL", ""),
        "iq_password": os.environ.get("IQ_PASSWORD", ""),
        "account_type": "PRACTICE",  # "PRACTICE" or "REAL"

        # Trading Settings
        "trade_amount": 1.0,      # Base trade amount in $
        "default_duration": 2,     # Default duration in minutes

        # AI Analysis (Optional - requires OpenAI API key)
        "ai_api_key": "your_openai_api_key",  # Get from platform.openai.com
        "ai_enabled": False,       # Set to True to enable AI analysis
        "confidence_threshold": 0.7,  # Minimum confidence to execute trade (0.0-1.0)

        # Martingale Strategy
        "martingale": {
            "enabled": True,       # Enable/disable martingale
            "max_level": 3,        # Maximum martingale attempts (1-3 recommended)
            "multiplier": 2.2      # Amount multiplier after each loss
        },

        # Logging
        "log_file": "trade_log.json"
    }

    # ========================================
    # 🚀 START BOT
    # ========================================
    bot = OTCTradingBot(config)
    bot.start()

