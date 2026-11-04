# October 30 Bybit depth archive validation

Completed November 4, 2026. All four catalog archives for BTCUSDT and ETHUSDT spot and perpetual passed complete transfer, SHA-256, expanded byte-count and ZIP CRC verification. Full replay processed 3,325,753 messages across 704,379,826 compressed bytes and 3,928,074,954 expanded bytes. The [manifest](full_day_archive_manifest.json) records exact source versions and results.

| Market | Messages | Excluded after UTC cutoff | Observed UTC minutes |
|---|---:|---:|---:|
| BTC spot | 828,721 | 10 | 1,440 |
| ETH spot | 769,960 | 20 | 1,440 |
| BTC perpetual | 863,948 | 6 | 1,440 |
| ETH perpetual | 863,124 | 1 | 1,440 |

Replay reconstructed 3,325,716 in-window states. No empty or locked/crossed reconstructed states were observed. The 37 excluded records fell beyond the requested half-open UTC window. Minute coverage measures the presence of records. Feed continuity, execution capacity, and liquidation behavior require separate evidence.

The selected implementation uses eight range workers per file and version-pinned chunk receipts. The initial download used the reviewed variant before the final deadline and single-member integrity corrections. Independent full-file verification subsequently read all four sole ZIP members to EOF and checked actual expanded sizes, CRCs and hashes. The final transport also passed a live one-byte range smoke test. The two spot replays used the same exact Decimal replay logic before the cache optimization. Independent ZIP checks cover the expanded-size validation added afterward.

The [archive transfer and replay service](../../../services/archive_transfer_r1/README.md) documents reproduction. All 24 new gate tests passed. Adverse checks cover HTTP stalls, resumptions, incorrect ranges and identities, CRC and size failures, and a 40,000-update replay oracle. Independent code review passed at `/tmp/r1-archive-transfer/critique/shipping.md`. Independent data checks at `/tmp/r1-archive-transfer/critique/actual-files.md` matched all four replay record counts after refresh.

Raw archives and reports remain in `data/research/r1-depth-20261102/` on this machine. This completes the one-day archive sample. The 90-day depth inventory, margin and collateral history, account permissions and costs remain open for R2 admission.

Self-rating 9/10. Proud of the completed acquisition and replay. Raw evidence still needs off-host backup. No service restart is required.
