"""
OTC Scanner Module - Auto Signal Discovery for OTC Binary Options.

Scans all available OTC pairs, analyzes with MTF gatekeeper,
and generates trade signals when confidence exceeds threshold.

Architecture:
- OTCScanner: Main scanner class with clean separation from worker
- Focuses ONLY on OTC pairs (-OTC and -op variants)
- Uses 2m entry timeframe with 5m/15m MTF confirmation
- Integrates with existing gatekeeper, patterns, and analyzer
"""

import time
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable, Tuple, Set, Union
from dataclasses import dataclass, field
from enum import Enum

from .analytics import MarketAnalyzer, SignalGatekeeper, VolatilityRegime, SignalScore
from .strategy_engine import StrategyEngine, TradeDecision
from .strategies.mhi_strategy import MHIStrategy
from .strategies.indicator_strategy import IndicatorStrategy
from .strategies.ccv2_strategy import CCV2Strategy
from .strategies.adaptive_strategy import AdaptiveStrategy
from .strategies.squeeze_strategy import SqueezeBreakoutStrategy
from .strategies.rubber_band_strategy import RubberBandStrategy
from .strategies.apex_exhaustion_strategy import ApexExhaustionStrategy
from .strategies.momentum_cascade import MomentumCascadeStrategy
from .strategies.compression_breakout import CompressionBreakoutStrategy
from .strategies.late_candle_sniper import LateCandleSniperStrategy
from .strategies.exhaustion_fade import ExhaustionFadeStrategy


class ScannerTradeMode(Enum):
    """Scanner trade mode."""
    SINGLE = "single"  # Block all trades while one is active
    MULTI = "multi"    # Allow multiple concurrent trades


class ScannerProfile(Enum):
    """Scanner trading profile/strategy."""
    TREND = "trend"        # Trend-following only (default, safest)
    REVERSAL = "reversal"  # Mean-reversion setups
    MIXED = "mixed"        # Both trend + reversal


@dataclass
class ScannerSignal:
    """
    Signal discovered by the OTC scanner.

    Contains all analysis data for trade decision and notification.
    """
    asset: str
    direction: str  # "call" or "put"
    confidence: float
    score: float
    confluence: int
    risk_level: str
    reason: str
    notes: List[str]

    # Trade duration (dynamic or fixed)
    recommended_duration: int = 2  # minutes (1-5)

    # Indicator summary
    rsi: Optional[float] = None
    trend: Optional[str] = None
    momentum: Optional[float] = None
    volatility_regime: Optional[str] = None

    # Pattern summary
    patterns: List[Dict] = field(default_factory=list)

    # Raw indicators for execution context/fingerprinting
    indicators_2m: dict = field(default_factory=dict)
    indicators_5m: Optional[dict] = None
    indicators_15m: Optional[dict] = None
    candles: Optional[List[Dict[str, float]]] = None

    # MTF data
    mtf_summary: str = ""

    # Timestamps
    discovered_at: float = field(default_factory=time.time)

    martingale_step: int = 0
    martingale_amount: Optional[float] = None
    martingale_series_id: Optional[str] = None

    # Strategy metadata
    use_mhi: bool = False
    mhi_strategy: str = "mhi"
    strategy_used: str = ""

    # Sprint 4: Analytical metadata for fingerprinting
    quality_score: Optional[float] = None
    regime: Optional[str] = None

    def to_notification(self) -> str:
        """Generate summarized notification message."""
        pattern_names = [p.get('name', 'Unknown') for p in self.patterns[:3]]

        return f"""🔍 *Scanner Signal Found*

📊 *{self.asset}*
Direction: {self.direction.upper()}
Confidence: {self.confidence:.0%}
Score: {abs(self.score):.0f}

📈 *Indicators:*
RSI: {self.rsi or 'N/A'}
Trend: {self.trend or 'N/A'}
Momentum: {self.momentum or 'N/A'}%

🔍 *Patterns:*
{', '.join(pattern_names) if pattern_names else 'None detected'}

📊 *MTF:* {self.mtf_summary}
Confluence: {self.confluence} indicators agree
{"Reasoning: " + ", ".join(self.notes) if self.notes else ""}"""


@dataclass
class ScannerConfig:
    """
    Scanner configuration — all tunable parameters for OTC auto-scanning.

    Organized into sections:
      1. Core          — on/off, interval, trade mode
      2. Scan Filters  — profile, top-N, candle window, volatility
      3. Duration      — fixed vs dynamic timeframe control
      4. Strategy      — which strategies, voting vs tournament, agreement
      5. Hard Gates    — data-proven rejection filters (Sprint 1)
      6. Quality       — data-calibrated signal scoring overlay (Sprint 2)
      7. Regime        — ATR-based strategy routing
      8. Blacklist     — per-asset performance tracking
      9. Deprecated    — legacy filters kept for backward compat (OFF by default)
    """

    # ── 1. Core ──────────────────────────────────────────────────
    enabled: bool = False
    interval: int = 10                  # seconds between scans
    confidence_min: float = 0.65        # min confidence to emit signal
    trade_mode: ScannerTradeMode = ScannerTradeMode.SINGLE
    cooldown_per_asset: int = 300       # seconds cooldown per asset after signal

    # ── 2. Scan Filters ─────────────────────────────────────────
    profile: ScannerProfile = ScannerProfile.TREND
    top_n_pairs: int = 15               # 0 = scan all OTC pairs
    close_window_sec: int = 10          # seconds near candle close to allow scan (16.7% duty cycle)
    min_confluence: int = 4             # min indicators that must agree
    allowed_volatility: List[str] = field(default_factory=lambda: ["normal", "low", "high", "extreme"])
    autostop_on_session_block: bool = True
    wait_for_pullback: bool = False     # EMA14 pullback filter

    # ── 3. Duration ──────────────────────────────────────────────
    dynamic_timeframe: bool = True      # True=volatility-based, False=fixed
    fixed_duration: int = 2             # minutes (used when dynamic=False)
    min_duration: int = 1               # min duration in dynamic mode
    max_duration: int = 3               # max duration (OTC mean-reverts after 3m)

    # ── 4. Strategy ──────────────────────────────────────────────
    scanner_strategy: str = "indicators"        # single strategy name
    active_strategies: List[str] = field(default_factory=list)  # multi-strategy combo (overrides scanner_strategy)
    scan_mode: str = "voting"                   # 'voting' or 'tournament'
    min_agreement: int = 2                      # strategies that must agree (voting mode)
    scanner_precision_timing: bool = True       # Second 58 Rule (MHI timing)

    # ── 5. Hard Gates (Sprint 1) — data-proven rejection filters ─
    rsi_extreme_block: bool = True      # Block RSI < 30 or > 70 (43-47% WR at extremes)
    rsi_extreme_low: float = 30.0
    rsi_extreme_high: float = 70.0
    expansion_trap_block: bool = True   # Block body > 1.2x previous (34.5% WR)
    expansion_trap_max: float = 1.33      # DATA: median winners 1.33, median losers 1.82 (Gold Zone: 0.8-1.5)
    wick_magnet_block: bool = True      # Block if rejection wick > 40% (20% WR)
    wick_magnet_max: float = 0.4
    calm_confluence_gate: bool = True   # Require 2m+5m trend alignment (58.7% vs 34.9%)

    # ── 6. Quality Overlay (Sprint 2) — data-calibrated scoring ──
    quality_score_enabled: bool = True  # Replace strategy scores with proven scoring
    quality_min_score: int = 70         # Minimum quality score to trade (Gold Zone floor)
    put_boost_enabled: bool = True      # PUT with 3-TF bearish alignment gets +10
    stoch_tiebreaker: bool = True       # Stoch K vs D adds +5 bonus
    run_length_cap: int = 4             # Block if candle run >= this (exhaustion)

    # ── 7. Regime Routing ────────────────────────────────────────
    regime_routing_enabled: bool = False # Auto-select strategy combo based on ATR regime
    # Trending: directional candles → Cascade + Compression + Exhaustion Fade
    # Ranging:  low commitment → Exhaustion Fade + Adaptive

    # ── 8. Blacklist & ML ────────────────────────────────────────
    blacklist_min_trades: int = 12           # DATA: Needs 12+ trades for statistical significance
    blacklist_win_rate: float = 0.38         # DATA: Minimum acceptable WR before asset isolation
    scanner_ml_enabled: bool = False    # ML Fingerprinting Engine
    scanner_adaptive_enabled: bool = False  # Volatility-Adaptive Thresholding

    # ── 9. Deprecated (OFF by default, kept for backward compat) ─
    rsi_deadzone_enabled: bool = False  # DEPRECATED: Blocks RSI 40-65 (the BEST zone)
    rsi_deadzone_low: float = 40.0
    rsi_deadzone_high: float = 65.0
    mtf_exhaustion_guard: bool = False  # DEPRECATED: Replaced by calm_confluence_gate

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'enabled': self.enabled,
            'interval': self.interval,
            'confidence_min': self.confidence_min,
            'trade_mode': self.trade_mode.value,
            'cooldown_per_asset': self.cooldown_per_asset,
            'profile': self.profile.value,
            'top_n_pairs': self.top_n_pairs,
            'close_window_sec': self.close_window_sec,
            'min_confluence': self.min_confluence,
            'allowed_volatility': self.allowed_volatility,
            'autostop_on_session_block': self.autostop_on_session_block,
            'dynamic_timeframe': self.dynamic_timeframe,
            'fixed_duration': self.fixed_duration,
            'min_duration': self.min_duration,
            'max_duration': self.max_duration,
            'blacklist_min_trades': self.blacklist_min_trades,
            'blacklist_win_rate': self.blacklist_win_rate,
            'scanner_ml_enabled': self.scanner_ml_enabled,
            'scanner_adaptive_enabled': self.scanner_adaptive_enabled,
            'scanner_strategy': self.scanner_strategy,
            'scanner_precision_timing': self.scanner_precision_timing,
            'active_strategies': self.active_strategies,
            'scan_mode': self.scan_mode,
            'min_agreement': self.min_agreement,
            'wait_for_pullback': self.wait_for_pullback,
            'rsi_deadzone_enabled': self.rsi_deadzone_enabled,
            'rsi_deadzone_low': self.rsi_deadzone_low,
            'rsi_deadzone_high': self.rsi_deadzone_high,
            'mtf_exhaustion_guard': self.mtf_exhaustion_guard,
            'rsi_extreme_block': self.rsi_extreme_block,
            'rsi_extreme_low': self.rsi_extreme_low,
            'rsi_extreme_high': self.rsi_extreme_high,
            'expansion_trap_block': self.expansion_trap_block,
            'expansion_trap_max': self.expansion_trap_max,
            'calm_confluence_gate': self.calm_confluence_gate,
            'wick_magnet_block': self.wick_magnet_block,
            'wick_magnet_max': self.wick_magnet_max,
            'quality_score_enabled': self.quality_score_enabled,
            'quality_min_score': self.quality_min_score,
            'put_boost_enabled': self.put_boost_enabled,
            'stoch_tiebreaker': self.stoch_tiebreaker,
            'run_length_cap': self.run_length_cap,
            'regime_routing_enabled': self.regime_routing_enabled,
        }


class OTCScanner:
    """
    OTC Scanner for auto signal discovery.

    Responsibilities:
    - Scan all available OTC pairs on schedule
    - Analyze each pair with MTF context (2m entry + 5m/15m confirm)
    - Filter by confidence threshold (>70%)
    - Emit signals via callback for trade execution
    - Respect trade mode (single/multi)
    - Track cooldowns per asset

    Usage:
        scanner = OTCScanner(
            api=iq_api,
            data_provider=market_data_provider,
            analyzer=market_analyzer,
            pattern_analyzer=pattern_analyzer,
            gatekeeper=signal_gatekeeper,
        )

        scanner.on_signal = async_callback_func
        await scanner.start()
    """

    def __init__(
        self,
        api,
        data_provider,
        analyzer,
        pattern_analyzer,
        gatekeeper,
        config: Optional[ScannerConfig] = None
    ):
        """
        Initialize OTC Scanner.

        Args:
            api: IQ Option API instance
            data_provider: MarketDataProvider for MTF candles
            analyzer: MarketAnalyzer for indicator calculation
            pattern_analyzer: PatternAnalyzer for pattern detection
            gatekeeper: SignalGatekeeper for decision making
            config: Optional scanner configuration
        """
        self.api = api
        self.data_provider = data_provider
        self.analyzer = analyzer
        self.pattern_analyzer = pattern_analyzer
        self.gatekeeper = gatekeeper

        # Configuration
        self.config = config or ScannerConfig()

        # Strategy Engine — unified strategy orchestration
        self.strategy_engine = self._build_strategy_engine()

        # State
        self.running = False
        self.last_scan_time = 0
        self.asset_cooldowns: Dict[str, float] = {}  # asset -> last_signal_time

        # Per-asset performance tracking: base_asset -> {wins: int, losses: int}
        self.asset_performance: Dict[str, Dict[str, int]] = {}
        self._stale_assets_notified: Set[str] = set()
        self._cycle_stagnant: int = 0
        self._cycle_scanned_count: int = 0
        self._cycle_agreement_blocked: int = 0
        self._cycle_no_data: int = 0
        self._cycle_no_indicators: int = 0
        self._cycle_no_signal: int = 0
        self._cycle_vol_rejected: int = 0
        self._cycle_conf_rejected: int = 0
        self._cycle_rsi_rejected: int = 0
        self._cycle_mtf_exhaustion: int = 0
        self._cycle_rsi_extreme: int = 0
        self._cycle_expansion_trap: int = 0
        self._cycle_wick_magnet: int = 0
        self._cycle_calm_confluence: int = 0
        self._cycle_run_exhaustion: int = 0
        self._cycle_quality_rejected: int = 0

        # Callbacks
        self.on_signal: Optional[Callable[[ScannerSignal], Any]] = None
        self.on_scan_complete: Optional[Callable[[int, int], Any]] = None  # (scanned, signals_found)

        # Trade gate callback (to check if trades are allowed)
        self.can_trade_callback: Optional[Callable[[], tuple]] = None

        # Connection checker
        self.is_connected_callback: Optional[Callable[[], bool]] = None

        # OTC pairs provider (uses cached pairs from worker for efficiency)
        self.get_otc_pairs_callback: Optional[Callable[[], List[str]]] = None

        # Cycle stats initialization
        self._reset_cycle_stats()

    def _reset_cycle_stats(self):
        """Initialize or reset counters for the current scan cycle."""
        self._cycle_agreement_blocked = 0
        self._cycle_agreement_strategies = {}
        self._cycle_no_data = 0
        self._cycle_no_indicators = 0
        self._cycle_no_signal = 0
        self._cycle_vol_rejected = 0
        self._cycle_conf_rejected = 0
        self._cycle_rsi_rejected = 0
        self._cycle_mtf_exhaustion = 0
        self._cycle_rsi_extreme = 0
        self._cycle_expansion_trap = 0
        self._cycle_wick_magnet = 0
        self._cycle_calm_confluence = 0
        self._cycle_run_exhaustion = 0
        self._cycle_quality_rejected = 0
        self._cycle_stagnant = 0
        self._cycle_scanned_count = 0
        self._cycle_regime_trending = 0
        self._cycle_regime_ranging = 0

    @property
    def stagnation_percent(self) -> float:
        """Percentage of scanned assets that were stagnant in the last cycle."""
        # Use a rolling average or just the last cycle? Last cycle for the heartbeat is fine.
        total_scanned = getattr(self, '_cycle_scanned_count', 66) # fallback
        if total_scanned == 0:
            return 0.0
        return (self._cycle_stagnant / total_scanned) * 100

    def _build_strategy_engine(self) -> StrategyEngine:
        """
        Create and configure the StrategyEngine with all available strategies.

        Weights are set so that the core strategies (Indicators, MHI) have more
        influence than the newer experimental ones (CCV2, Adaptive) until
        the performance tracker has seen enough trades to adjust dynamically.
        """
        engine = StrategyEngine()

        # Core strategies
        engine.register(IndicatorStrategy(), weight=1.2)
        
        # MHI family — 3 separate instances with different cluster sizes
        engine.register(MHIStrategy(variant='mhi'), weight=1.0)        # 3 candles
        engine.register(MHIStrategy(variant='majority'), weight=1.0)   # 5 candles
        engine.register(MHIStrategy(variant='r7'), weight=1.0)         # 7 candles

        # New strategies — lower initial weight until proven
        engine.register(CCV2Strategy(), weight=0.8)
        engine.register(AdaptiveStrategy(), weight=0.7)
        
        # New Quant Overhaul strategy
        engine.register(SqueezeBreakoutStrategy(), weight=1.0)
        
        # Snapback Architecture Strategies
        engine.register(RubberBandStrategy(), weight=2.0)
        engine.register(ApexExhaustionStrategy(), weight=2.0)

        # OTC-native candle geometry strategies (Phase 1)
        engine.register(MomentumCascadeStrategy(), weight=1.0)
        engine.register(CompressionBreakoutStrategy(), weight=1.0)
        engine.register(LateCandleSniperStrategy(), weight=1.0)

        # Mean-reversion strategy (genuinely independent from continuation strategies)
        engine.register(ExhaustionFadeStrategy(), weight=1.2)

        return engine

    def _get_active_strategy_names(self) -> List[str]:
        """Return list of active strategy names.
        
        If config.active_strategies is set, use that.
        Otherwise fall back to the single selected strategy, ensuring full names.
        """
        if self.config.active_strategies:
            return self.config.active_strategies
            
        strat = self.config.scanner_strategy.lower()
        name_map = {
            'indicators': 'Indicators', 'mhi': 'MHI', 'majority': 'Majority',
            'r7': 'R7', 'ccv2': 'CCV2', 'adaptive': 'Adaptive',
            'squeeze': 'Squeeze Breakout', 'rubber': 'Rubber Band', 'apex': 'Apex Exhaustion',
            'cascade': 'Momentum Cascade', 'compression': 'Compression Breakout',
            'sniper': 'Late Candle Sniper', 'exhaustion': 'Exhaustion Fade'
        }
        
        actual_name = name_map.get(strat, strat)
        return [actual_name]

    def _tournament_select(self, signals: List['ScannerSignal']) -> Optional['ScannerSignal']:
        """Select the single strongest signal in tournament mode.
        
        Picks the best signal based on:
          1. Highest absolute score
          2. Tie-break: highest confidence
          3. Tie-break: best asset historical win rate
        
        Args:
            signals: All valid signals from the scan cycle
            
        Returns:
            The single best signal, or None if no valid signals
        """
        if not signals:
            return None
        
        if len(signals) == 1:
            return signals[0]
        
        def _sort_key(sig):
            # Get asset win rate for tie-breaking
            perf = self.asset_performance.get(sig.asset, {})
            wins = perf.get('wins', 0)
            losses = perf.get('losses', 0)
            wr = wins / (wins + losses) if (wins + losses) > 0 else 0.5
            # Use id(sig) as final tie-breaker to prevent comparing ScannerSignal objects
            return (abs(sig.score), sig.confidence, wr, id(sig))
        
        # Sort descending by sort key
        ranked = sorted(signals, key=_sort_key, reverse=True)
        
        winner = ranked[0]
        if len(ranked) > 1:
            runner_up = ranked[1]
            print(f"   🏆 Tournament Winner: {winner.asset} {winner.direction.upper()} "
                  f"(score={abs(winner.score):.0f}, conf={winner.confidence:.0%}) "
                  f"beat {runner_up.asset} {runner_up.direction.upper()} "
                  f"(score={abs(runner_up.score):.0f})")
        
        return winner

    @staticmethod
    def _extract_candle_history(candles, max_candles: int = 10) -> Optional[List[Dict[str, float]]]:
        """Extract last N candles as simplified OHLC dicts for fingerprint storage.
        
        Keeps only o/h/l/c to minimize JSON size (~200 bytes per 10 candles).
        """
        if not candles:
            return None
        try:
            recent = candles[-max_candles:] if len(candles) > max_candles else candles
            result = []
            for c in recent:
                if isinstance(c, dict):
                    result.append({
                        'o': round(float(c.get('open', c.get('o', 0))), 6),
                        'h': round(float(c.get('max', c.get('high', c.get('h', 0)))), 6),
                        'l': round(float(c.get('min', c.get('low', c.get('l', 0)))), 6),
                        'c': round(float(c.get('close', c.get('c', 0))), 6),
                    })
                elif hasattr(c, 'open'):
                    result.append({
                        'o': round(float(c.open), 6),
                        'h': round(float(c.max if hasattr(c, 'max') else c.high), 6),
                        'l': round(float(c.min if hasattr(c, 'min') else c.low), 6),
                        'c': round(float(c.close), 6),
                    })
            return result if result else None
        except Exception:
            return None

    def _rank_assets(self, otc_pairs: List[str]) -> List[str]:
        """
        Sort assets by historical win rate (best first).

        Assets with no history stay in their original position to avoid
        bias against new/unseen pairs.
        """
        if not self.asset_performance:
            return otc_pairs

        def _win_rate(asset: str) -> float:
            base = asset.replace('-OTC', '').replace('-op', '')
            perf = self.asset_performance.get(base, {})
            wins = perf.get('wins', 0)
            total = wins + perf.get('losses', 0)
            if total < 3:
                return 0.5  # neutral for unseen assets
            return wins / total

        return sorted(otc_pairs, key=_win_rate, reverse=True)

    # ==========================================
    # CONFIGURATION
    # ==========================================

    def set_enabled(self, enabled: bool):
        """Enable or disable the scanner."""
        self.config.enabled = enabled
        print(f"🔍 Scanner {'enabled' if enabled else 'disabled'}")

    def set_interval(self, seconds: int):
        """Set scan interval in seconds (min 30s)."""
        self.config.interval = max(15, seconds)
        print(f"🔍 Scanner interval set to {self.config.interval}s")

    def set_trade_mode(self, mode: str):
        """Set trade mode: 'single' or 'multi'."""
        if mode in ("single", "multi"):
            self.config.trade_mode = ScannerTradeMode(mode)
            print(f"🔍 Scanner trade mode set to: {mode}")
        else:
            print(f"⚠️ Invalid trade mode: {mode}. Use 'single' or 'multi'")

    def set_confidence(self, confidence: float):
        """Set minimum confidence threshold (0.5-1.0)."""
        self.config.confidence_min = max(0.5, min(1.0, confidence))
        print(f"🔍 Scanner confidence threshold set to {self.config.confidence_min:.0%}")

    def set_profile(self, profile: str):
        """Set scanner profile: 'trend', 'reversal', or 'mixed'."""
        if profile in ("trend", "reversal", "mixed"):
            self.config.profile = ScannerProfile(profile)
            print(f"🔍 Scanner profile set to: {profile.upper()}")
        else:
            print(f"⚠️ Invalid profile: {profile}. Use 'trend', 'reversal', or 'mixed'")

    def set_top_n_pairs(self, n: int):
        """Set top N pairs to scan (0 = all)."""
        self.config.top_n_pairs = max(0, n)
        if n == 0:
            print(f"🔍 Scanner will scan ALL available OTC pairs")
        else:
            print(f"🔍 Scanner will scan TOP {n} OTC pairs only")

    def set_close_window(self, seconds: int):
        """Set candle close timing window (5-30 seconds)."""
        self.config.close_window_sec = max(5, min(30, seconds))
        print(f"🔍 Scanner candle-close window set to {self.config.close_window_sec}s")

    def set_min_confluence(self, count: int):
        """Set minimum confluence requirement (2-6)."""
        self.config.min_confluence = max(2, min(6, count))
        print(f"🔍 Scanner min confluence set to {self.config.min_confluence}")

    def set_allowed_volatility(self, volatility_list: List[str]):
        """Set allowed volatility regimes (normal, low, high)."""
        valid = [v for v in volatility_list if v in ("normal", "low", "high")]
        if valid:
            self.config.allowed_volatility = valid
            print(f"🔍 Scanner allowed volatility: {', '.join(valid)}")
        else:
            print(f"⚠️ Invalid volatility list. Use: normal, low, high")

    def set_autostop(self, enabled: bool):
        """Enable or disable auto-stop on session block."""
        self.config.autostop_on_session_block = enabled
        print(f"🔍 Scanner auto-stop on session block: {'ON' if enabled else 'OFF'}")

    def set_ml_enabled(self, enabled: bool):
        """Enable or disable the ML Probability Engine."""
        self.config.scanner_ml_enabled = enabled
        print(f"🔍 Scanner ML Prob Engine: {'ON' if enabled else 'OFF'}")

    def set_adaptive_enabled(self, enabled: bool):
        """Enable or disable Volatility-Adaptive Thresholding."""
        self.config.scanner_adaptive_enabled = enabled
        if hasattr(self.gatekeeper, 'adaptive_enabled'):
            self.gatekeeper.adaptive_enabled = enabled
        print(f"🔍 Scanner Adaptive Thresholds: {'ON' if enabled else 'OFF'}")

    def set_precision_timing(self, enabled: bool):
        """Enable or disable Precision Timing (Second 58 Rule)."""
        self.config.scanner_precision_timing = enabled
        print(f"🔍 Scanner Precision Timing: {'ON' if enabled else 'OFF'}")

    def set_timeframe_mode(self, dynamic: bool):
        """Set timeframe mode: True=dynamic, False=fixed."""
        self.config.dynamic_timeframe = dynamic
        mode = "DYNAMIC" if dynamic else f"FIXED ({self.config.fixed_duration}m)"
        print(f"🔍 Scanner timeframe mode: {mode}")

    def set_fixed_duration(self, minutes: int):
        """Set fixed duration in minutes (1-5)."""
        self.config.fixed_duration = max(1, min(5, minutes))
        print(f"🔍 Scanner fixed duration: {self.config.fixed_duration}m")

    # ==========================================
    # PER-ASSET PERFORMANCE TRACKING
    # ==========================================

    def _get_base_asset(self, asset: str) -> str:
        """Extract base asset name from OTC variant (e.g., EURUSD-OTC -> EURUSD)."""
        return asset.replace('-OTC', '').replace('-op', '')

    def record_asset_result(self, asset: str, won: bool):
        """Record a win or loss for an asset. Called from result_checker."""
        base = self._get_base_asset(asset)
        if base not in self.asset_performance:
            self.asset_performance[base] = {'wins': 0, 'losses': 0}
        if won:
            self.asset_performance[base]['wins'] += 1
        else:
            self.asset_performance[base]['losses'] += 1

        # Log if newly blacklisted
        perf = self.asset_performance[base]
        total = perf['wins'] + perf['losses']
        if total >= self.config.blacklist_min_trades:
            wr = perf['wins'] / total
            if wr < self.config.blacklist_win_rate:
                print(f"   ⛔ {base} auto-blacklisted: {perf['wins']}/{total} = {wr*100:.0f}% win rate (threshold: {self.config.blacklist_win_rate*100:.0f}%)")

    def _is_blacklisted(self, base_asset: str) -> bool:
        """Check if a base asset is blacklisted due to poor performance or hardcoded bans."""
        # toxic_assets = ["GBPCAD", "USDPLN", "NZDJPY", "AUDCHF"]
        # if base_asset.replace("-OTC", "") in toxic_assets:
        #     return True
        
        perf = self.asset_performance.get(base_asset)
        if not perf:
            return False
        
        total = perf['wins'] + perf['losses']
        if total < self.config.blacklist_min_trades:
            return False
            
        win_rate = perf['wins'] / total
        return win_rate < self.config.blacklist_win_rate

    def get_blacklisted_assets(self) -> List[str]:
        """Get list of currently blacklisted base assets."""
        blacklisted = []
        for base, perf in self.asset_performance.items():
            total = perf['wins'] + perf['losses']
            if total >= self.config.blacklist_min_trades:
                wr = perf['wins'] / total
                if wr < self.config.blacklist_win_rate:
                    blacklisted.append(base)
        return blacklisted

    def get_asset_performance_summary(self) -> List[Dict[str, Any]]:
        """Get sorted per-asset performance for display."""
        summary = []
        for base, perf in self.asset_performance.items():
            total = perf['wins'] + perf['losses']
            wr = (perf['wins'] / total * 100) if total > 0 else 0
            summary.append({
                'asset': base,
                'wins': perf['wins'],
                'losses': perf['losses'],
                'total': total,
                'win_rate': wr,
                'blacklisted': self._is_blacklisted(base),
            })
        # Sort by total trades descending
        summary.sort(key=lambda x: x['total'], reverse=True)
        return summary

    def reset_asset_performance(self, asset: Optional[str] = None):
        """Reset performance tracking. If asset given, reset only that asset."""
        if asset:
            base = self._get_base_asset(asset)
            if base in self.asset_performance:
                del self.asset_performance[base]
                print(f"🔍 Reset performance data for {base}")
            else:
                print(f"⚠️ No performance data for {base}")
        else:
            self.asset_performance.clear()
            print(f"🔍 All per-asset performance data reset")

    def get_status(self) -> Dict[str, Any]:
        """Get scanner status information."""
        # Get OTC pairs count from cache
        otc_pairs_count = 0
        if self.get_otc_pairs_callback:
            try:
                otc_pairs_count = len(self.get_otc_pairs_callback())
            except Exception:
                pass

        return {
            'enabled': self.config.enabled,
            'running': self.running,
            'interval': self.config.interval,
            'confidence_min': self.config.confidence_min,
            'trade_mode': self.config.trade_mode.value,
            'profile': self.config.profile.value,
            'top_n_pairs': self.config.top_n_pairs,
            'close_window_sec': self.config.close_window_sec,
            'min_confluence': self.config.min_confluence,
            'allowed_volatility': self.config.allowed_volatility,
            'autostop': self.config.autostop_on_session_block,
            'dynamic_timeframe': self.config.dynamic_timeframe,
            'fixed_duration': self.config.fixed_duration,
            'min_duration': self.config.min_duration,
            'max_duration': self.config.max_duration,
            'bb_squeeze_threshold': getattr(self.gatekeeper, 'bb_squeeze_threshold', 0.05),
            'last_scan': self.last_scan_time,
            'cooldowns_active': len(self.asset_cooldowns),
            'otc_pairs_count': otc_pairs_count,
            'blacklisted_assets': self.get_blacklisted_assets(),
            'asset_performance': {k: v.copy() for k, v in self.asset_performance.items()},
            'blacklist_min_trades': self.config.blacklist_min_trades,
            'blacklist_win_rate': self.config.blacklist_win_rate,
            'ml_enabled': self.config.scanner_ml_enabled,
            'adaptive_enabled': self.config.scanner_adaptive_enabled,
            'scanner_strategy': getattr(self.config, 'scanner_strategy', 'indicators'),
            'scanner_precision_timing': getattr(self.config, 'scanner_precision_timing', True),
            'active_strategies': self.config.active_strategies,
            'wait_for_pullback': self.config.wait_for_pullback
        }

    # ==========================================
    # MAIN SCANNER LOOP
    # ==========================================

    async def start(self):
        """Start the scanner loop."""
        if self.running:
            print("🔍 Scanner already running")
            return

        print(f"🔍 OTC Scanner started (interval: {self.config.interval}s, mode: {self.config.trade_mode.value})")

        # Log initial OTC pairs count
        if self.get_otc_pairs_callback:
            try:
                pairs = self.get_otc_pairs_callback()
                print(f"   📊 Forex OTC pairs to scan: {len(pairs)}")
                if pairs and len(pairs) <= 10:
                    print(f"   📋 Pairs: {pairs}")
                elif pairs:
                    print(f"   📋 Sample: {pairs[:5]}...")
            except Exception:
                pass

        self.running = True

        while self.running and self.config.enabled:
            try:
                await self._scan_cycle()
                await asyncio.sleep(self.config.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ Scanner error: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(5)

        self.running = False
        print("🔍 OTC Scanner stopped")

    async def stop(self):
        """Stop the scanner loop."""
        self.running = False

    async def _scan_cycle(self):
        """Execute one scan cycle across all OTC pairs."""
        # Check if connected
        if self.is_connected_callback and not self.is_connected_callback():
            return

        # NOTE: Trade mode gate (single/multi) is checked AFTER scanning,
        # at signal emission time. This ensures the scanner always analyzes
        # market state even when trades are active (vital for single mode).

        self.last_scan_time = time.time()

        # ==========================================
        # PHASE E: PRECISION TIMING (SECOND 58 RULE)
        # ==========================================
        # Only apply MHI/R7 precision timing when those strategies are
        # actually active (handles combos like indicators+mhi correctly).
        precision_triggered = False
        if self.config.scanner_precision_timing:
            now = datetime.now()
            
            # Determine which strategies actually need precision timing
            active_names = [s.lower() for s in self._get_active_strategy_names()]
            needs_mhi_timing = any(s in ("mhi", "majority") for s in active_names)
            needs_r7_timing = "r7" in active_names
            
            # Only check scanner_strategy fallback if NO custom combo is set.
            # When active_strategies is explicitly set (e.g. cascade+sniper+compression),
            # the active_names list above is the source of truth — don't let the
            # scanner_strategy 'hybrid' label falsely trigger MHI/R7 timing.
            if not self.config.active_strategies:
                strategy = self.config.scanner_strategy.lower()
                if strategy in ("mhi", "majority"):
                    needs_mhi_timing = True
                elif strategy == "r7":
                    needs_r7_timing = True
                elif strategy == "hybrid":
                    needs_mhi_timing = True
                    needs_r7_timing = True

            # Check timing windows
            is_mhi_window = now.minute % 5 == 4    # End of 5-min block (for MHI/Majority)
            is_r7_window = now.minute % 5 == 0     # Start of next block (for R7)
            
            timing_label = None
            if needs_mhi_timing and is_mhi_window:
                timing_label = "MHI Block Close"
            elif needs_r7_timing and is_r7_window:
                timing_label = "R7 Block Open"
            
            if timing_label:
                if now.second < 58:
                    wait_sec = 58 - now.second
                    print(f"   ⏳ Precision Timing: Waiting {wait_sec}s for Second 58 ({timing_label})...")
                    await asyncio.sleep(wait_sec)
                    self.last_scan_time = time.time()
                
                # If we are in the window, mark as triggered so we bypass normal candle check
                if 57 <= datetime.now().second <= 59:
                    precision_triggered = True

        # ==========================================
        # PROFESSIONAL FILTER 1: CANDLE-CLOSE TIMING
        # ==========================================
        if not precision_triggered and not self._is_near_candle_close():
            # Not near candle close and not MHI precision trigger - skip
            return

        # Get all OTC pairs
        otc_pairs = await self._get_otc_pairs()
        if not otc_pairs:
            return

        # ==========================================
        # SESSION-BASED ASSET RANKING
        # Sort by historical win rate, best performers first
        # ==========================================
        otc_pairs = self._rank_assets(otc_pairs)

        # ==========================================
        # PROFESSIONAL FILTER 2: TOP-N PAIRS ONLY
        # Reduce universe to avoid overtrading
        # ==========================================
        if self.config.top_n_pairs > 0 and len(otc_pairs) > self.config.top_n_pairs:
            otc_pairs = otc_pairs[:self.config.top_n_pairs]

        print(f"\n🔍 Scanning {len(otc_pairs)} OTC pairs (profile: {self.config.profile.value})...")

        # Per-cycle agreement gate tracking (for compact summary)
        self._reset_cycle_stats()
        self._cycle_scanned_count = len(otc_pairs)
        
        # CLEAR CACHE: Ensure each scan cycle gets FRESH candles from the API
        # across all 66 pairs. The 15s cache can sometimes cause overlap.
        self.data_provider.clear_cache()

        # ==========================================
        # STRATEGY FILTERING FOR PRECISION ENFORCEMENT
        # ==========================================
        allowed_strategies = None
        if self.config.scanner_precision_timing:
            active_names = [s.lower() for s in self._get_active_strategy_names()]
            mhi_family = ("mhi", "majority", "r7")
            
            # If precision rule triggered (it's the 5-min window), allow all.
            # Otherwise (normal 1-min scan), remove MHI family from this specific cycle.
            if not precision_triggered:
                # Normal 1-minute candle close scan.
                # Only allow non-precision strategies (indicators, ccv2, adaptive).
                allowed_strategies = [s for s in active_names if s not in mhi_family]
                if not allowed_strategies:
                    # If only MHI was active and it's not the window, skip scan entirely
                    return
            else:
                # Precision window - allow all active strategies
                allowed_strategies = active_names

        # Use a semaphore to limit concurrent API calls / analysis
        # Reduced from 10 to 5 to avoid API timeouts/pressure
        semaphore = asyncio.Semaphore(5)
        
        async def analyze_with_semaphore(asset):
            async with semaphore:
                # Add individual asset timeout to prevent stalling the whole scan
                try:
                    return await asyncio.wait_for(self._analyze_asset(asset, allowed_strategies=allowed_strategies, precision_triggered=precision_triggered), timeout=20.0)
                except asyncio.TimeoutError:
                    print(f"   ⚠️ Analysis Timeout: {asset} skipped after 20s")
                    return None
                except Exception as e:
                    print(f"   ⚠️ Analysis Error for {asset}: {e}")
                    return None

        # Run all analyses in parallel (with concurrency limit)
        tasks = [analyze_with_semaphore(asset) for asset in otc_pairs]
        results = await asyncio.gather(*tasks)

        # Collect valid signals
        valid_signals = [s for s in results if s is not None]

        # ==========================================
        # TOURNAMENT MODE: Independent strategy scanning
        # Each strategy picks its own best asset, then
        # we select the single strongest signal overall.
        # ==========================================
        if self.config.scan_mode == 'tournament' and len(self._get_active_strategy_names()) > 1:
            tournament_winner = self._tournament_select(valid_signals)
            if tournament_winner:
                valid_signals = [tournament_winner]
            else:
                valid_signals = []

        # ==========================================
        # CURRENCY FAMILY DEDUPLICATION
        # Prevent correlated batch losses by keeping
        # only the strongest signal per currency family.
        # ==========================================
        if len(valid_signals) > 1:
            valid_signals = self._dedup_by_currency_family(valid_signals)

        # ==========================================
        # TRADE MODE GATE (moved here from pre-scan)
        # In single mode, only emit if no active trades.
        # This way the scanner always analyzes the market
        # but respects the trade mode at emission time.
        # In single mode, emit AT MOST one signal per cycle.
        # ==========================================
        signals_found = 0
        signals_emitted = 0
        is_single_mode = (self.config.trade_mode == ScannerTradeMode.SINGLE)

        for signal in valid_signals:
            signals_found += 1

            # In single mode, only emit the first signal
            if is_single_mode and signals_emitted >= 1:
                print(f"   [Blocked] {signal.asset}: Single-trade mode (already emitted 1 this cycle)")
                continue

            # Check trade gate each iteration
            trade_blocked = False
            block_reason = ""
            if self.can_trade_callback:
                can_trade, block_reason = self.can_trade_callback()
                if not can_trade:
                    trade_blocked = True

            if trade_blocked:
                print(f"   [Blocked] {signal.asset}: {block_reason} (Score={signal.score:.0f}, Conf={signal.confidence:.0%})")
                continue

            # Emit signal via callback
            if self.on_signal:
                try:
                    await self.on_signal(signal)
                    signals_emitted += 1
                except Exception as e:
                    print(f"⚠️ Error in signal callback: {e}")

        # Notify scan complete
        scan_duration = time.time() - self.last_scan_time
        blocked_count = signals_found - signals_emitted
        blocked_tag = f" ({blocked_count} blocked)" if blocked_count > 0 else ""

        # Compact agreement gate summary (replaces 30 individual BLOCKED lines)
        gate_blocked = getattr(self, '_cycle_agreement_blocked', 0)
        no_data = getattr(self, '_cycle_no_data', 0)
        no_ind = getattr(self, '_cycle_no_indicators', 0)
        no_sig = getattr(self, '_cycle_no_signal', 0)
        vol_rej = getattr(self, '_cycle_vol_rejected', 0)
        conf_rej = getattr(self, '_cycle_conf_rejected', 0)
        rsi_rej = getattr(self, '_cycle_rsi_rejected', 0)
        mtf_exh = getattr(self, '_cycle_mtf_exhaustion', 0)
        rsi_ext = getattr(self, '_cycle_rsi_extreme', 0)
        exp_trap = getattr(self, '_cycle_expansion_trap', 0)
        wick_mag = getattr(self, '_cycle_wick_magnet', 0)
        calm_conf = getattr(self, '_cycle_calm_confluence', 0)
        run_exh = getattr(self, '_cycle_run_exhaustion', 0)
        q_rej = getattr(self, '_cycle_quality_rejected', 0)
        stagnant = getattr(self, '_cycle_stagnant', 0)

        # Build compact rejection breakdown
        rejection_parts = []
        if no_data:
            rejection_parts.append(f"no_data:{no_data}")
        if no_ind:
            rejection_parts.append(f"no_indicators:{no_ind}")
        if no_sig:
            rejection_parts.append(f"no_signal:{no_sig}")
        if gate_blocked:
            strat_summary = ", ".join(
                f"{name}:{count}" for name, count in
                sorted(self._cycle_agreement_strategies.items(), key=lambda x: -x[1])
            )
            rejection_parts.append(f"agreement:{gate_blocked} ({strat_summary})")
        if vol_rej:
            rejection_parts.append(f"volatility:{vol_rej}")
        if conf_rej:
            rejection_parts.append(f"low_conf:{conf_rej}")
        if rsi_ext:
            rejection_parts.append(f"rsi_extreme:{rsi_ext}")
        if exp_trap:
            rejection_parts.append(f"expansion_trap:{exp_trap}")
        if wick_mag:
            rejection_parts.append(f"wick_magnet:{wick_mag}")
        if calm_conf:
            rejection_parts.append(f"tf_misaligned:{calm_conf}")
        if run_exh:
            rejection_parts.append(f"run_exhaustion:{run_exh}")
        if stagnant:
            rejection_parts.append(f"market_stagnant:{stagnant}")
        if q_rej:
            rejection_parts.append(f"low_quality:{q_rej}")
        if rsi_rej:
            rejection_parts.append(f"rsi_deadzone:{rsi_rej}")
        if mtf_exh:
            rejection_parts.append(f"mtf_exhaustion:{mtf_exh}")

        if rejection_parts:
            print(f"   📊 Rejections: {' | '.join(rejection_parts)}")

        # Regime routing summary (only when enabled)
        regime_t = getattr(self, '_cycle_regime_trending', 0)
        regime_r = getattr(self, '_cycle_regime_ranging', 0)
        if regime_t or regime_r:
            print(f"   🔀 Regime routing: trending:{regime_t} | ranging:{regime_r}")

        print(f"✅ Scan complete: {len(otc_pairs)} pairs, {signals_emitted} signals{blocked_tag}, {scan_duration:.1f}s")

        if self.on_scan_complete:
            try:
                await self.on_scan_complete(len(otc_pairs), signals_found)
            except Exception:
                pass

        # Clean up old cooldowns
        self._cleanup_cooldowns()

    # Cooldown methods defined at end of class (lines 900+)

    def _dedup_by_currency_family(self, signals: List['ScannerSignal']) -> List['ScannerSignal']:
        """
        Deduplicate signals by currency family to prevent correlated batch losses.

        OTC pairs sharing the same base or quote currency (e.g., EURUSD, EURGBP,
        EURJPY) are highly correlated — if one loses, they all tend to lose.
        This method keeps only the strongest signal per currency family.

        Currency families are determined by the first 3 chars (base) and chars 3-6
        (quote) of the asset name. Two signals are considered 'same family' if they
        share the same base currency.

        Returns:
            Deduplicated list of signals (strongest per family).
        """
        if not signals:
            return signals

        # Group signals by base currency
        family_groups: Dict[str, List['ScannerSignal']] = {}
        for signal in signals:
            # Extract base currency (first 3 chars): EURUSD-OTC → EUR
            base_asset = signal.asset.replace('-OTC', '').replace('-op', '')
            base_currency = base_asset[:3].upper() if len(base_asset) >= 3 else base_asset.upper()

            if base_currency not in family_groups:
                family_groups[base_currency] = []
            family_groups[base_currency].append(signal)

        # Pick the strongest signal per family (highest abs score)
        deduped: List['ScannerSignal'] = []
        for family, group in family_groups.items():
            if len(group) == 1:
                deduped.append(group[0])
            else:
                # Sort by absolute score descending, break ties by confidence + id(s) to avoid TypeError
                best = max(group, key=lambda s: (abs(s.score), s.confidence, id(s)))
                dropped = [s.asset for s in group if s is not best]
                print(f"   [Dedup] {family} family: kept {best.asset} (Score={best.score:.0f}), dropped {', '.join(dropped)}")
                deduped.append(best)

        if len(deduped) < len(signals):
            print(f"   📊 Currency dedup: {len(signals)} signals → {len(deduped)} (removed {len(signals) - len(deduped)} correlated)")

        return deduped

    def _is_near_candle_close(self) -> bool:
        """
        Check if current time is within the candle-close window.

        For 2-minute candles, candle closes happen at:
        - :00, :02, :04, :06, ... (every 2 minutes)

        We want to trade only in the last N seconds before close
        OR the first N seconds after close.

        Returns True if we're within the trading window.
        """
        window = self.config.close_window_sec
        now = time.time()

        # Seconds into the current 2-minute period
        seconds_into_period = int(now) % 120

        # Near the END of the period (last N seconds before close)
        near_end = seconds_into_period >= (120 - window)

        # Near the START of the period (first N seconds after close)
        near_start = seconds_into_period <= window

        return near_end or near_start

    # ==========================================
    # OTC PAIR DISCOVERY
    # ==========================================

    async def _get_otc_pairs(self) -> List[str]:
        """
        Get list of all available OTC pairs.

        Uses cached OTC pairs from worker for efficiency (no API call needed).
        Falls back to API call if callback not provided.

        Focuses ONLY on OTC markets (-OTC and -op variants).
        Excludes regular/live market pairs.
        """
        # Use cached pairs from worker if available (more efficient)
        if self.get_otc_pairs_callback:
            try:
                cached_pairs = self.get_otc_pairs_callback()
                if cached_pairs:
                    return cached_pairs
            except Exception as e:
                print(f"⚠️ Error getting cached OTC pairs: {e}")

        # Fallback: fetch from API (less efficient)
        try:
            loop = asyncio.get_event_loop()
            all_assets = await loop.run_in_executor(None, self.api.get_all_open_time)

            if not all_assets:
                return []

            otc_pairs = []

            # Check binary/turbo options
            binary = all_assets.get('turbo', {})
            for asset, info in binary.items():
                if isinstance(info, dict) and info.get('open'):
                    # Only include OTC pairs
                    asset_upper = asset.upper()
                    if 'OTC' in asset_upper or '-OP' in asset_upper:
                        otc_pairs.append(asset)

            return otc_pairs

        except Exception as e:
            print(f"⚠️ Error getting OTC pairs from API: {e}")
            return []

    # ==========================================
    # ASSET ANALYSIS
    # ==========================================

    def _format_mtf_trends(self, i2: Dict, i5: Optional[Dict], i15: Optional[Dict]) -> str:
        """Helper to format trend summary for signal reports."""
        t2 = i2.get('trend', 'neutral').upper()
        t5 = i5.get('trend', 'neutral').upper() if i5 else 'UNDEFINED'
        t15 = i15.get('trend', 'neutral').upper() if i15 else 'UNDEFINED'
        return f"2m: {t2} | 5m: {t5} | 15m: {t15}"

    def _detect_regime(self, indicators_2m: Dict, candles: list) -> str:
        """
        Detect market regime using candle directionality + ATR context.

        OTC markets have synthetically stable ATR, so we use multiple
        heuristics to detect trending vs ranging:

        Trending if ANY of:
          1. Last 3 candles: 2/3 same direction
          2. Last 5 candles: 3/5 same direction (catches alternating noise)
          3. Net body momentum: sum of signed bodies is > 60% of total body size
          4. ATR is elevated above average (rare in OTC but valid)
          5. 2m trend indicator says bullish/bearish (not neutral)

        Ranging: None of the above triggered.

        Returns:
            'trending' or 'ranging'
        """
        directional = False

        if candles and len(candles) >= 3:
            # --- Heuristic 1: Last 3 candles, 2/3 same direction ---
            last3 = candles[-3:]
            dirs3 = []
            for c in last3:
                o = float(c.get('open', c.get('o', 0)))
                cl = float(c.get('close', c.get('c', 0)))
                if cl > o:
                    dirs3.append('call')
                elif cl < o:
                    dirs3.append('put')
                else:
                    dirs3.append('neutral')

            if dirs3.count('call') >= 2 or dirs3.count('put') >= 2:
                directional = True

            # --- Heuristic 2: Last 5 candles, 3/5 same direction ---
            if not directional and len(candles) >= 5:
                last5 = candles[-5:]
                dirs5 = []
                for c in last5:
                    o = float(c.get('open', c.get('o', 0)))
                    cl = float(c.get('close', c.get('c', 0)))
                    if cl > o:
                        dirs5.append('call')
                    elif cl < o:
                        dirs5.append('put')
                    else:
                        dirs5.append('neutral')

                if dirs5.count('call') >= 3 or dirs5.count('put') >= 3:
                    directional = True

            # --- Heuristic 3: Net body momentum ---
            if not directional and len(candles) >= 5:
                last5 = candles[-5:]
                signed_sum = 0.0
                total_abs = 0.0
                for c in last5:
                    o = float(c.get('open', c.get('o', 0)))
                    cl = float(c.get('close', c.get('c', 0)))
                    body = cl - o
                    signed_sum += body
                    total_abs += abs(body)

                if total_abs > 0 and abs(signed_sum) / total_abs > 0.60:
                    directional = True

        # --- Heuristic 4: ATR check (relaxed for OTC's tight bands) ---
        atr = float(indicators_2m.get('atr', 0))
        avg_atr = float(indicators_2m.get('avg_atr', 0))
        atr_elevated = atr > avg_atr * 1.02 if avg_atr > 0 else False

        # --- Heuristic 5: 2m trend indicator is not neutral ---
        trend_2m = str(indicators_2m.get('trend', 'neutral')).lower()
        trend_directional = trend_2m in ('bullish', 'bearish')

        if directional or atr_elevated or trend_directional:
            return 'trending'
        else:
            return 'ranging'

    def _get_regime_strategies(self, regime: str) -> tuple:
        """
        Get the strategy combo and agreement requirement for the detected regime.

        Regime A (Trending): ATR > avg, directional candles — continuation + breakout strategies.
        Regime B (Ranging/Low-Vol): ATR <= avg — mean-reversion + fade strategies.

        When regime routing is ON, it OVERRIDES the user's manual combo entirely.
        This is intentional — the regime decides which strategies are appropriate.

        Agreement uses the user's `/scanner agreement N` setting (self.config.min_agreement).

        Returns:
            (strategy_names: List[str], min_agreement: int)
        """
        agreement = self.config.min_agreement  # Respects /scanner agreement N

        if regime == 'trending':
            return ([
                'Momentum Cascade',       # 3-candle directional expansion
                'Compression Breakout',    # Range breakout on expansion candle
                'Squeeze Breakout',        # Keltner squeeze release
                'Late Candle Sniper',      # Fresh commitment after indecision
                'Indicators',              # Trend alignment + momentum confluence
            ], agreement)
        else:
            # Ranging: mean-reversion and fade strategies
            return ([
                'Exhaustion Fade',         # RSI/Stoch/BB extreme fade
                'Adaptive',                # KAMA mean-reversion
                'CCV2',                    # Consecutive candle streak reversal
                'Rubber Band',             # 2m extreme vs 15m macro fade
                'Apex Exhaustion',         # Fade extreme momentum breakouts
            ], agreement)

    async def _analyze_asset(self, asset: str, allowed_strategies: Optional[List[str]] = None, precision_triggered: bool = False) -> Optional[ScannerSignal]:
        """
        Analyze a single OTC asset for potential entry signal.

        PROFESSIONAL FILTERS APPLIED:
        1. Volatility regime must be in allowed list
        2. MTF alignment required (5m must match direction)
        3. 15m must not be opposite
        4. Confluence must meet scanner minimum (stricter than gatekeeper)
        5. Profile-based filtering (trend/reversal/mixed)

        Uses:
        - 2-minute candles for entry signal
        - 5-minute candles for trend confirmation
        - 15-minute candles for structure confirmation
        - Pattern analysis on 2m candles
        - Gatekeeper decision with MTF context

        Returns:
            ScannerSignal if all professional filters pass, None otherwise.
        """
        # Check cooldown first
        if self._is_on_cooldown(asset):
            print(f"   [Skipped] {asset}: On cooldown")
            return None

        # Check per-asset blacklist
        base_asset = asset.replace('-OTC', '').replace('-op', '')
        if self._is_blacklisted(base_asset):
            perf = self.asset_performance.get(base_asset, {})
            wins = perf.get('wins', 0)
            total = wins + perf.get('losses', 0)
            wr = (wins / total * 100) if total > 0 else 0
            print(f"   [Blacklisted] {asset}: Win rate {wr:.0f}% ({wins}/{total}) below {self.config.blacklist_win_rate*100:.0f}% threshold")
            return None

        try:
            # Fetch MTF bundle (2m entry + 5m/15m confirmation)
            mtf_bundle = await self.data_provider.get_mtf_bundle(
                asset,
                include_5m=True,
                include_15m=True
            )

            if not mtf_bundle.entry_tf.is_valid:
                self._cycle_no_data += 1
                return None

            # Check for market stagnation (Volatility Warning)
            if self._is_market_stagnant(mtf_bundle.entry_tf.candles):
                self._cycle_stagnant += 1
                if asset not in self._stale_assets_notified:
                    print(f"   ⚠️ Stale Market: {asset} - Price hasn't moved for several candles")
                    self._stale_assets_notified.add(asset)
            else:
                if asset in self._stale_assets_notified:
                    self._stale_assets_notified.remove(asset)


            # Calculate indicators for 2m (entry timeframe)
            indicators_2m = self.analyzer.calculate_indicators(mtf_bundle.entry_tf.candles, symbol=asset)
            if not indicators_2m:
                self._cycle_no_indicators += 1
                return None

            # Calculate previous indicators for 2m (for trapdoor/momentum delta)
            indicators_2m_prev = None
            if len(mtf_bundle.entry_tf.candles) > 30:
                indicators_2m_prev = self.analyzer.calculate_indicators(mtf_bundle.entry_tf.candles[:-1], symbol=asset)

            # Calculate indicators for higher timeframes (confirmation)
            indicators_5m = None
            indicators_15m = None

            if mtf_bundle.mid_tf and mtf_bundle.mid_tf.is_valid:
                indicators_5m = self.analyzer.calculate_indicators(mtf_bundle.mid_tf.candles, symbol=asset)

            if mtf_bundle.high_tf and mtf_bundle.high_tf.is_valid:
                indicators_15m = self.analyzer.calculate_indicators(mtf_bundle.high_tf.candles, symbol=asset)

            # Pattern analysis on 2m candles
            pattern_analysis = self.pattern_analyzer.analyze(mtf_bundle.entry_tf.candles)

            # ==========================================
            # STRATEGY ENGINE EVALUATION
            # Replaces inline MHI/Indicator calls with
            # unified weighted multi-strategy voting.
            # ==========================================
            scanner_strat = getattr(self.config, 'scanner_strategy', 'indicators').lower()

            # Pass active_strategies if set (custom combo)
            eval_kwargs = dict(
                indicators_2m=indicators_2m,
                indicators_2m_prev=indicators_2m_prev,
                indicators_5m=indicators_5m,
                indicators_15m=indicators_15m,
                profile=self.config.profile.value,
                strategy_type=scanner_strat,
                min_agreement=self.config.min_agreement,
            )
            # Only override active_strategies if allowed_strategies is actively filtering (e.g. MHI precision window)
            # If allowed_strategies is None, we just let the Strategy Engine use strategy_type 
            if allowed_strategies:
                eval_kwargs['active_strategies'] = allowed_strategies
            elif self.config.active_strategies:
                eval_kwargs['active_strategies'] = self.config.active_strategies

            # ==========================================
            # 2-REGIME ATR-BASED STRATEGY ROUTING
            # When enabled, detects trending vs ranging regime
            # per-asset and routes to the appropriate strategy
            # combo. Overrides active_strategies for this eval only.
            # Only skip when precision timing TRIGGERED (MHI window)
            # since those strategies need specific candle alignment.
            # ==========================================
            detected_regime = None
            if self.config.regime_routing_enabled and not precision_triggered:
                detected_regime = self._detect_regime(indicators_2m, mtf_bundle.entry_tf.candles)
                regime_strats, regime_agreement = self._get_regime_strategies(detected_regime)
                eval_kwargs['active_strategies'] = regime_strats
                eval_kwargs['min_agreement'] = regime_agreement
                if detected_regime == 'trending':
                    self._cycle_regime_trending += 1
                else:
                    self._cycle_regime_ranging += 1

            # Determine which strategies are actually active for this evaluation
            active_for_eval = eval_kwargs.get('active_strategies', self._get_active_strategy_names())

            if self.config.scan_mode == 'tournament' and len(active_for_eval) > 1:
                # In Tournament mode, strategies evaluate completely independently.
                # Since _analyze_asset runs for ONE asset at a time, we run evaluate_single()
                # for each strategy and keep the highest scoring one.
                best_decision = None
                best_score = -1.0
                for strat_name in active_for_eval:
                    decision = self.strategy_engine.evaluate_single(strat_name, candles=mtf_bundle.entry_tf.candles, symbol=asset, **eval_kwargs)
                    if decision.should_trade and decision.direction in ('call', 'put'):
                        weight = self.strategy_engine.strategies[strat_name].effective_weight if strat_name in self.strategy_engine.strategies else 1.0
                        competitive_score = abs(decision.score) * weight
                        if competitive_score > best_score:
                            best_score = competitive_score
                            best_decision = decision
                
                if best_decision:
                    engine_decision = best_decision
                else:
                    # Fallback if no strategy fired
                    engine_decision = self.strategy_engine.evaluate_single(active_for_eval[0], candles=mtf_bundle.entry_tf.candles, symbol=asset, **eval_kwargs)
            else:
                # Voting / Hybrid mode: use the standard evaluate() logic
                engine_decision = self.strategy_engine.evaluate(candles=mtf_bundle.entry_tf.candles, symbol=asset, **eval_kwargs)

            # Map TradeDecision → SignalScore for downstream gatekeeper compatibility
            if engine_decision.should_trade and engine_decision.direction in ('call', 'put'):
                score_obj = SignalScore(
                    score=engine_decision.score,
                    confidence=engine_decision.confidence,
                    direction=engine_decision.direction,
                    reasons=engine_decision.reasons,
                    warnings=engine_decision.warnings,
                    should_trade=engine_decision.should_trade,
                    confluence_count=engine_decision.confluence_count
                )
            else:
                score_obj = SignalScore(0.0, 0.0, "neutral", engine_decision.reasons, engine_decision.warnings, False, 0)
                # Track agreement-blocked for scan summary
                if engine_decision.direction in ('call', 'put') and engine_decision.agreeing_strategies:
                    self._cycle_agreement_blocked += 1
                    for s in engine_decision.agreeing_strategies:
                        self._cycle_agreement_strategies[s] = self._cycle_agreement_strategies.get(s, 0) + 1

            potential_direction = score_obj.direction
            # use_mhi is used for filter bypasses. 
            # If hybrid, we check if the primary reason starts with MHI/Majority/R7/CCV2
            use_mhi = False
            if score_obj.reasons:
                first_reason = score_obj.reasons[0].lower()
                if any(x in first_reason for x in ("mhi", "majority", "r7", "ccv2")):
                    use_mhi = True

            if potential_direction not in ("call", "put"):
                # No pattern or indicator signal found
                # Only increment no_signal if it wasn't already caught by the agreement gate
                if not (engine_decision.direction in ('call', 'put') and engine_decision.agreeing_strategies):
                    self._cycle_no_signal += 1
                return None

            # ==========================================
            # MEMORY CHECK (TRADE FINGERPRINTING)
            # ==========================================
            
            # Determine trade duration EARLY so it can be part of the fingerprint context
            duration = self._select_duration(
                confidence=engine_decision.confidence,
                confluence=engine_decision.confluence_count,
                mtf_5m_aligned=False, # Deprecated
                mtf_15m_aligned=False, # Deprecated
                score=engine_decision.score,
                volatility_regime=str(indicators_2m.get("volatility_regime", "normal")),
                indicators_2m=indicators_2m,
                use_mhi=use_mhi
            )

            # Generate fingerprint for the ML evaluation and worker
            from .fingerprint import TradeFingerprint
            
            current_fingerprint = TradeFingerprint(
                asset=asset,
                direction=engine_decision.direction,
                action_time=time.time(),
                duration=duration,
                rsi=float(indicators_2m.get("rsi", 50.0)),
                stoch_k=float(indicators_2m.get("stoch_k", 50.0)),
                stoch_d=float(indicators_2m.get("stoch_d", 50.0)),
                macd_hist=float(indicators_2m.get("macd_histogram", 0.0)),
                bb_position=float(indicators_2m.get("bb_position", 0.5)),
                volatility=str(indicators_2m.get("volatility_regime", "normal")),
                trend_2m=str(indicators_2m.get("trend", "neutral")),
                trend_5m=str(indicators_5m.get("trend", "neutral")) if indicators_5m else "neutral",
                trend_15m=str(indicators_15m.get("trend", "neutral")) if indicators_15m else "neutral",
                score=float(engine_decision.score),
                candles=self._extract_candle_history(mtf_bundle.entry_tf.candles) if mtf_bundle.entry_tf else None,
                strategy_used='+'.join(engine_decision.agreeing_strategies) if engine_decision.agreeing_strategies else engine_decision.winning_strategy
            )

            # ==========================================
            # SCANNER RISK CHECK (replaces gatekeeper for scanner path)
            # Scanner relies on StrategyEngine quality + agreement gate.
            # Gatekeeper stays fully intact for Telegram signals in worker.py.
            # ==========================================
            
            # Volatility regime filter
            vol_regime = str(indicators_2m.get("volatility_regime", "normal")).lower()
            if vol_regime not in self.config.allowed_volatility:
                self._cycle_vol_rejected += 1
                return None

            # ── RSI Dead-Zone Filter (LEGACY — disabled by default) ──
            rsi_2m = float(indicators_2m.get("rsi", 50.0))
            if getattr(self.config, 'rsi_deadzone_enabled', False):
                rsi_low = getattr(self.config, 'rsi_deadzone_low', 40.0)
                rsi_high = getattr(self.config, 'rsi_deadzone_high', 65.0)
                if rsi_low <= rsi_2m <= rsi_high:
                    self._cycle_rsi_rejected += 1
                    return None

            # ══════════════════════════════════════════
            # SPRINT 1 HARD GATES (data-calibrated)
            # ══════════════════════════════════════════

            # ── Gate 1: RSI Extreme Block ──
            # DATA: RSI <30 = 43.9% WR, RSI >70 = 47.3% WR
            # Both are below breakeven (54.1%). The OTC engine mean-reverts at
            # extremes regardless of direction — chasing AND fading both lose.
            if getattr(self.config, 'rsi_extreme_block', True):
                rsi_low_limit = getattr(self.config, 'rsi_extreme_low', 30.0)
                rsi_high_limit = getattr(self.config, 'rsi_extreme_high', 70.0)
                if rsi_2m < rsi_low_limit or rsi_2m > rsi_high_limit:
                    self._cycle_rsi_extreme += 1
                    print(f"   [Filtered] {asset}: Passed Agreement but blocked by RSI Extreme ({rsi_2m:.1f})")
                    return None

            # ── Gate 2: Expansion Trap Block ──
            # DATA: Body expansion >1.5x previous = 35.5% WR (trap candles in OTC)
            # Slight shrink (0.5-1x) = 61.1% WR. Big candles = broker traps.
            if getattr(self.config, 'expansion_trap_block', True) and mtf_bundle.entry_tf and mtf_bundle.entry_tf.candles:
                candles_list = mtf_bundle.entry_tf.candles
                if len(candles_list) >= 2:
                    last_c = candles_list[-1]
                    prev_c = candles_list[-2]
                    last_body = abs(float(last_c.get('close', last_c.get('c', 0))) - float(last_c.get('open', last_c.get('o', 0))))
                    prev_body = abs(float(prev_c.get('close', prev_c.get('c', 0))) - float(prev_c.get('open', prev_c.get('o', 0))))
                    prev_candle_size = abs(float(prev_c.get('max', prev_c.get('h', 0))) - float(prev_c.get('min', prev_c.get('l', 0))))
                    
                    # DOJI GUARD: If previous candle has no body (<10% of total candle size),
                    # use total candle size or skip the check to avoid division-by-nearly-zero.
                    if prev_candle_size > 0 and (prev_body / prev_candle_size) < 0.10:
                        # Skip expansion check for Dojis - they are too small to be traps
                        is_expansion_trap = False
                    elif prev_body > 0 and (last_body / prev_body) > getattr(self.config, 'expansion_trap_max', 1.33):
                        is_expansion_trap = True
                    else:
                        is_expansion_trap = False
                    if is_expansion_trap:
                        self._cycle_expansion_trap += 1
                        print(f"   [Filtered] {asset}: Passed Agreement but blocked by Expansion Trap ({last_body/max(0.000001, prev_body):.2f}x)")
                        return None

            # ── Gate 2.5: Wick Magnet Lock (Sprint 2) ──
            # DATA: Wick > 40% of candle = 20.0% WR (Magnet effect)
            if getattr(self.config, 'wick_magnet_block', True) and mtf_bundle.entry_tf and mtf_bundle.entry_tf.candles:
                candles_list = mtf_bundle.entry_tf.candles
                if candles_list:
                    c = candles_list[-1]
                    total_size = abs(float(c.get('max', c.get('h', 0))) - float(c.get('min', c.get('l', 0))))
                    if total_size > 0:
                        # Find the wick in the trade direction
                        # For CALL, we care if the LOWER wick is long (rejection of downs)
                        # For PUT, we care if the UPPER wick is long (rejection of ups)
                        # Counter-intuitively, in binary/OTC these get "filled" rather than rejected.
                        if engine_decision.direction == "call":
                            rejection_wick = min(float(c.get('open', c.get('o', 0))), float(c.get('close', c.get('c', 0)))) - float(c.get('min', c.get('l', 0)))
                        else:
                            rejection_wick = float(c.get('max', c.get('h', 0))) - max(float(c.get('open', c.get('o', 0))), float(c.get('close', c.get('c', 0))))
                        
                        magnet_threshold = getattr(self.config, 'wick_magnet_max', 0.4)
                        if (rejection_wick / total_size) > magnet_threshold:
                            self._cycle_wick_magnet += 1
                            print(f"   [Filtered] {asset}: Passed Agreement but blocked by Wick Magnet ({rejection_wick/total_size:.2f})")
                            return None

            # ── Gate 3: Calm Confluence Gate (2m+5m alignment check) ──
            # DATA: Both 2m+5m aligned with direction = 58.7% WR (75 trades)
            # Only one aligned = 34.9% WR (43 trades) = DEATH ZONE
            # This replaces the old MTF exhaustion guard which incorrectly BLOCKED aligned signals.
            if getattr(self.config, 'calm_confluence_gate', True) and indicators_5m:
                trend_2m_str = str(indicators_2m.get("trend", "neutral")).lower()
                trend_5m_str = str(indicators_5m.get("trend", "neutral")).lower()
                trade_dir = engine_decision.direction

                # Map direction to expected trend
                expected_trend = "bullish" if trade_dir == "call" else "bearish"
                tf_2m_aligned = trend_2m_str == expected_trend
                tf_5m_aligned = trend_5m_str == expected_trend

                # If exactly one is aligned and the other is opposed (not neutral), block
                # This is the 34.9% death zone: one confirms, one disagrees
                tf_2m_opposed = trend_2m_str in ("bullish", "bearish") and not tf_2m_aligned
                tf_5m_opposed = trend_5m_str in ("bullish", "bearish") and not tf_5m_aligned

                if (tf_2m_aligned and tf_5m_opposed) or (tf_5m_aligned and tf_2m_opposed) or (not tf_2m_aligned and not tf_5m_aligned):
                    self._cycle_calm_confluence += 1
                    print(f"   [Filtered] {asset}: Passed Agreement but blocked by Calm Confluence (2m:{trend_2m_str}, 5m:{trend_5m_str})")
                    return None

            # ── Legacy MTF Exhaustion Guard (disabled by default) ──
            if getattr(self.config, 'mtf_exhaustion_guard', False) and indicators_5m:
                trend_2m_str = str(indicators_2m.get("trend", "neutral")).lower()
                trend_5m_str = str(indicators_5m.get("trend", "neutral")).lower()
                trade_dir = engine_decision.direction

                # Check full alignment: trade direction matches both timeframes
                is_aligned = False
                if trade_dir == "call" and trend_2m_str == "bullish" and trend_5m_str == "bullish":
                    is_aligned = True
                elif trade_dir == "put" and trend_2m_str == "bearish" and trend_5m_str == "bearish":
                    is_aligned = True

                if is_aligned:
                    # Only allow if 3+ strategies agree (strong independent conviction)
                    # or RSI is at a genuine extreme (<30 or >70 = room to run)
                    min_agree = self.config.min_agreement
                    has_strong_agreement = engine_decision.confluence_count >= min_agree + 1
                    rsi_extreme = rsi_2m < 35 or rsi_2m > 70
                    if not has_strong_agreement and not rsi_extreme:
                        print(f"   [Filtered] {asset}: Blocked by MTF Exhaustion Guard (Direction Aligned but weak agreement)")
                        self._cycle_mtf_exhaustion += 1
                        return None

            # Confidence threshold check
            if not engine_decision:
                return None
                
            if not use_mhi and engine_decision.confidence < self.config.confidence_min:
                print(f"   [Filtered] {asset}: Low confidence ({engine_decision.confidence:.2f} < {self.config.confidence_min})")
                self._cycle_conf_rejected += 1
                return None

            # ══════════════════════════════════════════
            # SPRINT 2: QUALITY OVERLAY (data-calibrated)
            # ══════════════════════════════════════════

            # ── Gate 4: Run-Length Cap ──
            # DATA: 4-candle run = 33.3% WR, 5-candle = 31.2%. Exhausted.
            # 3-candle sweet spot = 61.5%. Block if run already >= cap.
            run_cap = getattr(self.config, 'run_length_cap', 4)
            if run_cap > 0 and mtf_bundle.entry_tf and mtf_bundle.entry_tf.candles:
                run_len = self._count_directional_run(
                    mtf_bundle.entry_tf.candles, engine_decision.direction
                )
                if run_len >= run_cap:
                    print(f"   [Filtered] {asset}: Blocked by Run-Length Cap ({run_len} {engine_decision.direction.upper()} candles)")
                    self._cycle_run_exhaustion += 1
                    return None

            # ── Quality Score Overlay ──
            # Replace arbitrary strategy scores with data-proven factors.
            # Every point has a measured WR basis from 192 fingerprints.
            if getattr(self.config, 'quality_score_enabled', True):
                q_score, q_confidence, q_notes = self._calculate_quality_score(
                    direction=engine_decision.direction,
                    indicators_2m=indicators_2m,
                    indicators_5m=indicators_5m,
                    indicators_15m=indicators_15m,
                    candles=mtf_bundle.entry_tf.candles if mtf_bundle.entry_tf else [],
                    engine_score=engine_decision.score,
                    engine_confidence=engine_decision.confidence,
                )

                # Minimum quality score gate
                min_q = getattr(self.config, 'quality_min_score', 50)
                if q_score < min_q:
                    print(f"   [Filtered] {asset}: Low Quality Score ({q_score:.1f} < {min_q}). Notes: {q_notes}")
                    self._cycle_quality_rejected += 1
                    return None

                # Use quality-adjusted values
                signal_direction = engine_decision.direction
                signal_score = q_score
                signal_confidence = q_confidence
                signal_confluence = engine_decision.confluence_count
                signal_reason = f"Strategy: {engine_decision.winning_strategy}"
                signal_notes = engine_decision.reasons + engine_decision.warnings + q_notes
            else:
                # Quality scoring disabled — use raw engine values
                signal_direction = engine_decision.direction
                signal_score = engine_decision.score
                signal_confidence = engine_decision.confidence
                signal_confluence = engine_decision.confluence_count
                signal_reason = f"Strategy: {engine_decision.winning_strategy}"
                signal_notes = engine_decision.reasons + engine_decision.warnings

            # Tag regime routing info if active
            if detected_regime:
                regime_label = "📈 Trending" if detected_regime == 'trending' else "📊 Ranging"
                signal_notes.insert(0, f"Regime: {regime_label}")

            # Cooldown is set right after the gatekeeper accepts.

            # Set cooldown if signal generated
            self._set_cooldown(asset)
            
            # ==========================================
            # CHECK FOR PARKED MARTINGALE SERIES
            # ==========================================
            martingale_step = 0
            martingale_amount = None
            martingale_series_id = None
            
            # If martingale is enabled and we're waiting for pullbacks, check if this
            # validated signal matches any active series waiting for a trigger.
            # We inject the active series directly into the scanner using an attribute from `bot.py`
            if hasattr(self, 'active_martingale_series') and getattr(self, 'martingale_enabled', False):
                if getattr(self, 'martingale_wait_for_pullback', True):
                    series_dict = getattr(self, 'active_martingale_series', {})
                    for s_id, s_data in series_dict.items():
                        if s_data.get('asset') == asset and s_data.get('direction') == engine_decision.direction:
                            martingale_step = s_data.get('step', 0) + 1
                            max_steps = getattr(self, 'martingale_max_steps', 3)
                            if martingale_step <= max_steps:
                                multiplier = getattr(self, 'martingale_multiplier', 2.3)
                                martingale_amount = s_data.get('base_amount', 1.0) * (multiplier ** martingale_step)
                                martingale_series_id = s_id
                                print(f"   🔁 Found parked Martingale series for {asset}! Triggering Step {martingale_step}")
                            break

            # Build scanner signal
            return ScannerSignal(
                asset=self.data_provider.normalize_otc_asset(asset),
                direction=signal_direction,
                confidence=signal_confidence,
                score=signal_score,
                confluence=signal_confluence,
                risk_level="normal" if vol_regime in ("normal", "low") else "high",
                reason=signal_reason,
                notes=signal_notes,
                recommended_duration=duration,
                rsi=indicators_2m.get('rsi'),
                trend=indicators_2m.get('trend'),
                momentum=indicators_2m.get('momentum'),
                volatility_regime=indicators_2m.get('volatility_regime'),
                patterns=pattern_analysis.get('patterns', [])[:3],
                mtf_summary=self._format_mtf_trends(indicators_2m, indicators_5m, indicators_15m),
                indicators_2m=indicators_2m,
                indicators_5m=indicators_5m,
                indicators_15m=indicators_15m,
                candles=current_fingerprint.candles,
                martingale_step=martingale_step,
                martingale_amount=martingale_amount,
                martingale_series_id=martingale_series_id,
                use_mhi=use_mhi,
                mhi_strategy=getattr(self.config, 'scanner_strategy', 'mhi'),
                strategy_used='+'.join(engine_decision.agreeing_strategies) if engine_decision.agreeing_strategies else engine_decision.winning_strategy,
                # Sprint 4: Analytical metadata
                quality_score=q_score if getattr(self.config, 'quality_score_enabled', True) else None,
                regime=detected_regime,
            )

        except Exception as e:
            # Log errors instead of silently swallowing them
            import traceback
            print(f"   ⚠️ Scanner analysis error for asset: {e}")
            traceback.print_exc()
            return None

    # ==========================================
    # SPRINT 2: QUALITY SCORING + HELPERS
    # ==========================================

    def _count_directional_run(self, candles: list, direction: str) -> int:
        """
        Count how many consecutive candles at the END of the series
        match the given direction (call=bullish, put=bearish).

        Returns 0 if the last candle doesn't match.
        Used to detect exhausted 4+ candle runs (33% WR).
        """
        if not candles or len(candles) < 2:
            return 0

        count = 0
        for c in reversed(candles):
            o = float(c.get('open', c.get('o', 0)))
            cl = float(c.get('close', c.get('c', 0)))
            if direction == "call" and cl > o:
                count += 1
            elif direction == "put" and cl < o:
                count += 1
            else:
                break  # Run broken

        return count

    def _calculate_quality_score(
        self,
        direction: str,
        indicators_2m: dict,
        indicators_5m: Optional[dict],
        indicators_15m: Optional[dict],
        candles: list,
        engine_score: float,
        engine_confidence: float,
    ) -> tuple:
        """
        Sprint 2: Data-calibrated quality scoring overlay.

        Replaces the strategy engine's arbitrary score with points
        derived from 192 fingerprinted trades. Every factor has a
        measured win-rate basis.

        Returns:
            (quality_score: int, adjusted_confidence: float, quality_notes: list)
        """
        score = 0
        notes = []
        confidence = engine_confidence

        trade_dir = direction
        expected_trend = "bullish" if trade_dir == "call" else "bearish"

        # ── Factor 1: 2m trend aligned (+25) ──
        # Part of the 58.7% aligned filter (75 trades)
        trend_2m = str(indicators_2m.get("trend", "neutral")).lower()
        if trend_2m == expected_trend:
            score += 25
        elif trend_2m == "neutral":
            score += 10  # Neutral is not opposition — partial credit

        # ── Factor 2: 5m trend aligned (+25) ──
        trend_5m = "neutral"
        if indicators_5m:
            trend_5m = str(indicators_5m.get("trend", "neutral")).lower()
        if trend_5m == expected_trend:
            score += 25
        elif trend_5m == "neutral":
            score += 10

        # ── Factor 3: RSI in calm zone 30-70 (+15) ──
        # 79.2% WR when combined with 2m+5m alignment
        rsi = float(indicators_2m.get("rsi", 50.0))
        if 30 <= rsi <= 70:
            score += 15
            # Full Calm Confluence: 2m+5m aligned + RSI calm = the 79.2% composite
            if trend_2m == expected_trend and trend_5m == expected_trend:
                notes.append("🎯 Calm Confluence (79% zone)")
                confidence = min(1.0, confidence + 0.10)  # Boost confidence by 10pp

        # ── Factor 4: 15m trend aligned (+10) ──
        # 78.6% for full PUT alignment, 58.3% for full CALL
        trend_15m = "neutral"
        if indicators_15m:
            trend_15m = str(indicators_15m.get("trend", "neutral")).lower()
        if trend_15m == expected_trend:
            score += 10
            # Full 3-TF alignment noted
            if trend_2m == expected_trend and trend_5m == expected_trend:
                notes.append("📊 Full 3-TF alignment")

        # ── Factor 5: PUT Gravity Bias (+15) ──
        # DATA: put|bearish/bearish/bearish = 78.6% vs call|bullish/.../bullish = 58.3%
        # Downward trends are cleaner in OTC microstructure.
        if getattr(self.config, 'put_boost_enabled', True):
            if trade_dir == "put" and trend_2m == "bearish" and trend_5m == "bearish" and trend_15m == "bearish":
                score += 15
                notes.append("🐻 Gravity Bias: Bearish Triple-Alignment (+15)")

        # ── Factor 6: 3-candle run sweet spot (+10) ──
        # 3 candles with direction = 61.5% WR. 1-2 = too early. 4+ = exhausted.
        if candles:
            run_len = self._count_directional_run(candles, trade_dir)
            if run_len == 3:
                score += 10
                notes.append(f"⚡ 3-candle momentum sweet spot")
            elif run_len >= 2:
                score += 5  # 2 candles = decent but not optimal

        # ── Factor 7: Body expansion < 1.5x (+5) ──
        # Slight shrink = 61.1% vs strong expansion = 35.5%
        if candles and len(candles) >= 2:
            last_c = candles[-1]
            prev_c = candles[-2]
            last_body = abs(float(last_c.get('close', last_c.get('c', 0))) - float(last_c.get('open', last_c.get('o', 0))))
            prev_body = abs(float(prev_c.get('close', prev_c.get('c', 0))) - float(prev_c.get('open', prev_c.get('o', 0))))
            if prev_body > 0:
                ratio = last_body / prev_body
                if ratio <= 1.0:
                    score += 5  # Steady state — ideal
                    notes.append("🧘 Steady candle (no expansion)")

        # ── Factor 8: Stochastic tiebreaker (+5/-5) ──
        # K>D + CALL = 60.0%, K<D + PUT = 56.0%
        if getattr(self.config, 'stoch_tiebreaker', True):
            stoch_k = float(indicators_2m.get("stoch_k", 50.0))
            stoch_d = float(indicators_2m.get("stoch_d", 50.0))
            if trade_dir == "call" and stoch_k > stoch_d:
                score += 5
            elif trade_dir == "put" and stoch_k < stoch_d:
                score += 5
            elif trade_dir == "call" and stoch_k < stoch_d:
                score -= 5  # Counter-momentum penalty
            elif trade_dir == "put" and stoch_k > stoch_d:
                score -= 5

        # ── Confidence downgrade for weak alignment ──
        # If 2m is neutral (not aligned, not opposed) — the signal is speculative
        if trend_2m != expected_trend:
            confidence = max(0.50, confidence - 0.08)
            notes.append("⚠️ 2m not aligned — reduced confidence")

        return (score, confidence, notes)

    def _select_duration(
        self,
        confidence: float,
        confluence: int,
        mtf_5m_aligned: bool,
        mtf_15m_aligned: bool,
        score: float,
        volatility_regime: str = "normal",
        indicators_2m: Optional[Dict] = None,
        use_mhi: bool = False
    ) -> int:
        """Select optimal trade duration dynamically."""
        if not self.config.dynamic_timeframe:
            return self.config.fixed_duration

        if use_mhi:
            return 2  # Standard for MHI

        duration = self.config.fixed_duration

        # 1. Volatility Adjustments
        if volatility_regime in ("high", "extreme"):
            duration += 1  # Need more time to absorb erratic spikes
            
        # 2. Confluence Adjustments
        base_confluence = getattr(self.config, 'min_confluence', 3)
        if confluence > base_confluence and confidence > 0.85:
            duration -= 1  # High conviction -> faster realization
            
        # 3. Macro Alignment Adjustments
        if not mtf_5m_aligned:
            duration += 1  # Fighting micro-trend -> need time to turn

        # Bound the duration
        return max(self.config.min_duration, min(self.config.max_duration, duration))




    # ==========================================
    # COOLDOWN MANAGEMENT
    # ==========================================

    def _is_on_cooldown(self, asset: str) -> bool:
        """Check if asset or its base variant is on cooldown."""
        now = time.time()
        cutoff = self.config.cooldown_per_asset
        
        # 1. Check specific asset
        if (now - self.asset_cooldowns.get(asset.upper(), 0)) < cutoff:
            return True
            
        # 2. Check base variant (e.g. "GBPUSD" for "GBPUSD-OTC")
        base = asset.upper().replace("-OTC", "").replace("-OP", "").strip()
        if base and base != asset.upper():
            if (now - self.asset_cooldowns.get(base, 0)) < cutoff:
                return True
                
        return False

    def _set_cooldown(self, asset: str):
        """Set cooldown for an asset and its base variant."""
        now = time.time()
        
        # 1. Set for specific asset
        self.asset_cooldowns[asset.upper()] = now
        
        # 2. Set for base variant
        base = asset.upper().replace("-OTC", "").replace("-OP", "").strip()
        if base and base != asset.upper():
            self.asset_cooldowns[base] = now

    def _cleanup_cooldowns(self):
        """Remove expired cooldowns."""
        now = time.time()
        expired = [
            asset for asset, ts in self.asset_cooldowns.items()
            if (now - ts) > self.config.cooldown_per_asset
        ]
        for asset in expired:
            del self.asset_cooldowns[asset]

    def clear_cooldowns(self):
        """Clear all cooldowns (manual reset)."""
        self.asset_cooldowns.clear()
        print("🔍 Scanner cooldowns cleared")

    def _is_market_stagnant(self, candles: List[dict], period: int = 5) -> bool:
        """Check if the last N candles have identical close prices (stale feed)."""
        if not candles or len(candles) < period:
            return False
        
        last_closes = [c.get('c', c.get('close', 0)) for c in candles[-period:]]
        # Ignore zero prices (no data)
        if any(v == 0 for v in last_closes):
            return False
            
        return all(x == last_closes[0] for x in last_closes)
