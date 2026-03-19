"""
Candlestick and Chart Pattern Analysis Module.

Detects common patterns that signal potential reversals or continuations:
- Candlestick patterns (Doji, Hammer, Engulfing, etc.)
- Chart patterns (Double Top/Bottom, Head & Shoulders concept)
- Support/Resistance levels
"""

from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum


class PatternType(Enum):
    """Pattern classification."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class PatternStrength(Enum):
    """Pattern reliability/strength."""
    STRONG = 3
    MODERATE = 2
    WEAK = 1


@dataclass
class PatternResult:
    """Result of pattern detection."""
    name: str
    pattern_type: PatternType
    strength: PatternStrength
    description: str
    confidence: float  # 0.0 to 1.0


class PatternAnalyzer:
    """
    Analyzes candlestick data for common trading patterns.

    Supports:
    - Single candlestick patterns (Doji, Hammer, Shooting Star, etc.)
    - Two-candle patterns (Engulfing, Harami, etc.)
    - Three-candle patterns (Morning/Evening Star, Three Soldiers/Crows)
    - Support/Resistance levels
    - Trend analysis
    """

    def __init__(self):
        self.body_threshold = 0.1  # Minimum body size as % of range
        self.doji_threshold = 0.05  # Max body size for doji as % of range
        self.shadow_ratio = 2.0  # Shadow must be X times body for hammer/star

    def analyze(self, candles: List[dict], direction: str = None) -> Dict[str, Any]:
        """
        Comprehensive pattern analysis.

        Args:
            candles: List of candle dicts with 'open', 'close', 'max', 'min'
            direction: Optional direction to check ('call' or 'put')

        Returns:
            Dictionary with pattern analysis results
        """
        if not candles or len(candles) < 5:
            return {
                "patterns": [],
                "signal": "neutral",
                "confidence": 0.5,
                "support": None,
                "resistance": None,
                "recommendation": "Insufficient data for pattern analysis"
            }

        # Detect all patterns
        patterns = []

        # Single candle patterns (most recent)
        single = self._detect_single_patterns(candles[-1], candles)
        patterns.extend(single)

        # Two candle patterns
        if len(candles) >= 2:
            two = self._detect_two_candle_patterns(candles[-2], candles[-1])
            patterns.extend(two)

        # Three candle patterns
        if len(candles) >= 3:
            three = self._detect_three_candle_patterns(candles[-3], candles[-2], candles[-1])
            patterns.extend(three)

        # Calculate support/resistance
        support, resistance = self._calculate_support_resistance(candles)

        # Analyze trend
        trend_info = self._analyze_trend(candles)

        # Generate overall signal
        signal, confidence, recommendation = self._generate_signal(
            patterns, trend_info, support, resistance, candles[-1], direction
        )

        return {
            "patterns": [self._pattern_to_dict(p) for p in patterns],
            "bullish_patterns": [p for p in patterns if p.pattern_type == PatternType.BULLISH],
            "bearish_patterns": [p for p in patterns if p.pattern_type == PatternType.BEARISH],
            "signal": signal,
            "confidence": confidence,
            "support": support,
            "resistance": resistance,
            "trend": trend_info,
            "recommendation": recommendation,
            "pattern_count": len(patterns)
        }

    def _get_candle_parts(self, candle: dict) -> Tuple[float, float, float, float, float, float, float, float, bool]:
        """Extract candle parts and calculate metrics."""
        open_p = candle.get('open', candle.get('from', 0))
        close = candle.get('close', candle.get('to', 0))
        high = candle.get('max', candle.get('high', max(open_p, close)))
        low = candle.get('min', candle.get('low', min(open_p, close)))

        body = abs(close - open_p)
        range_size = high - low if high != low else 0.0001
        upper_shadow = high - max(open_p, close)
        lower_shadow = min(open_p, close) - low
        is_bullish = close > open_p

        return open_p, close, high, low, body, range_size, upper_shadow, lower_shadow, is_bullish

    def _detect_single_patterns(self, candle: dict, all_candles: List[dict]) -> List[PatternResult]:
        """Detect single candlestick patterns."""
        patterns = []

        open_p, close, high, low, body, range_size, upper_shadow, lower_shadow, is_bullish = self._get_candle_parts(candle)

        body_pct = body / range_size if range_size > 0 else 0

        # Doji - very small body
        if body_pct < self.doji_threshold:
            # Dragonfly Doji (bullish) - long lower shadow, no upper shadow
            if lower_shadow > body * 3 and upper_shadow < body:
                patterns.append(PatternResult(
                    name="Dragonfly Doji",
                    pattern_type=PatternType.BULLISH,
                    strength=PatternStrength.MODERATE,
                    description="Bullish reversal signal at support",
                    confidence=0.65
                ))
            # Gravestone Doji (bearish) - long upper shadow, no lower shadow
            elif upper_shadow > body * 3 and lower_shadow < body:
                patterns.append(PatternResult(
                    name="Gravestone Doji",
                    pattern_type=PatternType.BEARISH,
                    strength=PatternStrength.MODERATE,
                    description="Bearish reversal signal at resistance",
                    confidence=0.65
                ))
            # Regular Doji
            else:
                patterns.append(PatternResult(
                    name="Doji",
                    pattern_type=PatternType.NEUTRAL,
                    strength=PatternStrength.WEAK,
                    description="Indecision - potential reversal",
                    confidence=0.5
                ))

        # Hammer (bullish) - small body at top, long lower shadow
        elif is_bullish and lower_shadow >= body * self.shadow_ratio and upper_shadow < body * 0.5:
            patterns.append(PatternResult(
                name="Hammer",
                pattern_type=PatternType.BULLISH,
                strength=PatternStrength.STRONG,
                description="Strong bullish reversal pattern",
                confidence=0.75
            ))

        # Inverted Hammer (bullish) - small body at bottom, long upper shadow
        elif is_bullish and upper_shadow >= body * self.shadow_ratio and lower_shadow < body * 0.5:
            patterns.append(PatternResult(
                name="Inverted Hammer",
                pattern_type=PatternType.BULLISH,
                strength=PatternStrength.MODERATE,
                description="Potential bullish reversal",
                confidence=0.6
            ))

        # Hanging Man (bearish) - same shape as hammer but in uptrend
        elif not is_bullish and lower_shadow >= body * self.shadow_ratio and upper_shadow < body * 0.5:
            # Check if in uptrend
            if len(all_candles) >= 5:
                recent_closes = [c.get('close', c.get('to', 0)) for c in all_candles[-5:]]
                if recent_closes[-1] > recent_closes[0]:  # Uptrend
                    patterns.append(PatternResult(
                        name="Hanging Man",
                        pattern_type=PatternType.BEARISH,
                        strength=PatternStrength.MODERATE,
                        description="Bearish reversal in uptrend",
                        confidence=0.65
                    ))

        # Shooting Star (bearish) - small body at bottom, long upper shadow
        elif not is_bullish and upper_shadow >= body * self.shadow_ratio and lower_shadow < body * 0.5:
            patterns.append(PatternResult(
                name="Shooting Star",
                pattern_type=PatternType.BEARISH,
                strength=PatternStrength.STRONG,
                description="Strong bearish reversal pattern",
                confidence=0.75
            ))

        # Marubozu (strong trend candle)
        elif body_pct > 0.9 and upper_shadow < body * 0.1 and lower_shadow < body * 0.1:
            if is_bullish:
                patterns.append(PatternResult(
                    name="Bullish Marubozu",
                    pattern_type=PatternType.BULLISH,
                    strength=PatternStrength.STRONG,
                    description="Strong bullish momentum",
                    confidence=0.7
                ))
            else:
                patterns.append(PatternResult(
                    name="Bearish Marubozu",
                    pattern_type=PatternType.BEARISH,
                    strength=PatternStrength.STRONG,
                    description="Strong bearish momentum",
                    confidence=0.7
                ))

        # Spinning Top (small body, shadows on both sides)
        elif body_pct < 0.3 and upper_shadow > body and lower_shadow > body:
            patterns.append(PatternResult(
                name="Spinning Top",
                pattern_type=PatternType.NEUTRAL,
                strength=PatternStrength.WEAK,
                description="Indecision in the market",
                confidence=0.5
            ))

        return patterns

    def _detect_two_candle_patterns(self, prev: dict, current: dict) -> List[PatternResult]:
        """Detect two-candle patterns."""
        patterns = []

        p_open, p_close, p_high, p_low, p_body, p_range, _, _, p_bullish = self._get_candle_parts(prev)
        c_open, c_close, c_high, c_low, c_body, c_range, _, _, c_bullish = self._get_candle_parts(current)

        # Bullish Engulfing
        if not p_bullish and c_bullish:
            if c_open < p_close and c_close > p_open and c_body > p_body:
                patterns.append(PatternResult(
                    name="Bullish Engulfing",
                    pattern_type=PatternType.BULLISH,
                    strength=PatternStrength.STRONG,
                    description="Strong bullish reversal - buyers overwhelm sellers",
                    confidence=0.8
                ))

        # Bearish Engulfing
        if p_bullish and not c_bullish:
            if c_open > p_close and c_close < p_open and c_body > p_body:
                patterns.append(PatternResult(
                    name="Bearish Engulfing",
                    pattern_type=PatternType.BEARISH,
                    strength=PatternStrength.STRONG,
                    description="Strong bearish reversal - sellers overwhelm buyers",
                    confidence=0.8
                ))

        # Bullish Harami (small bullish inside large bearish)
        if not p_bullish and c_bullish:
            if c_open > p_close and c_close < p_open and c_body < p_body * 0.5:
                patterns.append(PatternResult(
                    name="Bullish Harami",
                    pattern_type=PatternType.BULLISH,
                    strength=PatternStrength.MODERATE,
                    description="Potential bullish reversal - selling pressure weakening",
                    confidence=0.6
                ))

        # Bearish Harami (small bearish inside large bullish)
        if p_bullish and not c_bullish:
            if c_open < p_close and c_close > p_open and c_body < p_body * 0.5:
                patterns.append(PatternResult(
                    name="Bearish Harami",
                    pattern_type=PatternType.BEARISH,
                    strength=PatternStrength.MODERATE,
                    description="Potential bearish reversal - buying pressure weakening",
                    confidence=0.6
                ))

        # Tweezer Bottom (bullish)
        if abs(p_low - c_low) < p_range * 0.05 and not p_bullish and c_bullish:
            patterns.append(PatternResult(
                name="Tweezer Bottom",
                pattern_type=PatternType.BULLISH,
                strength=PatternStrength.MODERATE,
                description="Bullish reversal at same support level",
                confidence=0.65
            ))

        # Tweezer Top (bearish)
        if abs(p_high - c_high) < p_range * 0.05 and p_bullish and not c_bullish:
            patterns.append(PatternResult(
                name="Tweezer Top",
                pattern_type=PatternType.BEARISH,
                strength=PatternStrength.MODERATE,
                description="Bearish reversal at same resistance level",
                confidence=0.65
            ))

        # Piercing Line (bullish)
        if not p_bullish and c_bullish:
            p_mid = (p_open + p_close) / 2
            if c_open < p_low and c_close > p_mid and c_close < p_open:
                patterns.append(PatternResult(
                    name="Piercing Line",
                    pattern_type=PatternType.BULLISH,
                    strength=PatternStrength.MODERATE,
                    description="Bullish reversal - price piercing above midpoint",
                    confidence=0.65
                ))

        # Dark Cloud Cover (bearish)
        if p_bullish and not c_bullish:
            p_mid = (p_open + p_close) / 2
            if c_open > p_high and c_close < p_mid and c_close > p_open:
                patterns.append(PatternResult(
                    name="Dark Cloud Cover",
                    pattern_type=PatternType.BEARISH,
                    strength=PatternStrength.MODERATE,
                    description="Bearish reversal - price falling below midpoint",
                    confidence=0.65
                ))

        return patterns

    def _detect_three_candle_patterns(self, first: dict, second: dict, third: dict) -> List[PatternResult]:
        """Detect three-candle patterns."""
        patterns = []

        f_open, f_close, f_high, f_low, f_body, f_range, _, _, f_bullish = self._get_candle_parts(first)
        s_open, s_close, s_high, s_low, s_body, s_range, _, _, s_bullish = self._get_candle_parts(second)
        t_open, t_close, t_high, t_low, t_body, t_range, _, _, t_bullish = self._get_candle_parts(third)

        # Morning Star (bullish reversal)
        s_body_pct = s_body / s_range if s_range > 0 else 0
        if not f_bullish and s_body_pct < 0.3 and t_bullish:
            if s_close < f_close and t_close > (f_open + f_close) / 2:
                patterns.append(PatternResult(
                    name="Morning Star",
                    pattern_type=PatternType.BULLISH,
                    strength=PatternStrength.STRONG,
                    description="Strong bullish reversal - dawn of a new uptrend",
                    confidence=0.8
                ))

        # Evening Star (bearish reversal)
        if f_bullish and s_body_pct < 0.3 and not t_bullish:
            if s_close > f_close and t_close < (f_open + f_close) / 2:
                patterns.append(PatternResult(
                    name="Evening Star",
                    pattern_type=PatternType.BEARISH,
                    strength=PatternStrength.STRONG,
                    description="Strong bearish reversal - end of uptrend",
                    confidence=0.8
                ))

        # Three White Soldiers (bullish continuation/reversal)
        if f_bullish and s_bullish and t_bullish:
            if s_close > f_close and t_close > s_close:
                if s_open > f_open and t_open > s_open:  # Higher opens
                    patterns.append(PatternResult(
                        name="Three White Soldiers",
                        pattern_type=PatternType.BULLISH,
                        strength=PatternStrength.STRONG,
                        description="Strong bullish momentum - 3 consecutive bullish candles",
                        confidence=0.75
                    ))

        # Three Black Crows (bearish continuation/reversal)
        if not f_bullish and not s_bullish and not t_bullish:
            if s_close < f_close and t_close < s_close:
                if s_open < f_open and t_open < s_open:  # Lower opens
                    patterns.append(PatternResult(
                        name="Three Black Crows",
                        pattern_type=PatternType.BEARISH,
                        strength=PatternStrength.STRONG,
                        description="Strong bearish momentum - 3 consecutive bearish candles",
                        confidence=0.75
                    ))

        # Three Inside Up (bullish)
        if not f_bullish and s_bullish and t_bullish:
            # Second candle is inside first
            if s_open > f_close and s_close < f_open:
                # Third closes above first's open
                if t_close > f_open:
                    patterns.append(PatternResult(
                        name="Three Inside Up",
                        pattern_type=PatternType.BULLISH,
                        strength=PatternStrength.MODERATE,
                        description="Bullish reversal confirmation",
                        confidence=0.7
                    ))

        # Three Inside Down (bearish)
        if f_bullish and not s_bullish and not t_bullish:
            # Second candle is inside first
            if s_open < f_close and s_close > f_open:
                # Third closes below first's open
                if t_close < f_open:
                    patterns.append(PatternResult(
                        name="Three Inside Down",
                        pattern_type=PatternType.BEARISH,
                        strength=PatternStrength.MODERATE,
                        description="Bearish reversal confirmation",
                        confidence=0.7
                    ))

        return patterns

    def _calculate_support_resistance(self, candles: List[dict], lookback: int = 20) -> Tuple[Optional[float], Optional[float]]:
        """Calculate support and resistance levels."""
        if len(candles) < lookback:
            lookback = len(candles)

        recent = candles[-lookback:]
        lows = [c.get('min', c.get('low', 0)) for c in recent]
        highs = [c.get('max', c.get('high', 0)) for c in recent]

        # Simple support/resistance as recent low/high
        support = min(lows)
        resistance = max(highs)

        return round(support, 5), round(resistance, 5)

    def _analyze_trend(self, candles: List[dict], short_period: int = 5, long_period: int = 15) -> Dict[str, Any]:
        """Analyze trend using moving averages and price action."""
        if len(candles) < long_period:
            return {"direction": "unknown", "strength": 0, "description": "Insufficient data"}

        closes = [c.get('close', c.get('to', 0)) for c in candles]

        # Calculate SMAs
        short_sma = sum(closes[-short_period:]) / short_period
        long_sma = sum(closes[-long_period:]) / long_period
        current_price = closes[-1]

        # Determine trend direction
        if short_sma > long_sma and current_price > short_sma:
            direction = "bullish"
            strength = min(100, int((short_sma - long_sma) / long_sma * 1000))
        elif short_sma < long_sma and current_price < short_sma:
            direction = "bearish"
            strength = min(100, int((long_sma - short_sma) / long_sma * 1000))
        else:
            direction = "sideways"
            strength = 0

        # Higher highs / Lower lows analysis
        recent_highs = [c.get('max', c.get('high', 0)) for c in candles[-5:]]
        recent_lows = [c.get('min', c.get('low', 0)) for c in candles[-5:]]

        higher_highs = all(recent_highs[i] >= recent_highs[i-1] for i in range(1, len(recent_highs)))
        higher_lows = all(recent_lows[i] >= recent_lows[i-1] for i in range(1, len(recent_lows)))
        lower_highs = all(recent_highs[i] <= recent_highs[i-1] for i in range(1, len(recent_highs)))
        lower_lows = all(recent_lows[i] <= recent_lows[i-1] for i in range(1, len(recent_lows)))

        if higher_highs and higher_lows:
            structure = "uptrend"
        elif lower_highs and lower_lows:
            structure = "downtrend"
        else:
            structure = "consolidating"

        return {
            "direction": direction,
            "strength": strength,
            "structure": structure,
            "short_sma": round(short_sma, 5),
            "long_sma": round(long_sma, 5),
            "description": f"{direction.capitalize()} trend ({structure})"
        }

    def _generate_signal(self, patterns: List[PatternResult], trend: dict,
                         support: float, resistance: float,
                         current_candle: dict, direction: str = None) -> Tuple[str, float, str]:
        """Generate overall trading signal from patterns and analysis."""

        current_price = current_candle.get('close', current_candle.get('to', 0))

        # Count and weight patterns
        bullish_score = 0
        bearish_score = 0

        for p in patterns:
            weight = p.strength.value * p.confidence
            if p.pattern_type == PatternType.BULLISH:
                bullish_score += weight
            elif p.pattern_type == PatternType.BEARISH:
                bearish_score += weight

        # Factor in trend
        if trend['direction'] == 'bullish':
            bullish_score += 1
        elif trend['direction'] == 'bearish':
            bearish_score += 1

        # Factor in support/resistance proximity
        if support and resistance:
            range_size = resistance - support
            if range_size > 0:
                price_position = (current_price - support) / range_size

                # Near support = bullish bias
                if price_position < 0.2:
                    bullish_score += 0.5
                # Near resistance = bearish bias
                elif price_position > 0.8:
                    bearish_score += 0.5

        # Determine signal
        total_score = bullish_score + bearish_score
        if total_score == 0:
            signal = "neutral"
            confidence = 0.5
        elif bullish_score > bearish_score:
            signal = "bullish"
            confidence = min(0.9, 0.5 + (bullish_score - bearish_score) / 10)
        else:
            signal = "bearish"
            confidence = min(0.9, 0.5 + (bearish_score - bullish_score) / 10)

        # Generate recommendation
        pattern_names = [p.name for p in patterns[:3]]  # Top 3 patterns
        pattern_str = ", ".join(pattern_names) if pattern_names else "No strong patterns"

        if direction:
            # Check alignment with requested direction
            aligned = (direction == "call" and signal == "bullish") or \
                     (direction == "put" and signal == "bearish")

            if aligned:
                recommendation = f"✅ ALIGNED: {signal.upper()} signal supports {direction.upper()}. Patterns: {pattern_str}"
            elif signal == "neutral":
                recommendation = f"⚠️ NEUTRAL: No strong directional bias. Patterns: {pattern_str}"
            else:
                recommendation = f"⚠️ CONFLICTING: {signal.upper()} signal conflicts with {direction.upper()}. Patterns: {pattern_str}"
        else:
            if signal == "neutral":
                recommendation = f"⏸️ WAIT: No clear direction. {pattern_str}"
            else:
                suggested_direction = "CALL" if signal == "bullish" else "PUT"
                recommendation = f"📊 SIGNAL: {suggested_direction} ({confidence*100:.0f}% confidence). Patterns: {pattern_str}"

        return signal, round(confidence, 2), recommendation

    def _pattern_to_dict(self, pattern: PatternResult) -> dict:
        """Convert PatternResult to dictionary."""
        return {
            "name": pattern.name,
            "type": pattern.pattern_type.value,
            "strength": pattern.strength.name,
            "description": pattern.description,
            "confidence": pattern.confidence
        }

    def get_pattern_summary(self, analysis: dict) -> str:
        """Get a formatted summary of pattern analysis."""
        patterns = analysis.get('patterns', [])
        signal = analysis.get('signal', 'neutral')
        confidence = analysis.get('confidence', 0.5)
        trend = analysis.get('trend', {})

        lines = [
            f"📊 Pattern Analysis Summary",
            f"   Signal: {signal.upper()} ({confidence*100:.0f}% confidence)",
            f"   Trend: {trend.get('description', 'Unknown')}",
            f"   Patterns Found: {len(patterns)}"
        ]

        if patterns:
            lines.append("   Detected Patterns:")
            for p in patterns[:5]:  # Show top 5
                emoji = "🟢" if p['type'] == 'bullish' else "🔴" if p['type'] == 'bearish' else "⚪"
                lines.append(f"      {emoji} {p['name']} ({p['strength']})")

        lines.append(f"   Recommendation: {analysis.get('recommendation', 'N/A')}")

        return "\n".join(lines)

