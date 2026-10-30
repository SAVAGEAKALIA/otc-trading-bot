
import json
import os
import sys
from datetime import datetime
from collections import defaultdict

# Mocking the dependency structure to run the backtest
class MockDecision:
    def __init__(self, score, confidence):
        self.score = score
        self.confidence = confidence
        self.notes = []

class BacktestMartingaleReanalyzer:
    def __init__(self, fingerprints_path="fingerprints.json"):
        with open(fingerprints_path, 'r') as f:
            self.fingerprints = json.load(f)
        
        # Sort by time
        self.fingerprints.sort(key=lambda x: x.get('action_time', 0))
        
        self.results = {
            "total_recovery_steps": 0,
            "originally_won": 0,
            "originally_lost": 0,
            "smart_rejects": 0,
            "smart_flips": 0,
            "saved_by_reject": 0, # Was a loss, but we would have rejected
            "saved_by_flip": 0,   # Was a loss, but we would have flipped and won
            "flipped_to_loss": 0,  # Was a win, but we flipped and lost
            "rejected_a_win": 0,   # Was a win, but we rejected it
        }

    def simulate(self):
        assets = defaultdict(list)
        for fp in self.fingerprints:
            assets[fp['asset']].append(fp)
            
        for asset_name, trades in assets.items():
            for i in range(len(trades) - 1):
                current = trades[i]
                next_trade = trades[i+1]
                
                # Check if next_trade is a Martingale step
                time_diff = next_trade['action_time'] - current['action_time']
                
                # Loose definition: same asset, same direction, within 5 minutes after a loss
                if current['result'] in ('lose', 'loss') and \
                   next_trade['direction'] == current['direction'] and \
                   time_diff < 300: # 5 minutes
                    
                    self.results["total_recovery_steps"] += 1
                    if next_trade['result'] in ('win', 'win'):
                        self.results["originally_won"] += 1
                    else:
                        self.results["originally_lost"] += 1
                        
                    # Evaluate using Smart Logic
                    decision = self.evaluate_smart(next_trade)
                    
                    if decision == "reject":
                        self.results["smart_rejects"] += 1
                        if next_trade['result'] != 'win':
                            self.results["saved_by_reject"] += 1
                        else:
                            self.results["rejected_a_win"] += 1
                            
                    elif decision == "flip":
                        self.results["smart_flips"] += 1
                        # If it was a loss, flipping makes it a win (assuming binary outcome)
                        if next_trade['result'] != 'win':
                            self.results["saved_by_flip"] += 1
                        else:
                            self.results["flipped_to_loss"] += 1

    def evaluate_smart(self, fp):
        """
        Mimics SignalReAnalyzer.analyze logic using fingerprint data.
        """
        score = fp.get('score', 0)
        trend_15m = fp.get('trend_15m', 'neutral')
        direction = fp.get('direction', 'call')
        
        # 1. Flip Logic (min_score_to_flip = 30)
        is_call = direction == 'call'
        strong_trend_against = False
        if is_call and trend_15m == 'bearish': strong_trend_against = True
        if not is_call and trend_15m == 'bullish': strong_trend_against = True
        
        if strong_trend_against and abs(score) < 30:
            return "flip"
            
        # 2. Reject Logic (NEW: Only reject if score is EXPLICITLY negative)
        # This keeps neutral (0.0) trades as requested "not to reject wins"
        if score < 0:
            return "reject"
            
        return "keep"

    def analyze_thresholds(self):
        print("\n--- Sensitivity Analysis: Rejection Threshold ---")
        print(f"{'Threshold':<10} | {'Net Saved':<10} | {'Missed Wins':<12} | {'Saved Losses':<12}")
        print("-" * 50)
        
        for thresh in [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0]:
            net_saved = 0
            missed_wins = 0
            saved_losses = 0
            
            assets = defaultdict(list)
            for fp in self.fingerprints:
                assets[fp['asset']].append(fp)
                
            for asset, trades in assets.items():
                for i in range(len(trades) - 1):
                    current = trades[i]
                    next_trade = trades[i+1]
                    time_diff = next_trade['action_time'] - current['action_time']
                    
                    if current['result'] in ('lose', 'loss') and \
                       next_trade['direction'] == current['direction'] and \
                       time_diff < 300:
                        
                        score = next_trade.get('score', 0)
                        # Rejection check only (ignore flips for this specific analysis)
                        if abs(score) < thresh:
                            if next_trade['result'] == 'win':
                                missed_wins += 1
                                net_saved -= 1
                            else:
                                saved_losses += 1
                                net_saved += 1
            
            print(f"{thresh:<10.1f} | {net_saved:<10d} | {missed_wins:<12d} | {saved_losses:<12d}")

    def detect_death_spirals(self):
        assets = defaultdict(list)
        for fp in self.fingerprints:
            assets[fp['asset']].append(fp)
            
        spirals_found = 0
        saved_spirals = 0
        
        print("\n--- Death Spiral Analysis (3+ Loss Sequences) ---")
        for asset, trades in assets.items():
            loss_streak = 0
            for i in range(len(trades)):
                if trades[i]['result'] in ('lose', 'loss'):
                    loss_streak += 1
                    if loss_streak >= 3:
                        spirals_found += 1
                        # Check if Smart Logic would have broken the streak at trade i-1 or trade i
                        decision_2 = self.evaluate_smart(trades[i-1])
                        decision_3 = self.evaluate_smart(trades[i])
                        
                        if decision_2 in ("reject", "flip") or decision_3 in ("reject", "flip"):
                            saved_spirals += 1
                            print(f"🚨 Spiral Avoided: {asset} at {datetime.fromtimestamp(trades[i]['action_time'])}")
                else:
                    loss_streak = 0
        
        print(f"\nTotal Death Spirals Found: {spirals_found}")
        print(f"Total Death Spirals Avoided: {saved_spirals}")

    def report(self):
        print(f"═══ Martingale Smart Reanalyzer Backtest (Negative-Only Policy) ═══")
        print(f"Total Martingale Steps Identified: {self.results['total_recovery_steps']}")
        print(f"Original Performance: {self.results['originally_won']} Wins, {self.results['originally_lost']} Losses")
        print(f"Original Win Rate: {self.results['originally_won'] / self.results['total_recovery_steps']:.1%}" if self.results['total_recovery_steps'] > 0 else "N/A")
        print(f"\n--- Smart Impact ---")
        print(f"Total Rejects: {self.results['smart_rejects']}")
        print(f"Total Flips: {self.results['smart_flips']}")
        print(f"\nSaved from loss (Reject): {self.results['saved_by_reject']}")
        print(f"Saved from loss (Flip): {self.results['saved_by_flip']}")
        print(f"Missed wins (Rejected): {self.results['rejected_a_win']}")
        print(f"Flipped to loss: {self.results['flipped_to_loss']}")
        
        net_saved = self.results['saved_by_reject'] + self.results['saved_by_flip'] - self.results['rejected_a_win'] - self.results['flipped_to_loss']
        print(f"\nNET LOSSES AVOIDED: {net_saved}")
        
        # Hypothetical New Stats
        new_wins = self.results['originally_won'] - self.results['rejected_a_win'] - self.results['flipped_to_loss'] + self.results['saved_by_flip']
        new_total = self.results['total_recovery_steps'] - self.results['smart_rejects']
        
        if new_total > 0:
            print(f"New Recovery Win Rate: {new_wins / new_total:.1%}")
        print(f"═══ ═══ ═══ ═══ ═══ ═══ ═══ ═══ ═══ ═══")

if __name__ == "__main__":
    tester = BacktestMartingaleReanalyzer()
    tester.simulate()
    tester.report()
    tester.detect_death_spirals()
    tester.analyze_thresholds()
