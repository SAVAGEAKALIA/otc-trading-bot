import sys
import os
import time

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_platform.legacy.iqoption_bot.strategies.mhi_strategy import MHIStrategy

def test_mhi_dynamic_veto():
    strategy = MHIStrategy(variant='mhi')
    
    # Mock candle data (Minority Green, Majority Red -> CALL signal)
    candles = [
        {'close': 1.1, 'open': 1.0, 'from': int(time.time()) - 480}, # Green
        {'close': 0.9, 'open': 1.0, 'from': int(time.time()) - 360}, # Red
        {'close': 0.9, 'open': 1.0, 'from': int(time.time()) - 240}, # Red
    ]
    
    # Common kwargs
    base_kwargs = {
        'direction': 'call',
        'profile': 'trend',
        'indicators_2m': {
            'rsi': 30.0, # Oversold bonus
            'candle_open': 0.9,
            'candle_close': 1.1,
            'avg_body_ratio': 0.7,
        }
    }

    print("\n=== TESTING MHI DYNAMIC VETO ===")

    # Scenario 1: Conflict with Strong Trend (ADX 30)
    print("\nScenario 1: Conflict with Strong 15m Trend (ADX 30)")
    indicators_5m = {'trend': 'bearish', 'adx': 30.0}
    res = strategy.analyze(candles, indicators_5m=indicators_5m, **base_kwargs)
    print(f"Warnings: {res.warnings}")
    print(f"Confidence: {res.confidence:.2f}")
    assert not res.should_trade
    assert any("strong 5m" in w for w in res.warnings)

    # Scenario 2: Conflict with Moderate Trend (ADX 20)
    print("\nScenario 2: Conflict with Moderate 15m Trend (ADX 20)")
    indicators_5m = {'trend': 'bearish', 'adx': 20.0}
    res = strategy.analyze(candles, indicators_5m=indicators_5m, **base_kwargs)
    print(f"Warnings: {res.warnings}")
    print(f"Confidence: {res.confidence:.2f}")
    assert any("-20 pts" in w for w in res.warnings)
    assert not res.should_trade

    # Scenario 3: Conflict with Weak Trend (ADX 15)
    print("\nScenario 3: Conflict with Weak 15m Trend (ADX 15)")
    indicators_5m = {'trend': 'bearish', 'adx': 15.0}
    res = strategy.analyze(candles, indicators_5m=indicators_5m, **base_kwargs)
    print(f"Reasons: {res.reasons}")
    print(f"Confidence: {res.confidence:.2f}")
    assert any("Trend Veto Bypassed" in r for r in res.reasons)

    # Scenario 4: Align with Trend
    print("\nScenario 4: Aligned with 15m Trend")
    indicators_5m = {'trend': 'bullish', 'adx': 30.0}
    res = strategy.analyze(candles, indicators_5m=indicators_5m, **base_kwargs)
    print(f"Reasons: {res.reasons}")
    print(f"Confidence: {res.confidence:.2f}")
    assert any("Trend Alignment" in r for r in res.reasons)

    print("\n✅ ALL MHI DYNAMIC VETO TESTS PASSED")

if __name__ == "__main__":
    try:
        test_mhi_dynamic_veto()
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
