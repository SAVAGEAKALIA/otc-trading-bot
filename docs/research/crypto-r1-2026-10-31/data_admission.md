# R1 data admission follow-up

Research date: 2026-11-01. Scope: public source feasibility and bounded historical collection, not R2, model execution or trading. User confirmed willingness to move USDT where needed; this records custody flexibility, not a transfer instruction, current Earn status, authenticated permission or a chosen venue.

## Decision

Use **Bybit public REST for intraday reference prices and Coinbase USDT/USD for independent market marking**. Use official trade archives as a separate execution-research input. Historical order-book reconstruction and historical margin/collateral rules remain unverified. No paid dataset or new orchestration framework is justified yet.

Two independently researched acquisition options were compared: API-first gives small, bounded requests with explicit time windows; archive-first gives trade-level detail but requires schema/unit handling and complete compressed-file validation. Neither provides every missing input. The selected combination is API-first for price coverage, then archive validation for prints, with historical depth admitted separately. Do not substitute another venue's depth for Bybit's book.

## Measured evidence

The [machine-readable probe manifest](data_admission_probe.json) records exact URLs, SHA256, bytes, retrieval timestamps for API samples, accepted rows and limitations. Samples use October 30, 2026 UTC, ending exclusively October 31 at 00:00 UTC. Data already inspected is development evidence.

| Probe | Measured result | What it establishes |
|---|---|---|
| BTC and ETH Bybit spot/perpetual/mark/index, five-minute intervals | Eight series passed; 288 candles each, 2,304 total | One-day historical intraday price feasibility; exact grid, unique timestamps and positive finite consistent OHLC |
| Coinbase USDT/USD hourly candles | 25 returned, 24 inside the requested closed-day window; one excluded at the boundary | An independent market-price source exists for this sample; no forced USD peg or extrapolated missing bucket |
| Bybit BTC spot trade archive | HTTP 200; 65,536-byte prefix retained; reported full compressed size 11,978,026 bytes | URL and initial CSV schema accessible; not a complete file or complete day |
| Bybit BTC perpetual trade archive | HTTP 200; 65,536-byte prefix retained; reported full compressed size 87,867,539 bytes | URL and initial CSV schema accessible; not a complete file or complete day |
| BTC/ETH spot/perpetual archive directory pages | Four HTTP 200 partial HTML prefixes | Directory access only; no proof of a complete historical inventory or ETH daily-file coverage |

Raw hashes and byte sizes were independently rechecked locally. Exact millisecond alignment was checked in addition to the probe's second-based coverage test. Total accepted candles: **2,328**. No volume, turnover, aggregate trade reconciliation or full-depth assertion is made by this probe. Compressed prefixes cannot pass whole-file gzip CRC validation and are labelled partial in their manifest.

Spot archive timestamps in the inspected prefix are integer milliseconds; perpetual timestamps are fractional seconds. The headers also differ. Do not feed both through a shared positional decoder. Both inspected schemas carry an RPI field; any future filter must state how those prints relate to the visible book.

Local evidence lives under `data/research/r1-admission-20261101/`, outside Git. `probe.py` is a one-off experimental acquisition script, not a promoted collector service. Its exact hash is in the manifest. Re-fetch in a new directory with:

```bash
python3 data/research/r1-admission-20261101/probe.py /tmp/r1-admission-new-sample
```

Do not run Python with `-O`, which disables its research assertions. A re-fetch is a new observation and may differ; the retained raw files and hashes are the original evidence. This local script/data bundle is not off-host backed up and is not available from a fresh Git clone. The committed manifest preserves URLs, bounds, validation scope and hashes; transfer the ignored evidence bundle separately before relying on another host. No archive contents were committed.

## Full-window hourly acquisition

After the feasibility probe, acquired the original R1 window **August 2 through October 30, 2026 inclusive**, at hourly resolution. All nine series cover the exact 2,160-hour grid: BTC and ETH spot/perpetual/mark/index plus Coinbase USDT/USD. Total: **19,440 accepted candles, 32 public responses, 1,375,448 raw bytes**. The [hourly manifest](hourly_price_manifest.json) records every request, bounds, bytes and hash.

Checks passed for complete exact timestamp grids, no duplicates, positive finite consistent OHLC, and finite nonnegative volume/turnover where supplied. An additional cross-resolution check aggregated the previously fetched five-minute data into hourly bars: **192 of 192 OHLC comparisons matched exactly**, with no mismatches. This is internal consistency across two resolutions from the same provider, not independent proof of exchange correctness or a trade-volume reconciliation.

Hourly data now closes the historical reference-price coverage gap for BTC/ETH and the independent USDT/USD market-price series over that window. It does not close execution depth, intrabar ordering, historical rules, news availability, or the broader eight assets' intraday coverage. These inspected observations remain development data, not untouched evaluation data.

Raw files, exact acquisition script and report are at `data/research/r1-admission-20261101/hourly-90d/` and its parent `hourly.py`. The script intentionally rejects an existing output directory; do not delete original evidence to rerun it. For a new collection use a separately named output location and record that script's new hash. This is a bounded research script with assertions, not an extension of the service's supported daily-only interface. No model, backtest or execution service ran. Progress evidence: `/tmp/crypto-r1-data-admission/progress.log`.

## Official contracts and limits

- [Bybit klines](https://bybit-exchange.github.io/docs/v5/market/kline), [mark klines](https://bybit-exchange.github.io/docs/v5/market/mark-kline) and [index klines](https://bybit-exchange.github.io/docs/v5/market/index-kline) provide dated public price bars. Explicitly set category and interval, filter completed bars and validate pagination across the full intended interval. The full 90-day hourly result does not prove five-minute coverage across that entire window.
- [Coinbase candle contract](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles) limits requests to 300 buckets and permits missing no-tick periods. Its field order is time/low/high/open/close/volume, unlike Bybit. We decoded them separately. Coinbase data access does not imply the user can trade there; the price is not guaranteed Tether redemption value or a frictionless off-ramp.
- [Bybit order-book REST](https://bybit-exchange.github.io/docs/v5/market/orderbook) is a current snapshot with no documented historical date pagination; RPI orders are excluded. [Recent trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade) are not arbitrary historical trade pagination. A print is not unexecuted liquidity, maker priority or a paired-fill guarantee.
- Official archives: [BTC perpetual directory](https://public.bybit.com/trading/BTCUSDT/), [BTC spot directory](https://public.bybit.com/spot/BTCUSDT/). The [historical-data portal](https://www.bybit.com/derivatives/en/history-data) did not expose a verified order-book download route in this review. A candidate host found through third parties was not promoted to verified official provenance or downloaded.
- [Kraken OHLC](https://docs.kraken.com/api-reference/market-data/get-ohlc-data) only returns its latest 720 entries and includes an uncommitted current bar. It is a possible recent cross-check, not unrestricted historical backfill. No Kraken sample was fetched here.
- Current [instruments](https://bybit-exchange.github.io/docs/v5/market/instrument) and [risk limits](https://bybit-exchange.github.io/docs/v5/market/risk-limit) cannot establish past listing, suspension, haircut or margin rules. [Funding history](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) records settlements; preserve actual timestamps without inventing a permanent cadence from today's interval.

## Admission ledger

| Requirement | Before | After / remaining gate |
|---|---|---|
| Intraday reference prices | Only daily R1 dataset collected | One five-minute day plus full 90-day hourly BTC/ETH window verified; depth/intrabar paths and wider universe still pending |
| Independent USDT/USD market mark | No sample | Full 90-day hourly window verified without missing buckets; mark availability at bar close and an explicit staleness policy remain necessary in a simulator |
| Historical prints | Potential sources | BTC spot/perp file prefixes verified; complete-file integrity, day coverage, schema tests and candle-volume reconciliation required |
| Historical book/spreads/impact | Missing | Still missing; verify official provenance, paired-leg coverage and replay continuity, or retain conservative hypothetical cost bounds without execution claims |
| Historical rules/listings/collateral | Missing | Still missing; source dated notices/versioned snapshots or use a prospective-only rule capture design |
| Account/custody/fees | Unknown | User is willing to move funds; entity, permissions, actual fees and existing yield remain unknown |
| Capital and loss tolerances | Configurable and unset | Remain unset; no suggested sample capital is treated as authorization |

For an eventual archive admission, require complete decompression/CRC, symbol and day checks, unit-aware timestamps, monotonic sequence/gap policy, duplicate conflict detection, nonnegative finite quantities and reconciliation. Book admission additionally needs snapshots and deltas, reset handling and evidence for both legs. Trades alone never satisfy that gate. Mark candle extrema alone cannot establish intrabar liquidation survival.

## What can proceed and what cannot

Broader-asset intraday and historical depth collection can proceed as public R1 data work, retaining failures and measuring completeness. An implementation that extends the reusable collector needs its own tests/evals and independent review before replacing the daily-only contract. This report does not silently change that collector or label the one-off probe production-ready.

Account admission cannot be completed with public evidence or willingness to transfer funds. Budget fields stay configurable; they must contain chosen values before an account-specific economic conclusion. Until then, results remain hypothetical scenarios. No account access, credential request, transfer, Earn subscription or order was attempted.

## Review and validation

Independent one-day review: PASS, `/tmp/crypto-r1-data-admission/critique/final.md`. Independent full-window review: PASS, `/tmp/crypto-r1-data-admission/critique/hourly-review.md`; its verifier and detailed results are stored alongside the verdict. The reviewer independently recomputed raw hashes, full timestamp grids, all nine series and all 192 cross-resolution comparisons. Existing R1 gate suites and scenario evals also pass; they do not establish strategy performance. No reusable service code changed.

Self-rating: 9/10; proud: yes. The missing point is portability: raw evidence and the acquisition scripts are locally durable but not off-host backed up. Execution-depth and account admission remain explicitly outside this completed reference-price collection.

Next: validate the official historical depth route and effective-dated rules; resolve account facts before the R2 lock. No restart required.
