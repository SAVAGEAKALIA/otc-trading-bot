from typing import Dict, Any, List, Optional
from datetime import datetime
from .base import BaseStrategy, StrategyResult
from trading_platform.market_data import get_completed_candles

class MHIStrategy(BaseStrategy):
    """
    MHI Strategy Family (MHI, Majority, R7)
    - Minority color counting
    - Phase-aware (RSI filtering)
    - Reversal focus
    
    Variant determines cluster size:
      'mhi'      → 3 candles
      'majority' → 5 candles
      'r7'       → 7 candles
    """

    VARIANT_MAP = {'mhi': 3, 'majority': 5, 'r7': 7}

    def __init__(self, variant: str = 'mhi'):
        self._variant = variant.lower()
        self._cluster_size = self.VARIANT_MAP.get(self._variant, 3)
        # Name matches what the strategy engine uses for selection
        name = {'mhi': 'MHI', 'majority': 'Majority', 'r7': 'R7'}.get(self._variant, 'MHI')
        super().__init__(name)

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        """
        Implementation of color-cluster minority strategy.
        """
        # Use instance cluster size (set at construction), not runtime kwarg
        cluster_size = self._cluster_size
        candles = get_completed_candles(candles, min_required=cluster_size)
        if not candles:
            return StrategyResult(0.0, "neutral", 0.0, [], [f"Insufficient candles for {self._variant}"], False)

        profile = kwargs.get('profile', 'reversal')
        indicators_15m = kwargs.get('indicators_15m', {})
        indicators_2m = kwargs.get('indicators_2m', {})  # For RSI guard


        cluster = candles[-cluster_size:]
        label = {'mhi': 'MHI', 'majority': 'Majority', 'r7': 'R7'}.get(self._variant, 'MHI')

        # 2. Count colors and measure candle body strength
        verdes = 0
        vermelhas = 0
        dojis = 0
        total_body_ratio = 0.0
        for c in cluster:
            o = float(c.get('open', 0))
            cl = float(c.get('close', 0))
            hi = float(c.get('max', max(o, cl)))
            lo = float(c.get('min', min(o, cl)))
            candle_range = hi - lo
            body = abs(cl - o)
            body_ratio = body / candle_range if candle_range > 0 else 0.0
            total_body_ratio += body_ratio
            
            # Define dojis relative to this candle's own range.  An absolute
            # price epsilon classifies the same shape differently on JPY,
            # forex, crypto, and low-decimal synthetic symbols.
            is_doji = candle_range <= 0 or body_ratio <= 0.05
            if is_doji:
                dojis += 1
            elif cl > o:
                verdes += 1
            elif cl < o:
                vermelhas += 1

        avg_body_ratio = total_body_ratio / cluster_size if cluster_size > 0 else 0.0

        direction = "neutral"
        if verdes > vermelhas:
            direction = "put"
        elif vermelhas > verdes:
            direction = "call"
        else:
            return StrategyResult(0.0, "neutral", 0.0, [f"{label} Tie"], [], False)

        # 3. Dominance ratio: how lopsided is the color count?
        majority = max(verdes, vermelhas)
        minority = min(verdes, vermelhas)
        dominance_ratio = (majority - minority) / cluster_size  # 0.0 to 1.0

        # 4. Apply Professional Guards (RSI Extrema)
        rsi = float(indicators_2m.get('rsi', 50.0))
        is_overextended = False
        reasons = [f"{label} Pattern: {verdes}V x {vermelhas}R (dom: {dominance_ratio:.0%})"]
        warnings = []
        should_trade = True
        rsi_bonus = 0.0

        if direction == "call":
            if rsi < 32:
                is_overextended = True
                rsi_bonus = 12.0
                reasons.append(f"RSI Oversold Guard ({rsi:.1f})")
            elif rsi < 45:
                rsi_bonus = 5.0
            elif rsi > 65:
                return StrategyResult(0.0, "neutral", 0.0, [], [f"Rejected: MHI CALL blocked by high RSI ({rsi:.1f})"], False)
            else:
                rsi_bonus = -15.0
                warnings.append(f"RSI neutral ({rsi:.1f}) — risky reversal penalty (-15)")
        elif direction == "put":
            if rsi > 68:
                is_overextended = True
                rsi_bonus = 12.0
                reasons.append(f"RSI Overbought Guard ({rsi:.1f})")
            elif rsi > 55:
                rsi_bonus = 5.0
            elif rsi < 35:
                return StrategyResult(0.0, "neutral", 0.0, [], [f"Rejected: MHI PUT blocked by low RSI ({rsi:.1f})"], False)
            else:
                rsi_bonus = -15.0
                warnings.append(f"RSI neutral ({rsi:.1f}) — risky reversal penalty (-15)")

        indicators_5m = kwargs.get('indicators_5m', {})
        
        # 5. Profile Filtering (Dynamic Trend Security)
        trend_penalty = 0.0
        if profile == "trend" and indicators_5m:
            trend_5m = str(indicators_5m.get('trend', 'neutral')).lower()
            adx_5m = float(indicators_5m.get('adx', 0.0))
            
            # Conflict Check
            is_conflict = (direction == "call" and trend_5m != "bullish") or \
                          (direction == "put" and trend_5m != "bearish")
            
            if is_conflict:
                if adx_5m >= 25:
                    return StrategyResult(0.0, "neutral", 0.0, [], [f"Rejected: MHI {direction.upper()} vs strong 5m {trend_5m} trend (ADX {adx_5m:.1f})"], False)
                elif adx_5m >= 18:
                    trend_penalty = 20.0
                    warnings.append(f"MHI {direction.upper()} vs moderate 5m {trend_5m} trend: -{trend_penalty:.0f} pts")
                else:
                    trend_penalty = 0.0
                    reasons.append(f"Trend Veto Bypassed: 5m {trend_5m} is weak (ADX {adx_5m:.1f})")
            else:
                reasons.append(f"Trend Alignment: 5m {trend_5m}")

        # 6. Granular Scoring
        # Base:          40   (guaranteed above minimum, but needs bonuses to pass 70 threshold)
        # Dominance:     0-20 (proportional to how lopsided the count is)
        # Body Strength: 0-15 (strong candle bodies = high conviction, dojis = weak)
        # RSI Guard:     0-10 (overextended = max bonus)
        # Trend Align:   0-10 (5m trend alignment bonus)
        # Range: 40-95
        # typical "average" signal: 40 + 15 + 10 = 65 (just under threshold with weak dominance)
        # typical "good" signal:    40 + 20 + 12 = 72 (passes threshold)
        # perfect signal:           40 + 20 + 15 + 10 + 10 = 95

        # Dominance bonus: 0-20 (linear scale)
        # MHI:      2v1 → ratio=0.33 → 7pts;  3v0 → ratio=1.0 → 20pts
        # Majority: 3v2 → ratio=0.2  → 4pts;  5v0 → ratio=1.0 → 20pts
        # R7:       4v3 → ratio=0.14 → 3pts;  7v0 → ratio=1.0 → 20pts
        dominance_bonus = round(dominance_ratio * 20.0, 1)

        # Body strength bonus: 0-15
        # avg_body_ratio ~0.5 is normal, ~0.7+ is strong, <0.2 is doji-heavy
        if avg_body_ratio >= 0.6:
            body_bonus = 15.0
        elif avg_body_ratio >= 0.4:
            body_bonus = 10.0
        elif avg_body_ratio >= 0.2:
            body_bonus = 5.0
        else:
            body_bonus = 0.0
            warnings.append(f"Weak candle bodies (avg ratio: {avg_body_ratio:.2f})")

        # Doji penalty: if more than 1/3 of cluster are dojis, reduce body bonus
        if dojis > cluster_size / 3:
            body_bonus = max(0.0, body_bonus - 5.0)
            warnings.append(f"High doji count ({dojis}/{cluster_size})")

        final_score = 45.0 + dominance_bonus + body_bonus + rsi_bonus - trend_penalty
        if any("Trend Alignment" in r for r in reasons):
            final_score += 10.0

        reasons.append(f"Score: base=45 + dom={dominance_bonus:.0f} + body={body_bonus:.0f} + rsi={rsi_bonus:.0f}")
        
        # Hard threshold cutoff
        # MHI needs a score of >= 65 to be considered a valid entry
        if final_score < 65.0:
            signed_score = final_score if direction == "call" else -final_score
            return StrategyResult(signed_score, direction, min(1.0, final_score/100.0), reasons, warnings + [f"Rejected: Score too low ({final_score:.1f} < 65)"], False)
            
        return StrategyResult(
            score=final_score if direction == "call" else -final_score if direction == "put" else 0.0,
            direction=direction,
            confidence=min(0.95, final_score / 100.0),
            reasons=reasons,
            warnings=warnings,
            should_trade=True
        )
