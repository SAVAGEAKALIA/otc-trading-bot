"""
Momentum Cascade Strategy — OTC candle geometry.

Detects 2+ same-direction candles with STEADY bodies and enters
in the *continuation* direction (momentum, not reversal).

DATA BASIS (192 fingerprints, 110 with candle data):
- Steady expansion (0.5-1.0x) = 61.1% WR (18 trades) ← SWEET SPOT
- Mild expansion (1.0-1.5x) = 52.4% WR (21 trades)
- Strong expansion (1.5-2.5x) = 35.5% WR (31 trades) ← TRAP
- Explosive (>2.5x) = 40.6% WR (32 trades) ← TRAP

Key insight: OTC engines bait entries with big expanding candles then
reverse. The real edge is in STEADY, controlled continuation — candles
that maintain size without exploding. Calm momentum, not aggressive.

No RSI, MACD, or Bollinger — pure price structure.
"""
from typing import Dict, Any, List
from .base import BaseStrategy, StrategyResult
from ..data_provider import get_completed_candles


class MomentumCascadeStrategy(BaseStrategy):
    """Candle momentum cascade — ride expanding directional runs."""

    def __init__(self):
        super().__init__(name="Momentum Cascade")

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        NO_TRADE = StrategyResult(0.0, "neutral", 0.0, [], [], False)

        candles = get_completed_candles(candles, min_required=4)
        if not candles:
            return NO_TRADE


        # Extract last 4 completed candles (index -4 to -1)
        recent = candles[-4:]

        opens = []
        closes = []
        highs = []
        lows = []
        for c in recent:
            opens.append(float(c.get("open", c.get("o", 0))))
            closes.append(float(c.get("close", c.get("c", 0))))
            highs.append(float(c.get("max", c.get("high", c.get("h", 0)))))
            lows.append(float(c.get("min", c.get("low", c.get("l", 0)))))

        # Compute body and range for each candle
        bodies = [abs(closes[i] - opens[i]) for i in range(4)]
        ranges_ = [highs[i] - lows[i] for i in range(4)]
        directions = []
        for i in range(4):
            if closes[i] > opens[i]:
                directions.append("call")
            elif closes[i] < opens[i]:
                directions.append("put")
            else:
                directions.append("neutral")

        # ── GATE 1: Last 2 candles must share the same direction ──
        # (relaxed from 3 — OTC rarely gives 3 consecutive same-dir candles)
        last2_dirs = directions[2:]  # indices 2,3
        if "neutral" in last2_dirs:
            return NO_TRADE
        if len(set(last2_dirs)) != 1:
            return NO_TRADE
        cascade_dir = last2_dirs[0]

        # ── BONUS: If 3 candles align, boost confidence later ──
        three_aligned = (directions[1] == cascade_dir)

        # ── GATE 2: Last 2 body ratios must exceed 0.25 (no dojis) ──
        # DATA: Doji (<0.2) = 25% WR. Medium bodies (0.4-0.6) = 52.6% WR.
        # Floor lowered from 0.30 to 0.25 to include medium-body candles.
        for i in range(2, 4):
            if ranges_[i] == 0:
                return NO_TRADE
            ratio = bodies[i] / ranges_[i]
            if ratio < 0.25:
                return NO_TRADE

        # ── GATE 3: Body expansion — steady range (0.5x to 1.2x) ──
        # DATA: Steady (0.5-1.0x) = 61.1% WR. Mild (1.0-1.5x) = 52.4%.
        # Strong (>1.5x) = 35.5% WR — OTC trap candles.
        # The sweet spot is STEADY continuation, not explosive expansion.
        if bodies[2] == 0:
            return NO_TRADE
        expansion = bodies[3] / bodies[2]
        if expansion < 0.50:
            return NO_TRADE
        if expansion > 1.2:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"Expansion {expansion:.2f}x too strong (>1.2x — steady candles win in OTC)"], False
            )

        # ── GATE 4: Last candle closed in the outer 35% of its range ──
        last_range = ranges_[3]
        if last_range == 0:
            return NO_TRADE
        if cascade_dir == "call":
            close_position = (closes[3] - lows[3]) / last_range
        else:
            close_position = (highs[3] - closes[3]) / last_range

        if close_position < 0.65:
            return NO_TRADE

        # All gates passed — signal continuation
        confidence = 0.78 if three_aligned else 0.72
        cascade_label = "3-candle" if three_aligned else "2-candle"
        reasons = [
            f"{cascade_label} {cascade_dir} cascade with body expansion",
            f"Bodies: {bodies[2]:.6f} → {bodies[3]:.6f} (expansion {expansion:.2f}x)",
            f"Close position: {close_position:.2f} (strong)"
        ]

        return StrategyResult(
            score=80.0 if cascade_dir == "call" else -80.0,
            direction=cascade_dir,
            confidence=confidence,
            reasons=reasons,
            warnings=[],
            should_trade=True,
            confluence=1
        )

