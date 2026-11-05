# D3 decision-window quote coverage

November 5, 2026. **All 15 requested symbol/date windows contain an observed two-sided spot quote.** The existing threshold preview produces nine distinct decision dates: eight BTC windows and seven ETH windows. This completes the eight-date follow-up to the October 30 probe. It establishes archived quote availability only. It does not establish executable fills, capacity or strategy returns.

The [saved evidence](spot_quote_checks.json) records each archive SHA256, target and observed exchange timestamps, best bid/ask, displayed quantities and spread. The target is 00:10:00 UTC on the day after the signal bar, following the unchanged 00:05 decision plus five-minute submission lag. The probe selects the earliest valid update through 00:11:00 inclusive. It applies every preceding snapshot and delta from the archive's initial same-day snapshot, refuses ordering rewinds and invalid identity/numeric fields, and skips empty, locked or crossed books until a valid update arrives. [Frozen timing and signal rules](experiment_spec.md) · [Signal preview](spot_trend_preview.json)

| Symbol | Decision date UTC | Bid / ask, USDT | Offset from 00:10, ms |
|---|---|---:|---:|
| BTCUSDT | 2026-08-20 | 69643.6 / 69643.7 | 17 |
| BTCUSDT | 2026-08-21 | 73280.5 / 73280.6 | 16 |
| BTCUSDT | 2026-08-22 | 77889.9 / 77890 | 16 |
| BTCUSDT | 2026-09-16 | 75697 / 75697.1 | 116 |
| BTCUSDT | 2026-09-22 | 86329.9 / 86330 | 16 |
| BTCUSDT | 2026-10-09 | 81785.8 / 81785.9 | 16 |
| BTCUSDT | 2026-10-30 | 77880 / 77880.1 | 95 |
| BTCUSDT | 2026-10-31 | 77256.9 / 77257 | 94 |
| ETHUSDT | 2026-08-20 | 2258.65 / 2258.66 | 56 |
| ETHUSDT | 2026-08-22 | 2498.45 / 2498.46 | 55 |
| ETHUSDT | 2026-09-16 | 2401.06 / 2401.07 | 153 |
| ETHUSDT | 2026-09-22 | 2770.8 / 2770.81 | 56 |
| ETHUSDT | 2026-10-08 | 2571.93 / 2571.94 | 55 |
| ETHUSDT | 2026-10-09 | 2477.61 / 2477.62 | 55 |
| ETHUSDT | 2026-10-30 | 2245.54 / 2245.55 | 14 |

BTC offsets range from 16 to 116 ms; ETH offsets range from 14 to 153 ms. These are differences between archived exchange event times and the research target, not measured network latency. Displayed full spreads are approximately 0.01158–0.01436 bps for BTC and 0.03609–0.04453 bps for ETH. A displayed spread is neither a complete round-trip cost nor an order-size capacity estimate.

Twelve newly acquired archives in `data/research/r1-trend-quotes/` total 770,030,660 compressed bytes. The separately listed October 31 BTC archive in `data/research/r1-trend-quotes-oct31/` adds 32,830,206 bytes. All thirteen have full ZIP CRC verification receipts. The two October 30 archives were already verified in `data/research/r1-depth-20261102/verified/`. The public source for each is `https://quote-saver.bycsi.com/orderbook/spot/{symbol}/{date}_{symbol}_ob200.data.zip`; adjacent `.verified.json` receipts retain the exact URL, size, ETag and SHA256. The probe rehashes the whole ZIP and matches its size and digest to that CRC receipt, then replays only the prefix required for the quote. It does not repeat a full-day semantic audit or prove sequence completeness. Archive contents and receipts stay local and are not committed.

Reproduce from the repository root, after acquiring the same verified local archives:

```bash
python3 docs/research/crypto-r1-2026-10-31/spot_quote_checks.py \
  docs/research/crypto-r1-2026-10-31/spot_trend_preview.json \
  data/research/r1-trend-quotes \
  data/research/r1-trend-quotes-oct31 \
  data/research/r1-depth-20261102/verified \
  > /tmp/spot-quotes-reproduced.json
cmp /tmp/spot-quotes-reproduced.json \
  docs/research/crypto-r1-2026-10-31/spot_quote_checks.json
python3 -m unittest discover \
  -s docs/research/crypto-r1-2026-10-31 -p test_spot_quote_checks.py -q
python3 docs/research/crypto-r1-2026-10-31/eval_spot_quote_checks.py
```

The 15-test gate suite covers stale and late quotes, exact timing boundaries, snapshot replacement, unusable books, malformed messages and levels, ordering rewinds, archive tampering, missing receipts and duplicate archive sources. Its saved-evidence test rejects incomplete intermediate results before commit by checking every preview target, observed status and timing. The separate deterministic eval requires all 114 scenarios to pass: 96 seeded dictionary-oracle replays, six timing boundaries and twelve invalid-input scenarios. It uses no paid inference or trading connection. The independent archive replay comparison is retained at `/tmp/r1-video-review/critique/compare.py`, with its source observations in `independent.jsonl` and `independent-late.jsonl`.

All threshold dates are a superset of possible stateful trades. Repeated entry conditions while already long and exit conditions while flat are not additional trades. Historical candle publication before 00:05 remains unverified. Order sizing, precision, fees, depth beyond the top level, slippage and continuous valuation still need their own evidence. The observed history remains development data.

Next, freeze D3 allocation, component holdings and accounting rules before calculating any returns, then derive the exact stateful order and valuation requirements from that contract. Download additional archives only for those requirements. Carry remains subject to the separate account-fee gate; this quote result does not reverse the carry fee decision. No restart is required.
