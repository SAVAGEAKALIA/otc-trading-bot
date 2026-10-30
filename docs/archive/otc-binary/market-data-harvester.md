# IQ Option market-data harvester

`harvest_market_data.py` is a read-only research process. It opens its own IQ
Option connection, writes a separate SQLite database, and never imports the
trading bot or submits an order.

The API is an unofficial community wrapper. Messages and schemas can change
without notice, so collect with a practice account and monitor
`collection_health`.

## What is collected

| Dataset | Table/view | Intended use |
| --- | --- | --- |
| Historical closed candles | `historical_candles` | Optional 2m/5m/15m backfill |
| Live candle updates | `realtime_candles` | Broker-native live OHLCV; use only `finalized=1` for closed-candle models |
| Live bid/ask | `quote_samples` | Spread, short returns, quote freshness |
| Traders' mood | `mood_samples` | Call/put sentiment level and change |
| Payout/commission | `payout_samples` | Trade selection and payout-aware evaluation |
| Public deal flow | `live_deal_events` | Direction/amount flow without trader identity |
| Ten-second deal aggregates | `deal_flow_10s` | Causal call/put count and amount imbalance |
| Clock alignment | `clock_samples` | Broker/local clock offset and drift |
| Collector health | `collection_health` | Detect disconnects and stale feeds |

The collector deliberately excludes account balances, position history,
leaderboards, user IDs, names, countries, and raw websocket payloads. Account
state is not an asset predictor. Leaderboard/profile fields are personal,
unstable, and prone to selection bias. Identifiers received with public deals
are discarded before database insertion.

## Commands

Validate the schema and privacy filter without logging in:

```bash
python3 harvest_market_data.py --self-test
```

Collect live market context until `Ctrl+C`:

```bash
python3 harvest_market_data.py --mode live
```

Backfill closed 2m/5m/15m candles:

```bash
python3 harvest_market_data.py \
  --mode backfill \
  --history-days 180
```

Backfill first, then remain online for live context:

```bash
python3 harvest_market_data.py \
  --mode both \
  --history-days 30
```

Include digital-option public deal streams in addition to binary/turbo:

```bash
python3 harvest_market_data.py \
  --mode live \
  --digital-deals
```

Run a bounded smoke collection:

```bash
python3 harvest_market_data.py \
  --mode live \
  --run-seconds 300 \
  --assets EURUSD-OTC,GBPUSD-OTC
```

The default database is:

```text
data/ml/market_context.sqlite
```

The script reads `IQ_EMAIL` and `IQ_PASSWORD` from the project `.env`.
`--account-type PRACTICE` is the default. The selected account type is only
used to authenticate the feed; this process has no order-placement code.

After rebuilding the project image, it can also run as a disposable,
independent Docker container while reusing `.env` and the `./data` mount:

```bash
docker-compose build otc-bot
docker-compose run --rm --no-deps otc-bot \
  python3 harvest_market_data.py --mode live
```

Stopping that command removes only the harvester container; it does not stop
the main bot container.

## Recommended first collection

Start with the 15 trained assets, binary/turbo deals, and the defaults:

```bash
python3 harvest_market_data.py \
  --mode live \
  --mood-interval-seconds 5 \
  --payout-interval-seconds 300 \
  --live-timeframes 1,120,300,900
```

The all-size candle stream is used because the bundled receiver exposes broker
event time, bid, and ask on that message. Only the configured timeframes are
persisted. If the extra websocket load affects the trading bot, run the
collector during dedicated data-collection sessions or reduce `--assets`.
Two processes means two independent IQ Option sessions.

## Causal model use

The model row timestamp must represent the actual decision time. Join every
context table with an as-of/backward join:

```text
feature_timestamp <= decision_timestamp
```

Never use the closest row in either direction. A forward/nearest join can pull
future mood, deal, payout, or quote information into the feature row.

For candle models:

1. Filter `realtime_candles.finalized = 1`.
2. Use a candle only after `candle_start_ms + timeframe_sec * 1000`.
3. Build labels from later settlement prices, not from the current incomplete
   candle.
4. Purge overlapping sequences across train/validation/test boundaries.

For live-deal flow, train from `deal_flow_10s` or aggregate the event table
over trailing windows such as 10, 30, and 60 seconds. Candidate features are:

- call count fraction and its change;
- call amount fraction and its change;
- `log1p(deal_count)` and `log1p(total amount)`;
- count-versus-amount divergence;
- agreement/disagreement with traders' mood;
- quote spread and quote age;
- current payout and payout change.

Amounts should be log-transformed or winsorized using limits fitted on the
training partition only. Do not assume reported public-deal amount is a
complete market-volume feed; it is a broker-side sample.

## Data-quality queries

Inventory:

```bash
sqlite3 data/ml/market_context.sqlite "
SELECT 'quotes', COUNT(*) FROM quote_samples
UNION ALL SELECT 'mood', COUNT(*) FROM mood_samples
UNION ALL SELECT 'payouts', COUNT(*) FROM payout_samples
UNION ALL SELECT 'deals', COUNT(*) FROM live_deal_events
UNION ALL SELECT 'candles', COUNT(*) FROM realtime_candles;
"
```

Recent health:

```bash
sqlite3 -header -column data/ml/market_context.sqlite "
SELECT datetime(observed_bucket_ms/1000, 'unixepoch') AS utc,
       websocket_connected,
       assets_subscribed,
       queued_deals,
       last_quote_age_ms
FROM collection_health
ORDER BY observed_bucket_ms DESC
LIMIT 20;
"
```

Per-asset coverage:

```bash
sqlite3 -header -column data/ml/market_context.sqlite "
SELECT canonical_asset,
       COUNT(*) AS quotes,
       MIN(source_event_ms) AS first_ms,
       MAX(source_event_ms) AS last_ms
FROM quote_samples
GROUP BY canonical_asset
ORDER BY canonical_asset;
"
```

Deal-flow coverage:

```bash
sqlite3 -header -column data/ml/market_context.sqlite "
SELECT canonical_asset,
       COUNT(*) AS buckets,
       SUM(deal_count) AS deals,
       AVG(call_count_fraction) AS mean_call_fraction
FROM deal_flow_10s
GROUP BY canonical_asset
ORDER BY canonical_asset;
"
```

## Limits

- `get_candles()` is suitable for historical backfill, not a live decision
  clock. The community documentation warns it may lag live data.
- The quote fields are broker-feed bid/ask values from the all-size candle
  message, not an exchange order book.
- Traders' mood and public deals describe IQ Option activity, not global FX
  volume.
- Payout bootstrap uses the wrapper's initialization request in a daemon
  thread. If that request stalls, commission-change streaming and the rest of
  the collector continue.
- New context features do not guarantee predictability. Repeat the existing
  purged temporal tournament, calibration, payout-aware policy test, and
  untouched final test. Keep deployment rejected unless the lower confidence
  bound of out-of-sample expectancy is positive.
