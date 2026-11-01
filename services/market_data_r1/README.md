# R1 public market-data collector

Concern: collect a bounded, auditable public research dataset for the BTC/ETH baseline and eight named broader-universe candidates. This service has no trading/account endpoints, credentials, external packages or model calls. It does not select an approved venue or implement R2 backtests.

The old funding collector remains unchanged for historical reproduction. This code retains its documented backwards funding-pagination pattern, adds UTC windows, bounded retries/pages, API error checks, cursor progress checks, raw response hashes, strict duplicate checks, daily OHLC validation and offline replay.

## Contract and commands

Input: explicit exclusive UTC-midnight `--end`, `--days` between 1 and 90, and a fresh output directory. The public venue clock must confirm the requested cutoff is already complete. The ten seed assets are deliberately fixed in `SEEDS`; current Trading USDT spot/linear-perpetual instruments determine which have a matched pair. This is not a historical all-asset universe.

```bash
python3 -m unittest discover -s services/market_data_r1/tests -v
python3 services/market_data_r1/evals/eval_scenarios.py
python3 services/market_data_r1/collector.py --output data/research/crypto-r1/bybit-90d-20261031 --end 2026-10-31T00:00:00Z --days 90
```

Use a new output path for a new collection. Existing output directories, including a report-only directory, are rejected to prevent accidentally replacing the evidence. Each successful response is written immediately, with endpoint, query, retrieval/venue timestamps, SHA256 and byte count in `raw/manifest.json`. A failure stops the run; no completed `report.json` means the collection is incomplete. Retained partial raw requests are evidence, not a complete dataset.

The completed local snapshot can be checked without network:

```bash
python3 services/market_data_r1/collector.py --output /tmp/crypto-r1/replay-new --end 2026-10-31T00:00:00Z --days 90 --replay data/research/crypto-r1/bybit-90d-20261031/raw
cmp data/research/crypto-r1/bybit-90d-20261031/report.json /tmp/crypto-r1/replay-new/report.json
```

Replay requires the exact request order/URLs, validates every raw response checksum, reruns validation and calculations, and rejects unused or missing requests. Pick a fresh replay output directory. The snapshot is outside `/tmp` but local-only; it is ignored by Git and needs a separately approved off-box backup before long-term reliance.

Progress uses completed symbols, monotonic elapsed time, measured rate and computed ETA; both terminal and `/tmp/crypto-r1/data-progress.log` receive updates. Follow with `tail -f /tmp/crypto-r1/data-progress.log`. Replay also appends progress; its durations are offline replay, not network performance.

## Fields and quality limits

`report.json` includes current instrument details, quote screening, current risk-tier payloads and per-series coverage. Four daily candle series per matched asset are spot, perpetual, mark and index. Settled funding records retain actual timestamps; no missing day is zero-filled. Conflicting duplicate timestamps fail. Repeated identical records are deduplicated for summaries and counted.

Current quote screen: both leg spreads <=20 bps, spot 24h turnover >=1m USDT, perp >=10m USDT. It is a frozen research policy, not a capacity guarantee. Quotes and turnover are only one current snapshot; stablecoin value, order depth, account fee tiers, future funding, Nigerian permissions and historical liquidity remain unvalidated.

Observed funding-gap histograms identify cadence changes or potential omissions; current instrument funding interval does not prove historical schedules. Daily candles cannot validate intraday legging, executable fills or liquidation. Current risk tiers/margin metadata cannot be applied retrospectively without historical evidence. Any nonempty risk-tier cursor indicates additional tiers not collected; this snapshot's cursors were empty.

Twenty-one gate tests and six scenario evals are offline and standard-library only. They validate positive complete-UTC-day windows, strict UTC-midnight daily-candle alignment, duplicate conflicts, missing days, partial-day exclusion, OHLC ranges, finite nonnegative volume/turnover, stale-report protection, quote screening, cursor safety and replay integrity. Eval pass requires all cases to pass; no paid model eval applies because the service has no LLM.
