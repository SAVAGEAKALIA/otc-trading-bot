"""
Strategy Engine — Unified strategy orchestrator with weighted voting.

Replaces the inline strategy invocation in scanner.py with:
  - Multiple strategy registration (MHI, Indicators, CCV2, etc.)
  - Parallel evaluation and weighted score combination
  - Per-strategy win rate tracking with dynamic weight adjustment
  - Single `evaluate()` API returning a combined TradeDecision

SCORE ARCHITECTURE (three systems, each with a specific role):
─────────────────────────────────────────────────────────────
1. STRATEGY ENGINE RAW SCORE (this module)
   - Produced by: StrategyEngine.evaluate() → TradeDecision.score
   - Scale: -100 to +100 (positive=call, negative=put)
   - Used by: Scanner voting/tournament, Telegram gatekeeper
   - Authoritative for: deciding direction + whether strategies agree

2. QUALITY OVERLAY SCORE (scanner.py only)
   - Produced by: OTCScanner._compute_quality_score()
   - Scale: 0 to 105 (data-calibrated from fingerprint analysis)
   - Components: MTF alignment (50pts), body health (10pts), stoch bonus (5pts), etc.
   - Authoritative for: scanner signal filtering (replaces raw score in signal)
   - NOT used by Telegram signals

3. GATEKEEPER EXECUTION THRESHOLD (analytics.py)
   - Produced by: SignalGatekeeper.decide()
   - Uses: pre_calculated_score from StrategyEngine (score #1 above)
   - Authoritative for: final trade/reject decision on Telegram signals
   - Scanner signals BYPASS the gatekeeper (skip_gatekeeper=True)
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import time

from trading_platform.strategies.otc.implementations.base import BaseStrategy, StrategyResult


@dataclass
class TradeDecision:
    """Combined output from the strategy engine."""
    score: float          # Weighted combined score (positive=call, negative=put)
    direction: str        # 'call', 'put', or 'neutral'
    confidence: float     # Weighted average confidence (0.0-1.0)
    reasons: List[str]    # Combined reasons from contributing strategies
    warnings: List[str]   # Combined warnings
    should_trade: bool    # Whether the combined signal passes threshold
    
    # Strategy breakdown
    strategy_scores: Dict[str, float] = field(default_factory=dict)
    confluence_count: int = 0  # How many strategies agree
    winning_strategy: str = "" # Name of the strategy that generated the signal
    agreeing_strategies: List[str] = field(default_factory=list)  # Names of all strategies that agreed
    independent_family_count: int = 0
    agreeing_families: List[str] = field(default_factory=list)
    strategy_directions: Dict[str, str] = field(default_factory=dict)
    strategy_confidences: Dict[str, float] = field(default_factory=dict)
    eligible_strategies: List[str] = field(default_factory=list)
    calibrated_win_probability: Optional[float] = None
    calibration_id: Optional[str] = None


# Strategies in the same family are alternative views of substantially the
# same evidence.  They may still agree, but that agreement is not independent.
DEFAULT_STRATEGY_FAMILIES = {
    "MHI": "candle_reversal",
    "Majority": "candle_reversal",
    "R7": "candle_reversal",
    "CCV2": "candle_reversal",
    "Indicators": "trend_indicators",
    "Adaptive": "adaptive_kama",
    "Squeeze Breakout": "volatility_breakout",
    "Rubber Band": "macro_pullback",
    "Apex Exhaustion": "momentum_exhaustion",
    "Momentum Cascade": "price_continuation",
    "Compression Breakout": "price_continuation",
    "Late Candle Sniper": "impulse_shift",
    "Exhaustion Fade": "bb_mean_reversion",
    "ML_LSTM": "machine_learning",
    "ML_CatBoost_Directional": "machine_learning",
}


# RATIONALE FOR SEPARATING PRIMARY AND MARTINGALE STATS:
# A strategy's recovery-step outcomes reflect martingale mechanics (multiplier,
# max steps, re-analyzer behavior) as much as original signal quality.
# Mixing martingale outcomes into win_rate would distort effective_weight calculation.
# Therefore, effective_weight reads ONLY from primary trade stats.

@dataclass
class StrategySlot:
    """A registered strategy with its weight and performance stats."""
    strategy: BaseStrategy
    weight: float = 1.0
    
    # Primary trade performance tracking (used for effective_weight calculation)
    wins: int = 0
    losses: int = 0
    ties: int = 0

    # Martingale recovery-step performance tracking (tracked for reporting/visibility only)
    martingale_wins: int = 0
    martingale_losses: int = 0
    martingale_ties: int = 0

    @property
    def total_primary_trades(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def total_martingale_trades(self) -> int:
        return self.martingale_wins + self.martingale_losses + self.martingale_ties

    @property
    def total_trades(self) -> int:
        return self.total_primary_trades + self.total_martingale_trades
    
    @property
    def win_rate(self) -> float:
        """Primary trade win rate (used for effective_weight calculation)."""
        decided = self.wins + self.losses
        return self.wins / decided if decided > 0 else 0.5

    @property
    def martingale_win_rate(self) -> float:
        """Martingale recovery-step win rate (for reporting/visibility only)."""
        decided = self.martingale_wins + self.martingale_losses
        return self.martingale_wins / decided if decided > 0 else 0.5

    @property
    def effective_weight(self) -> float:
        """Dynamic weight: base weight × performance multiplier.
        Reads ONLY from primary trade stats.
        
        Performance multiplier:
          - Cold start (< 20 primary trades): use base weight
          - Win rate >= 60%: boost weight up to 1.5×
          - Win rate >= 55%: boost weight up to 1.2×
          - Win rate >= 45%: base weight (1.0×)
          - Win rate >= 40%: reduce weight to 0.6×
          - Win rate < 40%: reduce weight to 0.3×
        """
        if self.total_primary_trades < 20:
            return self.weight
        
        wr = self.win_rate
        if wr >= 0.60:
            mult = 1.5
        elif wr >= 0.55:
            mult = 1.2
        elif wr >= 0.45:
            mult = 1.0
        elif wr >= 0.40:
            mult = 0.6
        else:
            mult = 0.3
        
        return self.weight * mult


class StrategyEngine:
    """
    Unified strategy orchestrator.
    
    Usage:
        engine = StrategyEngine()
        engine.register(MHIStrategy(), weight=1.0)
        engine.register(IndicatorStrategy(), weight=1.2)
        
        decision = engine.evaluate(
            candles=candles,
            indicators_2m=indicators_2m,
            indicators_5m=indicators_5m,
            indicators_15m=indicators_15m,
            profile='reversal',
            strategy_type='mhi'
        )
    """

    def __init__(self):
        self.strategies: Dict[str, StrategySlot] = {}
        self._evaluation_count = 0

    def register(self, strategy: BaseStrategy, weight: float = 1.0):
        """Register a strategy with an initial weight."""
        self.strategies[strategy.name] = StrategySlot(
            strategy=strategy,
            weight=weight
        )

    def get_registered_names(self) -> List[str]:
        """Return list of all registered strategy names (lowercase)."""
        return [name.lower() for name in self.strategies.keys()]

    def record_result(self, strategy_name: str, result: str, is_martingale: bool = False):
        """Record a trade outcome for a specific strategy.
        
        Args:
            strategy_name: Name of the strategy (matches BaseStrategy.name)
            result: 'win', 'loss', or 'tie'
            is_martingale: True if trade was a martingale recovery step
        """
        slot = None
        if strategy_name in self.strategies:
            slot = self.strategies[strategy_name]
        else:
            # Fallback for case variations (e.g. "mhi" vs "MHI")
            s_low = strategy_name.lower()
            for k, v in self.strategies.items():
                if k.lower() == s_low:
                    slot = v
                    break

        if not slot:
            return

        # The broker/result checker uses "lose", while older tests and reports
        # use "loss".  Normalize at this boundary so live losses are not
        # silently omitted from performance weighting.
        normalized_result = {
            "win": "win",
            "won": "win",
            "loss": "loss",
            "lose": "loss",
            "lost": "loss",
            "tie": "tie",
            "draw": "tie",
        }.get(str(result).strip().lower())
        if normalized_result is None:
            return
        
        if is_martingale:
            if normalized_result == 'win':
                slot.martingale_wins += 1
            elif normalized_result == 'loss':
                slot.martingale_losses += 1
            elif normalized_result == 'tie':
                slot.martingale_ties += 1
        else:
            if normalized_result == 'win':
                slot.wins += 1
            elif normalized_result == 'loss':
                slot.losses += 1
            elif normalized_result == 'tie':
                slot.ties += 1


    def evaluate(self, candles: List[Dict[str, Any]], symbol: str = "Unknown", **kwargs) -> TradeDecision:
        """
        Run selected strategies and produce a combined decision.
        
        Accepts optional kwarg 'active_strategies' (List[str]) to limit
        which strategies participate. If not provided, uses strategy_type
        filtering (backward compatible).
        """
        self._evaluation_count += 1
        
        if not self.strategies:
            return TradeDecision(0.0, "neutral", 0.0, [], ["No strategies registered"], False)

        # 1. Determine which strategies to run
        active_strategies = kwargs.pop('active_strategies', None)  # List[str] or None
        min_agreement = max(1, int(kwargs.pop('min_agreement', 2)))
        min_independent_families = max(
            1, int(kwargs.pop('min_independent_families', 1))
        )
        configured_families = kwargs.pop('strategy_families', None) or {}
        strategy_families = {
            **DEFAULT_STRATEGY_FAMILIES,
            **configured_families,
        }
        requested_type = kwargs.get('strategy_type', 'hybrid').lower()
        
        strategies_to_run = {}
        
        if active_strategies:
            # Custom combo: run only the named strategies
            requested_names = {
                str(strategy_name).strip().lower()
                for strategy_name in active_strategies
                if str(strategy_name).strip()
            }
            for name, slot in self.strategies.items():
                if name.lower() in requested_names:
                    strategies_to_run[name] = slot
            if not strategies_to_run:
                return TradeDecision(
                    0.0,
                    "neutral",
                    0.0,
                    [],
                    [
                        "No requested strategies are registered: "
                        + ", ".join(sorted(requested_names))
                    ],
                    False,
                )
        elif requested_type == 'hybrid':
            # Run everything
            strategies_to_run = dict(self.strategies)
        else:
            # Legacy: filter by strategy_type
            is_mhi_family = any(x in requested_type for x in ("mhi", "majority", "r7"))
            if is_mhi_family:
                # If perfect match exists (e.g. 'Majority' registered as 'Majority'), use it
                target = requested_type.lower()
                for name, slot in self.strategies.items():
                    n_low = name.lower()
                    if target == n_low:
                        strategies_to_run[name] = slot
                
                # If no perfect match or extra matching is needed, fallback to 'mhi' in name
                if not strategies_to_run:
                    for name, slot in self.strategies.items():
                        if "mhi" in name.lower():
                            strategies_to_run[name] = slot
            else:
                for name, slot in self.strategies.items():
                    if requested_type in name.lower():
                        strategies_to_run[name] = slot
            if not strategies_to_run:
                return TradeDecision(
                    0.0,
                    "neutral",
                    0.0,
                    [],
                    [f"Requested strategy '{requested_type}' is not registered"],
                    False,
                )

        # 2. Run selected strategies
        results: Dict[str, Tuple[StrategyResult, float]] = {}  # name → (result, effective_weight)
        for name, slot in strategies_to_run.items():
            try:
                result = slot.strategy.analyze(candles, symbol=symbol, **kwargs)
                results[name] = (result, slot.effective_weight)
            except Exception as e:
                # Strategy crashed — skip it, don't kill the whole evaluation
                results[name] = (
                    StrategyResult(0.0, "neutral", 0.0, [], [f"{name} error: {e}"], False),
                    0.0
                )

        # 3. Find the single strongest signal
        best_signal_name = None
        best_signal_result = None
        best_score_abs = -1.0
        
        all_reasons = []
        all_warnings = []
        strategy_scores = {}
        strategy_directions = {}
        strategy_confidences = {}
        eligible_strategies = []
        confluence_count = 0
        
        # Collect all strategy scores for the breakdown
        for name, (result, weight) in results.items():
            strategy_scores[name] = result.score
            strategy_directions[name] = result.direction
            strategy_confidences[name] = result.confidence
            if result.should_trade and result.direction in ("call", "put"):
                eligible_strategies.append(name)
                abs_score = abs(result.score)
                # Apply dynamic weight to the competitive score for picking the best,
                # though the final reported score remains the raw strategy score.
                competitive_score = abs_score * weight
                if competitive_score > best_score_abs:
                    best_score_abs = competitive_score
                    best_signal_name = name
                    best_signal_result = result
        
        if not best_signal_result:
            return TradeDecision(
                score=0.0, direction="neutral", confidence=0.0,
                reasons=["No strategies generated a valid signal"],
                warnings=all_warnings, should_trade=False,
                strategy_scores=strategy_scores, confluence_count=0,
                winning_strategy="",
                strategy_directions=strategy_directions,
                strategy_confidences=strategy_confidences,
                eligible_strategies=eligible_strategies,
            )
            
        # Count confluence: how many strategies agreed with the winning direction
        best_dir = best_signal_result.direction
        agreeing_names = []
        for name, (result, weight) in results.items():
            if result.should_trade and result.direction == best_dir:
                confluence_count += 1
                agreeing_names.append(name)
            elif result.should_trade and result.direction != best_dir and result.direction in ("call", "put"):
                all_warnings.append(f"[{name}] Disagreed: signaled {result.direction}")

        agreeing_families = sorted({
            str(strategy_families.get(name, name))
            for name in agreeing_names
        })
        independent_family_count = len(agreeing_families)

        # Collect reasons from ALL agreeing strategies (not just the best one)
        all_reasons = [f"[{best_signal_name}] {r}" for r in best_signal_result.reasons]
        for name, (result, weight) in results.items():
            if name != best_signal_name and result.should_trade and result.direction == best_dir:
                all_reasons.extend([f"[{name}] {r}" for r in result.reasons])
                all_warnings.extend([f"[{name}] {w}" for w in result.warnings])
        all_warnings.extend([f"[{best_signal_name}] {w}" for w in best_signal_result.warnings])

        # ──────────────────────────────────────────────
        # VOTING AGREEMENT GATE
        # In voting mode, require min_agreement strategies
        # to agree on the direction before firing a trade.
        # Default is 2 — a lone strategy cannot trade alone.
        # ──────────────────────────────────────────────
        total_active = len(strategies_to_run)

        if total_active >= 2 and confluence_count < min_agreement:
            # Don't log every blocked asset — too noisy. Only log to debug.
            return TradeDecision(
                score=best_signal_result.score,
                direction=best_dir,
                confidence=best_signal_result.confidence,
                reasons=all_reasons,
                warnings=all_warnings + [
                    f"Agreement gate: {confluence_count}/{total_active} agree (need {min_agreement})"
                ],
                should_trade=False,
                strategy_scores=strategy_scores,
                confluence_count=confluence_count,
                winning_strategy=best_signal_name or "",
                agreeing_strategies=agreeing_names,
                independent_family_count=independent_family_count,
                agreeing_families=agreeing_families,
                strategy_directions=strategy_directions,
                strategy_confidences=strategy_confidences,
                eligible_strategies=eligible_strategies,
            )

        if (
            total_active >= 2
            and independent_family_count < min_independent_families
        ):
            return TradeDecision(
                score=best_signal_result.score,
                direction=best_dir,
                confidence=best_signal_result.confidence,
                reasons=all_reasons,
                warnings=all_warnings + [
                    "Independent-family gate: "
                    f"{independent_family_count} family/families agree "
                    f"(need {min_independent_families})"
                ],
                should_trade=False,
                strategy_scores=strategy_scores,
                confluence_count=confluence_count,
                winning_strategy=best_signal_name or "",
                agreeing_strategies=agreeing_names,
                independent_family_count=independent_family_count,
                agreeing_families=agreeing_families,
                strategy_directions=strategy_directions,
                strategy_confidences=strategy_confidences,
                eligible_strategies=eligible_strategies,
            )

        # Add agreeing strategy names to reasons for log visibility
        if len(agreeing_names) > 1:
            all_reasons.insert(0, f"✅ Agreement: {', '.join(agreeing_names)} ({confluence_count}/{total_active})")
        # Get the timestamp of the latest candle for data-freshness logging
        candle_data = candles[-1] if candles else {}
        ts_val = candle_data.get('at', candle_data.get('from', 0))
        last_candle_at = float(ts_val) if ts_val is not None else 0.0
        
        # Robust Normalization Guard: Handle milliseconds/microseconds/nanoseconds
        # (IQ Option sometimes returns high-resolution timestamps)
        while last_candle_at > 5000000000:  # Any timestamp > year 2128 is not seconds
            last_candle_at /= 1000.0
            
        dt_str = datetime.fromtimestamp(last_candle_at).strftime('%H:%M:%S') if last_candle_at > 0 else "N/A"
        
        print(f"   ✅ Agreement gate PASSED [{symbol}]: {confluence_count}/{total_active} agree on {best_dir.upper()} "
              f"across {independent_family_count} family/families "
              f"(Score: {abs(best_signal_result.score or 0.0):.1f}) | Candle: {dt_str} | Agreed: {agreeing_names}")

        return TradeDecision(
            score=best_signal_result.score,
            direction=best_dir,
            confidence=best_signal_result.confidence,
            reasons=all_reasons,
            warnings=all_warnings,
            should_trade=True,
            strategy_scores=strategy_scores,
            confluence_count=confluence_count,
            winning_strategy=best_signal_name or "",
            agreeing_strategies=agreeing_names,
            independent_family_count=independent_family_count,
            agreeing_families=agreeing_families,
            strategy_directions=strategy_directions,
            strategy_confidences=strategy_confidences,
            eligible_strategies=eligible_strategies,
            calibrated_win_probability=(
                best_signal_result.calibrated_win_probability
                if len(agreeing_names) == 1
                else None
            ),
            calibration_id=(
                best_signal_result.calibration_id
                if len(agreeing_names) == 1
                else None
            ),
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return performance stats for all strategies."""
        stats = {}
        for name, slot in self.strategies.items():
            stats[name] = {
                "weight": slot.weight,
                "effective_weight": round(slot.effective_weight, 2),
                "wins": slot.wins,
                "losses": slot.losses,
                "ties": slot.ties,
                "win_rate": f"{slot.win_rate:.1%}",
                "primary_trades": slot.total_primary_trades,
                "martingale_wins": slot.martingale_wins,
                "martingale_losses": slot.martingale_losses,
                "martingale_ties": slot.martingale_ties,
                "martingale_win_rate": f"{slot.martingale_win_rate:.1%}",
                "martingale_trades": slot.total_martingale_trades,
                "total_trades": slot.total_trades,
            }
        return stats

    def reset_stats(self):
        """Reset all performance tracking."""
        for slot in self.strategies.values():
            slot.wins = 0
            slot.losses = 0
            slot.ties = 0
            slot.martingale_wins = 0
            slot.martingale_losses = 0
            slot.martingale_ties = 0

    def evaluate_single(self, strategy_name: str, candles: List[Dict[str, Any]], symbol: str = "Unknown", **kwargs) -> TradeDecision:
        """
        Run a SINGLE named strategy independently (for tournament mode).
        
        Returns a TradeDecision from just that one strategy, without any
        voting or conflict resolution.
        
        Args:
            strategy_name: Name of the strategy to run (case-insensitive)
            candles: Price candle data
            **kwargs: Passed through to strategy.analyze()
        """
        # Find the strategy slot
        slot = None
        for name, s in self.strategies.items():
            if name.lower() == strategy_name.lower():
                slot = s
                strategy_name = name  # Use exact registered name
                break
        
        if slot is None:
            return TradeDecision(
                0.0, "neutral", 0.0, [],
                [f"Strategy '{strategy_name}' not registered"], False
            )
        
        try:
            result = slot.strategy.analyze(candles, symbol=symbol, **kwargs)
        except Exception as e:
            return TradeDecision(
                0.0, "neutral", 0.0, [],
                [f"{strategy_name} error: {e}"], False,
                winning_strategy=strategy_name
            )
        
        if not result.should_trade or result.direction not in ("call", "put"):
            return TradeDecision(
                score=result.score,
                direction=result.direction,
                confidence=result.confidence,
                reasons=[f"[{strategy_name}] {r}" for r in result.reasons],
                warnings=[f"[{strategy_name}] {w}" for w in result.warnings],
                should_trade=False,
                strategy_scores={strategy_name: result.score},
                confluence_count=0,
                winning_strategy=strategy_name
            )
        
        return TradeDecision(
            score=result.score,
            direction=result.direction,
            confidence=result.confidence,
            reasons=[f"[{strategy_name}] {r}" for r in result.reasons],
            warnings=[f"[{strategy_name}] {w}" for w in result.warnings],
            should_trade=True,
            strategy_scores={strategy_name: result.score},
            confluence_count=1,
            winning_strategy=strategy_name,
            agreeing_strategies=[strategy_name],
            independent_family_count=1,
            agreeing_families=[
                DEFAULT_STRATEGY_FAMILIES.get(
                    strategy_name,
                    strategy_name,
                )
            ],
            strategy_directions={strategy_name: result.direction},
            strategy_confidences={strategy_name: result.confidence},
            eligible_strategies=[strategy_name],
            calibrated_win_probability=result.calibrated_win_probability,
            calibration_id=result.calibration_id,
        )
