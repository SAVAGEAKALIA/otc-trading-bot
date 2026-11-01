# R1 bounded market-data audit

Research date: 2026-10-31. No account permissions, fees, orders or live strategy are inferred from public API access.

## Design comparison registered before collection

Variant A: extend `docs/research/crypto-evidence-2026-10-30/pull_funding_history.py`. It supplies the standard public funding pagination pattern, but executes on import, uses host-local `mktime`, collects unbounded history, does not validate venue error codes or cursor progress, and lacks immutable request provenance.

Variant B: reuse that documented endpoint/pagination pattern in a self-contained standard-library research collector, with explicit UTC window, request manifests, bounded pages, timestamp deduplication and offline tests. Chosen because the additional data types and validation should not silently change the old reproducible diagnostic. This is a research adapter, not an execution service or general market-data platform.

Frozen collection scope: BTC, ETH, SOL, XRP, DOGE, ADA, LINK, AVAX, LTC, BCH; at most 90 completed UTC days ending 2026-10-31T00:00:00Z. Discover current Bybit USDT spot/linear-perpetual intersection first, retain rejected seed candidates with reasons, then gather all currently matched seed pairs. BTC/ETH are the baseline, not claimed sole investable assets. Current universe membership cannot establish historical availability or eliminate survivorship bias.

Current quote screen: both markets Trading, same USDT quote/base asset, linear USDT perpetual; valid positive bid/ask, spread at most 20 bps on each leg, reported trailing-24h turnover at least USD-proxy 1 million spot and 10 million perp. These are research screening policy thresholds, not proven execution-capacity limits. USDT turnover is not guaranteed USD value. Failing the quote screen does not delete historical records; no asset is approved for trading.

Sources: [instruments](https://bybit-exchange.github.io/docs/v5/market/instrument), [funding](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate), [candles](https://bybit-exchange.github.io/docs/v5/market/kline), [tickers](https://bybit-exchange.github.io/docs/v5/market/tickers), [risk tiers](https://bybit-exchange.github.io/docs/v5/market/risk-limit). Public Bybit and Hyperliquid probes both returned 200; only Bybit is collected here to keep the first universe/collateral structure consistent. HTTP success is not user eligibility.

## Completed collection and evidence

Collected 75 public responses with 2,700 settled funding observations and 3,600 daily candles. Frozen interval: `2026-08-02T00:00:00+00:00` through exclusive `2026-10-31T00:00:00Z`. Current discovery found 288 USDT spot/perpetual base-asset intersections; this bounded run collected the ten predeclared seed assets, not all intersections.

All ten matched current instrument pairs and passed the declared current quote screen. No seed was silently removed. Every asset has 270 funding prints with observed consecutive eight-hour spacing, and 90 bars for each of spot, perp, mark and index. No whole missing days or duplicate timestamps were found. Historical funding schedules are still not independently verified; daily data do not validate intraday execution or collateral survival. Current risk-tier responses had empty continuation cursors.

| Asset | Funding rows | Spot / perp / mark / index bars | Spot spread bps | Perp spread bps | Spot turnover USDT | Perp turnover USDT | Current quote screen |
|---|---:|---|---:|---:|---:|---:|---|
| BTC | 270 | 90 / 90 / 90 / 90 | 0.0129 | 0.0129 | 850500368.14 | 5585688437.45 | pass |
| ETH | 270 | 90 / 90 / 90 / 90 | 0.0446 | 0.0446 | 288172337.48 | 2481808166.94 | pass |
| SOL | 270 | 90 / 90 / 90 / 90 | 1.0364 | 1.0366 | 71754955.36 | 539285258.71 | pass |
| XRP | 270 | 90 / 90 / 90 / 90 | 0.7972 | 0.7977 | 66409851.99 | 339057485.60 | pass |
| DOGE | 270 | 90 / 90 / 90 / 90 | 1.3173 | 1.3176 | 6312603.44 | 69659407.13 | pass |
| ADA | 270 | 90 / 90 / 90 / 90 | 5.1480 | 5.1533 | 2865890.98 | 51452287.86 | pass |
| LINK | 270 | 90 / 90 / 90 / 90 | 0.8632 | 0.8637 | 14100098.23 | 56038801.64 | pass |
| AVAX | 270 | 90 / 90 / 90 / 90 | 1.1633 | 1.1631 | 8403457.48 | 36483448.28 | pass |
| LTC | 270 | 90 / 90 / 90 / 90 | 1.8068 | 1.8078 | 3901092.99 | 19697757.40 | pass |
| BCH | 270 | 90 / 90 / 90 / 90 | 0.6863 | 0.3434 | 3834805.04 | 25664967.31 | pass |

Raw response bytes: 2,541,379. Local durable snapshot: `data/research/crypto-r1/bybit-90d-20261031` (ignored by Git; not an off-box backup). A portable [manifest](market_data_manifest.json) records each endpoint, timestamps, raw hash and output hash. Report SHA256: `917e2161acf13a5d28f1921f9a75a500bd587f2a8d1f8e648bbe05a7477abda6`.

## Reproduction and tests

The [service README](../../../services/market_data_r1/README.md) documents collection and replay. From the repository root:

```bash
python3 -m unittest discover -s services/market_data_r1/tests -v
python3 services/market_data_r1/evals/eval_scenarios.py
python3 services/market_data_r1/collector.py --output /tmp/crypto-r1/replay-new --end 2026-10-31T00:00:00Z --days 90 --replay data/research/crypto-r1/bybit-90d-20261031/raw
cmp data/research/crypto-r1/bybit-90d-20261031/report.json /tmp/crypto-r1/replay-new/report.json
```

Use a fresh replay path. The collection was replayed offline and its computed report matched byte-for-byte. Twenty-one deterministic gate tests and six adverse scenario evals pass. They cover positive complete-UTC-day windows, strict UTC-midnight candle alignment, timestamp/duplicate/cursor/candle validation, missing data, unsafe quotes and checksum-verified replay. No third-party code, model or trading action was executed.

## R2 admission limits

This is enough to specify a wider-universe experiment and inspect recent data coverage, not enough to approve a strategy. Still required for dependent R2 claims: longer historical validation, point-in-time listing/delisting universe, executable spread/depth history or labeled conservative cost scenarios, historical collateral/tier changes, authenticated fee tier and Nigerian account/product eligibility. Missing quantities are not imputed from current metadata. The 90-day dataset is now viewed development evidence; it cannot later be called an untouched holdout.

No service restart is required.

## Critic regression: daily-grid alignment

An independent critic showed that one shifted intraday candle per date could previously satisfy the calendar count. The audit now rejects non-midnight daily bars and nonpositive or partial UTC-day windows. Regression tests failed before the fix; adverse evals cover 1 ms, 1 minute, 1 hour and nearly-one-day shifts. Evidence: `/tmp/crypto-r1/critique/daily-alignment-before.txt` and `/tmp/crypto-r1/critique/daily-alignment-after.txt`. The unchanged raw snapshot still replays byte-for-byte to the same report hash.

## Critic regressions: activity fields and stale completion markers

Daily spot/perp volume and turnover must be finite and nonnegative; price-only mark/index bars remain valid. A collection now requires a fresh output directory itself, rejecting an existing report-only directory without mutation. This prevents an interrupted collection from inheriting an old completion report. Tests failed before these corrections and pass afterward: `/tmp/crypto-r1/critique/adjacent-data-before.txt` and `/tmp/crypto-r1/critique/adjacent-data-after.txt`. Raw inputs were unchanged, and offline replay retained the original report hash.
