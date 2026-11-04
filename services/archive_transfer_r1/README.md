# R1 archive transfer

Outcome: four public archives become durable, version-pinned, CRC-verified ZIPs; interrupted attempts reuse only hashed chunks. Python 3 standard library, Linux filesystem locking, no LLM or third-party dependency.

```
python3 transfer.py /absolute/path/partial_manifest.json --output /absolute/path/new-verified-directory --progress /tmp/r1-archive-transfer/progress.log
python3 -m unittest discover -s tests -q
python3 evals/eval_scenarios.py
```

Defaults: 8 workers per archive, 1 MiB chunks, 20-second socket timeout, 40-second hard deadline for the range reader process, four attempts with exponential sleep capped at eight seconds. Files download sequentially, ranges concurrently. The child reads at most the requested range plus one byte. Each worker retains a bounded response. The parent enforces the deadline across headers and body and terminates a stalled reader. Redirects and content encoding are forbidden.

Each archive has an exclusive process lock, immutable identity.json and offset-named byte/receipt pairs. Data and receipts are separately atomically replaced and fsynced; a crash between them leaves an untrusted chunk that is fetched again. A one-byte probe binds all ranges to a strong ETag. Every subsequent request supplies If-Range and validates ETag, exact 206 range/total, Content-Length and actual bytes. Changed identities fail closed, requiring a fresh directory. Existing partial files are never imported or changed.

Final assembly rechecks chunk hashes, exact length and every ZIP member CRC before atomic promotion. The adjacent .verified.json records total SHA256 and source identity. The final verified_manifest.json is written only after all four succeed. ZIP integrity is not full-day replay evidence, and its manifest explicitly says so. A killed run may have a promoted ZIP without a receipt: restart reassembles and verifies it safely.

Progress is append-only JSONL with measured verified bytes, percent, successful transfer rate, ETA and response/transport error count. Progress only advances after durable chunk receipts; failures exit nonzero and leave reusable evidence. Rejected protocol responses stop immediately, while connection failures and selected transient HTTP statuses retry. Do not share the output directory with untrusted processes that modify files; locking coordinates cooperating downloaders, not hostile local mutation. The source host must retain strong ETags; weak/missing ETags are rejected.

Gate and adverse evaluation commands are offline, using injected synthetic responses; the separate seeded evaluation varies archive length, chunk size and worker count across twelve scenarios, corrupts cached bytes, probes identity drift and requires 100 percent. Neither is evidence that the actual four archives have been downloaded.

Final ZIP validation requires exactly one non-directory member, rejects declared expansion above 128 GiB, and streams that specific ZipInfo to EOF for CRC verification. Duplicate names cannot redirect CRC validation. Run-level locking serializes CLI runs; before network access, verified_manifest.json becomes a non-success tombstone. run_status.json records running/failed/complete. A killed run remains running and must never be treated as complete; consumers require both run status complete and manifest integrity true. Each archive emits one failure event.

The standard transport runs one disposable subprocess per range. Its deadline covers header and body stalls. Injected test transports are responsible for their own deadlines.

Gate tests mock os.fsync to avoid host-load-dependent disk flush latency; evals exercise actual fsync. Neither simulates power-loss durability. Atomic write ordering and directory fsync remain active in production.

## Replay a verified archive

From the repository root, pass the archive path, symbol, and exact UTC window in milliseconds. October 30, 2026 uses the bounds below.

```bash
python3 services/archive_transfer_r1/audit.py "$ARCHIVE_PATH" \
  --symbol BTCUSDT --start-ms 1793318400000 --end-ms 1793404800000 \
  --output "$AUDIT_REPORT_PATH"
python3 services/archive_transfer_r1/evals/eval_audit.py
python3 services/archive_transfer_r1/evals/eval_deadline.py
```

The audit hashes the ZIP, reads the sole member through EOF for CRC, and processes all messages. A snapshot replaces the book. Zero sizes delete levels. Exact Decimal comparisons preserve ordering. A backwards timestamp, out-of-window message, or backwards update identifier on a delta taints state until a fresh valid snapshot. Report counts for such intervals separately. Minute coverage and observed gaps describe available records. They cannot establish feed completeness or executable fills.

## Download a catalog batch

The catalog mode accepts the SHA-256 pinned R1 inventory CSV and an inclusive range of one to seven UTC dates from August 2 through October 30. Each selected day must include both symbols and both legs. Use a separate output directory for each batch. Rerun with the same dates, output directory and chunk size to reuse verified chunks.

```bash
python3 services/archive_transfer_r1/transfer.py \
  docs/research/crypto-r1-2026-10-31/depth_catalog_inventory.csv \
  --start 2026-08-02 --end 2026-08-02 \
  --output data/research/r1-depth-batches/2026-08-02 \
  --progress /tmp/r1-batch/progress.log
python3 services/archive_transfer_r1/evals/eval_catalog.py
```

Before starting network requests, the downloader checks free space under the output lock. It requires twice the selected compressed bytes plus 1 GiB for retained chunks, assembled archives and working overhead. This deliberately budgets a fresh copy even during resume. Catalog mode requires chunks of at least 1 MiB and an output filesystem with allocation units no larger than 64 KiB. Chunk directories must share that filesystem. The check applies to the output filesystem and does not reserve capacity against unrelated writes or concurrent batches in other directories. Keep one batch active per filesystem. Use the replay command above for ZIPs from each batch, with the matching symbol and UTC timestamps. The original October 30 JSON manifest entry point remains available without date flags.
