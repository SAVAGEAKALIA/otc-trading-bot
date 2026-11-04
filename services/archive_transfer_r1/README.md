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
