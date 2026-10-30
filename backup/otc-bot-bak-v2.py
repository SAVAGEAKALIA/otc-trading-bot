"""
OTC Trading Bot v2.1
====================
A robust Telegram signal trading bot for IQ Option with:
- Fractional Kelly Criterion position sizing
- Fixed percentage sizing (alternative)
- Proper RSI calculation
- Async architecture with single API worker
- Real-time trade monitoring
- AI-powered trade analysis (optional)
- Comprehensive trade logging

Author: Trading Bot
Version: 2.1
"""

import re
import time
import json
import asyncio
import os
import tempfile
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from telethon import TelegramClient, events
from trading_platform.vendor.iqoptionapi.iqoptionapi.stable_api import IQ_Option
import requests

# Global defaults
DEFAULT_PAYOUT = 0.80  # 80% default payout when broker data is unavailable
DEFAULT_TIMEZONE = "Africa/Lagos"  # Signal channel timezone (adjust as needed)

# Suppress threading errors from trading_platform.vendor.iqoptionapi.iqoptionapi library
import logging
logging.getLogger('iqoptionapi').setLevel(logging.CRITICAL)

def _suppress_thread_exception(args):
    """Suppress known iqoptionapi threading errors."""
    exc_str = str(args.exc_value)
    # Ignore known iqoptionapi internal errors
    if any(x in exc_str for x in ["'underlying'", "KeyError", "digital"]):
        return  # Silently ignore
    # Print other exceptions normally
    import traceback
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

threading.excepthook = _suppress_thread_exception


# ==========================================
# 📊 DATA CLASSES & ENUMS
# ==========================================

class SizingMethod(Enum):
    """Position sizing methods."""
    FIXED_AMOUNT = "fixed_amount"
    FIXED_PERCENTAGE = "fixed_percentage"
    FRACTIONAL_KELLY = "fractional_kelly"


@dataclass
class TradeSignal:
    """Represents a parsed trade signal."""
    asset: str
    direction: str  # "call" or "put"
    duration: int   # minutes
    entry_time: Optional[datetime] = None  # Scheduled entry time
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TradeRequest:
    """Request to place a trade via the API worker."""
    signal: TradeSignal
    ai_confidence: float = 1.0
    reasoning: str = ""


# ==========================================
# 💰 POSITION SIZING
# ==========================================

class PositionSizer:
    """
    Handles position sizing using various methods:
    - Fixed Amount: Always trade the same dollar amount
    - Fixed Percentage: Trade X% of current balance
    - Fractional Kelly: Use Kelly Criterion with a safety fraction
    """

    def __init__(self, config: dict):
        self.method = SizingMethod(config.get('method', 'fixed_percentage'))
        self.fixed_amount = config.get('fixed_amount', 1.0)
        self.fixed_percentage = config.get('fixed_percentage', 0.01)  # 1%
        self.kelly_fraction = config.get('kelly_fraction', 0.25)  # 1/4 Kelly
        self.min_trade = config.get('min_trade', 1.0)
        self.max_trade = config.get('max_trade', 100.0)
        self.max_risk_percentage = config.get('max_risk_percentage', 0.05)  # Max 5% per trade

    def calculate_size(self, balance: float, win_rate: float = 0.55,
                       payout: float = DEFAULT_PAYOUT) -> float:
        """
        Calculate position size based on configured method.

        Args:
            balance: Current account balance
            win_rate: Historical win rate (0.0-1.0)
            payout: Broker payout rate (e.g., 0.80 = 80%)

        Returns:
            Trade amount in dollars
        """
        if self.method == SizingMethod.FIXED_AMOUNT:
            size = self.fixed_amount

        elif self.method == SizingMethod.FIXED_PERCENTAGE:
            size = balance * self.fixed_percentage

        elif self.method == SizingMethod.FRACTIONAL_KELLY:
            size = self._calculate_kelly(balance, win_rate, payout)

        else:
            size = self.fixed_amount

        # Apply constraints
        size = max(self.min_trade, size)
        size = min(self.max_trade, size)
        size = min(balance * self.max_risk_percentage, size)  # Never risk more than max %

        return round(size, 2)

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
        """
        p = win_rate
        q = 1 - p
        b = payout

        # Full Kelly
        if b <= 0:
            return self.min_trade

        kelly = (b * p - q) / b

        # If Kelly is negative, edge is negative - don't bet
        if kelly <= 0:
            print(f"   ⚠️ Negative Kelly ({kelly:.2%}) - using minimum size")
            return self.min_trade

        # Apply fraction (e.g., 1/4 Kelly)
        fractional_kelly = kelly * self.kelly_fraction

        # Calculate dollar amount
        size = balance * fractional_kelly

        return size

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
            return f"{fraction_name} Kelly Criterion"
        return "Unknown"


# ==========================================
# 📊 MARKET ANALYZER
# ==========================================

class MarketAnalyzer:
    """Handles market data fetching and technical analysis."""

    def __init__(self):
        self.candle_cache: Dict[str, list] = {}

    def calculate_indicators(self, candles: list, rsi_period: int = 14) -> Optional[Dict[str, Any]]:
        """
        Calculate technical indicators from candle data.

        Args:
            candles: List of candle dictionaries
            rsi_period: Period for RSI calculation (default 14)

        Returns:
            Dictionary with indicators or None if insufficient data
        """
        if not candles or len(candles) < rsi_period + 1:
            return None

        closes = [c['close'] for c in candles]
        highs = [c['max'] for c in candles]
        lows = [c['min'] for c in candles]
        volumes = [c['volume'] for c in candles]

        # Simple Moving Averages
        sma_10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else closes[-1]
        sma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else closes[-1]

        # RSI Calculation (FIXED)
        rsi = self._calculate_rsi(closes, rsi_period)

        # Trend detection
        trend = "bullish" if sma_10 > sma_20 else "bearish"

        # Momentum (rate of change)
        if len(closes) >= 10 and closes[-10] != 0:
            momentum = ((closes[-1] - closes[-10]) / closes[-10]) * 100
        else:
            momentum = 0

        # Volatility (ATR-like)
        if len(highs) >= 10:
            ranges = [highs[-i] - lows[-i] for i in range(1, 11)]
            avg_range = sum(ranges) / len(ranges)
            volatility = (avg_range / closes[-1]) * 100 if closes[-1] != 0 else 0
        else:
            volatility = 0

        return {
            "current_price": closes[-1],
            "sma_10": round(sma_10, 5),
            "sma_20": round(sma_20, 5),
            "rsi": round(rsi, 2),
            "trend": trend,
            "momentum": round(momentum, 2),
            "recent_high": max(highs[-20:]) if len(highs) >= 20 else max(highs),
            "recent_low": min(lows[-20:]) if len(lows) >= 20 else min(lows),
            "avg_volume": sum(volumes[-10:]) / 10 if len(volumes) >= 10 else sum(volumes) / len(volumes),
            "volatility": round(volatility, 2)
        }

    def _calculate_rsi(self, closes: list, period: int = 14) -> float:
        """
        Calculate RSI properly.

        RSI = 100 - (100 / (1 + RS))
        RS = Average Gain / Average Loss

        Args:
            closes: List of closing prices
            period: RSI period (default 14)

        Returns:
            RSI value (0-100)
        """
        if len(closes) < period + 1:
            return 50.0  # Neutral if insufficient data

        # Calculate price differences for the last 'period' periods
        diffs = []
        for i in range(len(closes) - period, len(closes)):
            if i > 0:
                diffs.append(closes[i] - closes[i - 1])

        if len(diffs) < period:
            return 50.0

        # Use exactly 'period' diffs
        diffs = diffs[-period:]

        # Calculate average gain and loss (including zeros)
        gains = [max(d, 0) for d in diffs]
        losses = [max(-d, 0) for d in diffs]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        # Handle edge case where avg_loss is 0
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

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
        volatility = indicators.get('volatility', 0)

        warnings = []

        if direction == "call":
            if rsi > 80:
                return False, f"RSI overbought ({rsi:.1f}) - avoid CALL"
            if rsi > 70:
                warnings.append(f"RSI high ({rsi:.1f})")
            if trend == "bearish" and rsi > 60:
                warnings.append(f"Against trend")
        else:  # put
            if rsi < 20:
                return False, f"RSI oversold ({rsi:.1f}) - avoid PUT"
            if rsi < 30:
                warnings.append(f"RSI low ({rsi:.1f})")
            if trend == "bullish" and rsi < 40:
                warnings.append(f"Against trend")

        if volatility > 3:
            warnings.append(f"High volatility ({volatility:.1f}%)")

        if warnings:
            return True, f"Caution: {', '.join(warnings)}"

        return True, f"Favorable for {direction.upper()} (RSI: {rsi:.1f}, Trend: {trend})"


# ==========================================
# 🤖 AI ANALYZER
# ==========================================

class AIAnalyzer:
    """Handles AI-based trade analysis using OpenAI API."""

    def __init__(self, api_key: str, enabled: bool = True, confidence_threshold: float = 0.7):
        self.api_key = api_key
        self.enabled = enabled
        self.confidence_threshold = confidence_threshold

    async def analyze(self, asset: str, direction: str, indicators: dict) -> Tuple[bool, float, str]:
        """
        Send market data to AI for trade decision (async).

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

        RULES:
        - For CALL: RSI should not be >75, trend should not be strongly bearish
        - For PUT: RSI should not be <25, trend should not be strongly bullish
        - High volatility (>2%) increases risk

        Respond ONLY in this exact JSON format:
        {{"should_trade": true, "confidence": 0.75, "reasoning": "brief explanation"}}
        """

        try:
            # Run in executor to not block async loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
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
        self.trade_history: List[dict] = []
        self._load_history()

    def _load_history(self):
        """Load existing trade history from file."""
        try:
            with open(self.log_file, "r") as f:
                self.trade_history = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.trade_history = []

    def log_trade(self, asset: str, direction: str, duration: int, order_id: int,
                  amount: float, ai_confidence: float, reasoning: str) -> dict:
        """Log a new trade."""
        trade = {
            "timestamp": datetime.now().isoformat(),
            "asset": asset,
            "direction": direction,
            "duration": duration,
            "order_id": order_id,
            "amount": amount,
            "ai_confidence": ai_confidence,
            "reasoning": reasoning,
            "result": None,
            "profit": None
        }

        self.trade_history.append(trade)
        self._save()

        return trade

    def update_result(self, order_id: int, result: str, profit: float):
        """Update trade result after expiration."""
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

    def get_win_rate(self, last_n: int = 50) -> float:
        """
        Calculate win rate from recent trades.

        Args:
            last_n: Number of recent trades to consider

        Returns:
            Win rate as decimal (0.0-1.0)
        """
        completed = [t for t in self.trade_history if t.get('result') in ('win', 'lose')]

        if not completed:
            return 0.55  # Default assumption

        recent = completed[-last_n:] if len(completed) > last_n else completed
        wins = len([t for t in recent if t['result'] == 'win'])

        return wins / len(recent) if recent else 0.55

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
        print(f"\n📊 TRADING STATISTICS")
        print(f"   Total Trades: {stats['total']}")
        print(f"   Wins: {stats['wins']} | Losses: {stats['losses']}")
        print(f"   Win Rate: {stats['win_rate']}%")
        print(f"   Total Profit: ${stats['total_profit']:.2f}")


class AtomicTradeLogger(TradeLogger):
    """
    Crash-safe logger using atomic file writes.
    Prevents data corruption if power/script fails during write.
    """

    def _save(self):
        """Write to temp file then atomic rename."""
        temp_path = None
        try:
            # Get directory of log file
            log_dir = os.path.dirname(self.log_file)
            if not log_dir:
                log_dir = '.'

            # 1. Write to a temporary file first
            fd, temp_path = tempfile.mkstemp(dir=log_dir, suffix='.tmp', text=True)
            with os.fdopen(fd, 'w') as f:
                json.dump(self.trade_history, f, indent=2)

            # 2. Atomic replace (instant swap)
            os.replace(temp_path, self.log_file)

        except Exception as e:
            print(f"⚠️ Atomic Save Error: {e}")
            # Cleanup temp file if it exists
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass


# ==========================================
# 🛡️ SESSION MANAGER (RISK CONTROL)
# ==========================================

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


# ==========================================
# 📡 SIGNAL PARSER
# ==========================================

class SignalParser:
    """Handles parsing of trading signals from Telegram messages."""

    def __init__(self, default_duration: int = 2, timezone: str = DEFAULT_TIMEZONE):
        self.default_duration = default_duration
        try:
            self.timezone = ZoneInfo(timezone)
        except Exception:
            print(f"⚠️ Invalid timezone '{timezone}', using UTC")
            self.timezone = ZoneInfo("UTC")

    def parse(self, message_text: str, available_assets: dict) -> Optional[TradeSignal]:
        """
        Parse raw text into TradeSignal.

        Args:
            message_text: Raw message text
            available_assets: Dict of available assets from IQ Option

        Returns:
            TradeSignal or None if parsing fails
        """
        # Remove emoji flags and other unicode characters that might interfere
        # Keep only ASCII letters, numbers, spaces, and common punctuation
        clean_text = re.sub(r'[^\x00-\x7F]+', ' ', message_text)
        text = clean_text.upper()

        # Also keep original for direction detection (emojis matter there)
        original_upper = message_text.upper()

        # Extract asset - look for currency pair pattern like "USD/JPY", "EUR-USD", "AUD USD"
        # Must be exactly 3 letters, separator, 3 letters
        full_asset_match = re.search(r'\b([A-Z]{3})\s*[/\-\s]\s*([A-Z]{3})\b', text)
        if not full_asset_match:
            return None

        raw_asset = full_asset_match.group(1) + full_asset_match.group(2)

        # Try different asset name formats that IQ Option might use
        otc_formats = [
            f"{raw_asset}-OTC",      # EURCAD-OTC
            f"{raw_asset}_OTC",      # EURCAD_OTC
            f"{raw_asset}OTC",       # EURCADOTC
        ]
        regular_formats = [raw_asset]  # EURCAD

        final_asset = None

        # Helper function to check if asset is available
        def find_asset_in_dict(asset_dict: dict, formats: list) -> Optional[str]:
            for fmt in formats:
                # Exact match
                if fmt in asset_dict and asset_dict[fmt].get('open'):
                    return fmt
                # Case-insensitive search
                for key in asset_dict:
                    if key.upper().replace("_", "-").replace("OTC", "-OTC") == fmt.upper().replace("_", "-"):
                        if asset_dict[key].get('open'):
                            return key
            return None

        # Check binary options first
        if available_assets and 'binary' in available_assets:
            # Try OTC first (available 24/7)
            final_asset = find_asset_in_dict(available_assets['binary'], otc_formats)
            # Then regular
            if not final_asset:
                final_asset = find_asset_in_dict(available_assets['binary'], regular_formats)

        # Check turbo options as fallback
        if not final_asset and available_assets and 'turbo' in available_assets:
            final_asset = find_asset_in_dict(available_assets['turbo'], otc_formats)
            if not final_asset:
                final_asset = find_asset_in_dict(available_assets['turbo'], regular_formats)

        # If still not found, try to use the OTC format anyway (it might work)
        if not final_asset:
            # Check if we have any data at all
            if not available_assets:
                print(f"   ⚠️ No asset data available, trying {otc_formats[0]} anyway")
                final_asset = otc_formats[0]
            else:
                print(f"⚠️ Asset {raw_asset} / {otc_formats[0]} is not available for trading")
                return None

        # Extract direction (use original text with emojis for better detection)
        # Note: 📈 and 📉 are removed as they're often used as decoration, not direction
        # Prioritize explicit text patterns over emojis

        direction = None
        check_text = original_upper + " " + text

        # First check explicit text patterns (most reliable)
        # Check SELL/PUT patterns FIRST since BUY appears in some decoration text
        text_put_patterns = ["DIRECTION: SELL", "DIRECTION:SELL", "DIRECTION SELL", ": SELL", " SELL ", "SELL ", " PUT ", "PUT "]
        text_call_patterns = ["DIRECTION: BUY", "DIRECTION:BUY", "DIRECTION BUY", ": BUY", " BUY ", "BUY ", " CALL ", "CALL "]

        for pattern in text_put_patterns:
            if pattern in check_text:
                direction = "put"
                break

        if not direction:
            for pattern in text_call_patterns:
                if pattern in check_text:
                    direction = "call"
                    break

        # If no explicit text found, use emoji patterns (excluding chart emojis)
        if not direction:
            call_emoji_patterns = ["⬆", "🟢", "🔼", "🟩"]
            put_emoji_patterns = ["⬇", "🔴", "🔽", "🟥"]

            if any(x in check_text for x in call_emoji_patterns):
                direction = "call"
            elif any(x in check_text for x in put_emoji_patterns):
                direction = "put"

        # Fallback to generic patterns
        if not direction:
            if any(x in check_text for x in ["UP", "LONG", "GREEN"]):
                direction = "call"
            elif any(x in check_text for x in ["DOWN", "SHORT", "RED"]):
                direction = "put"

        if not direction:
            return None

        # Extract duration
        duration = self.default_duration

        time_patterns = [
            r'(\d+)\s*(?:M(?:IN(?:UTES?)?)?)\b',
            r'\b(?:M)\s*(\d+)\b',
            r'(\d+)\s*(?:MINUTE)',
            r'EXP(?:IRY)?[:\s]*(\d+)',
        ]

        for pattern in time_patterns:
            time_match = re.search(pattern, text)
            if time_match:
                duration = int(time_match.group(1))
                break

        # Validate duration (1-5 minutes for binary)
        duration = max(1, min(duration, 5))

        # Extract entry time (e.g., "Entry Time: 4:02 PM" or "Entry Time: 16:02")
        entry_time = self._parse_entry_time(text)

        return TradeSignal(
            asset=final_asset,
            direction=direction,
            duration=duration,
            entry_time=entry_time
        )

    def _parse_entry_time(self, text: str) -> Optional[datetime]:
        """
        Parse entry time from signal text.

        Supports formats:
        - "Entry Time: 4:02 PM"
        - "Entry Time: 16:02"
        - "Entry: 4:02PM"

        Returns timezone-aware datetime.
        """
        # Pattern for 12-hour format (e.g., "4:02 PM", "4:02PM")
        pattern_12h = r'ENTRY\s*(?:TIME)?[:\s]*(\d{1,2}):(\d{2})\s*(AM|PM)'
        match = re.search(pattern_12h, text, re.IGNORECASE)

        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            period = match.group(3).upper()

            # Convert to 24-hour format
            if period == "PM" and hour != 12:
                hour += 12
            elif period == "AM" and hour == 12:
                hour = 0

            # Create timezone-aware datetime for today
            now = datetime.now(self.timezone)
            entry_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If the time has already passed by more than 12 hours, assume tomorrow
            time_diff = (now - entry_time).total_seconds()
            if time_diff > 12 * 3600:
                entry_time = entry_time + timedelta(days=1)

            return entry_time

        # Pattern for 24-hour format (e.g., "16:02")
        pattern_24h = r'ENTRY\s*(?:TIME)?[:\s]*(\d{1,2}):(\d{2})(?!\s*[AP]M)'
        match = re.search(pattern_24h, text, re.IGNORECASE)

        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))

            now = datetime.now(self.timezone)
            entry_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            time_diff = (now - entry_time).total_seconds()
            if time_diff > 12 * 3600:
                entry_time = entry_time + timedelta(days=1)

            return entry_time

        return None  # No entry time found - execute immediately


# ==========================================
# 🔧 API WORKER (Single-threaded IQ Option access)
# ==========================================

class APIWorker:
    """Single worker that handles all IQ Option API calls."""

    def __init__(self, iq_api: IQ_Option, trade_logger: TradeLogger,
                 position_sizer: PositionSizer, market_analyzer: MarketAnalyzer,
                 session_manager: Optional[SessionManager] = None):
        self.api = iq_api
        self.logger = trade_logger
        self.sizer = position_sizer
        self.analyzer = market_analyzer
        self.session_manager = session_manager
        self.trade_queue: asyncio.Queue = asyncio.Queue()
        self.active_trades: Dict[int, dict] = {}
        self.running = False
        self.payout_rate = DEFAULT_PAYOUT  # Default, updated dynamically

    async def start(self):
        """Start the API worker."""
        self.running = True
        # Run trade processor, result checker, AND connection maintainer
        await asyncio.gather(
            self._process_trades(),
            self._check_results(),
            self._maintain_connection()  # Keep connection alive
        )

    async def stop(self):
        """Stop the API worker."""
        self.running = False

    async def submit_trade(self, request: TradeRequest):
        """Submit a trade request to the queue."""
        await self.trade_queue.put(request)

    async def _process_trades(self):
        """Process trades from the queue (single point of API access)."""
        while self.running:
            try:
                # Wait for trade request with timeout
                try:
                    request = await asyncio.wait_for(
                        self.trade_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                await self._execute_trade(request)
                self.trade_queue.task_done()

            except Exception as e:
                print(f"⚠️ Trade processor error: {e}")

    async def _execute_trade(self, request: TradeRequest):
        """Execute a single trade (runs in executor to not block)."""
        signal = request.signal

        print(f"\n💰 Executing trade...")

        # Get current balance and calculate position size
        loop = asyncio.get_event_loop()

        try:
            balance = await loop.run_in_executor(None, self.api.get_balance)
            win_rate = self.logger.get_win_rate()

            # Get payout for this asset (default to 80% for OTC)
            self.payout_rate = await self._get_payout(signal.asset)

            # Ensure minimum reasonable payout for Kelly calculation
            if self.payout_rate < 0.5:
                print(f"   ⚠️ Payout too low ({self.payout_rate*100:.0f}%), using default 80%")
                self.payout_rate = 0.80

            amount = self.sizer.calculate_size(balance, win_rate, self.payout_rate)

            print(f"   Balance: ${balance:.2f}")
            print(f"   Win Rate: {win_rate*100:.1f}%")
            print(f"   Payout: {self.payout_rate*100:.0f}%")
            print(f"   Position Size: ${amount:.2f}")

            if balance < amount:
                print(f"❌ Insufficient balance! Have: ${balance:.2f}, Need: ${amount:.2f}")
                return

            # Place trade - wrap in try/except to catch specific errors
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: self.api.buy(amount, signal.asset, signal.direction, signal.duration)
                )

                # Handle different return formats
                if isinstance(result, tuple) and len(result) >= 2:
                    check, order_id = result[0], result[1]
                else:
                    check, order_id = False, str(result)

            except Exception as buy_error:
                print(f"❌ Buy API error: {buy_error}")
                # Try with alternative asset format
                alt_asset = signal.asset.replace("-OTC", "_OTC") if "-OTC" in signal.asset else signal.asset
                print(f"   Retrying with asset format: {alt_asset}")
                try:
                    result = await loop.run_in_executor(
                        None,
                        lambda: self.api.buy(amount, alt_asset, signal.direction, signal.duration)
                    )
                    if isinstance(result, tuple) and len(result) >= 2:
                        check, order_id = result[0], result[1]
                    else:
                        check, order_id = False, str(result)
                except Exception as retry_error:
                    print(f"❌ Retry also failed: {retry_error}")
                    return

            if check:
                print(f"✅ Trade Placed!")
                print(f"   Order ID: {order_id}")
                print(f"   Amount: ${amount:.2f}")

                new_balance = await loop.run_in_executor(None, self.api.get_balance)
                print(f"   New Balance: ${new_balance:.2f}")

                # Log trade
                self.logger.log_trade(
                    signal.asset, signal.direction, signal.duration,
                    order_id, amount, request.ai_confidence, request.reasoning
                )

                # Track for result checking
                expiry_time = time.time() + (signal.duration * 60) + 10
                self.active_trades[order_id] = {
                    "asset": signal.asset,
                    "direction": signal.direction,
                    "amount": amount,
                    "expiry_time": expiry_time
                }
            else:
                print(f"❌ Trade Failed: {order_id}")

        except Exception as e:
            import traceback
            print(f"⚠️ Trade execution error: {e}")
            traceback.print_exc()

    async def _get_payout(self, asset: str) -> float:
        """Get current payout rate for asset."""
        try:
            loop = asyncio.get_event_loop()
            all_profit = await loop.run_in_executor(
                None,
                self.api.get_all_profit
            )

            if not all_profit:
                return DEFAULT_PAYOUT

            # Try different asset name formats
            asset_keys_to_try = [
                asset,                          # EURCAD-OTC
                asset.replace("-OTC", ""),      # EURCAD
                asset.lower(),                  # eurcad-otc
                asset.replace("-OTC", "").lower(),  # eurcad
            ]

            for key in asset_keys_to_try:
                if key in all_profit:
                    profit_data = all_profit[key]

                    # Handle different response formats
                    if isinstance(profit_data, dict):
                        payout = profit_data.get('binary', profit_data.get('turbo', None))
                        if payout is None:
                            # Try getting any numeric value
                            for v in profit_data.values():
                                if isinstance(v, (int, float)) and v > 1:
                                    payout = v
                                    break
                    elif isinstance(profit_data, (int, float)):
                        payout = profit_data
                    else:
                        continue

                    # Validate payout is reasonable (typically 70-95%)
                    if payout is not None:
                        if 50 <= payout <= 100:
                            return payout / 100
                        elif 0.5 <= payout <= 1.0:
                            return payout
                        elif 1 < payout < 50:
                            # Might be percentage in different format
                            return DEFAULT_PAYOUT

        except Exception as e:
            print(f"   ⚠️ Could not get payout: {e}")

        # Default 80% payout for OTC assets
        return DEFAULT_PAYOUT

    async def _check_results(self):
        """Periodically check results of active trades."""
        while self.running:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds

                current_time = time.time()
                completed = []

                for order_id, trade_info in list(self.active_trades.items()):
                    if current_time >= trade_info['expiry_time']:
                        # Check result
                        result, profit = await self._check_single_result(order_id, trade_info['amount'])

                        if result != "pending":
                            completed.append(order_id)

                            if result == "win":
                                print(f"\n🎉 Trade {order_id} WON! Profit: +${profit:.2f}")
                            elif result == "lose":
                                print(f"\n😔 Trade {order_id} LOST! Amount: -${trade_info['amount']:.2f}")
                                profit = -trade_info['amount']  # Ensure negative for losses
                            elif result == "tie":
                                print(f"\n🔄 Trade {order_id} TIE! Amount returned.")
                                profit = 0

                            # Update logger
                            self.logger.update_result(order_id, result, profit)

                            # Register with session manager for risk control
                            if self.session_manager:
                                self.session_manager.register_result(profit)

                # Remove completed trades
                for order_id in completed:
                    del self.active_trades[order_id]

            except Exception as e:
                print(f"⚠️ Result checker error: {e}")

    async def _check_single_result(self, order_id: int, amount: float) -> Tuple[str, float]:
        """Check result of a single trade."""
        loop = asyncio.get_event_loop()

        for attempt in range(5):
            try:
                # Use check_win_v3 which returns the profit/loss directly
                result = await loop.run_in_executor(
                    None,
                    lambda oid=order_id: self.api.check_win_v3(oid)
                )

                # Handle different return types from the API
                if result is None:
                    await asyncio.sleep(2)
                    continue

                # If result is a tuple, extract the value
                if isinstance(result, tuple):
                    result = result[0] if result else None

                if result is not None and isinstance(result, (int, float)):
                    if result > 0:
                        return "win", float(result)
                    elif result < 0:
                        return "lose", float(result)
                    else:
                        return "tie", 0.0

            except Exception as e:
                if attempt == 4:
                    print(f"   ⚠️ Could not check result for {order_id}: {e}")

            await asyncio.sleep(2)

        return "unknown", 0

    async def _maintain_connection(self):
        """Background task to ensure API connection stays alive."""
        print("🔌 Connection monitor started")
        while self.running:
            try:
                # Run the blocking check in executor
                loop = asyncio.get_event_loop()
                is_connected = await loop.run_in_executor(
                    None,
                    self.api.check_connect
                )

                if not is_connected:
                    print("\n⚠️ Connection lost! Attempting reconnect...")

                    # Try to reconnect
                    reconnect_result = await loop.run_in_executor(
                        None,
                        self.api.connect
                    )

                    # Handle different return formats from connect()
                    if isinstance(reconnect_result, tuple):
                        reconnected = reconnect_result[0]
                    else:
                        reconnected = bool(reconnect_result)

                    if reconnected:
                        print("✅ Reconnected successfully!")
                        # Refresh balance to verify session
                        balance = await loop.run_in_executor(None, self.api.get_balance)
                        print(f"   Balance: ${balance:.2f}")
                    else:
                        print("❌ Reconnection failed. Retrying in 10s...")

                await asyncio.sleep(10)  # Check every 10 seconds

            except Exception as e:
                print(f"⚠️ Connection monitor error: {e}")
                await asyncio.sleep(10)

    async def get_market_data(self, asset: str, timeframe: int = 120,
                               candle_count: int = 50) -> Optional[list]:
        """Fetch market data through the worker."""
        loop = asyncio.get_event_loop()
        try:
            candles = await loop.run_in_executor(
                None,
                lambda: self.api.get_candles(asset, timeframe, candle_count, time.time())
            )
            return candles
        except Exception as e:
            print(f"⚠️ Error fetching candles: {e}")
            return None

    async def get_available_assets(self) -> dict:
        """Get available assets through the worker."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self.api.get_all_open_time)
            return result if result else {}
        except Exception as e:
            print(f"⚠️ Error getting assets: {e}")
            return {}


# ==========================================
# 🤖 MAIN TRADING BOT
# ==========================================

class OTCTradingBot:
    """
    Main trading bot with async architecture.

    Features:
    - Telegram signal listening
    - Single API worker for thread safety
    - Fractional Kelly position sizing
    - AI-powered analysis (optional)
    - Real-time trade monitoring
    - Comprehensive logging
    """

    def __init__(self, config: dict):
        self.config = config
        self.iq_api: Optional[IQ_Option] = None
        self.telegram_client: Optional[TelegramClient] = None
        self.api_worker: Optional[APIWorker] = None
        self.market_analyzer: Optional[MarketAnalyzer] = None
        self.ai_analyzer: Optional[AIAnalyzer] = None
        self.trade_logger: Optional[TradeLogger] = None
        self.position_sizer: Optional[PositionSizer] = None
        self.signal_parser: Optional[SignalParser] = None
        self.session_manager: Optional[SessionManager] = None
        self.scheduled_trades: List[asyncio.Task] = []
        self.is_running = False

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
        self.market_analyzer = MarketAnalyzer()

        self.ai_analyzer = AIAnalyzer(
            self.config.get('ai_api_key', ''),
            self.config.get('ai_enabled', False),
            self.config.get('confidence_threshold', 0.7)
        )

        # Use AtomicTradeLogger for crash-safe logging
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

        # Initialize session manager for risk control
        session_config = {
            'max_daily_loss': self.config.get('max_daily_loss', 50.0),
            'max_consecutive_losses': self.config.get('max_consecutive_losses', 3),
            'daily_profit_target': self.config.get('daily_profit_target', 100.0)
        }
        self.session_manager = SessionManager(session_config)

        self.api_worker = APIWorker(
            self.iq_api,
            self.trade_logger,
            self.position_sizer,
            self.market_analyzer,
            self.session_manager
        )

    async def process_signal(self, message_text: str):
        """Process a trading signal from Telegram."""
        # Get available assets
        available_assets = await self.api_worker.get_available_assets()

        # Parse signal
        signal = self.signal_parser.parse(message_text, available_assets)
        if not signal:
            print("   ⚠️ Could not parse signal from message")
            return

        # Get current time in signal timezone
        now = datetime.now(self.signal_parser.timezone)

        print(f"\n{'=' * 50}")
        print(f"🚀 NEW SIGNAL RECEIVED")
        print(f"   Asset: {signal.asset}")
        print(f"   Direction: {signal.direction.upper()}")
        print(f"   Duration: {signal.duration}M")
        if signal.entry_time:
            print(f"   Entry Time: {signal.entry_time.strftime('%I:%M %p %Z')}")
            print(f"   Current Time: {now.strftime('%I:%M %p %Z')}")
        print(f"{'=' * 50}")

        # Pre-check session manager (can still trade?)
        allowed, reason = self.session_manager.check_trade_allowed()
        if not allowed:
            print(f"⛔ Trade blocked by Session Manager: {reason}")
            return

        # If entry time is specified, schedule the trade
        if signal.entry_time:
            await self._schedule_trade(signal)
        else:
            # Execute immediately if no entry time
            await self._execute_signal(signal)

    async def _schedule_trade(self, signal: TradeSignal):
        """Schedule a trade to execute at the specified entry time."""
        now = datetime.now(self.signal_parser.timezone)
        wait_seconds = (signal.entry_time - now).total_seconds()

        # Define tolerance for "missed" entry times
        MAX_LATE_SECONDS = 90  # Execute if within 90 seconds of entry time

        if wait_seconds < -MAX_LATE_SECONDS:
            # Too late - entry time passed by more than tolerance
            print(f"   ⚠️ Entry time {signal.entry_time.strftime('%I:%M %p')} has passed by {abs(wait_seconds):.0f}s. Skipping.")
            return
        elif wait_seconds < 0:
            # Entry time just passed (within tolerance), execute immediately
            print(f"   ⏰ Entry time was {abs(wait_seconds):.0f}s ago, executing now...")
            wait_seconds = 0
        else:
            # Future entry time - schedule it
            print(f"   ⏰ Scheduled to execute in {wait_seconds:.0f} seconds ({wait_seconds/60:.1f} min)...")

        if wait_seconds > 0:
            # Wait until entry time (minus a small buffer for processing)
            wait_seconds = max(0, wait_seconds - 3)  # 3 second buffer for API calls
            await asyncio.sleep(wait_seconds)
            print(f"\n⏰ Entry time reached for {signal.asset} {signal.direction.upper()}!")

        # Re-check session manager at execution time (conditions may have changed)
        allowed, reason = self.session_manager.check_trade_allowed()
        if not allowed:
            print(f"⛔ Trade blocked at execution time: {reason}")
            return

        await self._execute_signal(signal)

    async def _execute_signal(self, signal: TradeSignal):
        """
        Execute a trading signal (internal method).

        This is called at entry time, so market analysis happens here.
        """
        print(f"\n📊 Analyzing market for {signal.asset}...")

        indicators = None
        ai_confidence = 1.0
        reasoning = "Direct signal execution"

        # Market analysis (done at execution time, not scheduling time)
        candles = await self.api_worker.get_market_data(
            signal.asset.replace("-OTC", ""),
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
                    indicators, signal.direction
                )
                print(f"   Condition: {condition_reason}")
        else:
            print("   ⚠️ Could not fetch market data")
            indicators = {"rsi": 50, "trend": "unknown", "current_price": 0}

        # AI Analysis (if enabled)
        if self.config.get('ai_enabled', False):
            print("\n🤖 AI Analysis...")
            should_trade, ai_confidence, reasoning = await self.ai_analyzer.analyze(
                signal.asset, signal.direction, indicators
            )
            print(f"   Should Trade: {'Yes' if should_trade else 'No'}")
            print(f"   Confidence: {ai_confidence * 100:.0f}%")
            print(f"   Reasoning: {reasoning}")

            if not should_trade or ai_confidence < self.config.get('confidence_threshold', 0.7):
                threshold = self.config.get('confidence_threshold', 0.7) * 100
                print(f"\n❌ TRADE SKIPPED")
                print(f"   Confidence {ai_confidence * 100:.0f}% < Threshold {threshold:.0f}%")
                return

        # Submit trade to worker
        trade_request = TradeRequest(
            signal=signal,
            ai_confidence=ai_confidence,
            reasoning=reasoning
        )

        await self.api_worker.submit_trade(trade_request)

    async def run(self):
        """Main async run loop."""
        print("\n" + "=" * 60)
        print("🤖 OTC TRADING BOT v2.1")
        print("=" * 60)

        # Connect to IQ Option
        if not self.connect_iq_option():
            return

        # Initialize components
        self.initialize_components()

        # Print configuration
        print(f"\n⚙️ CONFIGURATION")
        print(f"   Account Type: {self.config['account_type']}")
        print(f"   Position Sizing: {self.position_sizer.get_description()}")
        print(f"   Default Duration: {self.config.get('default_duration', 2)}M")
        print(f"   Signal Timezone: {self.config.get('signal_timezone', DEFAULT_TIMEZONE)}")
        print(f"   AI Analysis: {'Enabled' if self.config.get('ai_enabled') else 'Disabled'}")

        if self.config.get('ai_enabled'):
            print(f"   Confidence Threshold: {self.config.get('confidence_threshold', 0.7) * 100:.0f}%")

        # Show position sizing details
        sizing = self.config.get('position_sizing', {})
        if sizing.get('method') == 'fractional_kelly':
            print(f"\n💰 KELLY CRITERION SETTINGS")
            print(f"   Fraction: {sizing.get('kelly_fraction', 0.25)}")
            print(f"   Min Trade: ${sizing.get('min_trade', 1.0):.2f}")
            print(f"   Max Trade: ${sizing.get('max_trade', 100.0):.2f}")
            print(f"   Max Risk: {sizing.get('max_risk_percentage', 0.05)*100:.1f}% of balance")

        # Show session manager (risk control) settings
        print(f"\n🛡️ SESSION RISK CONTROLS")
        print(f"   Max Daily Loss: ${self.config.get('max_daily_loss', 50.0):.2f}")
        print(f"   Max Consecutive Losses: {self.config.get('max_consecutive_losses', 3)}")
        print(f"   Daily Profit Target: ${self.config.get('daily_profit_target', 100.0):.2f}")

        # Setup Telegram client
        self.telegram_client = TelegramClient(
            'otc_session',
            self.config['api_id'],
            self.config['api_hash']
        )

        @self.telegram_client.on(events.NewMessage(chats=self.config['channel_name']))
        async def handler(event):
            # Get message text with fallback to raw_text
            message = event.message.message or event.raw_text or ""
            if not message:
                print(f"\n📨 Empty message received (ID: {event.id})")
                return

            # Check if this looks like a trade signal
            message_upper = message.upper()
            signal_keywords = [
                "TRADE NOW", "DIRECTION", "ENTRY TIME", "EXPIRY", "OTC",
                "BUY", "SELL", "CALL", "PUT", "🟩", "🟥", "🟢", "🔴"
            ]
            is_signal = any(keyword in message_upper or keyword in message for keyword in signal_keywords)

            if is_signal:
                print(f"\n📩 Trade signal detected (Chat: {event.chat_id}):")
                print(f"   {message[:200]}{'...' if len(message) > 200 else ''}")

                # Create task for scheduled execution (allows multiple concurrent schedules)
                task = asyncio.create_task(self.process_signal(message))
                self.scheduled_trades.append(task)

                # Clean up completed tasks
                self.scheduled_trades = [t for t in self.scheduled_trades if not t.done()]
            else:
                # Only log in debug mode to reduce noise
                if self.config.get('debug', False):
                    print(f"\n📨 Non-signal message (Chat: {event.chat_id}): {message[:50]}...")

        print(f"\n🎧 Bot is now listening for signals...")
        print(f"   Channel: {self.config['channel_name']}")
        print(f"   Press Ctrl+C to stop\n")

        self.is_running = True

        try:
            # Start Telegram client
            await self.telegram_client.start()

            # Run API worker and Telegram client concurrently
            await asyncio.gather(
                self.api_worker.start(),
                self.telegram_client.run_until_disconnected()
            )

        except KeyboardInterrupt:
            print("\n\n🛑 Bot stopped by user")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the bot and print statistics."""
        self.is_running = False

        # Cancel any pending scheduled trades
        if self.scheduled_trades:
            print(f"\n🛑 Cancelling {len(self.scheduled_trades)} pending scheduled trade(s)...")
            for task in self.scheduled_trades:
                if not task.done():
                    task.cancel()
            # Wait for all tasks to complete cancellation
            await asyncio.gather(*self.scheduled_trades, return_exceptions=True)
            self.scheduled_trades.clear()

        if self.api_worker:
            await self.api_worker.stop()

        if self.session_manager:
            self.session_manager.print_session_status()

        if self.trade_logger:
            self.trade_logger.print_statistics()

        if self.telegram_client:
            await self.telegram_client.disconnect()

        print("\n👋 Goodbye!")

    def start(self):
        """Entry point - starts the async event loop."""
        try:
            asyncio.run(self.run())
        except KeyboardInterrupt:
            print("\n\n🛑 Bot stopped by user")


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
        "default_duration": 2,  # Default duration in minutes
        "signal_timezone": "Africa/Lagos",  # Timezone of the signal channel (for entry times)

        # Debug Mode
        "debug": False,  # Set to True to see all messages (including non-signals)

        # Position Sizing Configuration
        "position_sizing": {
            # Method: "fixed_amount", "fixed_percentage", or "fractional_kelly"
            "method": "fractional_kelly",

            # Fixed Amount Settings (if method = "fixed_amount")
            "fixed_amount": 1.0,

            # Fixed Percentage Settings (if method = "fixed_percentage")
            "fixed_percentage": 0.01,  # 1% of balance

            # Fractional Kelly Settings (if method = "fractional_kelly")
            "kelly_fraction": 0.25,  # ¼ Kelly (conservative)
            # Other options:
            # 0.5   = ½ Kelly (moderate)
            # 0.25  = ¼ Kelly (conservative)
            # 0.125 = ⅛ Kelly (very conservative)

            # Risk Limits (apply to all methods)
            "min_trade": 1.0,         # Minimum trade amount
            "max_trade": 50.0,        # Maximum trade amount
            "max_risk_percentage": 0.05,  # Never risk more than 5% per trade
        },

        # AI Analysis (Optional - requires OpenAI API key)
        "ai_api_key": "your_openai_api_key",  # Get from platform.openai.com
        "ai_enabled": False,  # Set to True to enable AI analysis
        "confidence_threshold": 0.7,  # Minimum confidence to execute trade (0.0-1.0)

        # Session Manager (Risk Control)
        "max_daily_loss": 50.0,          # Stop trading after losing this amount
        "max_consecutive_losses": 3,      # Stop after this many losses in a row
        "daily_profit_target": 100.0,     # Stop after reaching this profit

        # Logging
        "log_file": "trade_log.json"
    }

    # ========================================
    # 🚀 START BOT
    # ========================================
    bot = OTCTradingBot(config)
    bot.start()

