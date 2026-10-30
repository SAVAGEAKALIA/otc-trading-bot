"""
Market analysis and technical indicators for Binary OTC trading.
Enhanced with multi-indicator analysis, volatility detection, and signal scoring.
"""

import time
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from enum import Enum
import math
try:
    from .config import STRATEGY_PROFILE
    from .data_provider import get_completed_candles
    # Removed MHIStrategy and IndicatorStrategy as per instruction
except (ImportError, ValueError):
    try:
        from config import STRATEGY_PROFILE
        from data_provider import get_completed_candles
        # Removed MHIStrategy and IndicatorStrategy as per instruction
    except ImportError:
        STRATEGY_PROFILE = "trend"
        MHIStrategy = None
        IndicatorStrategy = None
        from data_provider import get_completed_candles



class VolatilityRegime(Enum):
    """Market volatility classification."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass
class SignalScore:
    """Comprehensive signal scoring result."""
    score: float  # -100 to +100 (negative=PUT, positive=CALL)
    confidence: float  # 0 to 1
    direction: str  # "call", "put", "neutral"
    reasons: List[str]
    warnings: List[str]
    should_trade: bool
    confluence_count: int = 0


@dataclass
class TradeDecision:
    """
    Final accept/reject decision with full reasoning.

    This is the output of SignalGatekeeper.decide() and should be used
    to determine whether to execute a trade.
    """
    accept: bool
    direction: str  # "call", "put", "neutral"
    score: float
    confidence: float
    reason: str  # Primary reason for accept/reject
    notes: List[str]  # Supporting details
    risk_level: str  # "low", "normal", "high"
    confluence_count: int  # How many indicators agree



class SignalGatekeeper:
    """
    Improved SignalGatekeeper

    Key improvements:
      - Safe casts and robust string/enum handling
      - Pattern-based override for BB vs Trend trap when pattern is very strong
      - Strong pattern adds immediate confluence (+1)
      - Trend counts as 1 (not 2) in confluence to avoid dominance
      - Pattern align/penalty parameters loaded from presets
      - MTF penalties/boosts tunable and softened
      - Helpful debug notes for diagnostics
    """

    PRESETS = {
        "strict": {
            "min_score": {"low": 15.0, "normal": 22.0, "high": 30.0, "extreme": 999.0},
            "min_conf": {"low": 0.40, "normal": 0.50, "high": 0.60, "extreme": 1.0},
            "min_confluence_normal": 4,
            "min_confluence_high": 5,
            "min_body_ratio": 0.08,
            "max_body_ratio": 0.85,
            "max_direction_conflict": 25.0,
            "pattern_strong_conf": 0.60,
            "pattern_conflict_reject": True,
            "pattern_align_boost": 0.12,
            "pattern_conflict_penalty": 0.18,
            "loss_streak_cooldown": 2,
            "mtf_5m_weight": 0.6,
            "mtf_15m_weight": 0.4,
            "mtf_align_boost": 0.15,
            "mtf_conflict_penalty": 0.20,
        },
        "normal": {
            "min_score": {"low": 15.0, "normal": 22.0, "high": 30.0, "extreme": 999.0},
            "min_conf": {"low": 0.38, "normal": 0.48, "high": 0.55, "extreme": 1.0},
            "min_confluence_normal": 3,
            "min_confluence_high": 4,
            "min_body_ratio": 0.06,
            "max_body_ratio": 0.88,
            "max_direction_conflict": 28.0,
            "pattern_strong_conf": 0.65,
            "pattern_conflict_reject": True,
            "pattern_align_boost": 0.12,
            "pattern_conflict_penalty": 0.18,
            "loss_streak_cooldown": 3,
            "mtf_5m_weight": 0.6,
            "mtf_15m_weight": 0.4,
            "mtf_align_boost": 0.12,
            "mtf_conflict_penalty": 0.15,
        },
        "relaxed": {
            "min_score": {"low": 8.0, "normal": 12.0, "high": 18.0, "extreme": 999.0},
            "min_conf": {"low": 0.28, "normal": 0.35, "high": 0.42, "extreme": 1.0},
            "min_confluence_normal": 2,
            "min_confluence_high": 3,
            "min_body_ratio": 0.04,
            "max_body_ratio": 0.92,
            "max_direction_conflict": 35.0,
            "pattern_strong_conf": 0.75,
            "pattern_conflict_reject": False,
            "pattern_align_boost": 0.10,
            "pattern_conflict_penalty": 0.12,
            "loss_streak_cooldown": 5,
            "mtf_5m_weight": 0.5,
            "mtf_15m_weight": 0.3,
            "mtf_align_boost": 0.10,
            "mtf_conflict_penalty": 0.12,
        },
        "very_relaxed": {
            # --- Core acceptance thresholds (softened, not disabled) ---
            "min_score": {
                "low": 3.0,  # was 4.0
                "normal": 4.0,  # was 6.0
                "high": 3.0,  # lowered from 9.0 to allow high-volatility trades
                "extreme": 50.0  # keep extreme very high → still blocked
            },

            "min_conf": {
                "low": 0.15,  # was 0.20
                "normal": 0.20,  # was 0.28
                "high": 0.12,  # lowered from 0.30 to allow high-volatility trades
                "extreme": 0.80  # unchanged → extreme still protected
            },

            # --- Confluence (allow minimal confirmation) ---
            "min_confluence_normal": 2,  # User requested 2
            "min_confluence_high": 2,  # User requested 2

            "confidence_floor": 0.15,

            # --- Candle quality (leave mostly intact) ---
            "min_body_ratio": 0.02,
            "max_body_ratio": 0.95,

            # --- Direction conflict tolerance ---
            "max_direction_conflict": 65.0,  # was 45 → allow mild disagreement

            # --- Pattern logic (VERY IMPORTANT FIXES) ---
            "pattern_strong_conf": 0.55,  # was 0.85 → too strict
            "pattern_override_conf": 0.70,  # NEW → only VERY strong patterns override BB traps

            "pattern_conflict_reject": False,  # keep false (good)
            "pattern_align_boost": 0.12,  # was 0.08 → patterns matter more
            "pattern_conflict_penalty": 0.02,  # was 0.10 → reduce over-penalization

            # --- Risk control ---
            "loss_streak_cooldown": 6,  # was 10 → still safe, less restrictive

            # --- Multi-timeframe (MTF) SOFTENING ---
            "mtf_5m_weight": 0.20,  # was 0.4 → reduce veto power
            "mtf_15m_weight": 0.10,  # was 0.2

            "mtf_align_boost": 0.05,  # was 0.08 → alignment helps, doesn’t dominate
            "mtf_conflict_penalty": 0.04,  # User requested 4 (0.04)
        },
        "telegram_passthrough": {
            "min_score": {"low": 3.0, "normal": 5.0, "high": 8.0, "extreme": 40.0},
            "min_conf": {"low": 0.15, "normal": 0.18, "high": 0.22, "extreme": 0.6},
            "min_confluence_normal": 1,
            "min_confluence_high": 1,
            "min_body_ratio": 0.01,
            "max_body_ratio": 0.99,
            "max_direction_conflict": 60.0,
            "pattern_strong_conf": 0.90,
            "pattern_conflict_reject": False,
            "pattern_align_boost": 0.10,
            "pattern_conflict_penalty": 0.05,
            "loss_streak_cooldown": 8,
            "mtf_5m_weight": 0.20,
            "mtf_15m_weight": 0.10,
            "mtf_align_boost": 0.05,
            "mtf_conflict_penalty": 0.03,
            "weight_2m": 0.50,
            "weight_5m": 0.30,
            "weight_15m": 0.20,
        },
    }

    def __init__(self, mode: str = "normal", ml_enabled: bool = False, fingerprint_db: Optional[Any] = None):
        self.mode = (mode or "normal").lower()
        self.ml_enabled = ml_enabled
        self.fingerprint_db = fingerprint_db

        # Session tracking
        self.consecutive_losses = 0
        self.total_trades = 0
        self.session_wins = 0
        self.session_losses = 0
        self._base_threshold = 70.0
        self._manual_threshold: Optional[float] = None
        self.adaptive_enabled = False
        self.alpha_hours_enabled = True

        # MTF config (can be overridden via set_mtf_enabled)
        self.mtf_enabled = True
        self.mtf_2m_enabled = True
        self.mtf_5m_enabled = True
        self.mtf_15m_enabled = True

        # Load all preset-driven attributes (scores, weights, thresholds)
        self._load_preset(self.mode)

    # -------------------------
    # Preset load
    # -------------------------
    def check_alpha_hours(self) -> Tuple[bool, str]:
        """
        Pillar 1 of Strategy Overhaul: The Alpha Hours Gatekeeper.
        Checks if the current UTC hour aligns with the historical peak win rate hours.
        Reports in both UTC and Africa/Lagos (UTC+1) for user convenience.
        """
        import datetime
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        current_hour_utc = now_utc.hour
        
        # Africa/Lagos is UTC + 1
        lagos_hour = (current_hour_utc + 1) % 24
        
        # Based on deep_quant.py analysis (Logic MUST stay on UTC)
        alpha_hours = {0, 9, 14, 15, 16, 20, 21}
        
        time_msg = f"(UTC: {current_hour_utc:02d}:00, Lagos: {lagos_hour:02d}:00)"
        
        if current_hour_utc in alpha_hours:
            return True, f"Alpha Hour Active {time_msg}"
        else:
            return False, f"Dead Zone Active {time_msg}"

    def _load_preset(self, mode: str):
        preset = self.PRESETS.get(mode, self.PRESETS["normal"])

        # thresholds by volatility regime
        self.MIN_SCORE_BY_REGIME: Dict[str, float] = preset.get("min_score", {"normal": 18.0})
        self.MIN_CONF_BY_REGIME: Dict[str, float] = preset.get("min_conf", {"normal": 0.42})

        # candle quality
        self.MIN_BODY_RATIO = float(preset.get("min_body_ratio", 0.06))
        self.MAX_BODY_RATIO = float(preset.get("max_body_ratio", 0.88))

        # confluence
        self.MIN_CONFLUENCE_NORMAL = int(preset.get("min_confluence_normal", 3))
        self.MIN_CONFLUENCE_HIGH_VOL = int(preset.get("min_confluence_high", 4))

        # direction conflict
        self.MAX_DIRECTION_CONFLICT = float(preset.get("max_direction_conflict", 28.0))

        # pattern
        self.PATTERN_STRONG_CONF = float(preset.get("pattern_strong_conf", 0.65))
        self.PATTERN_STRONG_CONFLICT_REJECT = bool(preset.get("pattern_conflict_reject", True))
        self.PATTERN_ALIGN_BOOST = float(preset.get("pattern_align_boost", 0.12))
        self.PATTERN_CONFLICT_PENALTY = float(preset.get("pattern_conflict_penalty", 0.18))

        # NEW: how strong a pattern must be to OVERRIDE BB-vs-trend trap
        self.PATTERN_OVERRIDE_CONF = float(preset.get("pattern_override_conf", 0.80))

        self.CONFIDENCE_FLOOR = float(preset.get("confidence_floor", 0.0))

        # loss streak cooldown
        self.LOSS_STREAK_COOLDOWN = int(preset.get("loss_streak_cooldown", 3))

        # MTF
        self.MTF_5M_WEIGHT = float(preset.get("mtf_5m_weight", 0.6))
        self.MTF_15M_WEIGHT = float(preset.get("mtf_15m_weight", 0.4))
        self.MTF_ALIGN_BOOST = float(preset.get("mtf_align_boost", 0.12))
        self.MTF_CONFLICT_PENALTY = float(preset.get("mtf_conflict_penalty", 0.15))

        # Bollinger Squeeze threshold (adjustable at runtime)
        self.bb_squeeze_threshold = float(preset.get("bb_squeeze_threshold", 0.03))

        # MTF toggles
        self.mtf_enabled = True
        self.mtf_2m_enabled = True
        self.mtf_5m_enabled = True
        self.mtf_15m_enabled = True
        
        # Explicit Weights (fallback to defaults if missing in preset)
        self.WEIGHT_2M = float(preset.get("weight_2m", 0.50))
        self.WEIGHT_5M = float(preset.get("weight_5m", 0.30))
        self.WEIGHT_15M = float(preset.get("weight_15m", 0.20))

    def set_mode(self, mode: str):
        self.mode = (mode or "normal").lower()
        self._load_preset(self.mode)

    def set_mtf_enabled(self, enabled: bool, include_5m: bool = True, include_15m: bool = True, include_2m: bool = True):
        self.mtf_enabled = enabled
        self.mtf_5m_enabled = include_5m
        self.mtf_15m_enabled = include_15m
        self.mtf_2m_enabled = include_2m

    def get_current_settings(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "min_score_normal": self.MIN_SCORE_BY_REGIME.get("normal", 18),
            "min_confidence_normal": self.MIN_CONF_BY_REGIME.get("normal", 0.42),
            "min_confluence": self.MIN_CONFLUENCE_NORMAL,
            "pattern_conflict_reject": self.PATTERN_STRONG_CONFLICT_REJECT,
            "loss_streak_cooldown": self.LOSS_STREAK_COOLDOWN,
            "mtf_enabled": self.mtf_enabled,
            "mtf_2m_enabled": self.mtf_2m_enabled,
            "mtf_5m_enabled": self.mtf_5m_enabled,
            "mtf_15m_enabled": self.mtf_15m_enabled,
            "weight_2m": self.WEIGHT_2M,
            "weight_5m": self.WEIGHT_5M,
            "weight_15m": self.WEIGHT_15M,
            "bb_squeeze_threshold": self.bb_squeeze_threshold,
        }

    # -------------------------
    # Main decision function
    # -------------------------
    def decide(
        self,
        analyzer: "MarketAnalyzer",
        indicators: Dict[str, Any],
        pattern_analysis: Optional[Dict[str, Any]] = None,
        requested_direction: Optional[str] = None,
        indicators_2m: Optional[Dict[str, Any]] = None,
        indicators_5m: Optional[Dict[str, Any]] = None,
        indicators_15m: Optional[Dict[str, Any]] = None,
        profile_override: Optional[str] = None,
        is_martingale: bool = False,
        use_mhi: bool = False,
        raw_candles: Optional[List[Dict[str, Any]]] = None,
        mhi_strategy: str = "mhi",
        pre_calculated_score: Optional[SignalScore] = None,
        fingerprint: Optional[Any] = None
    ) -> TradeDecision:
        """
        Global Risk & Execution Layer (Gatekeeper).

        PRIMARY ROLE: Final trade/reject decision for TELEGRAM signals.
        Scanner signals bypass this entirely (skip_gatekeeper=True).

        Uses the pre-calculated score from StrategyEngine (Score System #1)
        and applies execution thresholds, Alpha Hours checks, martingale
        safety locks, and optional ML probability engine.

        See strategy_engine.py module docstring for the full score architecture.
        """
        notes: List[str] = []

        # Stage 0: validation
        if not indicators:
            return TradeDecision(False, "neutral", 0.0, 0.0, "Rejected: No indicator data available", ["Missing data"], "high", 0)

        base_indicators = indicators_2m if indicators_2m else indicators
        vol_regime = str(base_indicators.get("volatility_regime", "normal")).lower()

        # Handle Score Retrieval
        confluence_count = 0
        if pre_calculated_score:
            current_score = pre_calculated_score.score
            current_confidence = pre_calculated_score.confidence
            direction = pre_calculated_score.direction
            notes.extend(pre_calculated_score.reasons)
            notes.extend(pre_calculated_score.warnings)
            confluence_count = getattr(pre_calculated_score, 'confluence_count', 0)
        else:
            return TradeDecision(False, "neutral", 0.0, 0.0, "Rejected: No pre-calculated score provided.", ["Strategy Engine bypassed"], "high", 0)

        # Alpha Hours Enforcement (Bypass for Telegram signals)
        if self.alpha_hours_enabled and self.mode != "telegram_passthrough" and not is_martingale:
            is_alpha, alpha_msg = self.check_alpha_hours()
            if not is_alpha:
                # To allow testing, we check if we are in very_relaxed mode to bypass
                if self.mode not in ("very_relaxed", "relaxed"):
                    return TradeDecision(False, "neutral", current_score, current_confidence, f"Rejected: {alpha_msg}", [alpha_msg], "high", 0)
                else:
                    notes.append(f"⚠️ {alpha_msg} - Bypassed due to relaxed mode")
            else:
                notes.append(f"✅ {alpha_msg}")

        abs_score = abs(current_score)
        
        # Determine dynamic execution threshold based on gatekeeper mode
        if self.mode == "telegram_passthrough":
            self._base_threshold = 20.0
        elif self.mode == "very_relaxed":
            self._base_threshold = 50.0
        elif self.mode == "relaxed":
            self._base_threshold = 50.0
        elif self.mode == "martingale":
            self._base_threshold = 40.0
        else:
            self._base_threshold = 75.0 # Normal (Scanner) - Balanced Middle Ground for OTC

        # Get effective threshold
        manual_val = self._manual_threshold
        if manual_val is not None:
            EXECUTION_THRESHOLD = manual_val
        elif self.adaptive_enabled and vol_regime in self.MIN_SCORE_BY_REGIME:
            EXECUTION_THRESHOLD = self.MIN_SCORE_BY_REGIME[vol_regime]
            if EXECUTION_THRESHOLD != self._base_threshold:
                notes.append(f"Adaptive Shift: {vol_regime.upper()} volatility requires score {EXECUTION_THRESHOLD}")
        else:
            EXECUTION_THRESHOLD = self._base_threshold

        # Wait on score cutoff (already enforced by strategy, but double check)
        if hasattr(pre_calculated_score, 'should_trade') and not pre_calculated_score.should_trade:
            return TradeDecision(False, direction, current_score, current_confidence, "Rejected: Strategy Hard Veto", notes, "high", 0)

        # -------------------------------------------------------------------
        # SPRINT 1 & 2 HARD GATES (Data-Proven Rejections)
        # -------------------------------------------------------------------

        # 1. RSI Extreme Block (43-47% WR)
        rsi_current = float(base_indicators.get("rsi", 50.0))
        if rsi_current < 30.0 or rsi_current > 70.0:
            if self.mode not in ("very_relaxed", "telegram_passthrough"):
                reason = f"Rejected: RSI Extreme ({rsi_current:.1f}) - Must be 30-70 for 60%+ WR"
                notes.append(reason)
                return TradeDecision(False, direction, current_score, current_confidence, reason, notes, "high", confluence_count)

        # 2. Expansion Trap Veto (34.5% WR)
        if raw_candles and len(raw_candles) >= 2:
            last_c = raw_candles[-1]
            prev_c = raw_candles[-2]
            last_body = abs(float(last_c.get('close', last_c.get('c', 0))) - float(last_c.get('open', last_c.get('o', 0))))
            prev_body = abs(float(prev_c.get('close', prev_c.get('c', 0))) - float(prev_c.get('open', prev_c.get('o', 0))))
            if prev_body > 0 and (last_body / prev_body) > 1.2:
                reason = f"Rejected: Expansion Trap (Ratio: {last_body/prev_body:.2f} > 1.2)"
                notes.append(reason)
                return TradeDecision(False, direction, current_score, current_confidence, reason, notes, "high", confluence_count)

        # 3. Wick Magnet Lock (20.0% WR)
        if raw_candles and len(raw_candles) >= 1:
            c = raw_candles[-1]
            high = float(c.get('max', c.get('h', 0)))
            low = float(c.get('min', c.get('l', 0)))
            total_size = high - low
            if total_size > 0:
                if direction == "call":
                    rejection_wick = min(float(c.get('open', c.get('o', 0))), float(c.get('close', c.get('c', 0)))) - low
                else:
                    rejection_wick = high - max(float(c.get('open', c.get('o', 0))), float(c.get('close', c.get('c', 0))))
                
                if (rejection_wick / total_size) > 0.4:
                    reason = f"Rejected: Wick Magnet Lock (Wick Ratio: {rejection_wick/total_size:.2f} > 0.4)"
                    notes.append(reason)
                    return TradeDecision(False, direction, current_score, current_confidence, reason, notes, "high", confluence_count)

        # 4. Mandatory Alignment Guard (34% WR Avoidance)
        if self.mode not in ("very_relaxed", "telegram_passthrough"):
            trend_2m = str(indicators_2m.get("trend", "neutral")).lower() if indicators_2m else "neutral"
            trend_5m = str(indicators_5m.get("trend", "neutral")).lower() if indicators_5m else "neutral"
            expected = "bullish" if direction == "call" else "bearish"
            
            # If NEITHER is aligned, or if ONE is conflicting, block.
            # Must have at least one aligned and zero conflicting.
            if (trend_2m != expected and trend_5m != expected) or (trend_2m != "neutral" and trend_2m != expected) or (trend_5m != "neutral" and trend_5m != expected):
                reason = f"Rejected: Trend Misalignment (2m:{trend_2m}, 5m:{trend_5m})"
                notes.append(reason)
                return TradeDecision(False, direction, current_score, current_confidence, reason, notes, "high", confluence_count)

        # -------------------------------------------------------------------
        # MARTINGALE SAFETY LOCKS
        # -------------------------------------------------------------------
        if is_martingale:
            # 1. Trend Reversal Lock
            trend_5m = str(indicators_5m.get('trend', 'neutral')).lower() if indicators_5m else 'neutral'
            trend_15m = str(indicators_15m.get('trend', 'neutral')).lower() if indicators_15m else 'neutral'
            opp_trend = "bearish" if direction == "call" else "bullish"
            
            if trend_5m == opp_trend or trend_15m == opp_trend:
                reason = f"Rejected: Martingale Trend Reversal Lock (5m:{trend_5m}, 15m:{trend_15m})"
                notes.append(reason)
                return TradeDecision(False, direction, current_score, current_confidence, reason, notes, "high", confluence_count)
                
            # 2. Momentum Requirement
            macd = float(base_indicators.get("macd_histogram", 0.0))
            stoch = float(base_indicators.get("stoch_k", 50.0))
            
            has_momentum = False
            if direction == "call" and (macd > 0 or stoch > 20):
                has_momentum = True
            elif direction == "put" and (macd < 0 or stoch < 80):
                has_momentum = True
                
            if not has_momentum:
                reason = "Rejected: Martingale Momentum Lock (No supportive momentum)"
                notes.append(reason)
                return TradeDecision(False, direction, current_score, current_confidence, reason, notes, "high", confluence_count)

        # -------------------------------------------------------------------
        # ML PROBABILITY ENGINE (Phase 10)
        # -------------------------------------------------------------------
        if self.ml_enabled and self.fingerprint_db and fingerprint:
            ml_result = self.fingerprint_db.calculate_probability(fingerprint)
            if ml_result.get('match_count', 0) > 0:
                probability = ml_result.get('probability', 0.5)
                notes.append(f"ML Adjustment: {ml_result.get('reason')} ({ml_result.get('match_count')} matches, prob={probability:.2f})")
                
                # Dynamic multiplier based on historical probability
                # Cap the multiplier between 0.5 (halves score) and 1.5 (boosts score 50%)
                multiplier = max(0.5, min(1.5, probability / 0.5))
                current_score *= multiplier
                abs_score = abs(current_score)
                current_confidence = min(0.95, current_confidence * multiplier)

        # -------------------------------------------------------------------
        # FINAL ACCEPTANCE
        # -------------------------------------------------------------------
        is_adaptive = self.adaptive_enabled and vol_regime in self.MIN_SCORE_BY_REGIME
        if abs_score >= EXECUTION_THRESHOLD:
            reason = f"Accepted: Score={abs_score:.1f}/100"
            return TradeDecision(True, direction, current_score, current_confidence, reason, notes, "high" if vol_regime == "high" else "normal", confluence_count)
        else:
            reason = f"Rejected: Score {abs_score:.1f}/100 below Execution Threshold ({EXECUTION_THRESHOLD})"
            return TradeDecision(False, direction, current_score, current_confidence, reason, notes, "normal", confluence_count)

    def set_manual_threshold(self, threshold: Optional[float]):
        """Override the configuration preset with a dynamic Telegram-supplied threshold."""
        if threshold is None:
            self._manual_threshold = None
        else:
            self._manual_threshold = max(0.0, min(100.0, float(threshold)))
            
    @property
    def execution_threshold(self) -> float:
        """Get the currently active execution threshold, prioritizing manual overrides."""
        manual_val = self._manual_threshold
        if manual_val is not None:
             return manual_val
        
        # Recalculate base just in case
        if self.mode == "telegram_passthrough": return 20.0
        elif self.mode == "very_relaxed": return 50.0
        elif self.mode == "relaxed": return 50.0
        return 75.0



    # -------------------------
    # Session results
    # -------------------------
    def record_result(self, won: bool):
        self.total_trades += 1
        if won:
            self.session_wins += 1
            self.consecutive_losses = 0
        else:
            self.session_losses += 1
            self.consecutive_losses += 1

    def reset_session(self):
        self.consecutive_losses = 0
        self.total_trades = 0
        self.session_wins = 0
        self.session_losses = 0

    def get_stats(self) -> Dict[str, Any]:
        win_rate = float((self.session_wins / self.total_trades * 100.0)) if self.total_trades > 0 else 0.0
        return {
            "total_trades": int(self.total_trades),
            "wins": int(self.session_wins),
            "losses": int(self.session_losses),
            "win_rate": float(round(win_rate, 1)),
            "consecutive_losses": int(self.consecutive_losses),
            "cooldown_active": bool(self.consecutive_losses >= self.LOSS_STREAK_COOLDOWN),
        }

    def format_decision(self, decision: TradeDecision) -> str:
        status = "✅ ACCEPT" if decision.accept else "⛔ REJECT"
        lines = [
            f"{status}: {decision.reason}",
            f"   Direction: {decision.direction.upper()}",
            f"   Score: {decision.score:.1f} | Confidence: {decision.confidence:.0%}",
            f"   Risk Level: {decision.risk_level} | Confluence: {decision.confluence_count}",
        ]
        if decision.notes:
            lines.append(f"   Notes: {'; '.join(decision.notes[:6])}")
        return "\n".join(lines)



class MarketAnalyzer:
    """
    MarketAnalyzer -- robust indicator calculation and signal scoring for OTC / binary trading.

    Key improvements:
      - Wilder RSI
      - MACD using EMA series + signal EMA(macd_series)
      - Stochastic computed as %K from last k period and %D as SMA of recent %K values
      - ATR-percentile volatility regime detection using a rolling history per symbol
      - Weight-normalized scoring system with tunable weights
      - Defensive checks and fallbacks
    """

    # Indicator cache settings
    INDICATOR_CACHE_TTL = 3    # seconds — kept very short to prevent stale cross-asset data
    INDICATOR_CACHE_MAX = 100  # max entries

    def __init__(self) -> None:
        # caches (for ATR pct history / symbol-specific)
        self.atr_history: Dict[str, List[float]] = {}
        # default weights (sum = 100)
        self.weights = {
            "rsi": 2.0,
            "stochastic": 1.5,
            "macd": 2.5,  # increased from 2.0
            "bollinger": 2.0,
            "trend": 4.0,  # increased from 3.0 (trend is king in OTC)
            "momentum": 1.5,
            "price_pos": 1.0,
            "volume": 1.5,
            "adx": 3.0,  # increased from 2.0 (trend strength)
        }
        # tuning / thresholds
        self.confidence_trade_threshold = 0.4
        self.min_score_to_trade = 15.0  # normalized score magnitude threshold
        self.atr_history_limit = 500  # max points to keep in ATR history per symbol

        # Indicator cache: key -> (timestamp, indicators_dict)
        self._indicator_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._indicator_cache_hits = 0
        self._indicator_cache_misses = 0


    # -------------------------
    # Public entry points
    # -------------------------

    def _make_indicator_cache_key(self, candles: List[Dict[str, Any]], symbol: str) -> str:
        """Build a collision-proof cache key from full candle identity + symbol.

        Previous implementation used only last-3-closes + count, which caused
        cross-asset cache collisions during parallel scanner sweeps (the same
        RSI/BB/candle data was stamped onto 20+ different assets).  The new key
        includes first-open, last-close, extremes, and count — making accidental
        collisions statistically impossible.
        """
        n = len(candles)
        if n == 0:
            return f"{symbol}:0:empty"

        first_open = round(float(candles[0].get("open", candles[0].get("o", 0))), 8)
        last_close = round(float(candles[-1].get("close", candles[-1].get("c", 0))), 8)

        # Use raw min/max across all candle lows/highs for uniqueness
        all_lows = [float(c.get("min", c.get("low", c.get("l", 0)))) for c in candles]
        all_highs = [float(c.get("max", c.get("high", c.get("h", 0)))) for c in candles]
        lo = round(min(all_lows), 8)
        hi = round(max(all_highs), 8)

        return f"{symbol}:{n}:{first_open}:{last_close}:{lo}:{hi}"

    def _get_cached_indicators(self, key: str) -> Optional[Dict[str, Any]]:
        """Return cached indicators if still within TTL."""
        entry = self._indicator_cache.get(key)
        if entry is not None:
            ts, indicators = entry
            if (time.time() - ts) < self.INDICATOR_CACHE_TTL:
                self._indicator_cache_hits += 1
                return indicators
            # expired — remove
            del self._indicator_cache[key]
        return None

    def _set_cached_indicators(self, key: str, indicators: Dict[str, Any]) -> None:
        """Store indicators in cache, evicting oldest if full."""
        if len(self._indicator_cache) >= self.INDICATOR_CACHE_MAX:
            # evict oldest entry
            oldest_key = min(self._indicator_cache, key=lambda k: self._indicator_cache[k][0])
            del self._indicator_cache[oldest_key]
        self._indicator_cache[key] = (time.time(), indicators)
        self._indicator_cache_misses += 1

    def get_indicator_cache_stats(self) -> Dict[str, Any]:
        """Return cache hit/miss statistics."""
        total = self._indicator_cache_hits + self._indicator_cache_misses
        return {
            "hits": self._indicator_cache_hits,
            "misses": self._indicator_cache_misses,
            "hit_rate": (self._indicator_cache_hits / total * 100) if total > 0 else 0.0,
            "entries": len(self._indicator_cache),
        }

    def calculate_indicators(
        self, candles: List[Dict[str, Any]], rsi_period: int = 14, symbol: str = "global"
    ) -> Optional[Dict[str, Any]]:
        """
        Calculate indicators from candles (list of dicts with keys: 'open','close','max','min', optional 'volume').
        Optionally provide a `symbol` to maintain ATR percentiles per symbol.
        Results are cached for INDICATOR_CACHE_TTL seconds.
        """
        candles = get_completed_candles(candles, min_required=max(15, rsi_period + 1))
        if not candles:
            return None


        # Check indicator cache
        cache_key = self._make_indicator_cache_key(candles, symbol)
        cached = self._get_cached_indicators(cache_key)
        if cached is not None:
            return cached

        closes = [float(c["close"]) for c in candles]
        highs = [float(c["max"]) for c in candles]
        lows = [float(c["min"]) for c in candles]
        volumes = [float(c.get("volume", 0)) for c in candles]

        current_price = closes[-1]

        # --- Moving averages / trend ---
        sma_5 = self._sma(closes, 5)
        sma_10 = self._sma(closes, 10)
        sma_20 = self._sma(closes, 20) if len(closes) >= 20 else sma_10
        ema_9 = self._ema(closes, 9)
        ema_14 = self._ema(closes, 14)
        ema_21 = self._ema(closes, 21) if len(closes) >= 21 else ema_14

        # --- Momentum / RSI / Stochastic / MACD ---
        rsi = self._calculate_rsi(closes, rsi_period)
        stoch_k, stoch_d = self._calculate_stochastic(highs, lows, closes, k_period=14, d_period=3)

        # MACD requires 26+ candles for the slow EMA; gracefully return zeros if insufficient
        if len(closes) >= 26:
            macd_line, signal_line, macd_histogram = self._calculate_macd(closes, fast=12, slow=26, signal=9)
        else:
            macd_line, signal_line, macd_histogram = 0.0, 0.0, 0.0

        # --- Volatility / ATR / BB / Average ATR ---
        bb_upper, bb_middle, bb_lower = self._calculate_bollinger(closes, period=20, std_dev=2.0)
        atr = self._calculate_atr(highs, lows, closes, period=14)
        volatility_pct = (atr / current_price) * 100 if current_price else 0.0

        # update ATR history and detect regime
        self._update_atr_history(symbol, volatility_pct)
        volatility_regime = self._detect_volatility_regime(atr, closes, symbol)

        # Average ATR for dynamic expiry
        hist = self.atr_history.get(symbol, [])
        avg_atr_pct = sum(hist) / len(hist) if hist else volatility_pct
        avg_atr = (avg_atr_pct / 100) * current_price if current_price else atr

        # --- Price action / momentum ---
        trend = self._determine_trend(sma_5, sma_10, sma_20, ema_9, ema_21)
        momentum = self._calculate_momentum(closes, period=10)
        price_position = self._calculate_price_position(current_price, highs, lows, period=20)

        # Bollinger position (0..1)
        bb_width = bb_upper - bb_lower if bb_upper is not None and bb_lower is not None else 0.0
        # Calculate Width % for Squeeze Detection
        bb_width_pct = (bb_width / bb_middle) * 100.0 if bb_middle and bb_middle > 0 else 0.0

        if bb_width == 0:
            bb_position = 0.5
        else:
            bb_position = (current_price - bb_lower) / bb_width

        # Rate of change (5)
        roc_5 = (
            ((closes[-1] - closes[-6]) / closes[-6]) * 100
            if len(closes) >= 6 and closes[-6] != 0
            else 0.0
        )

        # --- Keltner Channels & Squeeze Check ---
        kc_middle = self._ema(closes, period=20)
        atr_20 = self._calculate_atr(highs, lows, closes, period=20)
        kc_upper = kc_middle + (1.5 * atr_20)
        kc_lower = kc_middle - (1.5 * atr_20)
        
        # Squeeze logic: Bollinger Bands are fully inside Keltner Channels
        in_squeeze = (bb_upper < kc_upper) and (bb_lower > kc_lower) if bb_upper and bb_lower else False

        # Candle analysis
        last_candle = candles[-1]
        candle_body = abs(float(last_candle["close"]) - float(last_candle["open"]))
        candle_range = float(last_candle["max"]) - float(last_candle["min"])
        body_ratio = (candle_body / candle_range) if candle_range > 0 else 0.0
        is_bullish_candle = float(last_candle["close"]) > float(last_candle["open"])

        avg_volume = 0.0
        if len(volumes) >= 20 and sum(volumes[-20:]) > 0:
            avg_volume = sum(volumes[-20:]) / 20.0

        # --- ADX (Average Directional Index) ---
        adx_value = self._calculate_adx(highs, lows, closes, period=14)
        if adx_value > 25:
            adx_trend = "strong"
        elif adx_value > 20:
            adx_trend = "moderate"
        else:
            adx_trend = "weak"

        result = {
            # Basic
            "current_price": round(current_price, 8),
            "trend": trend["direction"],
            "trend_strength": trend["strength"],
            # MA/EMA
            "sma_5": round(sma_5, 8),
            "sma_10": round(sma_10, 8),
            "sma_20": round(sma_20, 8),
            "ema_9": round(ema_9, 8),
            "ema_14": round(ema_14, 8),
            "ema_21": round(ema_21, 8),
            # RSI
            "rsi": round(rsi, 4),
            "rsi_signal": self._rsi_signal(rsi),
            # Stochastic
            "stoch_k": round(stoch_k, 4),
            "stoch_d": round(stoch_d, 4),
            "stoch_signal": self._stochastic_signal(stoch_k, stoch_d),
            # MACD
            "macd_line": round(macd_line, 8),
            "macd_signal_line": round(signal_line, 8),
            "macd_histogram": round(macd_histogram, 8),
            "macd_trend": "bullish" if macd_histogram > 0 else ("bearish" if macd_histogram < 0 else "neutral"),
            # Bollinger
            "bb_upper": round(bb_upper, 8),
            "bb_middle": round(bb_middle, 8),
            "bb_lower": round(bb_lower, 8),
            "bb_position": round(bb_position, 4),
            "bb_width_pct": round(bb_width_pct, 6),
            "bb_signal": self._bollinger_signal(current_price, bb_upper, bb_lower, bb_middle),
            # Keltner Squeeze
            "in_squeeze": in_squeeze,
            "kc_upper": round(kc_upper, 8),
            "kc_lower": round(kc_lower, 8),
            # Volatility
            "atr": round(atr, 8),
            "avg_atr": round(avg_atr, 8),
            "volatility": round(volatility_pct, 4),
            "volatility_regime": volatility_regime.value,
            # Momentum
            "momentum": round(momentum, 4),
            "roc_5": round(roc_5, 4),
            # Price Action
            "recent_high": max(highs[-20:]) if len(highs) >= 20 else max(highs),
            "recent_low": min(lows[-20:]) if len(lows) >= 20 else min(lows),
            "price_position": round(price_position, 4),
            # Candle
            "body_ratio": round(body_ratio, 4),
            "is_bullish_candle": bool(is_bullish_candle),
            # Volume
            "avg_volume": round(avg_volume, 4),
            "current_volume": round(volumes[-1], 4) if volumes else 0.0,
            # ADX
            "adx": round(adx_value, 2),
            "adx_trend": adx_trend,
            # Candle timing (for staleness detection)
            "last_candle_time": float(last_candle.get("from", 0) or last_candle.get("at", 0) or 0),
            # Raw Candle Anatomy
            "candle_open": float(last_candle["open"]),
            "candle_high": float(last_candle["max"]),
            "candle_low": float(last_candle["min"]),
            "candle_close": float(last_candle["close"]),
        }



        # Store in cache
        self._set_cached_indicators(cache_key, result)
        return result



    # -------------------------
    # Indicator helpers
    # -------------------------

    def _sma(self, data: List[float], period: int) -> float:
        if not data:
            return 0.0
        if len(data) < period:
            return sum(data) / len(data)
        return sum(data[-period:]) / period

    def _ema_series(self, data: List[float], period: int) -> List[float]:
        """Return EMA series aligned with input length. Seed with first value simple method."""
        if not data:
            return []
        multiplier = 2.0 / (period + 1.0)
        ema_series: List[float] = []
        ema = data[0]
        for price in data:
            ema = (price - ema) * multiplier + ema
            ema_series.append(ema)
        return ema_series

    def _ema(self, data: List[float], period: int) -> float:
        """Return last EMA value for data using iterative method."""
        series = self._ema_series(data, period)
        return series[-1] if series else 0.0

    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Wilder's RSI smoothing implementation (robust)."""
        if len(closes) < period + 1:
            return 50.0

        gains: List[float] = []
        losses: List[float] = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0.0))
            losses.append(max(-diff, 0.0))

        # Seed with simple average of first 'period' changes (take the earliest available)
        if len(gains) < period:
            avg_gain = sum(gains) / len(gains) if gains else 0.0
            avg_loss = sum(losses) / len(losses) if losses else 0.0
        else:
            avg_gain = sum(gains[-(period + 1):-1]) / period if len(gains) >= period + 1 else sum(gains[-period:]) / period
            avg_loss = sum(losses[-(period + 1):-1]) / period if len(losses) >= period + 1 else sum(losses[-period:]) / period

        # Apply Wilder smoothing for the last 'period' values
        recent_gains = gains[-period:]
        recent_losses = losses[-period:]
        for g, l in zip(recent_gains, recent_losses):
            avg_gain = (avg_gain * (period - 1) + g) / period
            avg_loss = (avg_loss * (period - 1) + l) / period

        if avg_loss == 0.0:
            return 100.0 if avg_gain > 0.0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def _calculate_stochastic(
        self, highs: List[float], lows: List[float], closes: List[float], k_period: int = 14, d_period: int = 3
    ) -> Tuple[float, float]:
        """Compute latest %K and %D. %K from last k_period; %D is SMA of last d_period %K values."""
        n = len(closes)
        if n < k_period:
            return 50.0, 50.0

        k_values: List[float] = []
        # compute K series where possible
        for i in range(k_period - 1, n):
            window_high = max(highs[i - k_period + 1 : i + 1])
            window_low = min(lows[i - k_period + 1 : i + 1])
            if window_high == window_low:
                k = 50.0
            else:
                k = ((closes[i] - window_low) / (window_high - window_low)) * 100.0
            k_values.append(k)

        if not k_values:
            return 50.0, 50.0

        latest_k = k_values[-1]
        if len(k_values) < d_period:
            d = sum(k_values) / len(k_values)
        else:
            d = sum(k_values[-d_period:]) / d_period

        return latest_k, d

    def _calculate_macd(self, closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        """
        Compute MACD line (last), signal line (EMA of macd_series), and histogram.
        Uses _ema_series to produce stable EMAs.
        """
        if not closes or len(closes) < slow:
            return 0.0, 0.0, 0.0

        ema_fast_series = self._ema_series(closes, fast)
        ema_slow_series = self._ema_series(closes, slow)

        # macd_series aligned (element-wise difference)
        macd_series = [f - s for f, s in zip(ema_fast_series, ema_slow_series)]

        macd_line = macd_series[-1]
        # signal line is EMA of macd_series
        signal_series = self._ema_series(macd_series, signal)
        signal_line = signal_series[-1] if signal_series else macd_line
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _calculate_bollinger(self, closes: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
        if not closes:
            return 0.0, 0.0, 0.0
        if len(closes) < period:
            sma = sum(closes) / len(closes)
            return sma, sma, sma
        window = closes[-period:]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std = math.sqrt(variance)
        return sma + std_dev * std, sma, sma - std_dev * std

    def _calculate_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        if len(closes) < 2:
            return 0.0
        true_ranges: List[float] = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            true_ranges.append(tr)
        if not true_ranges:
            return 0.0
        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges)
        return sum(true_ranges[-period:]) / period

    def _calculate_momentum(self, closes: List[float], period: int = 10) -> float:
        if len(closes) < period + 1 or closes[-period - 1] == 0.0:
            return 0.0
        return ((closes[-1] - closes[-period - 1]) / closes[-period - 1]) * 100.0

    def _calculate_price_position(self, current: float, highs: List[float], lows: List[float], period: int = 20) -> float:
        if not highs or not lows:
            return 0.5
        p = min(period, len(highs))
        recent_high = max(highs[-p:])
        recent_low = min(lows[-p:])
        if recent_high == recent_low:
            return 0.5
        return (current - recent_low) / (recent_high - recent_low)

    def _update_atr_history(self, symbol: str, atr_pct: float) -> None:
        """Keep rolling ATR percent history per symbol for percentile calculations."""
        if symbol not in self.atr_history:
            self.atr_history[symbol] = []
        hist = self.atr_history[symbol]
        hist.append(atr_pct)
        if len(hist) > self.atr_history_limit:
            # drop oldest
            del hist[0]

    def _detect_volatility_regime(self, atr: float, closes: List[float], symbol: str = "global") -> VolatilityRegime:
        """Detect volatility regime using rolling ATR percentiles if possible, else fallback to absolute thresholds."""
        if not closes or atr == 0.0:
            return VolatilityRegime.NORMAL
        current_price = closes[-1]
        vol_pct = (atr / current_price) * 100.0 if current_price != 0.0 else 0.0

        hist = self.atr_history.get(symbol, [])
        regime = VolatilityRegime.NORMAL

        if len(hist) >= 20:
            # compute percentiles robustly
            p90 = self._percentile(hist, 90.0)
            p75 = self._percentile(hist, 75.0)
            p25 = self._percentile(hist, 25.0)
            if p90 is not None and vol_pct > p90:
                regime = VolatilityRegime.EXTREME
            elif p75 is not None and vol_pct > p75:
                regime = VolatilityRegime.HIGH
            elif p25 is not None and vol_pct < p25:
                regime = VolatilityRegime.LOW
            else:
                regime = VolatilityRegime.NORMAL
        else:
            # fallback absolute thresholds (in percent)
            # These are conservative fallbacks; prefer percentile mode when data is available.
            if vol_pct > 1.5:  # 1.5% ATR -> extreme fallback
                regime = VolatilityRegime.EXTREME
            elif vol_pct > 0.8:
                regime = VolatilityRegime.HIGH
            elif vol_pct < 0.2:
                regime = VolatilityRegime.LOW
            else:
                regime = VolatilityRegime.NORMAL

        return regime

    def _percentile(self, data: List[float], percentile: float) -> Optional[float]:
        """Compute percentile (linear interpolation) - returns None when empty."""
        if not data:
            return None
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (percentile / 100.0)
        f = int(math.floor(k))
        c = int(math.ceil(k))
        if f == c:
            return sorted_data[int(k)]
        d0 = sorted_data[f] * (c - k)
        d1 = sorted_data[c] * (k - f)
        return d0 + d1

    def _determine_trend(self, sma_5: float, sma_10: float, sma_20: float, ema_9: float, ema_21: float) -> Dict[str, str]:
        bullish = bearish = 0
        if sma_5 > sma_10 > sma_20:
            bullish += 2
        elif sma_5 < sma_10 < sma_20:
            bearish += 2
        elif sma_5 > sma_10:
            bullish += 1
        elif sma_5 < sma_10:
            bearish += 1

        if ema_9 > ema_21:
            bullish += 1
        else:
            bearish += 1

        net = bullish - bearish
        if net >= 3:
            return {"direction": "bullish", "strength": "strong_bullish"}
        elif net == 2:
            return {"direction": "bullish", "strength": "bullish"}
        elif net == 1:
            return {"direction": "bullish", "strength": "weak_bullish"}
        elif net == -1:
            return {"direction": "bearish", "strength": "weak_bearish"}
        elif net == -2:
            return {"direction": "bearish", "strength": "bearish"}
        elif net <= -3:
            return {"direction": "bearish", "strength": "strong_bearish"}
        return {"direction": "neutral", "strength": "neutral"}

    def _calculate_adx(self, highs: List[float], lows: List[float],
                       closes: List[float], period: int = 14) -> float:
        """
        Calculate ADX (Average Directional Index) using Wilder smoothing.
        Returns ADX value (0-100). Higher = stronger trend.
        """
        n = len(closes)
        if n < period + 1:
            return 0.0

        # True Range, +DM, -DM
        tr_list: List[float] = []
        plus_dm_list: List[float] = []
        minus_dm_list: List[float] = []

        for i in range(1, n):
            high_diff = highs[i] - highs[i - 1]
            low_diff = lows[i - 1] - lows[i]

            plus_dm = high_diff if high_diff > low_diff and high_diff > 0 else 0.0
            minus_dm = low_diff if low_diff > high_diff and low_diff > 0 else 0.0

            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            tr_list.append(tr)
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        if len(tr_list) < period:
            return 0.0

        # Wilder smoothing: initial = sum of first 'period' values
        atr = sum(tr_list[:period])
        plus_dm_smooth = sum(plus_dm_list[:period])
        minus_dm_smooth = sum(minus_dm_list[:period])

        dx_list: List[float] = []

        for i in range(period, len(tr_list)):
            atr = atr - (atr / period) + tr_list[i]
            plus_dm_smooth = plus_dm_smooth - (plus_dm_smooth / period) + plus_dm_list[i]
            minus_dm_smooth = minus_dm_smooth - (minus_dm_smooth / period) + minus_dm_list[i]

            if atr == 0:
                continue

            plus_di = (plus_dm_smooth / atr) * 100.0
            minus_di = (minus_dm_smooth / atr) * 100.0

            di_sum = plus_di + minus_di
            if di_sum == 0:
                dx_list.append(0.0)
            else:
                dx = abs(plus_di - minus_di) / di_sum * 100.0
                dx_list.append(dx)

        if len(dx_list) < period:
            return sum(dx_list) / len(dx_list) if dx_list else 0.0

        # ADX = Wilder-smoothed average of DX
        adx = sum(dx_list[:period]) / period
        for i in range(period, len(dx_list)):
            adx = (adx * (period - 1) + dx_list[i]) / period

        return max(0.0, min(100.0, adx))

    def _rsi_signal(self, rsi: float) -> str:
        if rsi >= 80:
            return "extremely_overbought"
        if rsi >= 70:
            return "overbought"
        if rsi <= 20:
            return "extremely_oversold"
        if rsi <= 30:
            return "oversold"
        if rsi > 55:
            return "bullish"
        if rsi < 45:
            return "bearish"
        return "neutral"

    def _stochastic_signal(self, k: float, d: float) -> str:
        if k > 80 and d > 80:
            return "overbought"
        if k < 20 and d < 20:
            return "oversold"
        if k > d and k < 50:
            return "bullish_cross"
        if k < d and k > 50:
            return "bearish_cross"
        return "neutral"

    def _bollinger_signal(self, price: float, upper: float, lower: float, middle: float) -> str:
        if price >= upper:
            return "above_upper"
        if price <= lower:
            return "below_lower"
        if price > middle:
            return "upper_half"
        return "lower_half"




