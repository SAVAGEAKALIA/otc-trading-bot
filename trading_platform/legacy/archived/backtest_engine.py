"""
Backtest Engine — Offline replay of historical fingerprints through strategy engine.

Features:
  - Replay stored fingerprints.json through strategy pipeline
  - Calculate per-strategy, per-asset, per-time-of-day win rates
  - Generate comparison reports (before/after strategy changes)
  - Supports filtering by asset, time window, and strategy type
"""
import json
import os
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, cast, Union
from datetime import datetime
from collections import defaultdict


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    
    # Financial
    total_profit: float = 0.0
    
    # Per-asset breakdown
    asset_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    
    # Per-hour breakdown
    hourly_stats: Dict[int, Dict[str, int]] = field(default_factory=dict)
    
    # Per-strategy breakdown
    strategy_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    
    @property
    def win_rate(self) -> float:
        decided = self.wins + self.losses
        return self.wins / decided if decided > 0 else 0.0
    
    @property
    def expected_value(self) -> float:
        """Expected value per trade at 84% payout."""
        wr = self.win_rate
        return (wr * 0.84) - ((1 - wr) * 1.0)  # Win pays 84%, loss costs 100%

    def summary(self) -> str:
        """Human-readable summary of backtest results."""
        lines = [
            f"═══ Backtest Results ═══",
            f"Total Trades: {self.total_trades}",
            f"Wins: {self.wins} | Losses: {self.losses} | Ties: {self.ties}",
            f"Win Rate: {self.win_rate:.1%}",
            f"Expected Value: {self.expected_value:+.2%} per trade",
            f"Total P&L: ${self.total_profit:+.2f}",
            "",
            "── Top Assets ──",
        ]
        
        # Sort assets by trade count
        asset_items = list(self.asset_stats.items())
        sorted_assets = sorted(
            asset_items,
            key=lambda x: x[1].get('total', 0),
            reverse=True
        )[:10]
        
        for asset, stats in sorted_assets:
            total = stats.get('total', 0)
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            wr = wins / (wins + losses) if (wins + losses) > 0 else 0
            lines.append(f"  {asset}: {total} trades, {wr:.0%} WR")
        
        lines.append("")
        lines.append("── Hourly Performance ──")
        
        for hour in sorted(self.hourly_stats.keys()):
            stats = self.hourly_stats[hour]
            total = stats.get('total', 0)
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            wr = wins / (wins + losses) if (wins + losses) > 0 else 0
            lines.append(f"  {hour:02d}:00 UTC: {total} trades, {wr:.0%} WR")
        
        return "\n".join(lines)


class BacktestEngine:
    """
    Replays historical trade fingerprints to evaluate strategy performance.
    """

    def __init__(self, fingerprint_path: str = "data/fingerprints.json"):
        self.fingerprint_path = fingerprint_path
        self.fingerprints: List[Dict[str, Any]] = []
        self._load_fingerprints()

    def _load_fingerprints(self):
        """Load fingerprints from disk."""
        if not os.path.exists(self.fingerprint_path):
            print(f"⚠️ Backtest: No fingerprints at {self.fingerprint_path}")
            return
        
        try:
            with open(self.fingerprint_path, 'r') as f:
                self.fingerprints = json.load(f)
            print(f"📊 Backtest: Loaded {len(self.fingerprints)} fingerprints")
        except Exception as e:
            print(f"⚠️ Backtest: Failed to load fingerprints: {e}")

    def run(self, 
            asset_filter: Optional[str] = None,
            hour_filter: Optional[Tuple[int, int]] = None,
            direction_filter: Optional[str] = None,
            min_score: Optional[float] = None) -> BacktestResult:
        """
        Run a backtest with optional filters.
        
        Args:
            asset_filter: Only include trades for this asset (or None for all)
            hour_filter: Tuple of (start_hour, end_hour) UTC (or None for all)
            direction_filter: 'call' or 'put' only (or None for both)
            min_score: Only include trades with abs(score) >= this value
        """
        result = BacktestResult()
        
        for fp in self.fingerprints:
            # Skip if no resolved result
            if not fp.get('result') or fp['result'] not in ('win', 'loss', 'tie'):
                continue
            
            asset = fp.get('asset', 'unknown')
            direction = fp.get('direction', '')
            score = float(fp.get('score', 0))
            action_time = float(fp.get('action_time', 0))
            trade_result = fp['result']
            profit = float(fp.get('profit', 0))
            
            # Apply filters
            if asset_filter and asset != asset_filter:
                continue
            if direction_filter and direction != direction_filter:
                continue
            if min_score is not None and abs(score) < min_score:
                continue
            
            # Time filter
            if action_time > 0:
                trade_dt = datetime.utcfromtimestamp(action_time)
                hour = trade_dt.hour
                
                if hour_filter is not None:
                    start_h, end_h = hour_filter
                    if start_h <= end_h:
                        if not (start_h <= hour < end_h):
                            continue
                    else:  # Wraps midnight
                        if not (hour >= start_h or hour < end_h):
                            continue
            else:
                hour = -1
            
            # Count result
            result.total_trades += 1
            result.total_profit += profit
            
            if trade_result == 'win':
                result.wins += 1
            elif trade_result == 'loss':
                result.losses += 1
            else:
                result.ties += 1
            
            # Per-asset stats
            result_key = {'win': 'wins', 'loss': 'losses', 'tie': 'ties'}[trade_result]
            if asset not in result.asset_stats:
                result.asset_stats[asset] = {'total': 0, 'wins': 0, 'losses': 0, 'ties': 0}
            result.asset_stats[asset]['total'] += 1
            result.asset_stats[asset][result_key] += 1
            
            # Per-hour stats
            if hour >= 0:
                if hour not in result.hourly_stats:
                    result.hourly_stats[hour] = {'total': 0, 'wins': 0, 'losses': 0, 'ties': 0}
                result.hourly_stats[hour]['total'] += 1
                result.hourly_stats[hour][result_key] += 1
        
        return result

    def reevaluate(self, engine: Any, **kwargs) -> BacktestResult:
        """
        Re-score historical fingerprints through a StrategyEngine.
        
        This simulates how the bot would have performed if it had used a 
        different strategy configuration.
        
        Args:
            engine: StrategyEngine instance
            **kwargs: Additional parameters for engine.evaluate (e.g. strategy_type)
        """
        result = BacktestResult()
        
        for fp in self.fingerprints:
            # Skip if no resolved result
            if not fp.get('result') or fp['result'] not in ('win', 'loss', 'tie'):
                continue
            
            asset = fp.get('asset', 'unknown')
            old_direction = fp.get('direction', 'neutral')
            old_result = fp['result']
            action_time = float(fp.get('action_time', 0))
            
            # Construct indicator dictionaries from fingerprint fields
            # Note: fingerprints lack candles, so we pass empty list
            # Strategies that depend on candles (MHI, CCV2, Adaptive) 
            # will likely return neutral unless mocked.
            indicators_2m = {
                'rsi': fp.get('rsi', 50.0),
                'stoch_k': fp.get('stoch_k', 50.0),
                'stoch_d': fp.get('stoch_d', 50.0),
                'macd_histogram': fp.get('macd_hist', 0.0),
                'bb_position': fp.get('bb_position', 0.0),
                'trend': fp.get('trend_2m', 'neutral'),
                'volatility_regime': fp.get('volatility', 'normal'),
                # Partial mocks for missing fields to avoid crashes
                'adx': 25.0, 
                'ema_14': 0.0, # Disable EMA location check
                'atr': 0.0001
            }
            
            indicators_5m = {'trend': fp.get('trend_5m', 'neutral')}
            indicators_15m = {'trend': fp.get('trend_15m', 'neutral')}
            
            # Re-evaluate
            decision = engine.evaluate(
                candles=[], 
                indicators_2m=indicators_2m,
                indicators_5m=indicators_5m,
                indicators_15m=indicators_15m,
                **kwargs
            )
            
            if not decision.should_trade or decision.direction == 'neutral':
                continue
            
            new_direction = decision.direction
            
            # Determine result for the "new" trade
            # If we predict the SAME direction as before, we get SAME result
            # If we predict OPPOSITE direction, we get OPPOSITE result (win<->loss)
            if old_result == 'tie':
                new_result = 'tie'
            elif new_direction == old_direction:
                new_result = old_result
            else:
                new_result = 'win' if old_result == 'loss' else 'loss'
                
            # Financial tracking
            # Simplified: assuming same payout ratio (84%)
            new_profit = 0.84 if new_result == 'win' else -1.0 if new_result == 'loss' else 0.0
            
            # Update stats
            result.total_trades += 1
            result.total_profit += new_profit
            
            if new_result == 'win':
                result.wins += 1
            elif new_result == 'loss':
                result.losses += 1
            else:
                result.ties += 1
                
            # Breakdowns
            result_key = {'win': 'wins', 'loss': 'losses', 'tie': 'ties'}[new_result]
            
            # Asset
            if asset not in result.asset_stats:
                result.asset_stats[asset] = {'total': 0, 'wins': 0, 'losses': 0, 'ties': 0}
            result.asset_stats[asset]['total'] += 1
            result.asset_stats[asset][result_key] += 1
            
            # Hour
            if action_time > 0:
                hour = datetime.utcfromtimestamp(action_time).hour
                if hour not in result.hourly_stats:
                    result.hourly_stats[hour] = {'total': 0, 'wins': 0, 'losses': 0, 'ties': 0}
                result.hourly_stats[hour]['total'] += 1
                result.hourly_stats[hour][result_key] += 1
                
        return result

    def compare_strategies(self, score_threshold_before: float = 60.0,
                          score_threshold_after: float = 70.0) -> str:
        """
        Compare performance at different score thresholds.
        Useful for evaluating the impact of scoring changes.
        """
        result_before = self.run(min_score=score_threshold_before)
        result_after = self.run(min_score=score_threshold_after)
        
        lines = [
            f"═══ Strategy Comparison ═══",
            f"",
            f"Threshold {score_threshold_before:.0f}:",
            f"  Trades: {result_before.total_trades} | WR: {result_before.win_rate:.1%} | EV: {result_before.expected_value:+.2%}",
            f"",
            f"Threshold {score_threshold_after:.0f}:",
            f"  Trades: {result_after.total_trades} | WR: {result_after.win_rate:.1%} | EV: {result_after.expected_value:+.2%}",
            f"",
            f"Impact: {result_after.total_trades - result_before.total_trades:+d} trades, "
            f"{(result_after.win_rate - result_before.win_rate)*100:+.1f}pp WR"
        ]
        
        return "\n".join(lines)

    def best_assets(self, min_trades: int = 5) -> List[Tuple[str, float, int]]:
        """Return assets sorted by win rate (with minimum trade count)."""
        result = self.run()
        ranked = []
        
        for asset, stats in result.asset_stats.items():
            total = stats.get('total', 0)
            if total < min_trades:
                continue
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            wr = wins / (wins + losses) if (wins + losses) > 0 else 0
            ranked.append((asset, wr, total))
        
        return sorted(ranked, key=lambda x: x[1], reverse=True)

    def best_hours(self, min_trades: int = 3) -> List[Tuple[int, float, int]]:
        """Return hours sorted by win rate."""
        result = self.run()
        ranked = []
        
        for hour, stats in result.hourly_stats.items():
            total = stats.get('total', 0)
            if total < min_trades:
                continue
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            wr = wins / (wins + losses) if (wins + losses) > 0 else 0
            ranked.append((hour, wr, total))
        
        return sorted(ranked, key=lambda x: x[1], reverse=True)
