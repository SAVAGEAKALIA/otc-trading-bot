"""
CCV2 Strategy — Consecutive Candle Version 2.

Popular OTC reversal strategy:
  - Counts consecutive same-color candles
  - After N consecutive candles (3-5), predicts reversal
  - RSI extrema confirmation strengthens the signal
  - Volume surge at streak end adds conviction

Scoring: base 55 + streak bonus (0-20) + RSI confirmation (0-15)
         + body strength (0-15) + volume surge (0-10) = max 115 (capped at 100)
"""
from typing import Dict, Any, List
from .base import BaseStrategy, StrategyResult
from ..data_provider import get_completed_candles


class CCV2Strategy(BaseStrategy):
    """
    Consecutive Candle V2 — reversal strategy based on exhaustion of
    same-color streaks.  Expects a reversal after 3-5 consecutive
    green or red candles, confirmed by RSI extrema.
    """

    def __init__(self, min_streak: int = 3, max_streak: int = 7):
        super().__init__("CCV2")
        self.min_streak = min_streak
        self.max_streak = max_streak

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        candles = get_completed_candles(candles, min_required=self.min_streak + 1)
        if not candles:
            return StrategyResult(0.0, "neutral", 0.0, [], ["Not enough candles for CCV2"], False)

        indicators_2m = kwargs.get("indicators_2m", {})


        # ------------------------------------------------------------------
        # 1.  Count the *current* consecutive same-color streak (newest first)
        # ------------------------------------------------------------------
        streak_color = None  # 'green' or 'red'
        streak_len = 0
        streak_bodies: List[float] = []  # body sizes for strength check

        for c in reversed(candles):
            o = float(c.get("open", 0))
            cl = float(c.get("close", 0))
            hi = float(c.get("max", max(o, cl)))
            lo = float(c.get("min", min(o, cl)))

            if cl > o + 1e-6:
                color = "green"
            elif cl < o - 1e-6:
                color = "red"
            else:
                break  # doji breaks the streak

            if streak_color is None:
                streak_color = color
            elif color != streak_color:
                break

            streak_len += 1
            candle_range = hi - lo
            body = abs(cl - o)
            streak_bodies.append(body / candle_range if candle_range > 0 else 0.0)

            if streak_len >= self.max_streak:
                break

        if streak_len < self.min_streak or streak_color is None:
            return StrategyResult(0.0, "neutral", 0.0, [], ["No qualifying streak"], False)

        # Reversal direction: opposite of streak color
        direction = "call" if streak_color == "red" else "put"

        reasons: List[str] = []
        warnings: List[str] = []

        reasons.append(f"CCV2 {streak_len}-candle {streak_color} streak → {direction.upper()} reversal")

        # ------------------------------------------------------------------
        # 2.  Streak length bonus  (0-20)
        # ------------------------------------------------------------------
        # 3 consecutive -> 10 pts, 4 -> 16, 5+ -> 20
        streak_bonus = min(20.0, 10.0 + (streak_len - self.min_streak) * 6.0)
        if streak_len >= 5:
            streak_bonus = 20.0

        # ------------------------------------------------------------------
        # 3.  RSI confirmation  (0-15)
        # ------------------------------------------------------------------
        rsi = float(indicators_2m.get("rsi", 50.0))
        rsi_bonus = 0.0

        if direction == "call":
            # After a red streak we want oversold — widened from 30→35
            if rsi < 35:
                rsi_bonus = 15.0
                reasons.append(f"RSI Oversold ({rsi:.1f}) confirms reversal")
            elif rsi < 45:
                rsi_bonus = 8.0
            elif rsi > 60:
                warnings.append(f"RSI not oversold ({rsi:.1f}) — weak reversal")
        else:
            # After a green streak we want overbought — widened from 70→65
            if rsi > 65:
                rsi_bonus = 15.0
                reasons.append(f"RSI Overbought ({rsi:.1f}) confirms reversal")
            elif rsi > 55:
                rsi_bonus = 8.0
            elif rsi < 40:
                warnings.append(f"RSI not overbought ({rsi:.1f}) — weak reversal")

        # ------------------------------------------------------------------
        # 4.  Body strength  (0-15)
        # ------------------------------------------------------------------
        avg_body = sum(streak_bodies) / len(streak_bodies) if streak_bodies else 0.0

        if avg_body >= 0.6:
            body_bonus = 15.0
        elif avg_body >= 0.4:
            body_bonus = 10.0
        elif avg_body >= 0.2:
            body_bonus = 5.0
        else:
            body_bonus = 0.0
            warnings.append(f"Weak streak bodies ({avg_body:.2f})")

        # ------------------------------------------------------------------
        # 5.  Volume surge  (0-10)
        # ------------------------------------------------------------------
        avg_vol = float(indicators_2m.get("avg_volume", 0.0))
        cur_vol = float(indicators_2m.get("current_volume", 0.0))
        vol_bonus = 0.0

        if avg_vol > 0:
            vol_ratio = cur_vol / avg_vol
            if vol_ratio >= 1.5:
                vol_bonus = 10.0
                reasons.append(f"Volume Surge ({vol_ratio:.1f}×)")
            elif vol_ratio >= 1.2:
                vol_bonus = 5.0

        # ------------------------------------------------------------------
        # 6.  Stochastic confirmation bonus (0-5)
        # ------------------------------------------------------------------
        stoch_k = float(indicators_2m.get("stoch_k", 50.0))
        stoch_bonus = 0.0
        if direction == "call" and stoch_k < 25:
            stoch_bonus = 5.0
        elif direction == "put" and stoch_k > 75:
            stoch_bonus = 5.0
            
        # ------------------------------------------------------------------
        # 7.  Trend Aware Reversal Blocking (Phase 3 Hard Veto)
        # ------------------------------------------------------------------
        # Block reversal if the 15m trend is strongly aligned with the current streak
        # (e.g., don't try to PUT reverse a GREEN streak if 15m trend is BULLISH)
        indicators_15m = kwargs.get("indicators_15m", {})
        if indicators_15m:
            trend_15m = str(indicators_15m.get("trend", "neutral")).lower()
            if direction == "put" and trend_15m == "bullish":
                return StrategyResult(0.0, "neutral", 0.0, [], ["VETO: Trying to reverse bullish streak against 15m Bullish Trend"], False)
            if direction == "call" and trend_15m == "bearish":
                return StrategyResult(0.0, "neutral", 0.0, [], ["VETO: Trying to reverse bearish streak against 15m Bearish Trend"], False)

        # ------------------------------------------------------------------
        # Final score
        # ------------------------------------------------------------------
        total = 55.0 + streak_bonus + rsi_bonus + body_bonus + vol_bonus + stoch_bonus
        total = min(100.0, total)

        reasons.append(
            f"Score: base=55 + streak={streak_bonus:.0f} + rsi={rsi_bonus:.0f} "
            f"+ body={body_bonus:.0f} + vol={vol_bonus:.0f} + stoch={stoch_bonus:.0f}"
        )

        confidence = min(0.95, total / 100.0)
        
        # Hard threshold cutoff
        # CCV2 needs a score of >= 65 to be considered a valid entry
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
