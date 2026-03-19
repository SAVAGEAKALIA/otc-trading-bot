from typing import Dict, Any, List
from .base import BaseStrategy, StrategyResult

class SqueezeBreakoutStrategy(BaseStrategy):
    """
    Squeeze Breakout Strategy (Pillar 3 of Quant Overhaul)
    
    Designed specifically for algorithmic OTC micro-markets:
    - Hunts for low/normal volatility regimes where Bollinger Bands are constricted (the Squeeze).
    - Ensures RSI is NEUTRAL (40-60). We avoid RSI extremes (>70/<30) because in OTC, 
      those are mathematically proven exhaustion/reversal traps.
    - The Trigger: A strong ignition candle that pierces and closes decisively across the 20 SMA,
      supported by a sudden MACD histogram baseline cross or expansion.
    """

    def __init__(self):
        super().__init__("Squeeze Breakout")

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        indicators_2m = kwargs.get('indicators_2m', {})
        indicators_5m = kwargs.get('indicators_5m', {}) # For secondary bias
        
        if not indicators_2m or not indicators_5m or len(candles) < 3:
            return StrategyResult(0.0, "neutral", 0.0, [], ["Requires both 2m and 5m indicators for Squeeze Breakout"], False)

        reasons: List[str] = []
        warnings: List[str] = []
        
        # ------------------------------------------------------------------
        # 1. Volatility & Squeeze Condition
        # ------------------------------------------------------------------
        vol_regime = str(indicators_2m.get("volatility_regime", "normal")).lower()
        bb_width_pct = float(indicators_2m.get("bb_width_pct", 100.0))
        in_squeeze = indicators_2m.get("in_squeeze", False)
        
        # We only want to trade breakouts from tight consolidation.
        if vol_regime in ("high", "extreme"):
            return StrategyResult(0.0, "neutral", 0.0, [], [f"Rejected: Volatility too high ({vol_regime}) for a Squeeze Breakout"], False)
            
        if not in_squeeze:
            warnings.append(f"Not strictly in a Keltner squeeze (BB width: {bb_width_pct:.2f}%)")
            # If not in a true squeeze but somewhat tight, penalize score later
            if bb_width_pct > 0.8:
                return StrategyResult(0.0, "neutral", 0.0, [], [f"Rejected: Not in a squeeze, Bollinger Bands too wide ({bb_width_pct:.2f}%)"], False)
        else:
            reasons.append(f"True Keltner Squeeze confirmed (BB width: {bb_width_pct:.2f}%)")

        # ------------------------------------------------------------------
        # 2. RSI Neutrality (The Anti-Exhaustion Guard)
        # ------------------------------------------------------------------
        rsi = float(indicators_2m.get("rsi", 50.0))
        if rsi > 70 or rsi < 30:
            return StrategyResult(0.0, "neutral", 0.0, [], [f"Rejected: RSI {rsi:.1f} is at exhaustion levels. Squeeze requires ignition."], False)
        
        reasons.append(f"RSI securely neutral ({rsi:.1f}) - No exhaustion.")

        # ------------------------------------------------------------------
        # 3. Ignition Trigger (SMA 20 Pierce OR BB Band Pierce)
        # ------------------------------------------------------------------
        sma_20 = float(indicators_2m.get("sma_20", 0.0))
        bb_upper = float(indicators_2m.get("bb_upper", 0.0))
        bb_lower = float(indicators_2m.get("bb_lower", 0.0))
        
        c1 = candles[-1] # Current candle
        c2 = candles[-2] # Previous candle
        
        c1_open = float(c1.get("open", 0.0))
        c1_close = float(c1.get("close", 0.0))
        c2_close = float(c2.get("close", 0.0))
        
        c1_body = abs(c1_close - c1_open)
        c1_range = float(c1.get("max", c1_close)) - float(c1.get("min", c1_open))
        c1_body_ratio = (c1_body / c1_range) if c1_range > 0 else 0
        
        direction = "neutral"
        trigger_type = ""
        
        # Condition A: SMA-20 Crossover (Exploding from the bottom up/top down)
        if c1_close > sma_20 and c2_close <= sma_20 and c1_close > c1_open:
            direction = "call"
            trigger_type = "SMA 20 Pierce"
        elif c1_close < sma_20 and c2_close >= sma_20 and c1_close < c1_open:
            direction = "put"
            trigger_type = "SMA 20 Pierce"
            
        # Condition B: BB Band Piercing (Riding the edge already)
        elif bb_upper > 0 and c1_close > bb_upper and c1_open <= bb_upper and c1_close > c1_open:
            direction = "call"
            trigger_type = "BB Upper Pierce"
        elif bb_lower > 0 and c1_close < bb_lower and c1_open >= bb_lower and c1_close < c1_open:
            direction = "put"
            trigger_type = "BB Lower Pierce"
            
        if direction == "neutral":
            return StrategyResult(0.0, "neutral", 0.0, [], ["No clear ignition pierces detected."], False)
            
        if c1_body_ratio < 0.4:
            return StrategyResult(0.0, "neutral", 0.0, [], [f"Rejected: Ignition candle is too weak (body ratio {c1_body_ratio:.2f})"], False)

        reasons.append(f"Strong Ignition Trigger: {trigger_type} ({direction.upper()})")

        # ------------------------------------------------------------------
        # 4. Momentum & 5m Confluence Scoring (Base 70)
        # ------------------------------------------------------------------
        final_score = 70.0
        
        # MACD checking for histogram expansion
        macd_hist = float(indicators_2m.get("macd_histogram", 0.0))
        if direction == "call" and macd_hist > 0:
            final_score += 10.0
            reasons.append("MACD Histogram expanding Bullish (+10)")
        elif direction == "put" and macd_hist < 0:
            final_score += 10.0
            reasons.append("MACD Histogram expanding Bearish (+10)")
        else:
            warnings.append("MACD Histogram opposing ignition")
            
        # 5m Trend confirmation (ABSOLUTE BLOCK)
        # We do not take Squeeze Breakouts against the macro trend. Counter-trend breakouts are liquidity traps.
        if indicators_5m:
            trend_5m = str(indicators_5m.get("trend", "neutral")).lower()
            if direction == "call" and trend_5m == "bullish":
                final_score += 10.0
                reasons.append("5m Macro Trend confirms Bullish Squeeze (+10)")
            elif direction == "put" and trend_5m == "bearish":
                final_score += 10.0
                reasons.append("5m Macro Trend confirms Bearish Squeeze (+10)")
            elif (direction == "call" and trend_5m == "bearish") or (direction == "put" and trend_5m == "bullish"):
                return StrategyResult(0.0, "neutral", 0.0, [], [f"Rejected: Squeeze Breakout ({direction.upper()}) is fighting the 5m Macro Trend ({trend_5m}). Liquidity trap detected."], False)
                
        # Squeeze tightness bonus
        if in_squeeze:
            final_score += 15.0
            reasons.append(f"True Keltner Squeeze Tension Release (+15)")
        elif bb_width_pct < 0.3:
            final_score += 10.0
            reasons.append(f"Extreme BB Compression ({bb_width_pct:.2f}%) (+10)")
            
        # Hard Cap
        final_score = min(100.0, max(0.0, final_score))
        
        # Threshold enforcement (Requires >= 75 to pass)
        if final_score < 75.0:
            return StrategyResult(final_score, direction, min(0.95, final_score/100.0), reasons, warnings + [f"Rejected: Squeeze Score too low ({final_score:.1f} < 75)"], False)

        return StrategyResult(
            score=final_score if direction == "call" else -final_score,
            direction=direction,
            confidence=min(0.95, final_score/100.0),
            reasons=reasons,
            warnings=warnings,
            should_trade=True
        )
