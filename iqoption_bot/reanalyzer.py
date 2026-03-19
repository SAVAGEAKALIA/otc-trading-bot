import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from .analytics import MarketAnalyzer, SignalGatekeeper, TradeDecision
from .data_provider import MarketDataProvider
from .patterns import PatternAnalyzer

@dataclass
class SmartSignalConfig:
    enabled: bool = True  # Enabled by default for Telegram signal validation
    flip_trades: bool = True  # Default to True for "Smart" flipping
    dynamic_duration: bool = True  # Default to True for "Smart" durations
    sentiment_weight: float = 0.6  # Weight of independent ReAnalyzer sentiment
    technical_weight: float = 0.4  # Weight of Gatekeeper technical score
    min_confidence_to_modify: float = 0.60
    min_score_to_flip: float = 30.0  # Score threshold to trigger flip evaluation
    min_score_to_approve: float = 10.0  # Reject below this (too neutral/confusing)
    martingale_min_score: float = 15.0  # NEW: Conviction floor for recovery
    max_duration: int = 4  # Cap duration (consistent with scanner)
    dry_run: bool = False

@dataclass
class ReAnalysisResult:
    action: str  # "keep", "reject", "flip", "modify_duration"
    new_direction: str
    new_duration: int
    confidence: float
    score: float
    reason: str
    original_signal: Dict[str, Any]

class SignalReAnalyzer:
    def __init__(self, data_provider: MarketDataProvider, analyzer: MarketAnalyzer, gatekeeper: SignalGatekeeper, pattern_analyzer: Optional[PatternAnalyzer] = None):
        self.data_provider = data_provider
        self.analyzer = analyzer
        self.gatekeeper = gatekeeper
        self.pattern_analyzer = pattern_analyzer
        self.config = SmartSignalConfig()
        self.logger = logging.getLogger(__name__)

    def set_config(self, config: SmartSignalConfig):
        self.config = config

    async def analyze(self, asset: str, original_direction: str, original_duration: int, is_martingale: bool = False) -> ReAnalysisResult:
        """
        Re-analyze a signal using the bot's internal logic (Gatekeeper + MTF).
        Returns a decision to keep, reject, flip, or modify the signal.
        """
        if not self.config.enabled:
            return ReAnalysisResult("keep", original_direction, original_duration, 0.0, 0.0, "SmartSignal disabled", {})

        # 1. Fresh MTF Data Fetch
        include_5m = True 
        include_15m = True 
        
        try:
            mtf_bundle = await self.data_provider.get_mtf_bundle(
                asset, include_5m=include_5m, include_15m=include_15m
            )
        except Exception as e:
            self.logger.error(f"Failed to fetch data for re-analysis: {e}")
            return ReAnalysisResult("keep", original_direction, original_duration, 0.0, 0.0, f"Data fetch error: {e}", {})

        if not mtf_bundle.entry_tf.is_valid:
             return ReAnalysisResult("keep", original_direction, original_duration, 0.0, 0.0, "Not enough data", {})

        # 2. Key Indicators
        indicators = self.analyzer.calculate_indicators(mtf_bundle.entry_tf.candles, symbol=asset)
        if not indicators: indicators = {}
        
        volatility_regime = str(indicators.get('volatility_regime', 'normal')).lower()
        adx_val = float(indicators.get("adx", 0.0))

        # ---- Volatility Safety Check ----
        if volatility_regime == "extreme" and not is_martingale:
            return ReAnalysisResult("reject", original_direction, original_duration, 0.0, 0.0,
                                   "SmartReject: Extreme volatility (High Risk)", {})

        # 3. Independent Smart Sentiment Audit (Phase 20)
        sentiment_score = self._compute_smart_sentiment(mtf_bundle, original_direction, asset)
        
        # 4. Gatekeeper Check (Technical Layer)
        orig_gatekeeper_mode = self.gatekeeper.mode
        if is_martingale:
            self.gatekeeper.set_mode("very_relaxed")
            
        decision = self._run_gatekeeper(mtf_bundle, original_direction, asset, is_martingale=is_martingale)
        
        # Restore gatekeeper mode
        if is_martingale:
            self.gatekeeper.set_mode(orig_gatekeeper_mode)
            
        # Composite Decision: 60% ReAnalyzer Sentiment + 40% Gatekeeper Technicals
        raw_gatekeeper_score = decision.score
        score = (sentiment_score * self.config.sentiment_weight) + (raw_gatekeeper_score * self.config.technical_weight)
        
        # 5. Result Extraction
        action = "keep"
        new_direction = original_direction
        new_duration = original_duration
        confidence = decision.confidence  # Confidence remains derived from technicals
        
        # 4. Flip Evaluation (Trend-Following Recovery)
        if self.config.flip_trades:
            opposite_direction = "put" if original_direction == "call" else "call"
            flip_threshold = self.config.min_score_to_flip
            
            # Lower flipping threshold in strong trends (joining the trend)
            if adx_val > 30: flip_threshold *= 0.6
            elif adx_val > 20: flip_threshold *= 0.8
            
            # For Martingale, we are MORE willing to flip if Step 1 is clearly fighting a trend
            score_triggers_flip = False
            if original_direction == "put" and score > flip_threshold:
                score_triggers_flip = True
            elif original_direction == "call" and score < -flip_threshold:
                score_triggers_flip = True
            
            if score_triggers_flip:
                should_flip = False
                flip_reason_detail = ""

                # Pattern check
                has_reversal_pattern = False
                if self.pattern_analyzer:
                    pat_analysis = self.pattern_analyzer.analyze(mtf_bundle.entry_tf.candles, opposite_direction)
                    for p in pat_analysis.get('patterns', []):
                        if p['type'] == ('bullish' if opposite_direction == 'call' else 'bearish'):
                            has_reversal_pattern = True
                            flip_reason_detail = f"Pattern: {p['name']}"
                            break

                # Strong Trend + Confident score = Flip (Zero tolerance for fighting strong trends)
                if has_reversal_pattern:
                    should_flip = True
                elif abs(score) > flip_threshold * 1.5 and adx_val > 25:
                    should_flip = True
                    flip_reason_detail = f"Strong trend breakout (ADX {adx_val:.0f})"
                
                if should_flip:
                    # Verify flip with relaxed gatekeeper
                    decision_flip = self._run_gatekeeper(mtf_bundle, opposite_direction, asset, is_martingale=is_martingale)
                    
                    if decision_flip.accept:
                        action = "flip"
                        new_direction = opposite_direction
                        confidence = decision_flip.confidence
                        score = decision_flip.score
                        reason = f"🔄 SMART RECOVERY FLIP: {flip_reason_detail} | Score: {abs(score):.0f}"
                    else:
                        reason = f"Flip blocked by risk ({decision_flip.reason})"
                else:
                    reason = f"Keep direction (Weak flip confirmation)"
            else:
                reason = f"Signal matches bias (Score {abs(score):.0f})"
        else:
            reason = f"Gatekeeper result: {decision.reason}"

        # 5. Dynamic Duration
        if self.config.dynamic_duration and action != "reject":
            # MTF alignment used for duration boosting
            align_5m, align_15m = self._check_mtf_alignment(new_direction, mtf_bundle, asset)
            new_duration = self._select_duration(
                confidence=confidence,
                confluence=decision.confluence_count,
                mtf_5m_aligned=align_5m,
                mtf_15m_aligned=align_15m,
                score=abs(score),
                volatility_regime=volatility_regime,
                adx=adx_val
            )
            if new_duration != original_duration:
                if action == "keep": action = "modify_duration"
                reason += f" | ⏱️ {original_duration}m->{new_duration}m"

        # 6. Safety Reject (Score Check)
        reject_threshold = self.config.min_score_to_approve
        
        is_rejected = False
        if is_martingale:
            # Conservative Rejection: "The Safety Floor"
            # If score is NEGATIVE, it's a trend-reversal risk (Flip or Block)
            # If score is POSITIVE but below Floor (e.g. 5.0), it's too weak (Reject)
            m_threshold = self.config.martingale_min_score
            
            if score < 0:
                is_rejected = True
                reason = f"SmartReject: Negative sentiment for recovery (Score {score:.1f})"
            elif score < m_threshold:
                is_rejected = True
                reason = f"SmartReject: Conviction below recovery floor {m_threshold} (Score {score:.1f})"
        else:
            # Normal Trade Rejection
            if score < 0:
                is_rejected = True
                reason = f"SmartReject: Sentiment clash (Independent Score {score:.1f})"
            elif score < reject_threshold:
                is_rejected = True
                reason = f"SmartReject: Market too neutral (Score {score:.1f})"

        if is_rejected:
            action = "reject"
            return ReAnalysisResult(action, new_direction, new_duration, confidence, score, reason, {"original_score": decision.score})

        return ReAnalysisResult(
            action=action,
            new_direction=new_direction,
            new_duration=new_duration,
            confidence=confidence,
            score=score,
            reason=reason,
            original_signal={"score": decision.score, "notes": decision.notes}
        )

    def _check_time_to_close(self, period: int = 120, threshold: int = 30) -> bool:
        """Check if we are within the last `threshold` seconds of the candle `period`."""
        # Current timestamp
        now = time.time()
        # Seconds elapsed in the current period
        elapsed = now % period
        # Seconds remaining
        remaining = period - elapsed
        return remaining <= threshold

    def _check_mtf_alignment(self, direction: str, bundle, asset: str = "global") -> tuple[bool, bool]:
        """Check if 5m and 15m timeframes align with direction.
        Requires actual trend direction match — momentum alone is not enough.
        Neutral trends count as non-opposing (allow but don't confirm)."""
        is_call = direction == "call"
        align_5m = False
        align_15m = False
        
        if bundle.mid_tf and bundle.mid_tf.is_valid:
            ind_5m = self.analyzer.calculate_indicators(bundle.mid_tf.candles, symbol=asset)
            if ind_5m:
                trend_5m = str(ind_5m.get("trend", "neutral")).lower()
                if is_call:
                    align_5m = trend_5m == "bullish"
                else:
                    align_5m = trend_5m == "bearish"
                
        if bundle.high_tf and bundle.high_tf.is_valid:
            ind_15m = self.analyzer.calculate_indicators(bundle.high_tf.candles, symbol=asset)
            if ind_15m:
                trend_15m = str(ind_15m.get("trend", "neutral")).lower()
                if is_call:
                    align_15m = trend_15m == "bullish"
                else:
                    align_15m = trend_15m == "bearish"
                
        return align_5m, align_15m

    def _select_duration(self, confidence: float, confluence: int, mtf_5m_aligned: bool, mtf_15m_aligned: bool, score: float, volatility_regime: str = "normal", adx: float = 0.0) -> int:
        """Select optimal duration using ADX + Volatility — consistent with scanner logic.
        
        - ADX determines BASE duration (strong trends persist longer)
        - Volatility ADJUSTS (±1)
        - Confluence + MTF act as BONUS (+1)
        - Score magnitude acts as SAFETY CAP
        """
        max_dur = self.config.max_duration
        
        # ---- Step 1: ADX-Based Duration (Primary Driver) ----
        if adx >= 25:
            base_duration = 3  # Strong trend — give it room
        elif adx >= 18:
            base_duration = 2  # Moderate trend
        else:
            base_duration = 1  # Weak/ranging — quick in-and-out

        # ---- Step 2: Volatility Adjustment (±1) ----
        if volatility_regime == "low":
            base_duration += 1  # Slow market, need more time
        elif volatility_regime in ("high", "extreme"):
            base_duration -= 1  # Fast market, move happens quickly

        # ---- Step 3: Confluence + MTF Bonus (+1 max) ----
        if confluence >= 4 and mtf_5m_aligned and mtf_15m_aligned:
            base_duration += 1  # Full alignment across all dimensions

        # ---- Step 4: Safety Cap for Weak Scores ----
        abs_score = abs(score)
        if abs_score < 25:
            base_duration = min(base_duration, 1)  # Very weak → 1 min max
        elif abs_score < 40:
            base_duration = min(base_duration, 2)  # Moderate → 2 min max

        # Clamp to configured bounds
        return max(1, min(max_dur, base_duration))

    def _compute_smart_sentiment(self, bundle, direction: str, asset: str) -> float:
        """Independent ReAnalyzer Brain: Calculates a score (-100 to +100) based purely on MTF and Sentiment.
        Specifically ignores 1m technical indicators to avoid circular validation with Gatekeeper."""
        sentiment_points = 0.0
        is_call = direction == "call"
        
        # 1. MTF Alignment (Heavy Weight: 60 pts total)
        align_5m, align_15m = self._check_mtf_alignment(direction, bundle, asset)
        oppose_5m, oppose_15m = self._check_mtf_alignment("put" if is_call else "call", bundle, asset)
        
        # 15m Trend Alignment (+30 or -30)
        if align_15m: sentiment_points += 30.0
        elif oppose_15m: sentiment_points -= 40.0 # Veto-like penalty for opposing macro trend
        
        # 5m Trend Alignment (+20 or -20)
        if align_5m: sentiment_points += 20.0
        elif oppose_5m: sentiment_points -= 30.0
        
        # 2. Pattern Sentiment (20 pts)
        if self.pattern_analyzer:
            pattern_analysis = self.pattern_analyzer.analyze(bundle.entry_tf.candles, direction)
            pats = pattern_analysis.get('patterns', [])
            if pats:
                sentiment_points += min(20.0, len(pats) * 10.0) # Bonus for patterns
            
            # Check for patterns against us
            opposite_analysis = self.pattern_analyzer.analyze(bundle.entry_tf.candles, "put" if is_call else "call")
            opp_pats = opposite_analysis.get('patterns', [])
            if opp_pats:
                sentiment_points -= min(30.0, len(opp_pats) * 15.0) # Penalty for opposing patterns
                
        # 3. Trend Intensity (ADX Bonus: 20 pts)
        # We boost the score if a trend is active and align_15m is True
        indicators = self.analyzer.calculate_indicators(bundle.entry_tf.candles, symbol=asset)
        adx_val = float(indicators.get("adx", 0.0))
        if adx_val > 25 and (align_15m or align_5m):
            sentiment_points += 20.0
        elif adx_val > 35 and (oppose_15m or oppose_5m):
            sentiment_points -= 30.0 # High ADX in wrong direction is deadly
            
        # Clamp to -100 to +100
        return max(-100.0, min(100.0, sentiment_points))

    def _run_gatekeeper(self, bundle, direction: str, asset: str = "global", is_martingale: bool = False) -> TradeDecision:
        """Run Gatekeeper decision logic on the bundle for a specific direction."""
        
        # 1. Base Indicators (Entry TF)
        indicators = self.analyzer.calculate_indicators(bundle.entry_tf.candles, symbol=asset)
        
        # 2. MTF Indicators
        indicators_2m = indicators # Use entry for 2m base score if needed
        indicators_5m = None
        if bundle.mid_tf and bundle.mid_tf.is_valid:
            indicators_5m = self.analyzer.calculate_indicators(bundle.mid_tf.candles, symbol=asset)
            
        indicators_15m = None
        if bundle.high_tf and bundle.high_tf.is_valid:
            indicators_15m = self.analyzer.calculate_indicators(bundle.high_tf.candles, symbol=asset)

        # 3. Pattern Analysis
        pattern_analysis = None
        if self.pattern_analyzer:
            try:
                # Use entry TF for pattern analysis
                assert self.pattern_analyzer is not None
                pattern_analysis = self.pattern_analyzer.analyze(bundle.entry_tf.candles, direction)
            except Exception as e:
                self.logger.warning(f"Pattern analysis failed: {e}")

        # 4. Run Gatekeeper
        decision = self.gatekeeper.decide(
            self.analyzer,
            indicators=indicators,
            pattern_analysis=pattern_analysis,
            requested_direction=direction,
            indicators_2m=indicators_2m,
            indicators_5m=indicators_5m,
            indicators_15m=indicators_15m,
            raw_candles=bundle.entry_tf.candles if bundle.entry_tf.is_valid else None,
            is_martingale=is_martingale
        )
        return decision
