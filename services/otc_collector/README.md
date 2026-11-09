# Fresh OTC receipt collector

Outcome: preserve actual newly received EURUSD-OTC and GBPUSD-OTC quote frames with exact UTC callback receipt, monotonic arrival, source stamp, and observable gaps. The reference is the archived harvester wire protocol in Git tag `otc-binary-final-2026-10-30`.

This cohort is exploratory development evidence from a received price proxy. It has no accepted-contract evidence, no account-mode assertion, and no capital promotion. Public deal flow is unavailable in this narrow collector and cannot be inferred from aggregate mood. Quotes have no broker product field; `turbo-option` is an explicit research assumption. Archived mood also lacks a product field and records `subscription_scope_assumed`; any explicit conflicting product is quarantined.

## Install and offline checks

Run from the project root containing `services/otc_collector`. Python 3.11+ and standard-library SQLite are sufficient for tests/evals. Live transport adds `requests` and `websocket-client`; the existing project venv has requests 2.34.2 and websocket-client 1.8.0. No broker SDK or order methods are imported.

```bash
/home/saviour/PycharmProjects/I2/IQoption/venv/bin/python -m pip install -r services/otc_collector/requirements.txt
python3 -m unittest discover -s services/otc_collector/tests -t . -q
python3 -m services.otc_collector.tests.gate --output /tmp/fresh-otc/gate.json
python3 -m services.otc_collector.evals.replay --output /tmp/fresh-otc/eval.json
```

Gate budget: under 2 seconds in-process. Offline replay threshold: every check must pass, score 1.0. Replay injects missing GBP quotes, invalid numeric/product/commission/offer frames, privacy markers, both clock jumps, restart/reconnect, conflicting IDs, queue overflow, and SQLite failure. A mutation reproducing all-size quote amplification must be rejected by the regression gate. It invokes no network, credential file, paid model, or historical database. Test research sources are frozen unit fixtures; live registration hashes the actual research service and contracts supplied below.

## Register before connecting

Registration requires an explicit future UTC start aligned to 120 seconds. Substitute the chosen start, then keep that exact start regardless of quote, payout, mood, or label coverage. The example start below is UTC, not Lagos time. The seven days end exactly seven UTC days later.

```bash
python3 -m services.otc_collector.runner register --start-utc 2026-11-08T00:00:00Z --registration /tmp/fresh-otc/registration.json --research-source-root /home/saviour/PycharmProjects/I2/IQoption
python3 -m services.otc_collector.runner dry-run --registration /tmp/fresh-otc/registration.json
```

Registration freezes `created_ms`, `start_ms`, `end_ms`, full ISO UTC chronology, assets 76/EURUSD-OTC and 81/GBPUSD-OTC, grid/expiry 120 seconds, entry 2 seconds, lookback 60 seconds, ages quote 5 seconds/mood 60 seconds/payout 600 seconds, last received at/before expiry, full-refund ties, and the source priorities. `partitions` records train 3 days, early 1 day, calibration 1 day, policy 1 day, diagnostic_test 1 day. The ordered `phases` list preserves chronology even in canonical JSON, whose mapping keys sort alphabetically. No partition depends on label availability.

`source_hashes` freezes collector Python files, all research Python files, and `contracts/otc_v1` Python files. Code/config/registration hashes are checked again before opening the fresh database and before network access. Changed source or schedule cannot resume a registered database. Registration reads source files only. Dry-run reads neither credentials nor broker state.

## Start, monitor, stop

Use the existing external absolute env file `/home/saviour/PycharmProjects/I2/IQoption/.env`, with its established `IQ_EMAIL=` and `IQ_PASSWORD=` keys and private mode 0600. The collector reads only these keys after explicit live acknowledgement. Keep it outside the isolated collector directory. Never copy its contents into a replay fixture, an output directory, a command-line argument, or a commit.

```bash
python3 -m services.otc_collector.runner live --registration /tmp/fresh-otc/registration.json --db /tmp/fresh-otc/receipts.sqlite --env-file /home/saviour/PycharmProjects/I2/IQoption/.env --progress-log /tmp/fresh-otc/progress.log --allow-account-read
python3 -m services.otc_collector.monitor --db /tmp/fresh-otc/receipts.sqlite --progress-log /tmp/fresh-otc/progress.log --watch
tail -f /tmp/fresh-otc/progress.log
```

The live command stays in the foreground. Press Ctrl+C or send SIGTERM to its own process to stop gracefully. It automatically closes at the registered end. Starting after the registered start exposes a leading gap and retains the original chronology. Starting before the window waits for that start and creates the frozen database registration before authentication. Restart the same command with the same registration/database to resume; the clock starts unsynchronized and unclosed prior sessions become `partial_crash_recovery` evidence.

Progress prints and appends timestamped JSON at least every 30 seconds while connected. It computes percent/ETA from the fixed schedule, rates and quote coverage from persisted receipts, and gaps separately per asset. Coverage is the union of five-second receipt-valid intervals, not a count of cached polls. Latest health, disconnects, and missing assets remain visible. Feature-specific failures do not silently become zeros or default payouts.

## Freeze and compare boundary

```bash
python3 -m services.otc_collector.runner export --db /tmp/fresh-otc/receipts.sqlite --output /tmp/fresh-otc/frozen-collection
```

Export accepts a new `/tmp` directory and takes a consistent SQLite backup. It writes canonical `Observation` rows to `observations.jsonl`, clock-admissible rows separately to `observations-admissible.jsonl`, exact lineage, registration, sessions, health, and hashes. Sources are `quote_samples`, `mood_samples`, `commission-stream`, and `init-snapshot`, matching the existing builder. `event_ms == available_ms == callback receipt`, clock ID `receiver_utc`; original broker source times stay in lineage. The fresh-boundary loader must check schedule completion, receipt provenance, health admission, and all registered opportunities before passing any export to the fixed six-policy comparison. Historical August guards remain unchanged. Collector export alone does not assert cohort or training admission. Fresh matrix export/compare/package commands belong to the separately implemented research boundary.

## Failure semantics and security boundary

`candles-generated` contributes one top-level bid/ask midpoint per received frame even when it contains many candle sizes. Subscription requests use only the all-size quote stream, aggregate mood for the two active IDs, turbo commission updates, and the bounded initial offer snapshot. `candle-generated` is accepted only with size 1. Decimal values reject booleans, strings, nonfinite numbers, crossed/negative quotes, excess precision, and unsupported asset IDs. Unknown/private/auth frames are discarded without body, name, raw digest, or log content. Valid quote payloads retain only permitted market fields.

HTTP is fixed to HTTPS authentication with TLS verification, no redirects, and a 10-second timeout. Websocket is fixed to the IQ Option WSS URL with required certificates and hostname verification, five-second socket timeout, bounded acknowledgement/snapshot deadlines, eight reconnects and at most 30-second backoff. Every outgoing operation passes an exact structural allowlist. There is no account switch, balance reset, position fetch, order, capital, or trading operation. Credentials and session cookies stay in memory; external error text is never printed.

The callback samples UTC and monotonic time before parsing. A receiver clock jump beyond one second in either direction halts. Broker offsets beyond 15 seconds, missing synchronization, stale synchronization beyond 60 seconds, and inconsistent quote source age remain persisted but clock-ineligible. There is no timestamp reconstruction that moves causal availability earlier.

Each callback receives a UUID session plus monotonically increasing sequence. The SQLite receipt, all its canonical observations, and health evidence commit atomically with `synchronous=FULL`. Identical IDs/values are idempotent; conflicting IDs halt. Database triggers forbid updates/deletes. An advisory lock permits one writer; a historic/incompatible database is rejected before any mutation. A bounded queue and frame size prevent unbounded ingress. Overflow, SQLite failure, shutdown timeout, or internal writer fault halt collection and preserve safe evidence. Pending memory at a process crash can be lost; the unclosed-session journal detects that uncertainty, and admission must not claim lossless complete coverage across it.

Broker stamp version `broker_epoch_floor_ms_v2` accepts valid finer-resolution seconds, milliseconds, microseconds, and nanoseconds. It preserves the original numeric token as `broker_stamp_text`, short unit as `source_stamp_unit`, reported decimal quantum, exact ns, and fractional ms. `source_event_ms` is floored metadata only. Live callback receipts also preserve `received_at_ns` from one UTC sample; `available_ms` and `event_ms` remain that receipt floored to ms. `raw_source_receiver_delta_ns` is an uncorrected difference between broker and receiver clocks, not a claim of synchronized network latency. Focused verification: `python3 -m services.otc_collector.tests.test_fractional_stamps`.

The original precision-failed pilot stays intact as failed operational evidence. Deploy this source under a new namespace, freeze its actual code hashes, and register a new future UTC window before collection. Never edit the previous registration or its hashes to resume with this changed source.

No existing service needs restarting to use this standalone CLI. Run registration/dry-run first, then start the explicitly acknowledged collector when collection is authorized.
