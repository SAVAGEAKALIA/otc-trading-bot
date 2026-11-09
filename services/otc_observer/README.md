# OTC observation service

This service creates a read-only, traceable source export for an offline price experiment. It has no broker connection and submits no orders. The measurable output is the number of archived rows admitted or quarantined, the original source hash, and the exact received observations available to research.

Use Python 3.12. Run from the repository root. All export paths must be new or empty. Generated SQLite files and JSONL observations stay outside Git.

```bash
python3 -m unittest discover -s services/otc_observer/tests -q
python3 -m services.otc_observer.evals.eval_observer --output /tmp/otc-observer-eval.json
```

The source archive can use SQLite WAL mode. A consistent backup merges its committed WAL pages without modifying the original data. The backup preserves one read transaction, switches its own journal mode to DELETE, verifies SQLite integrity, and records the input file sizes and snapshot hash.

```bash
python3 -m services.otc_observer.snapshot \
  --source /home/saviour/PycharmProjects/I2/IQoption/data/ml/market_context.sqlite \
  --destination /tmp/market-context-snapshot.sqlite
python3 -m services.otc_observer.export \
  --database /tmp/market-context-snapshot.sqlite \
  --output /tmp/otc-observations
```

A database without an active WAL or rollback journal can be exported directly. The exporter reads schema, scope census and observations in one query-only transaction. It checks both main-file metadata and SHA-256 before and after extraction. A changing source or active sidecar is rejected. The consistent snapshot hash identifies the SQLite input used for labels; it is not presented as the original live main-file hash.

The output contains:

- `registration.json`: the asset, product, clock and exclusion rules written before extraction.
- `observations.jsonl`: immutable `contracts.otc_v1.Observation` records.
- `source_lineage.jsonl`: original source or bucket timestamp, recorded clock offset, raw-row hash and explicit product mapping per event.
- `manifest.json`: successful source admission, exact artifact hashes, column inventory, input/output counts and receipt ranges.
- `progress.log`: deterministic row progress and remaining-time estimates; `tail -f /tmp/otc-observations/progress.log` follows it.

The scope is EURUSD-OTC and GBPUSD-OTC. Mood and payout rows must record `turbo-option`; quote rows lack product identity, so this mapping is an explicit experimental assumption. Clock offsets outside 15,000ms are quarantined. Quote source timestamps after receipt or more than 15,000ms old are quarantined. Receipt batches are simultaneous: only their newest original quote survives, and conflicting values at that newest timestamp quarantine the batch.

The receiver-clock experiment sets event time equal to recorded receipt time and keeps the original source timestamp in lineage. This prevents a future receipt from entering an earlier feature. It measures prices observed by the recorder, including recorder delay. It cannot establish the broker strike or expiry price. Mood and payout bucket timestamps are grouping keys, not proof of availability.

Rows overwritten inside old buckets cannot be recovered. No binding expiry offers, accepted strikes or authoritative settlement cash were recorded, so actual contract win rate and cash returns remain unknown. No runtime restart is needed for these offline commands.
