"""
Exhaustion Fade Strategy — "Steady State Mean-Reversion Pocket"

Detects situations where price is at a Bollinger Band extreme BUT RSI is
calm (30-70). Enters AGAINST the BB extreme: lower BB → CALL, upper BB → PUT.

DATA BASIS (192 fingerprints):
- CALL from lower BB + RSI 30-70 = 64.7% WR (17 trades)
- PUT from upper BB + RSI 30-70 = 57.1% WR (7 trades)
- RSI < 30 (any direction) = 43.9% WR ← AVOID
- RSI > 70 (any direction) = 47.3% WR ← AVOID
- Supportive wick + 2m aligned + calm RSI = 0W/6L ← AVOID (OTC fake wicks)

Key insight: OTC engines fake wick rejections to bait entries. The real
signal is a HESITATION candle (small body, body_ratio < 0.60) at BB
extreme with calm RSI. The small body indicates the engine is pausing
before mean-reverting — this is harder to fake than a wick.

Requires indicators_2m kwargs (RSI, Stochastic, BB position, ADX).
"""
from typing import Dict, Any, List
from .base import BaseStrategy, StrategyResult
from ..data_provider import get_completed_candles


class ExhaustionFadeStrategy(BaseStrategy):
    """Steady State Mean-Reversion — fade BB extremes when RSI is calm."""

    def __init__(self):
        super().__init__(name="Exhaustion Fade")

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        NO_TRADE = StrategyResult(0.0, "neutral", 0.0, [], [], False)

        candles = get_completed_candles(candles, min_required=6)
        if not candles:
            return NO_TRADE

        indicators_2m = kwargs.get("indicators_2m", {})
        if not indicators_2m:
            return NO_TRADE


        rsi = float(indicators_2m.get("rsi", 50.0))
        stoch_k = float(indicators_2m.get("stoch_k", 50.0))
        stoch_d = float(indicators_2m.get("stoch_d", 50.0))
        bb_pos = float(indicators_2m.get("bb_position", 0.5))
        adx = float(indicators_2m.get("adx", 0.0))

        reasons = []
        direction = "neutral"

        # ── GATE 1: RSI must be CALM (30-70) — the key Sprint 3 change ──
        # DATA: RSI extremes (<30 or >70) = 43-47% WR. AVOID.
        # RSI 30-70 + BB extreme = 64.7% WR. The "Steady State Pocket".
        if rsi < 30 or rsi > 70:
            return NO_TRADE
        reasons.append(f"RSI calm: {rsi:.1f} (30-70 pocket)")

        # ── GATE 2: BB position at extreme — price is stretched ──
        if bb_pos < 0.10:
            direction = "call"
            reasons.append(f"BB lower extreme: {bb_pos:.2f} (below 10%)")
        elif bb_pos > 0.90:
            direction = "put"
            reasons.append(f"BB upper extreme: {bb_pos:.2f} (above 90%)")
        else:
            return NO_TRADE

        # ── GATE 3: Stochastic confirms the stretch (not contradicting) ──
        if direction == "call" and stoch_k > 50:
            return NO_TRADE  # Stoch says not oversold at all
        if direction == "put" and stoch_k < 50:
            return NO_TRADE  # Stoch says not overbought at all
        reasons.append(f"Stoch K confirms stretch: {stoch_k:.1f}")

        # ── GATE 4: Hesitation candle — small body indicates genuine indecision ──
        # DATA: Supportive wick + 2m aligned + calm RSI = 0W/6L (0% WR).
        # OTC engines FAKE wick rejections to bait entries. But small-body
        # candles (hesitation/indecision) are harder to fake — they indicate
        # the engine is pausing before mean-reverting.
        # Medium bodies (0.4-0.6) = 52.6% WR. Marubozu (>0.8) = 46.2%.
        c = candles[-1]
        o = float(c.get("open", c.get("o", 0)))
        h = float(c.get("max", c.get("high", c.get("h", 0))))
        l = float(c.get("min", c.get("low", c.get("l", 0))))
        cl = float(c.get("close", c.get("c", 0)))

        rng = h - l
        if rng == 0 or rng < 1e-8:
            return NO_TRADE

        body = abs(cl - o)
        body_ratio = body / rng

        if body_ratio > 0.60:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"Entry candle body ratio {body_ratio:.2f} too strong (need hesitation < 0.60)"], False
            )
        reasons.append(f"Hesitation candle: body {body_ratio:.0%} of range (indecision)")

        # ── GATE 5: 5m trend must not strongly oppose the trade ──
        indicators_5m = kwargs.get("indicators_5m", {})
        if indicators_5m:
            trend_5m = str(indicators_5m.get("trend", "neutral")).lower()
            adx_5m = float(indicators_5m.get("adx", 0.0))
            # Only block if 5m has strong opposing trend
            if adx_5m > 25:
                if direction == "call" and trend_5m == "bearish":
                    return StrategyResult(
                        0.0, "neutral", 0.0, [],
                        ["5m bearish trend too strong to fade"], False
                    )
                if direction == "put" and trend_5m == "bullish":
                    return StrategyResult(
                        0.0, "neutral", 0.0, [],
                        ["5m bullish trend too strong to fade"], False
                    )

        # ── GATE 6: Not a runaway move (ADX guard) ──
        if adx > 40:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"ADX {adx:.1f} too high — runaway move, not mean-reversion"], False
            )

        # ── BONUS: Stochastic crossover confirmation ──
        confidence = 0.78
        if direction == "call" and stoch_k > stoch_d:
            confidence = 0.82  # Stoch turning up from low = bounce starting
            reasons.append(f"Stoch K>{stoch_d:.1f} crossover — bounce starting")
        elif direction == "put" and stoch_k < stoch_d:
            confidence = 0.82  # Stoch turning down from high = fade starting
            reasons.append(f"Stoch K<{stoch_d:.1f} crossover — fade starting")

        score = 85.0

        return StrategyResult(
            score=score if direction == "call" else -score,
            direction=direction,
            confidence=confidence,
            reasons=reasons,
            warnings=[],
            should_trade=True,
            confluence=1
        )

