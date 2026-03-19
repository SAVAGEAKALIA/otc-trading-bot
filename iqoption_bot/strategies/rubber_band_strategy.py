import math
from typing import Dict, Any, List

from .base import BaseStrategy, StrategyResult

class RubberBandStrategy(BaseStrategy):
    """
    Rubber Band Strategy (Macro Pullback).
    
    Trades the snap-back when a micro timeframe (2m) crashes violently
    against an established macro trend (15m). Designed exclusively for OTC.
    
    Condition: 15m is strictly trending. 2m is heavily oversold/overbought against it.
    Action: Fade the 2m move to re-align with the 15m.
    """
    
    name = "RubberBand"
    description = "Trades 2m extreme pullbacks against established 15m macro trends."
    
    def __init__(self):
        super().__init__("Rubber Band")
    
    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        if not candles or len(candles) < 2:
            return self._neutral("Insufficient 2m candles")
            
        indicators_2m = kwargs.get('indicators_2m', {})
        indicators_5m = kwargs.get('indicators_5m', {})
        indicators_15m = kwargs.get('indicators_15m', {})
        
        if not indicators_2m or not indicators_5m or not indicators_15m:
            return self._neutral("Requires 2m, 5m, and 15m indicators")
            
        reasons = []
        warnings = []
        
        # 1. Macro Alignment (15m + 5m)
        # Ruthless Rule: 5m MUST agree with 15m or we don't fade the 2m move.
        trend_15m = str(indicators_15m.get('trend', 'neutral')).lower()
        trend_5m = str(indicators_5m.get('trend', 'neutral')).lower()
        
        if trend_15m == 'neutral':
            return self._neutral("Macro trend (15m) is neutral. No elastic tension.")
            
        if trend_5m != trend_15m:
            return self._neutral(f"Macro conflict: 15m is {trend_15m} but 5m is {trend_5m}. Standing aside.")
            
        # 2. Micro Condition (2m Extreme Stretch)
        rsi_2m = float(indicators_2m.get('rsi', 50.0))
        bb_pos = float(indicators_2m.get('bb_position', 0.5))
        stoch_k = float(indicators_2m.get('stoch_k', 50.0))
        macd_hist = float(indicators_2m.get('macd_histogram', 0.0))
        adx_2m = float(indicators_2m.get('adx', 0.0))
        
        # 3. Runaway Guard (ADX)
        # If ADX is spiking > 40 on 2m, the "pullback" is actually a violent breakout. Do not fade.
        if adx_2m > 40:
            return self._neutral(f"Runaway detected: 2m ADX {adx_2m:.1f} too strong for a pullback trade")
            
        direction = "neutral"
        score = 0.0
        
        if trend_15m == 'bullish':
            # Looking for a crash (bearish 2m) to buy the dip
            # Tightened: RSI < 30 (from 35), BB < 0.05 (from 0.1)
            if rsi_2m < 30 and bb_pos < 0.05:
                direction = "call"
                score = 85.0
                reasons.append(f"Bullish Alignment (5m+15m) + 2m Extreme Crash (RSI {rsi_2m:.1f}, BB {bb_pos:.2f})")
                
                if stoch_k < 20:
                    score += 5.0
                    reasons.append("Stochastic oversold")
                if macd_hist > kwargs.get('prev_macd_hist', macd_hist):
                    score += 10.0
                    reasons.append("Momentum curling up")
            else:
                return self._neutral(f"15m/5m Bullish, but 2m stretch (RSI {rsi_2m:.1f}, BB {bb_pos:.2f}) insufficient")
                
        elif trend_15m == 'bearish':
            # Looking for a spike (bullish 2m) to sell the rip
            # Tightened: RSI > 70 (from 65), BB > 0.95 (from 0.9)
            if rsi_2m > 70 and bb_pos > 0.95:
                direction = "put"
                score = -85.0
                reasons.append(f"Bearish Alignment (5m+15m) + 2m Extreme Spike (RSI {rsi_2m:.1f}, BB {bb_pos:.2f})")
                
                if stoch_k > 80:
                    score -= 5.0
                    reasons.append("Stochastic overbought")
                if macd_hist < kwargs.get('prev_macd_hist', macd_hist):
                    score -= 10.0
                    reasons.append("Momentum curling down")
            else:
                return self._neutral(f"15m/5m Bearish, but 2m stretch (RSI {rsi_2m:.1f}, BB {bb_pos:.2f}) insufficient")

        if direction == "neutral":
            return self._neutral("Conditions not met")
            
        # Final Score Cap
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
