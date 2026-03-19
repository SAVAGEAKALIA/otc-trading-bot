import json
import statistics
from collections import defaultdict
import datetime
import math

# Load and deduplicate
with open('fingerprints.json', 'r') as f:
    data = json.load(f)

# Deduplicate by asset, direction, and roughly the same action time (within 1 minute)
unique_trades = []
seen = set()
for t in data:
    rounded_time = round(t['action_time'] / 60) * 60
    key = f"{t['asset']}_{t['direction']}_{rounded_time}"
    if key not in seen:
        seen.add(key)
        unique_trades.append(t)

print(f"Total Raw Logs: {len(data)}")
print(f"Total Unique Trades: {len(unique_trades)}")
print(f"Duplication factor: {len(data) / len(unique_trades):.1f}x")

# --- 1. Score Analysis ---
score_buckets = defaultdict(lambda: {'win': 0, 'loss': 0, 'tie': 0})
for t in unique_trades:
    score = abs(t['score'])
    bucket = round(score / 10) * 10
    res = 'loss' if t['result'] == 'lose' else t['result']
    score_buckets[bucket][res] += 1

print("\n--- Score Analysis ---")
for b in sorted(score_buckets.keys()):
    stats = score_buckets[b]
    total = sum(stats.values())
    wins = stats['win']
    win_rate = (wins / total) * 100 if total > 0 else 0
    print(f"Score ~{b}: {total} trades | Win: {wins}, Loss: {stats['loss']}, Tie: {stats['tie']} | Win Rate: {win_rate:.1f}%")

# --- 2. Score 0 trades ---
score_0 = [t for t in unique_trades if abs(t['score']) < 1]
print(f"\n--- Score 0.0 Trades ---")
print(f"Total: {len(score_0)}")
if len(score_0) > 0:
    wins = sum(1 for t in score_0 if t['result'] == 'win')
    print(f"Win Rate: {(wins / len(score_0)) * 100:.1f}%")

# --- 3. High Volatility + High Score ---
high_vol = [t for t in unique_trades if t['volatility'] == 'high' and abs(t['score']) >= 75]
print(f"\n--- High Volatility + High Score (>75) ---")
print(f"Total: {len(high_vol)}")
if len(high_vol) > 0:
    wins = sum(1 for t in high_vol if t['result'] == 'win')
    loss = sum(1 for t in high_vol if t['result'] in ('lose', 'loss'))
    print(f"Win Rate: {(wins / len(high_vol)) * 100:.1f}%")
    print(f"Win: {wins}, Loss: {loss}")

# --- 4. Weak MTF Alignment ---
neutral_15m = [t for t in unique_trades if t['trend_15m'] == 'neutral']
aligned_15m = [t for t in unique_trades if t['trend_15m'] != 'neutral']

print("\n--- MTF Alignment Impact ---")
if neutral_15m:
    wins = sum(1 for t in neutral_15m if t['result'] == 'win')
    print(f"Trend 15m Neutral: {len(neutral_15m)} trades, Win Rate: {(wins / len(neutral_15m)) * 100:.1f}%")
if aligned_15m:
    wins = sum(1 for t in aligned_15m if t['result'] == 'win')
    print(f"Trend 15m Aligned/Opposed: {len(aligned_15m)} trades, Win Rate: {(wins / len(aligned_15m)) * 100:.1f}%")
    
# --- 5. RSI and Stochastic Optimization ---
rsi_buckets = defaultdict(lambda: {'win': 0, 'loss': 0, 'tie': 0})
for t in unique_trades:
    rsi = t['rsi']
    bucket = round(rsi / 10) * 10
    res = 'loss' if t['result'] == 'lose' else t['result']
    rsi_buckets[bucket][res] += 1

print("\n--- RSI Analysis ---")
for b in sorted(rsi_buckets.keys()):
    stats = rsi_buckets[b]
    total = sum(stats.values())
    if total > 0:
        wins = stats['win']
        win_rate = (wins / total) * 100
        print(f"RSI ~{b}: {total} trades, Win Rate: {win_rate:.1f}%")
