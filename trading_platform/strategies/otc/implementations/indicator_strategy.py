from typing import Dict, Any, List, Optional
from .base import BaseStrategy, StrategyResult
from trading_platform.market_data import get_completed_candles

class IndicatorStrategy(BaseStrategy):
    """
    Standard Indicator Strategy (Modularized Phase 2 logic)
    - Trend Alignment
    - Entry Location (EMA 14 Pullbacks)
    - Momentum Confluence (RSI, MACD, Stoch)
    - Candle Anatomy
    """

    def __init__(self):
        super().__init__("Indicators")

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        """
        Modularized version of calculate_signal_score.
        """
        candles = get_completed_candles(candles, min_required=15)
        indicators_2m = kwargs.get('indicators_2m', {})

        indicators_5m = kwargs.get('indicators_5m')
        indicators_15m = kwargs.get('indicators_15m')
        direction = kwargs.get('direction')

        if not indicators_2m:
            return StrategyResult(0.0, "neutral", 0.0, [], ["No 2m indicator data"], False)

        reasons: List[str] = []
        warnings: List[str] = []
        total_score = 0.0
        
        target_dir = direction
        if not target_dir:
            trend_2m = str(indicators_2m.get("trend", "neutral")).lower()
            if trend_2m == "bullish": target_dir = "call"
            elif trend_2m == "bearish": target_dir = "put"
            else: target_dir = "neutral"
                
        if target_dir not in ("call", "put"):
            return StrategyResult(0.0, "neutral", 0.0, [], ["No clear direction"], False)

        # ---- NEW: Hard Constraints (Self-Contained Modularity) ----
        # 1. Minimum ADX Filter (was in scanner.py)
        adx = float(indicators_2m.get("adx", 0.0))
        if adx < 15.0:
            return StrategyResult(0.0, "neutral", 0.0, [], [f"Rejected: ADX too weak ({adx:.1f} < 15)"], False)
            
        # 2. Hard MTF 5m Alignment Check (was in scanner.py)
        if indicators_5m:
            trend_5m = str(indicators_5m.get("trend", "neutral")).lower()
            if (target_dir == "call" and trend_5m == "bearish") or (target_dir == "put" and trend_5m == "bullish"):
                return StrategyResult(0.0, target_dir, 0.0, [], [f"Rejected: 5m trend ({trend_5m}) opposes {target_dir}"], False)

        # ---- SCORING (0 to 100) ----
        # 1. Trend Alignment (30 Points)
        trend_score = 0
        trend_2m = str(indicators_2m.get("trend", "neutral"))
        
        # ADX multiplier: strong trends (>25) get full points, moderate get slight penalty
        if adx >= 25:
            adx_mult = 1.0
            reasons.append(f"ADX Strong ({adx:.0f})")
        else:
            adx_mult = 0.85
            warnings.append(f"ADX Moderate ({adx:.0f})")
        
        if target_dir == "call":
            if trend_2m == "bullish": trend_score += 15
            if indicators_5m and str(indicators_5m.get("trend", "")) == "bullish": trend_score += 15
        elif target_dir == "put":
            if trend_2m == "bearish": trend_score += 15
            if indicators_5m and str(indicators_5m.get("trend", "")) == "bearish": trend_score += 15

        if not indicators_5m:
            trend_score = trend_score * 2
        
        # Apply ADX multiplier to trend score
        trend_score = round(trend_score * adx_mult)
            
        total_score += trend_score
        reasons.append(f"Trend: {trend_score}/30")

        # 2. Entry Location (30 Points)
        location_score = 0
        ema_14 = float(indicators_2m.get("ema_14", 0.0))
        c_open = float(indicators_2m.get("candle_open", 0.0))
        c_close = float(indicators_2m.get("candle_close", 0.0))
        c_high = float(indicators_2m.get("candle_high", 0.0))
        c_low = float(indicators_2m.get("candle_low", 0.0))
        recent_high = float(indicators_2m.get("recent_high", 0.0))
        recent_low = float(indicators_2m.get("recent_low", 0.0))
        
        if ema_14 > 0:
            if target_dir == "call":
                if c_low <= ema_14:
                    location_score += 30 if c_close > ema_14 else 20
                else:
                    dist_pct = (c_low - ema_14) / ema_14
                    if dist_pct < 0.0005: location_score += 20
                    elif dist_pct < 0.0010: location_score += 10
                    else: warnings.append("Chasing entry far from EMA")
                if recent_low > 0 and recent_high > 0:
                    if (c_close - recent_low) / recent_low < 0.001:
                        location_score += 10
                        reasons.append("S/R: Bouncing off Support (+10)")
                    if (recent_high - c_close) / recent_high < 0.0002:
                        location_score -= 30
                        warnings.append("S/R ⚠️: Smashing into Resistance")
            elif target_dir == "put":
                if c_high >= ema_14:
                    location_score += 30 if c_close < ema_14 else 20
                else:
                    dist_pct = (ema_14 - c_high) / ema_14
                    if dist_pct < 0.0005: location_score += 20
                    elif dist_pct < 0.0010: location_score += 10
                    else: warnings.append("Chasing entry far from EMA")
                if recent_low > 0 and recent_high > 0:
                    if (recent_high - c_close) / recent_high < 0.001:
                        location_score += 10
                        reasons.append("S/R: Rejecting off Resistance (+10)")
                    if (c_close - recent_low) / recent_low < 0.0002:
                        location_score -= 30
                        warnings.append("S/R ⚠️: Smashing into Support")
        
        location_score = min(30, max(-30, location_score))
        total_score += location_score
        reasons.append(f"Entry Location: {location_score}/30")

        # 3. Momentum Confluence (20 Points) — tighter RSI bands
        mom_score = 0
        rsi = float(indicators_2m.get("rsi", 50.0))
        macd_hist = float(indicators_2m.get("macd_histogram", 0.0))
        stoch_k = float(indicators_2m.get("stoch_k", 50.0))
        stoch_d = float(indicators_2m.get("stoch_d", 50.0))
        atr = float(indicators_2m.get("atr", 0.0001))
        
        macd_meaningful = (abs(macd_hist) / atr if atr > 0 else 0) > 0.02
        if target_dir == "call":
            # Widened from 55-68 → 52-72 (was killing valid trend signals)
            if 52 < rsi < 72: mom_score += 7
            elif 48 < rsi <= 52: mom_score += 3  # Marginal zone
            if macd_hist > 0 and macd_meaningful: mom_score += 7
            if stoch_k > stoch_d: mom_score += 6
        elif target_dir == "put":
            # Widened from 32-45 → 28-48 (was killing valid trend signals)
            if 28 < rsi < 48: mom_score += 7
            elif 48 <= rsi < 52: mom_score += 3  # Marginal zone
            if macd_hist < 0 and macd_meaningful: mom_score += 7
            if stoch_k < stoch_d: mom_score += 6
            
        total_score += mom_score
        reasons.append(f"Momentum: {mom_score}/20")
        
        # 4. Candle Anatomy (20 Points)
        anatomy_score = 0
        body = abs(c_close - c_open)
        total_range = c_high - c_low
        body_ratio = body / total_range if total_range > 0 else 0
        if 0.15 <= body_ratio <= 0.85: anatomy_score += 10
        else: warnings.append(f"Poor candle body ({body_ratio:.2f})")
            
        if target_dir == "call":
            if c_close > c_open:
                anatomy_score += 5
                if (min(c_open, c_close) - c_low) >= body * 0.3: anatomy_score += 5
        elif target_dir == "put":
            if c_close < c_open:
                anatomy_score += 5
                if (c_high - max(c_open, c_close)) >= body * 0.3: anatomy_score += 5
                
        total_score += anatomy_score
        reasons.append(f"Candle Anatomy: {anatomy_score}/20")
        
        # Multipliers & Locks
        avg_vol = float(indicators_2m.get("avg_volume", 0.0))
        cur_vol = float(indicators_2m.get("current_volume", 0.0))
        if avg_vol > 0:
            vol_ratio = cur_vol / avg_vol
            if vol_ratio >= 1.2: total_score *= 1.15
            elif vol_ratio < 0.6: total_score *= 0.8

        # Directional RSI penalties (Trading against short-term momentum)
        if target_dir == "call" and rsi < 45:
            total_score -= 15
            warnings.append(f"⚠️ Anti-Momentum: RSI too low ({rsi:.1f}) for CALL")
        elif target_dir == "put" and rsi > 55:
            total_score -= 15
            warnings.append(f"⚠️ Anti-Momentum: RSI too high ({rsi:.1f}) for PUT")
        elif 45 <= rsi <= 55:
            # Neutral zone penalty
            total_score -= 5
        # Exhaustion Vetos: Hard penalty for buying at psychological extremes
        if target_dir == "call" and (rsi > 75 or stoch_k > 85):
            return StrategyResult(0.0, "neutral", 0.0, [], ["Rejected: Technical Overload (CALL at extreme high)"], False)
        if target_dir == "put" and (rsi < 25 or stoch_k < 15):
            return StrategyResult(0.0, "neutral", 0.0, [], ["Rejected: Technical Overload (PUT at extreme low)"], False)
        
        # Determine confidence (0.0 to 1.0 mapping of the 0-100 score)
        confidence = max(0.0, min(1.0, total_score / 100.0))
        vol_regime = str(indicators_2m.get("volatility_regime", "normal"))
        if vol_regime in ("extreme", "high"):
            total_score *= 0.8  # Penalty for crazy wick markets
            confidence *= 0.8
            warnings.append(f"Volatility penalty applied ({vol_regime})")
            
        # Hard threshold cutoff (was handled by scanner/gatekeeper)
        # If score is < 65, it is not a strong enough indicator setup
        if total_score < 65.0:
             return StrategyResult(total_score, target_dir, confidence, reasons, warnings + [f"Rejected: Score too low ({total_score:.1f} < 65)"], False)

        return StrategyResult(
            score=total_score if target_dir == "call" else -total_score,
            direction=target_dir,
            confidence=confidence,
            reasons=reasons,
            warnings=warnings,
            should_trade=True
        )
