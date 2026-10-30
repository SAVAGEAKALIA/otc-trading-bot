import sys
import os
from datetime import datetime

# Add the project directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from trading_platform.legacy.iqoption_bot.strategy_engine import StrategyEngine
from trading_platform.legacy.iqoption_bot.strategies.indicator_strategy import IndicatorStrategy
from trading_platform.legacy.iqoption_bot.strategies.mhi_strategy import MHIStrategy
from trading_platform.legacy.iqoption_bot.strategies.ccv2_strategy import CCV2Strategy
from trading_platform.legacy.iqoption_bot.strategies.adaptive_strategy import AdaptiveStrategy
from trading_platform.legacy.iqoption_bot.backtest_engine import BacktestEngine

def run_suite():
    print("🚀 Starting Strategy Backtest Suite...")
    
    # 1. Setup Engine
    engine = StrategyEngine(conflict_mode="veto")
    engine.register(IndicatorStrategy(), weight=1.2)
    engine.register(MHIStrategy(), weight=1.0)
    engine.register(CCV2Strategy(), weight=0.8)
    engine.register(AdaptiveStrategy(), weight=0.7)
    
    # 2. Setup Backtest
    # Path is relative to project root
    bt = BacktestEngine(fingerprint_path="data/fingerprints.json")
    if not bt.fingerprints:
         # Try alternative path
         bt = BacktestEngine(fingerprint_path="fingerprints.json")
    
    if not bt.fingerprints:
        print("❌ Error: No fingerprints found. Backtest cannot proceed.")
        return

    print(f"📊 Analyzing {len(bt.fingerprints)} historical trades...")

    # 3. Re-evaluate Indicators (Baseline)
    print("\n[1/3] Evaluating Modified Indicators Strategy...")
    res_ind = bt.reevaluate(engine, strategy_type='indicators')
    print(res_ind.summary())

    # 4. Re-evaluate Hybrid (Weighted Multi-Strategy)
    # Note: CCV2/Adaptive will likely be neutral due to missing candles
    print("\n[2/3] Evaluating Hybrid Strategy (Multi-Strategy Veto)...")
    res_hybrid = bt.reevaluate(engine, strategy_type='hybrid')
    print(res_hybrid.summary())

    # 5. Comparing performance
    print("\n═══ Final Comparison ═══")
    print(f"Indicator Strategy: {res_ind.win_rate:.1%} ({res_ind.total_trades} trades)")
    print(f"Hybrid Strategy:    {res_hybrid.win_rate:.1%} ({res_hybrid.total_trades} trades)")
    
    print("\n💡 Note: Hybrid strategy is more selective (fewer trades) but aims for higher precision.")
    print("💡 Note: Adaptive and CCV2 results are limited by lack of candle history in fingerprints.json.")

if __name__ == "__main__":
    run_suite()
