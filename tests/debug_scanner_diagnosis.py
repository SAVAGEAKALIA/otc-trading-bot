import asyncio
import time
import logging
from datetime import datetime

# Set up logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Mock objects to simulate the bot environment
class MockAPI:
    def get_candles(self, asset, timeframe, count, now):
        # Simulate returning a candle with a timestamp
        # adapting this to what the real API returns (simplified)
        current_time = int(time.time())
        # Return 50 candles, ending near 'now'
        candles = []
        for i in range(count):
            t = current_time - (timeframe * (count - i))
            candles.append({
                'id': i,
                'from': t,
                'at': t * 1000000000, # IQ Option sometimes uses nanoseconds? or seconds?
                # Usually it's seconds 'at': timestamp
                'at': t, # Assuming seconds for this test, we will see
                'to': t + timeframe,
                'open': 1.0, 'close': 1.0, 'min': 0.9, 'max': 1.1, 'volume': 100
            })
        return candles

    def get_all_open_time(self):
         return {'turbo': {'EURUSD-OTC': {'open': True}}}

# Import the actual classes (assuming they are in the python path or same dir)
import sys
import os

# Add the project root to path so we can import modules
sys.path.append(os.getcwd())

async def run_diagnostic():
    print("--- 🔍 Scanner Diagnosis Tool ---")
    
    # 1. Check Timezone / System Time
    now = time.time()
    print(f"1. System Time: {now} ({datetime.fromtimestamp(now)})")
    
    # 2. Check Data Provider Logic (Simulated)
    print("\n2. Testing Data Freshness Logic...")
    
    # We will copy the exact logic from data_provider.py to test it
    # Logic: if last_candle_time > 0: data_age = time.time() - last_candle_time
    
    # CASE A: Timestamp is in seconds (correct)
    last_candle_seconds = now - 100 # 100 seconds ago
    age_seconds = now - last_candle_seconds
    print(f"   [Case A] Seconds Timestamp: Age = {age_seconds:.2f}s (Expect ~100s)")
    
    # CASE B: Timestamp is in ms (potential bug source if API changed)
    last_candle_ms = (now - 100) * 1000 
    age_ms_logic = now - last_candle_ms # This would be huge negative or positive
    print(f"   [Case B] MS Timestamp interpreted as Seconds: Age = {age_ms_logic:.2f}s (Expect Huge/Wrong)")
    
    print("\n3. Inspecting Codebase for Silent Failures...")
    # We will read the logs in the next step, this script just verifies the environment basics
    
if __name__ == "__main__":
    asyncio.run(run_diagnostic())
