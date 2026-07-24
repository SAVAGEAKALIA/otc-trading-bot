"""
Adaptive Strategy — Kaufman Adaptive Moving Average (KAMA) based.

Uses an Efficiency Ratio (ER) to detect whether the market is trending
or ranging, and adapts the signal accordingly:
  - High ER (trending): trend-following signal (price crosses above/below KAMA)
  - Low ER (ranging):   mean-reversion signal on extreme distance from KAMA)

Combined with RSI and Stochastic for momentum confirmation.

Scoring: base 40 + ER-adjusted trend score (0-25) + KAMA distance (0-20)
         + momentum confirmation (0-15) = max 100
"""
import math
from typing import Dict, Any, List
from .base import BaseStrategy, StrategyResult
from ..data_provider import get_completed_candles


class AdaptiveStrategy(BaseStrategy):
    """
    KAMA-inspired adaptive strategy that switches between trend-following
    and mean-reversion based on market efficiency.
    """

    def __init__(self, er_period: int = 10, fast_sc: float = 2 / 3, slow_sc: float = 2 / 31):
        """
        Args:
            er_period: Lookback period for Efficiency Ratio calculation
            fast_sc: Fast smoothing constant (default ≈ 2-period EMA)
            slow_sc: Slow smoothing constant (default ≈ 30-period EMA)
        """
        super().__init__("Adaptive")
        self.er_period = er_period
        self.fast_sc = fast_sc
        self.slow_sc = slow_sc

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    def _calculate_er(self, closes: List[float]) -> float:
        """
        Efficiency Ratio = abs(direction) / sum(abs(changes))
        Values close to 1.0  → strong trend
        Values close to 0.0  → choppy / ranging
        """
        if len(closes) < self.er_period + 1:
            return 0.5  # default

        recent = closes[-(self.er_period + 1):]
        direction = abs(recent[-1] - recent[0])
        volatility = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent)))

        if volatility == 0:
            return 0.0
        return direction / volatility

    def _calculate_kama(self, closes: List[float]) -> float:
        """
        Compute the Kaufman Adaptive Moving Average value for the latest bar.
        """
        if len(closes) < self.er_period + 1:
            return closes[-1] if closes else 0.0

        er = self._calculate_er(closes)
        sc = (er * (self.fast_sc - self.slow_sc) + self.slow_sc) ** 2

        # Bootstrap KAMA from the first close in the window
        kama = closes[-(self.er_period + 1)]
        for close in closes[-self.er_period:]:
            kama = kama + sc * (close - kama)

        return kama

    def _extract_closes(self, candles: List[Dict[str, Any]]) -> List[float]:
        return [float(c.get("close", 0)) for c in candles]

    # ------------------------------------------------------------------
    # Strategy evaluation
    # ------------------------------------------------------------------

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        candles = get_completed_candles(candles, min_required=self.er_period + 2)
        if not candles:
            return StrategyResult(0.0, "neutral", 0.0, [], ["Not enough candles for Adaptive"], False)

        indicators_2m = kwargs.get("indicators_2m", {})


        closes = self._extract_closes(candles)
        current_close = closes[-1]
        prev_close = closes[-2]

        er = self._calculate_er(closes)
        kama = self._calculate_kama(closes)
        prev_kama = self._calculate_kama(closes[:-1])

        reasons: List[str] = []
        warnings: List[str] = []

        # ------------------------------------------------------------------
        # 1.  Determine regime and direction
        # ------------------------------------------------------------------
        is_trending = er >= 0.40
        direction = "neutral"

        if is_trending:
            # Trend-following: price crosses KAMA
            if current_close > kama and prev_close <= prev_kama:
                direction = "call"
                reasons.append(f"Trend CALL: Price crossed above KAMA (ER={er:.2f})")
            elif current_close < kama and prev_close >= prev_kama:
                direction = "put"
                reasons.append(f"Trend PUT: Price crossed below KAMA (ER={er:.2f})")
            elif current_close > kama and kama > prev_kama:
                direction = "call"
                reasons.append(f"Trend CALL: Price above rising KAMA (ER={er:.2f})")
            elif current_close < kama and kama < prev_kama:
                direction = "put"
                reasons.append(f"Trend PUT: Price below falling KAMA (ER={er:.2f})")
        else:
            # Mean-reversion: extreme distance from KAMA
            if kama > 0:
                distance_pct = (current_close - kama) / kama
            else:
                distance_pct = 0.0

            # Need noticeable distance for mean-reversion
            if distance_pct < -0.0008:
                direction = "call"
                reasons.append(f"MR CALL: Price {distance_pct*100:.3f}% below KAMA (ER={er:.2f})")
            elif distance_pct > 0.0008:
                direction = "put"
                reasons.append(f"MR PUT: Price {distance_pct*100:.3f}% above KAMA (ER={er:.2f})")

        if direction == "neutral":
            return StrategyResult(0.0, "neutral", 0.0, reasons or ["No Adaptive signal"],
                                  warnings, False)

        # ------------------------------------------------------------------
        # 2.  ER-adjusted trend score  (0-25)
        # ------------------------------------------------------------------
        if is_trending:
            # Reward strong trends
            trend_score = round(min(25.0, er * 35.0))
        else:
            # Reward extreme inefficiency (very choppy = strong reversion expected)
            reversion_strength = max(0.0, 0.40 - er) / 0.40
            trend_score = round(min(25.0, reversion_strength * 25.0))

        reasons.append(f"ER Score: {trend_score}/25 (ER={er:.2f}, {'trend' if is_trending else 'MR'})")

        # ------------------------------------------------------------------
        # 3.  Price-to-KAMA distance  (0-20)
        # ------------------------------------------------------------------
        if kama > 0:
            dist_pct = abs(current_close - kama) / kama
        else:
            dist_pct = 0.0

        if is_trending:
            # Closer to KAMA is better for trend (just crossed)
            if dist_pct < 0.0003:
                dist_score = 25.0  # Increased bonus for perfect pullback
            elif dist_pct < 0.0008:
                dist_score = 15.0
            elif dist_pct < 0.0015:
                dist_score = 5.0
            else:
                dist_score = -10.0
                warnings.append("Too far from KAMA for trend entry (-10 penalty)")
        else:
            # Farther from KAMA is better for MR
            if dist_pct >= 0.002:
                dist_score = 20.0
            elif dist_pct >= 0.0012:
                dist_score = 14.0
            elif dist_pct >= 0.0008:
                dist_score = 8.0
            else:
                dist_score = 3.0

        reasons.append(f"Distance Score: {dist_score}/20")

        # ------------------------------------------------------------------
        # 4.  Momentum confluence  (0-15)
        # ------------------------------------------------------------------
        rsi = float(indicators_2m.get("rsi", 50.0))
        stoch_k = float(indicators_2m.get("stoch_k", 50.0))
        stoch_d = float(indicators_2m.get("stoch_d", 50.0))
        mom_score = 0.0

        if direction == "call":
            if 45 < rsi < 65:
                mom_score += 5.0  # Healthy bullish momentum zone
            elif rsi < 35:
                mom_score += 8.0  # Oversold — good for reversal CALL
            if stoch_k > stoch_d:
                mom_score += 5.0  # Bullish stochastic crossover
            if stoch_k < 30:
                mom_score += 2.0  # Oversold stochastic
        elif direction == "put":
            if 35 < rsi < 55:
                mom_score += 5.0
            elif rsi > 65:
                mom_score += 8.0
            if stoch_k < stoch_d:
                mom_score += 5.0
            if stoch_k > 70:
                mom_score += 2.0

        mom_score = min(15.0, mom_score)
        reasons.append(f"Momentum: {mom_score}/15")
        
        # ------------------------------------------------------------------
        # 5.  Trend Aware Reversal Blocking (Phase 3 Hard Veto)
        # ------------------------------------------------------------------
        indicators_5m = kwargs.get("indicators_5m", {})
        if indicators_5m and not is_trending:
            # If we are trying to mean-revert, don't do it against a strong 5m trend
            trend_5m = str(indicators_5m.get("trend", "neutral")).lower()
            adx_5m = float(indicators_5m.get("adx", 0.0))
            if adx_5m > 20.0:
                if direction == "put" and trend_5m == "bullish":
                    return StrategyResult(0.0, "neutral", 0.0, [], ["VETO: Trying to MR short against strong 5m Bullish Trend"], False)
                if direction == "call" and trend_5m == "bearish":
                    return StrategyResult(0.0, "neutral", 0.0, [], ["VETO: Trying to MR long against strong 5m Bearish Trend"], False)

        # ------------------------------------------------------------------
        # Final score
        # ------------------------------------------------------------------
        total = 40.0 + trend_score + dist_score + mom_score
        total = min(100.0, total)

        confidence = min(0.95, total / 100.0)
        
        # Hard threshold cutoff
        # Adaptive needs a score of >= 65 to be considered a valid entry
        if total < 65.0:
            return StrategyResult(total, direction, confidence, reasons, warnings + [f"Rejected: Score too low ({total:.1f} < 65)"], False)

        return StrategyResult(
            score=total if direction == "call" else -total,
            direction=direction,
            confidence=confidence,
            reasons=reasons,
            warnings=warnings,
            should_trade=True,
        )
