import json
import os

def verify_v2_logic():
    path = "/home/saviour/PycharmProjects/I2/IQoption/fingerprints.json"
    if not os.path.exists(path):
        path = "fingerprints.json"
        
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error: {e}")
        return

    def get_wr(subset):
        w = [r for r in subset if r.get('result') == 'win']
        l = [r for r in subset if r.get('result') == 'lose']
        t = len(w) + len(l)
        if t == 0: return "0% (0 trades)"
        return f"{len(w)/t*100:.1f}% ({t} trades)"

    print("=== V2 MATH VERIFICATION (HISTORICAL AUDIT) ===")
    
    baseline = [r for r in data if r.get('result') in ('win', 'lose')]
    print(f"Baseline WR: {get_wr(baseline)}")

    v2_subset = []
    rejections = {"rsi": 0, "expansion": 0, "wick": 0, "alignment": 0}
    
    for r in data:
        if r.get('result') not in ('win', 'lose'): continue
        
        # 1. RSI 30-70
        rsi = float(r.get('rsi', 50))
        if rsi < 30 or rsi > 70:
            rejections["rsi"] += 1
            continue
            
        # 2. Expansion Veto (1.2x)
        candles = r.get('candles', [])
        if candles and len(candles) >= 2:
            last = candles[-1]
            prev = candles[-2]
            last_body = abs(last['c'] - last['o'])
            prev_body = abs(prev['c'] - prev['o'])
            if prev_body > 0 and (last_body / prev_body) > 1.2:
                rejections["expansion"] += 1
                continue
                
        # 3. Wick Magnet Lock (0.4x)
        if candles:
            c = candles[-1]
            high, low = c['h'], c['l']
            total = high - low
            if total > 0:
                if r['direction'] == 'call':
                    wick = min(c['o'], c['c']) - low
                else:
                    wick = high - max(c['o'], c['c'])
                
                if (wick / total) > 0.4:
                    rejections["wick"] += 1
                    continue
                    
        # 4. Mandatory Alignment (2m+5m)
        dir = r['direction']
        expected = 'bullish' if dir == 'call' else 'bearish'
        t2 = r.get('trend_2m', 'neutral')
        t5 = r.get('trend_5m', 'neutral')
        
        # Must have at least one aligned and ZERO conflicts
        # (Actually implementation in scanner/gatekeeper is even stricter now)
        is_aligned = (t2 == expected and t5 == expected)
        if not is_aligned:
            rejections["alignment"] += 1
            continue
            
        v2_subset.append(r)

    print("\n--- Rejection Breakdown ---")
    for k, v in rejections.items():
        print(f"{k.upper()}: {v} trades blocked")
        
    print("\n--- Final V2 Results ---")
    print(f"V2 Predicted WR: {get_wr(v2_subset)}")
    
    wins = [r for r in v2_subset if r.get('result') == 'win']
    if len(v2_subset) > 0 and (len(wins) / len(v2_subset)) >= 0.6:
        print("\n✅ SUCCESS: Win rate exceeds 60% goal.")
    else:
        print("\n❌ FAILURE: Goal not met.")

if __name__ == "__main__":
    verify_v2_logic()
