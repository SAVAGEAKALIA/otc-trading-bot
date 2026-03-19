"""
Market Regime Detector — OTC-specific market state classification.

Detects:
  - Time-of-day patterns (weekday OTC, weekend OTC, session transitions)
  - Volatility clustering (calm/normal/volatile/extreme regimes)
  - Liquidity detection (spread widening as sign of manipulation)

Used to adjust strategy weights and filter trades in unfavorable conditions.
"""
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import time


@dataclass
class MarketRegime:
    """Current market regime assessment."""
    # Volatility
    volatility_regime: str     # 'calm', 'normal', 'volatile', 'extreme'
    volatility_score: float    # 0.0 (dead) to 1.0 (extreme)
    
    # Session info
    session: str               # 'tokyo', 'london', 'new_york', 'weekend_otc', 'off_hours'
    is_weekend_otc: bool       # True if it's weekend-only OTC trading
    
    # Quality assessment
    trade_quality: str         # 'good', 'fair', 'poor'
    recommended_weight_mult: float  # Multiplier for strategy scores (0.5 - 1.5)
    
    # Warnings
    warnings: List[str]


class MarketRegimeDetector:
    """
    Detects current OTC market regime based on time, volatility, and spread behavior.
    """
    
    # Session windows (UTC hours)
    SESSIONS = {
        "tokyo":    (0, 8),     # 00:00 - 08:00 UTC
        "london":   (7, 16),    # 07:00 - 16:00 UTC
        "new_york": (13, 21),   # 13:00 - 21:00 UTC
        "off_hours": (21, 24),  # 21:00 - 00:00 UTC
    }

    # Volatility percentile thresholds (based on ATR history)
    VOL_THRESHOLDS = {
        "calm":     0.2,   # Bottom 20%
        "normal":   0.6,   # 20-60%
        "volatile": 0.85,  # 60-85%
        "extreme":  1.0,   # Top 15%
    }

    def __init__(self):
        self._atr_history: List[float] = []
        self._spread_history: List[float] = []
        self._max_atr_history = 200  # Rolling window

    def detect(self, indicators: Optional[Dict[str, Any]] = None,
               utc_now: Optional[datetime] = None) -> MarketRegime:
        """
        Assess current market regime.
        
        Args:
            indicators: Current 2m indicator dict (with atr, volatility_regime, etc.)
            utc_now: Current UTC time (defaults to datetime.utcnow())
        """
        if utc_now is None:
            utc_now = datetime.now(timezone.utc)
        
        # 1. Session detection
        session = self._detect_session(utc_now)
        is_weekend = utc_now.weekday() >= 5  # Saturday=5, Sunday=6
        
        # 2. Volatility regime
        vol_regime, vol_score = self._assess_volatility(indicators)
        
        # 3. Trade quality assessment
        warnings = []
        quality, weight_mult = self._assess_quality(
            session, is_weekend, vol_regime, vol_score, utc_now, warnings
        )
        
        return MarketRegime(
            volatility_regime=vol_regime,
            volatility_score=vol_score,
            session=session if not is_weekend else "weekend_otc",
            is_weekend_otc=is_weekend,
            trade_quality=quality,
            recommended_weight_mult=weight_mult,
            warnings=warnings
        )

    def _detect_session(self, utc_now: datetime) -> str:
        """Determine current trading session based on UTC hour."""
        hour = utc_now.hour
        
        # Check which sessions are active (can overlap)
        if 13 <= hour < 21:
            return "new_york"
        elif 7 <= hour < 16:
            return "london"
        elif 0 <= hour < 8:
            return "tokyo"
        else:
            return "off_hours"

    def _assess_volatility(self, indicators: Optional[Dict[str, Any]]) -> tuple:
        """Assess volatility regime from current indicators and historical ATR."""
        if not indicators:
            return "normal", 0.5
        
        # Get current ATR percentage
        atr_pct = float(indicators.get("volatility_pct", 0.0))
        vol_regime_raw = str(indicators.get("volatility_regime", "normal")).lower()
        
        # Update ATR history
        if atr_pct > 0:
            self._atr_history.append(atr_pct)
            if len(self._atr_history) > self._max_atr_history:
                self._atr_history = self._atr_history[-self._max_atr_history:]
        
        # Calculate percentile-based regime
        if len(self._atr_history) >= 20:
            sorted_atr = sorted(self._atr_history)
            percentile = sorted_atr.index(min(sorted_atr, key=lambda x: abs(x - atr_pct))) / len(sorted_atr)
            
            if percentile < self.VOL_THRESHOLDS["calm"]:
                regime = "calm"
            elif percentile < self.VOL_THRESHOLDS["normal"]:
                regime = "normal"
            elif percentile < self.VOL_THRESHOLDS["volatile"]:
                regime = "volatile"
            else:
                regime = "extreme"
            
            return regime, round(percentile, 3)
        
        # Not enough history — use raw indicator regime
        score_map = {"low": 0.2, "calm": 0.2, "normal": 0.5, "high": 0.75, "volatile": 0.8, "extreme": 0.95}
        return vol_regime_raw, score_map.get(vol_regime_raw, 0.5)

    def _assess_quality(self, session: str, is_weekend: bool,
                        vol_regime: str, vol_score: float,
                        utc_now: datetime, warnings: List[str]) -> tuple:
        """Determine trade quality and recommended weight multiplier."""
        weight_mult = 1.0
        
        # Weekend OTC: generally lower liquidity, wider spreads
        if is_weekend:
            weight_mult *= 0.85
            warnings.append("Weekend OTC: Lower liquidity expected")
        
        # Off-hours: lowest liquidity
        if session == "off_hours":
            weight_mult *= 0.7
            warnings.append("Off-hours: Very low liquidity")
        
        # Extreme volatility: reduce exposure
        if vol_regime == "extreme":
            weight_mult *= 0.6
            warnings.append("Extreme volatility — reduce exposure")
        elif vol_regime == "calm":
            # Too calm can mean sparse price action
            weight_mult *= 0.9
            warnings.append("Very calm market — limited opportunity")
        
        # Session transition windows (high uncertainty, 30 min overlap)
        hour = utc_now.hour
        if hour in (7, 13, 21):
            weight_mult *= 0.85
            warnings.append(f"Session transition at {hour}:00 UTC — increased uncertainty")
        
        # Determine quality label
        if weight_mult >= 0.9:
            quality = "good"
        elif weight_mult >= 0.65:
            quality = "fair"
        else:
            quality = "poor"
        
        return quality, round(weight_mult, 3)

    def update_spread(self, bid: float, ask: float):
        """Track spread for liquidity detection."""
        if ask > 0 and bid > 0:
            spread_pct = ((ask - bid) / ask) * 100
            self._spread_history.append(spread_pct)
            if len(self._spread_history) > self._max_atr_history:
                self._spread_history = self._spread_history[-self._max_atr_history:]

    def is_spread_abnormal(self) -> bool:
        """Check if current spread is significantly wider than recent average."""
        if len(self._spread_history) < 10:
            return False
        
        recent = self._spread_history[-1]
        avg = sum(self._spread_history[:-1]) / (len(self._spread_history) - 1)
        
        return recent > avg * 2.0  # Spread more than 2× average

    def get_status(self) -> Dict[str, Any]:
        """Return current regime state for logging/display."""
        return {
            "atr_history_size": len(self._atr_history),
            "spread_history_size": len(self._spread_history),
            "spread_abnormal": self.is_spread_abnormal() if self._spread_history else False
        }
