"""
Compression Breakout Strategy — OTC candle geometry.

Detects volatility compression (5 candles with below-average range)
followed by a MILD expansion candle, then enters in the micro-trend direction.

DATA BASIS (192 fingerprints):
- Steady expansion (0.5-1.0x) = 61.1% WR ← best zone
- Mild expansion (1.0-1.5x) = 52.4% WR ← acceptable
- Strong expansion (>1.5x) = 35.5% WR ← OTC trap, BLOCKED
- Explosive (>2.5x) = 40.6% WR ← OTC trap, BLOCKED

OTC engines bait entries with large expansion candles after compression.
Mild breakouts (1.1-1.5x) are the real signal. Explosive ones are traps.

No Bollinger, no Keltner, no indicators — pure price structure.
"""
from typing import Dict, Any, List
from .base import BaseStrategy, StrategyResult


class CompressionBreakoutStrategy(BaseStrategy):
    """Volatility compression → expansion breakout."""

    def __init__(self):
        super().__init__(name="Compression Breakout")

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        NO_TRADE = StrategyResult(0.0, "neutral", 0.0, [], [], False)

        if not candles or len(candles) < 25:
            return NO_TRADE

        # Extract OHLC for last 25 candles
        def _f(c, key, *alts):
            for k in (key, *alts):
                if k in c:
                    return float(c[k])
            return 0.0

        highs = [_f(c, "max", "high", "h") for c in candles[-25:]]
        lows = [_f(c, "min", "low", "l") for c in candles[-25:]]
        closes = [_f(c, "close", "c") for c in candles[-25:]]
        opens = [_f(c, "open", "o") for c in candles[-25:]]

        ranges_ = [highs[i] - lows[i] for i in range(25)]

        # ── 20-candle average range (the "normal" volatility baseline) ──
        avg_range_20 = sum(ranges_[:20]) / 20.0
        if avg_range_20 == 0:
            return NO_TRADE

        # ── 5-candle average range (the compression window) ──
        compression_window = ranges_[20:25]  # last 5 candles
        avg_range_5 = sum(compression_window) / 5.0

        # ── GATE 1: Compression — 5-candle avg must be below 20-candle avg ──
        if avg_range_5 >= avg_range_20:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"No compression: 5c avg {avg_range_5:.6f} >= 20c avg {avg_range_20:.6f}"], False
            )

        # ── GATE 2: Last candle is the expansion candle ──
        # DATA: Steady expansion (0.5-1.0x) = 61.1% WR. Strong (>1.5x) = 35.5% WR.
        # Expansion must be MILD (1.1-1.5x). Explosive breakouts (>1.5x) are OTC traps.
        # Lowered floor from 1.2 to 1.1 to capture subtler breakouts.
        last_range = ranges_[24]
        expansion_ratio = last_range / avg_range_5 if avg_range_5 > 0 else 0
        if expansion_ratio < 1.1:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"No expansion: ratio {expansion_ratio:.2f} < 1.1x"], False
            )
        if expansion_ratio > 1.5:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"Expansion {expansion_ratio:.1f}x too strong (>1.5x = trap in OTC)"], False
            )

        # ── Determine micro-trend from last 5 close-to-close moves ──
        net_moves = 0
        for i in range(21, 25):
            if closes[i] > closes[i - 1]:
                net_moves += 1
            elif closes[i] < closes[i - 1]:
                net_moves -= 1

        if net_moves == 0:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                ["Micro-trend is flat (net moves = 0)"], False
            )

        micro_dir = "call" if net_moves > 0 else "put"

        # ── GATE 3: Expansion candle must confirm direction ──
        expansion_candle_bullish = closes[24] > opens[24]
        if micro_dir == "call" and not expansion_candle_bullish:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                ["Expansion candle is bearish but micro-trend is bullish"], False
            )
        if micro_dir == "put" and expansion_candle_bullish:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                ["Expansion candle is bullish but micro-trend is bearish"], False
            )

        # ── GATE 4: Expansion candle body must be meaningful ──
        exp_body = abs(closes[24] - opens[24])
        exp_range = ranges_[24]
        if exp_range == 0:
            return NO_TRADE
        body_ratio = exp_body / exp_range
        if body_ratio < 0.35:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"Expansion candle body ratio {body_ratio:.2f} too weak"], False
            )

        # All gates passed
        compression_pct = (1.0 - avg_range_5 / avg_range_20) * 100
        reasons = [
            f"Compression {compression_pct:.0f}% (5c avg < 20c avg)",
            f"Expansion {expansion_ratio:.1f}x on {'bullish' if expansion_candle_bullish else 'bearish'} candle",
            f"Micro-trend: {micro_dir} (net {net_moves:+d} moves)",
        ]

        return StrategyResult(
            score=80.0 if micro_dir == "call" else -80.0,
            direction=micro_dir,
            confidence=0.72,
            reasons=reasons,
            warnings=[],
            should_trade=True,
            confluence=1
        )

