# D3 spot trend data readiness

November 5, 2026. BTCUSDT and ETHUSDT each have 190 consecutive completed daily spot candles from April 24 through October 30 UTC. The first 100 are warm-up for the original 20/55/100 entry lookbacks. The 90 subsequent signal bars overlap the earlier R1 snapshot exactly for each symbol. Source URLs, hashes and coverage are in the [preview manifest](spot_trend_preview.json). [Bybit daily kline contract](https://bybit-exchange.github.io/docs/v5/market/kline)

The preview applies the existing strict conditions to every eligible completed close. It excludes the signal bar from the preceding high/low threshold. August 2 through October 30 are **signal-bar dates**. The corresponding scheduled decisions run August 3 through October 31 at 00:05 UTC. A retrospective daily response verifies candle contents. Historical publication before the decision remains unverified. [Existing comparator specification](experiment_spec.md)

| Symbol | Entry/exit lookback | Eligible days | Entry condition true | Exit condition true |
|---|---:|---:|---:|---:|
| BTC | 20/10 | 90 | 4 | 4 |
| BTC | 55/20 | 90 | 4 | 3 |
| BTC | 100/50 | 90 | 1 | 0 |
| ETH | 20/10 | 90 | 3 | 4 |
| ETH | 55/20 | 90 | 3 | 1 |
| ETH | 100/50 | 90 | 2 | 1 |

Counts describe threshold conditions and may repeat while a component would already be long or flat. The preview does not simulate holdings, orders, fills, returns or fees. Across both symbols, the entry or exit conditions identify nine distinct next-day decision dates for a future quote feasibility check. October 31 is outside the existing August 2–October 30 archive catalog window. The two verified replay days include October 30, which overlaps this check. Continuous valuation and liquidation checks are separate requirements.

The October 30 spot quote probe applies snapshots and deltas from midnight to the first valid book update at or after 00:10 UTC. BTC had a bid/ask of 77,880.00 / 77,880.10 at +95 ms. ETH had 2,245.54 / 2,245.55 at +14 ms. Both fit the 60-second quote window. The offsets use exchange timestamps. The probe records displayed prices and quantities and does not reconstruct client receipt time or fill an order. [Quote evidence](spot_quote_probe.json)

The carry fee decision remains conditional on actual account rates. The spot comparator is a separate descriptive candidate and uses the existing rules without tuning. Before a return experiment, freeze allocation and accounting and obtain eligible post-submission quotes under the existing five-minute lag and 60-second wait. Historical observations remain development data.

Raw daily responses and acquisition metadata are in `data/research/r1-spot-warmup-20261105/`, with local-only storage. Reproduce the threshold preview from the repository root:

```bash
python3 docs/research/crypto-r1-2026-10-31/spot_trend_preview.py \
  data/research/r1-spot-warmup-20261105 > /tmp/r1-trend/reproduced.json
cmp /tmp/r1-trend/reproduced.json docs/research/crypto-r1-2026-10-31/spot_trend_preview.json
python3 -m unittest discover -s docs/research/crypto-r1-2026-10-31 -p test_spot_trend_preview.py -q
```

Independent review passed at `/tmp/r1-trend/critique/final.md`. It recomputed all threshold dates, checked all 180 overlapping bars and independently replayed both quote probes. The JSON reproduced byte for byte. Self-rating 9/10. Proud of the verified readiness check. Quote coverage for the other decision dates and historical publication timing remain open. No restart required.
