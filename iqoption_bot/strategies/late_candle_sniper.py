"""
Late Candle Sniper Strategy — OTC candle geometry.

Detects candles with strong directional commitment AFTER a period of
indecision or counter-movement. The "sniper" thesis: when the OTC
algorithm suddenly commits hard in a direction after being flat or
going the other way, it signals a genuine regime shift — not just
continuation of existing momentum.

This makes the Sniper genuinely INDEPENDENT from Momentum Cascade
(which detects consecutive same-direction candles). Sniper fires on
"surprise commitment", Cascade fires on "sustained momentum". When
both agree, you have real confluence.

Uses completed candle structure — no real-time tick data needed.
No RSI, MACD, or Bollinger — pure price structure.
"""
from typing import Dict, Any, List
from .base import BaseStrategy, StrategyResult


class LateCandleSniperStrategy(BaseStrategy):
    """Fresh commitment after indecision — snipe the regime shift."""

    def __init__(self):
        super().__init__(name="Late Candle Sniper")

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        NO_TRADE = StrategyResult(0.0, "neutral", 0.0, [], [], False)

        if not candles or len(candles) < 6:
            return NO_TRADE

        # Work with the last completed candle
        c = candles[-1]

        o = float(c.get("open", c.get("o", 0)))
        h = float(c.get("max", c.get("high", c.get("h", 0))))
        l = float(c.get("min", c.get("low", c.get("l", 0))))
        cl = float(c.get("close", c.get("c", 0)))

        body = abs(cl - o)
        range_ = h - l

        # ── GATE 1: Meaningful range (not a flat/doji) ──
        if range_ == 0 or range_ < 1e-8:
            return NO_TRADE

        body_ratio = body / range_

        # ── GATE 2: Body ratio must exceed 0.80 (very strong commitment) ──
        # Tightened from 0.70 — the Sniper was firing on 80%+ of assets,
        # polluting the agreement gate. Only truly decisive candles qualify.
        if body_ratio < 0.80:
            return NO_TRADE

        # Determine candle direction
        if cl > o:
            direction = "call"
            close_pos = (cl - l) / range_
        elif cl < o:
            direction = "put"
            close_pos = (h - cl) / range_
        else:
            return NO_TRADE

        # ── GATE 3: Close must be in outer 10% of range (tightened from 15%) ──
        if close_pos < 0.90:
            return NO_TRADE

        # ── GATE 4: Candle range must be well above 5-candle average ──
        # Tightened from 1.1x to 1.3x — must be a true outlier, not just slightly above avg.
        recent_ranges = []
        for rc in candles[-6:-1]:
            rh = float(rc.get("max", rc.get("high", rc.get("h", 0))))
            rl = float(rc.get("min", rc.get("low", rc.get("l", 0))))
            recent_ranges.append(rh - rl)
        avg_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 0
        if avg_range > 0 and range_ < avg_range * 1.3:
            return NO_TRADE

        # ── GATE 5: Previous candle must be NEUTRAL or OPPOSITE direction ──
        # This is the independence fix: Sniper detects fresh commitment
        # after indecision/counter-movement, NOT continuation.
        prev = candles[-2]
        prev_o = float(prev.get("open", prev.get("o", 0)))
        prev_cl = float(prev.get("close", prev.get("c", 0)))
        prev_dir = "call" if prev_cl > prev_o else ("put" if prev_cl < prev_o else "neutral")

        # REJECT if previous candle is SAME direction (that's Cascade's job)
        if prev_dir == direction:
            return NO_TRADE

        # ── GATE 6: Candle 2 periods back must also be opposite/neutral ──
        # Ensures the "surprise" pattern: indecision/counter → indecision → STRONG commit
        prev2 = candles[-3]
        prev2_o = float(prev2.get("open", prev2.get("o", 0)))
        prev2_cl = float(prev2.get("close", prev2.get("c", 0)))
        prev2_dir = "call" if prev2_cl > prev2_o else ("put" if prev2_cl < prev2_o else "neutral")

        if prev2_dir == direction:
            return NO_TRADE

        warnings = []
        # Higher confidence when previous candle was actively opposite (true reversal)
        confidence = 0.76 if prev_dir != "neutral" else 0.72

        context = "reversal" if prev_dir != "neutral" else "indecision"
        reasons = [
            f"Fresh {direction} commitment after {context}: body_ratio={body_ratio:.2f}, close_pos={close_pos:.2f}",
            f"Range {range_:.6f} > avg {avg_range:.6f} (outlier candle)",
            f"Prior context: [{prev2_dir}] → [{prev_dir}] → [STRONG {direction.upper()}]",
        ]

        return StrategyResult(
            score=80.0 if direction == "call" else -80.0,
            direction=direction,
            confidence=confidence,
            reasons=reasons,
            warnings=warnings,
            should_trade=True,
            confluence=1
        )

