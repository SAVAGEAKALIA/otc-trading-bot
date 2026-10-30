"""Pull full public funding history: Bybit linear perps (paginated back) and Hyperliquid (hourly)."""
import json, sys, time, urllib.request
OUT = sys.argv[1]
def get(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None, headers={"Content-Type": "application/json"})
    for i in range(5):
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception as e:
            time.sleep(2 * (i + 1)); err = e
    raise err
rows = []
for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"):
    end = int(time.time() * 1000); n0 = len(rows)
    while True:
        r = get(f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={sym}&limit=200&endTime={end}")["result"]["list"]
        if not r: break
        rows += [("bybit", sym, int(x["fundingRateTimestamp"]), float(x["fundingRate"])) for x in r]
        end = min(int(x["fundingRateTimestamp"]) for x in r) - 1
        time.sleep(0.12)
    print("bybit", sym, len(rows) - n0, flush=True)
for coin in ("BTC", "ETH", "SOL"):
    start = int(time.mktime((2023, 6, 1, 0, 0, 0, 0, 0, 0))) * 1000; n0 = len(rows)
    while start < time.time() * 1000:
        r = get("https://api.hyperliquid.xyz/info", {"type": "fundingHistory", "coin": coin, "startTime": start})
        if not r: break
        rows += [("hyperliquid", coin, int(x["time"]), float(x["fundingRate"])) for x in r]
        start = max(int(x["time"]) for x in r) + 1
        time.sleep(0.2)
    print("hyperliquid", coin, len(rows) - n0, flush=True)
json.dump(rows, open(OUT, "w"))
