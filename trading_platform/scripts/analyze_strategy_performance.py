import json
import os
from collections import defaultdict

def analyze_trade_logs(filepath="trade_log.json"):
    if not os.path.exists(filepath):
        print(f"❌ Error: {filepath} not found.")
        return

    with open(filepath, 'r') as f:
        trades = json.load(f)

    print(f"📊 Analyzing {len(trades)} historical trades from logs...")
    
    strategies = {
        "MHI": ["MHI"],
        "Majority": ["Majority"],
        "R7": ["R7"],
        "Indicators": ["Indicator", "Score", "Trend"],
        "Adaptive": ["Adaptive", "Kaufman"],
        "CCV2": ["CCV2", "Consecutive", "streak"]
    }
    
    stats = {}
    for name in strategies:
        stats[name] = {"total": 0, "wins": 0, "losses": 0, "ties": 0}

    for t in trades:
        reasoning = t.get("reasoning", "").lower()
        result = t.get("result", "unknown")
        
        # Determine which strategy/strategies were involved
        involved = []
        for name, keywords in strategies.items():
            if any(k.lower() in reasoning for k in keywords):
                involved.append(name)
        
        # If no specific recognized pattern, it's likely standard Indicators if it has a "score"
        if not involved and ("score" in reasoning or "confluence" in reasoning):
            involved.append("Indicators")
            
        for name in involved:
            stats[name]["total"] += 1
            if result == "win":
                stats[name]["wins"] += 1
            elif result == "loss" or result == "lose":
                stats[name]["losses"] += 1
            elif result == "tie":
                stats[name]["ties"] += 1

    print("\n═══ Strategy Performance (Historical Logs) ═══")
    print(f"{'Strategy':<12} | {'Trades':<6} | {'Win Rate':<8} | {'Outcome'}")
    print("-" * 45)
    
    for name, s in stats.items():
        if s["total"] == 0:
            continue
        decided = s["wins"] + s["losses"]
        wr = s["wins"] / decided if decided > 0 else 0
        print(f"{name:<12} | {s['total']:<6} | {wr:>7.1%} | W:{s['wins']} L:{s['losses']} T:{s['ties']}")

    print("\n💡 Note: Indicators are involved in almost all trades as a base filter.")
    print("💡 Note: Adaptive and CCV2 may show 0 if they haven't been active in logs yet.")

if __name__ == "__main__":
    analyze_trade_logs("trade_log.json")
