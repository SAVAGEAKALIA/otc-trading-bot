# iqoption_bot/simulate_strategy_changes.py

import sys
from typing import Dict, Any, List

# Add path to ensure we can import
sys.path.append(".")

from analytics import SignalGatekeeper, MarketAnalyzer

def run_simulation():
    print("--- 🔬 STRATEGY DRY RUN (Using ACTUAL Gatekeeper Logic) ---")
    
    # Initialize the REAL gatekeeper (Normal Mode)
    gatekeeper = SignalGatekeeper(mode="normal")
    analyzer = MarketAnalyzer()  # initialized with default weights
    
    # Enforce Fibonacci Enabled
    analyzer.set_fibonacci_mode(True)

    scenarios = [
        # 1. CLASSIC TREND FOLLOW
        {
            "name": "✅ Strong Bullish Trend (Ideal)",
            "indicators": {
                "rsi": 60, "adx": 35, "trend": "bullish", "trend_strength": "strong",
                "volatility_regime": "normal", "momentum": 5.0,
                "bb_position": 0.8, "stoch_k": 70, "stoch_d": 65,
                "macd_histogram": 0.5, "body_ratio": 0.6
            },
            "direction": "call"
        },
        # 2. MOMENTUM CONFLICT
        {
            "name": "⚠️ Trend UP but Momentum DOWN (Lag Protection)",
            "indicators": {
                "rsi": 55, "adx": 15, "trend": "bullish", "trend_strength": "weak",
                "volatility_regime": "normal", "momentum": -2.0, # Divergence!
                "macd_histogram": -0.1, "body_ratio": 0.4
            },
            "direction": "call"
        },
        # 3. DEAD MARKET
        {
            "name": "⛔ Dead Market Squeeze",
            "indicators": {
                "rsi": 50, "adx": 8, "trend": "neutral", 
                "volatility_regime": "low", "bb_width_pct": 0.02, # Too tight
                "body_ratio": 0.05
            },
            "direction": "call"
        },
        # 4. REVERSAL SNIPER
        {
            "name": "🎯 Reversal Sniper (RSI Extreme)",
            "indicators": {
                "rsi": 15, "adx": 20, "trend": "bearish", 
                "volatility_regime": "normal", "momentum": -10.0,
                "bb_position": -0.1, # Below lower band
                "stoch_k": 5, "stoch_d": 8
            },
            "direction": "call" # Betting against the drop
        },
        # 5. DANGEROUS REVERSAL
        {
            "name": "💀 Dangerous Reversal (Fighting Strong Trend)",
            "indicators": {
                "rsi": 28, "adx": 55, "trend": "bearish", "trend_strength": "strong_bearish",
                "volatility_regime": "high", "momentum": -15.0, # Crashing
                "bb_position": 0.0,
            },
            "direction": "call"
        }
    ]

    for scen in scenarios:
        print(f"\n📄 Scenario: {scen['name']}")
        direction = scen['direction']
        
        # Calculate full score using the REAL analyzer logic
        # We need to mock 'indicators' to match what MarketAnalyzer expects slightly? 
        # Actually SignalGatekeeper.decide() calls analyzer.calculate_signal_score internally?
        # No, decide() TAKES indicators. It calls analyzer.calculate_signal_score inside.
        
        decision = gatekeeper.decide(
            analyzer, 
            scen['indicators'], 
            requested_direction=direction
        )
        
        # Output results
        status = "✅ ACCEPT" if decision.accept else "⛔ REJECT"
        print(f"👉 Decision: {status}")
        print(f"   Score: {decision.score:.1f} | Conf: {decision.confidence:.0%}")
        print(f"   Reason: {decision.reason}")
        if decision.notes:
            print(f"   Notes: {', '.join(decision.notes[:3])}")

if __name__ == "__main__":
    run_simulation()
