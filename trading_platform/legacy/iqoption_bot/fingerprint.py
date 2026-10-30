import os
import json
import time
import math
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Session classification (mirrors market_regime)
# ─────────────────────────────────────────────
def _hour_to_session(hour: int) -> str:
    """Map UTC hour to session name."""
    if 13 <= hour < 21:
        return "new_york"
    elif 7 <= hour < 16:
        return "london"
    elif 0 <= hour < 8:
        return "tokyo"
    return "off_hours"


@dataclass
class TradeFingerprint:
    """Represents the exact market conditions at the time a trade was taken."""
    asset: str
    direction: str
    action_time: float

    # Core indicators at entry
    rsi: float
    stoch_k: float
    stoch_d: float
    macd_hist: float
    bb_position: float
    volatility: str

    # MTF Context
    trend_2m: str
    trend_5m: str
    trend_15m: str

    # Gatekeeper Score
    score: float

    # Meta / Outcome (populated later)
    duration: Optional[int] = None  # timeframe in minutes (1, 2, 3...)
    result: Optional[str] = None  # 'win', 'loss', 'tie'
    profit: float = 0.0

    # Time-of-day context (auto-populated from action_time)
    hour: Optional[int] = None

    # Candle history for offline backtesting (last 10 candles: [{o,h,l,c}, ...])
    candles: Optional[List[Dict[str, float]]] = None

    # Which strategy produced this signal
    strategy_used: Optional[str] = None

    # How the result was determined: 'api', 'balance', 'forced', or None (pending)
    result_method: Optional[str] = None

    # ── Sprint 4: Analytical fields for future recalibration ──
    # Signal source: 'scanner' or 'telegram'
    source: Optional[str] = None
    # Quality score from Sprint 2 overlay (0-105)
    quality_score: Optional[float] = None
    # Market regime at entry: 'trending' or 'ranging'
    regime: Optional[str] = None
    # Body expansion ratio of entry candle vs previous (e.g. 1.2 = 20% larger)
    body_expansion: Optional[float] = None
    # Number of same-direction candles at entry (run length)
    run_length: Optional[int] = None
    # ADX at entry (trend strength)
    adx: Optional[float] = None

    def __post_init__(self):
        """Auto-populate hour from action_time if not provided."""
        if self.hour is None and self.action_time:
            try:
                dt = datetime.fromtimestamp(self.action_time, tz=timezone.utc)
                self.hour = dt.hour
            except (OSError, ValueError):
                self.hour = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'TradeFingerprint':
        # Filter to only known fields for backward compatibility
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class RollingMemoryDB:
    """
    A lightweight, JSON-backed rolling database that stores trade fingerprints.
    It caps the number of stored fingerprints to prevent bloat.
    """

    def __init__(self, filepath: str = "data/fingerprints.json", max_records: int = 1000):
        self.filepath = filepath
        self.max_records = max_records
        self.records: List[TradeFingerprint] = []
        self._load()
        print(f"🧠 RollingMemoryDB: Initialized ({self.filepath}, {len(self.records)} records)")

    def _load(self):
        """Load records from disk."""
        if not os.path.exists(self.filepath):
            # Ensure dir exists
            dir_path = os.path.dirname(self.filepath)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            self.records = []
            return

        try:
            with open(self.filepath, 'r') as f:
                data = json.load(f)
                self.records = [TradeFingerprint.from_dict(item) for item in data]
        except Exception as e:
            logger.error(f"Failed to load fingerprint DB: {e}")
            self.records = []

    def _save(self):
        """Save records to disk, maintaining max_records limit."""
        try:
            # Enforce rolling limit (keep newest)
            if len(self.records) > self.max_records:
                self.records = self.records[-self.max_records:]

            dir_path = os.path.dirname(self.filepath)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(self.filepath, 'w') as f:
                json.dump([r.to_dict() for r in self.records], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save fingerprint DB: {e}")

    def add_fingerprint(self, fingerprint: TradeFingerprint):
        """Add a new completed trade fingerprint to the database."""
        # Only add if it has a resolved result
        if not fingerprint.result:
            logger.warning("Attempted to add fingerprint without a resolved result. Ignored.")
            return

        self.records.append(fingerprint)
        self._save()

    def calculate_probability(self, current: TradeFingerprint, max_matches: int = 25) -> Dict[str, Any]:
        """
        Calculates the statistical win probability using:
          1. Fuzzy indicator-distance similarity
          2. Temporal decay (recency weighting)
          3. Time-of-day bonus (same hour/session matches count more)
          4. Bayesian posterior update (better small-sample handling)

        Returns:
            Dict with probability, match_count, reason, and modifier.
        """
        if not self.records:
            return {
                "probability": 0.5,
                "match_count": 0,
                "reason": "Cold Start: No historical data in memory.",
                "modifier": 0
            }

        # Hyperparameters
        DECAY_HALF_LIFE = 12 * 3600  # 12 hours (in seconds)
        DECAY_LAMBDA = math.log(2) / DECAY_HALF_LIFE

        # Vector Weights for Distance Calculation
        WEIGHTS = {
            "rsi": 1.0,
            "stoch": 0.5,
            "bb": 0.8,
            "macd": 0.2
        }

        matches = []
        now = time.time()

        # Current hour / session for time-of-day matching
        current_hour = current.hour
        if current_hour is None:
            try:
                current_hour = datetime.fromtimestamp(current.action_time, tz=timezone.utc).hour
            except (OSError, ValueError):
                current_hour = None
        current_session = _hour_to_session(current_hour) if current_hour is not None else None

        # 1. Filter and Calculate Distance
        for past in reversed(self.records):
            if past.asset != current.asset or past.direction != current.direction:
                continue

            # Calculate Euclidean Distance
            d_rsi = (past.rsi - current.rsi) / 100.0
            d_stoch = (past.stoch_k - current.stoch_k) / 100.0
            d_bb = past.bb_position - current.bb_position

            dist_sq = (WEIGHTS["rsi"] * (d_rsi**2) +
                       WEIGHTS["stoch"] * (d_stoch**2) +
                       WEIGHTS["bb"] * (d_bb**2))

            dist = math.sqrt(dist_sq)

            # Similarity score (1.0 = identical, 0.0 = completely different)
            if dist > 0.35:
                continue

            similarity = 1.0 - (dist / 0.35)

            # 2. Temporal Weighting (Recency)
            delta_t = now - past.action_time
            time_weight = math.exp(-DECAY_LAMBDA * delta_t)

            # 3. Time-of-day bonus
            tod_mult = 1.0
            if current_hour is not None and past.hour is not None:
                hour_diff = abs(current_hour - past.hour)
                if hour_diff > 12:
                    hour_diff = 24 - hour_diff
                if hour_diff <= 1:
                    tod_mult = 1.20  # Same hour ±1 → 20% boost
                elif current_session and _hour_to_session(past.hour) == current_session:
                    tod_mult = 1.10  # Same session → 10% boost

            combined_weight = similarity * time_weight * tod_mult

            matches.append({
                "result": past.result,
                "weight": combined_weight,
                "dist": dist
            })

            if len(matches) >= max_matches:
                break

        if not matches:
            return {
                "probability": 0.5,
                "match_count": 0,
                "reason": "Statistical Check: No recent similar setups found.",
                "modifier": 0
            }

        # 4. Bayesian posterior update
        # Prior: Beta(1, 1)  — uninformative (equivalent to 50%)
        # Each match updates: alpha += weight if win, beta += weight if loss
        alpha = 1.0  # prior pseudo-wins
        beta_val = 1.0  # prior pseudo-losses

        for m in matches:
            w = m["weight"]
            if m["result"] == "win":
                alpha += w
            elif m["result"] == "loss":
                beta_val += w
            # ties contribute nothing

        # Posterior mean
        prob = alpha / (alpha + beta_val)

        # 5. Determine Modifier
        modifier = 0
        if prob >= 0.65:
            modifier = min(15, int((prob - 0.5) * 100))   # 70% → +20
        elif prob <= 0.40:
            modifier = max(-40, int((prob - 0.5) * 150))   # 30% → -30

        bayesian_tag = f" [Bayesian α={alpha:.1f}, β={beta_val:.1f}]"
        reason = (f"Statistical Match: {prob*100:.0f}% Win Prob "
                  f"(based on {len(matches)} similar trades){bayesian_tag}")

        return {
            "probability": prob,
            "match_count": len(matches),
            "reason": reason,
            "modifier": modifier
        }

    # Backward compatibility shim
    def calculate_memory_modifier(self, current: TradeFingerprint) -> Dict[str, Any]:
        res = self.calculate_probability(current)
        return {
            "modifier": res["modifier"],
            "reason": res["reason"],
            "wins": 0,   # Deprecated
            "losses": 0  # Deprecated
        }
