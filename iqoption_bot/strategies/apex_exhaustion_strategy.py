import math
from typing import Dict, Any, List

from .base import BaseStrategy, StrategyResult
from ..data_provider import get_completed_candles

class ApexExhaustionStrategy(BaseStrategy):
    """
    Apex Exhaustion Strategy (Inverse Breakout).
    
    Identifies 2m trades that score 95+ on standard momentum indicators
    (which historically have a 39.4% win rate as breakouts in OTC) and 
    fades them. Trades the algorithmic exhaustion/liquidity trap.
    """
    
    name = "ApexExhaustion"
    description = "Fades extreme momentum breakouts (RSI>80/ADX>45) that represent broker traps in OTC."
    
    def __init__(self):
        super().__init__("Apex Exhaustion")
    
    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        candles = get_completed_candles(candles, min_required=10)
        if not candles:
            return self._neutral("Insufficient 2m candles for Apex audit")

            
        indicators = kwargs.get('indicators_2m', {})
        indicators_prev = kwargs.get('indicators_2m_prev', {})
        indicators_15m = kwargs.get('indicators_15m', {})
        
        if not indicators:
            return self._neutral("Missing 2m indicators")
            
        rsi = float(indicators.get('rsi', 50.0))
        adx = float(indicators.get('adx', 0.0))
        bb_pos = float(indicators.get('bb_position', 0.5))
        
        reasons = []
        warnings = []
        direction = "neutral"
        score = 0.0
        
        # 1. Macro Trend Fail-Safe
        # Fading a micro-breakout is DANGEROUS if it's aligned with the macro trend.
        # We only fade BULLISH pops if 15m is BEARISH or NEUTRAL.
        # We only fade BEARISH drops if 15m is BULLISH or NEUTRAL.
        trend_15m = str(indicators_15m.get('trend', 'neutral')).lower() if indicators_15m else "neutral"

        # 2. Volume/Range Climax Check (Blowoff Requirement)
        # Truth: A micro-breakout only "Exhausts" if it ends with a climax candle.
        c1 = candles[-1]
        c1_range = float(c1.get('max', 0)) - float(c1.get('min', 0))
        
        prev_ranges = [float(c.get('max', 0)) - float(c.get('min', 0)) for s in [candles[-11:-1]] for c in s]
        avg_range = sum(prev_ranges) / len(prev_ranges) if prev_ranges else 0.0
        
        is_blowoff = c1_range > (avg_range * 1.5) if avg_range > 0 else False
        
        # 3. ADX Intensity Hardening (35 -> 40)
        if adx < 40:
            return self._neutral(f"ADX ({adx:.1f}) too low for a high-conviction Apex fade")

        if rsi > 75 and bb_pos > 0.95:
            # Check for Macro Conflict
            if trend_15m == 'bullish':
                return self._neutral("Rejected: Cannot fade Bullish Apex when 15m Macro is Bullish")
                
            if not is_blowoff:
                warnings.append(f"Caution: No range blowoff detected (Range: {c1_range:.5f} vs Avg: {avg_range:.5f})")
                
            # Fake Bullish Breakout -> Fade it (PUT)
            direction = "put"
            score = -90.0
            reasons.append(f"Apex Bullish Trap: RSI {rsi:.1f}, BB {bb_pos:.2f}, ADX {adx:.1f}")
            
            # 4. The Trapdoor Risk Condition: Parabolic ADX
            prev_adx = float(indicators_prev.get('adx', 0.0)) if indicators_prev else 0.0
            if prev_adx > 0 and adx > (prev_adx + 2.0) and adx > 55 and rsi > 80:
                warnings.append("🚨 TRAPDOOR: ADX is going parabolic. This is a runaway event, not exhaustion.")
                score = -30.0 # Force block
                
        elif rsi < 25 and bb_pos < 0.05:
            # Check for Macro Conflict
            if trend_15m == 'bearish':
                return self._neutral("Rejected: Cannot fade Bearish Apex when 15m Macro is Bearish")

            if not is_blowoff:
                warnings.append(f"Caution: No range blowoff detected (Range: {c1_range:.5f} vs Avg: {avg_range:.5f})")
                
            # Fake Bearish Breakout -> Fade it (CALL)
            direction = "call"
            score = 90.0
            reasons.append(f"Apex Bearish Trap: RSI {rsi:.1f}, BB {bb_pos:.2f}, ADX {adx:.1f}")
            
            # 4. The Trapdoor Risk Condition: Parabolic ADX
            prev_adx = float(indicators_prev.get('adx', 0.0)) if indicators_prev else 0.0
            if prev_adx > 0 and adx > (prev_adx + 2.0) and adx > 55 and rsi < 20:
                warnings.append("🚨 TRAPDOOR: ADX is going parabolic. This is a runaway event, not exhaustion.")
                score = 30.0 # Force block
                
        else:
            return self._neutral("Conditions not at extreme apex levels")

        # Bonus: Blowoff Confirmation
        if is_blowoff and abs(score) >= 85:
            score = score * 1.1 # Extra conviction
            reasons.append(f"Blowoff Climax confirmed (Range 1.5x avg) (+10%)")

        final_score = min(100.0, max(0.0, abs(score)))

        return StrategyResult(
            score=final_score if direction == "call" else -final_score,
            direction=direction,
            confidence=final_score / 100.0,
            reasons=reasons,
            warnings=warnings,
            should_trade=final_score >= 85.0
        )
        
    def _neutral(self, reason: str) -> StrategyResult:
        return StrategyResult(0.0, "neutral", 0.0, [], [reason], False)
