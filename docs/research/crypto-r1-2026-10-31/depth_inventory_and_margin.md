# 90-day depth catalog and margin evidence

On November 4, 2026, Bybit's official catalog listed all 360 expected BTC/ETH spot and perpetual depth ZIPs for August 2 through October 30, 2026 UTC. Each of the four series has 90 distinct dates. The four archive directory listings corroborated every expected filename. The full-window catalog request returned application error 10016. All 26 seven-day-or-shorter queries succeeded. [Official catalog](https://www.bybit.com/en/derivative-activity/history-data)

| Market | Files | Listed compressed bytes |
|---|---:|---:|
| Spot | 180 | 8,835,515,728 |
| Perpetual | 180 | 29,115,383,803 |
| Total | 360 | 37,950,899,531 |

The [file inventory](depth_catalog_inventory.csv) contains exact URLs and listed byte sizes. The [manifest](depth_catalog_inventory.json) records request URLs and response hashes. Validation checked unique date/symbol/market keys, positive sizes, expected filenames and archive paths. Raw catalog evidence and the acquisition and check scripts are in the ignored local directory `data/research/r1-depth-20261102/inventory/`.

The four October 30 files have passed transfer and full replay. At inventory time, the remaining 356 files represented 37,246,519,705 listed bytes. The catalog batch helper now accepts one to seven days from the pinned inventory. See the pilot update below. [October 30 replay](full_day_archive.md)

## Historical margin rules

The August 18 notice records an increase in maximum leverage from 100x to 150x for BTCUSDT and ETHUSDT by August 20 at 08:00 UTC. It supplies neither full tier tables nor an observed account transition timestamp. [August notice](https://announcements.bybit.com/en/article/risk-limit-adjustment-for-selected-perpetual-contracts-aug-20-2026--artd5e4344ee603/)

The BTC example embedded in Bybit's risk-limit help page shows an older-looking 100x first tier and several associated risk parameters. The image has no verified capture date. Its 100x tier shows a zero maintenance deduction, while the current BTC 100x tier shows 510 USDT. Even matching rates and notional limits are insufficient to carry deductions across versions. The November 4 public API snapshots provide 35 current rows per contract. Both first tiers in those snapshots show a 300,000 USDT limit, 150x maximum leverage, 0.66% initial margin and 0.33% maintenance margin. No effective interval is inferred from the snapshot. [Risk-limit guide](https://www.bybit.com/en/help-center/article/Risk-Limit-Perpetual-and-Expiry-Contracts) · [Public API contract](https://bybit-exchange.github.io/docs/v5/market/risk-limit)

The UTA guide lists a USDT collateral ratio of 100% for its cross/portfolio calculation, consistent with the November 4 public collateral snapshot. The guide values assets with an index price as well as a collateral ratio. A 100% ratio therefore does not establish a USD peg or an invariant historical account value. Spot borrowing tier notices and loan collateral schedules apply to different products. [UTA guide](https://www.bybit.com/en/help-center/article/Introduction-to-Bybit-Unified-Trading-Account)

Full effective-dated BTC/ETH tier, deduction and collateral history remains unverified. Keep historical liquidation admission closed. Prospectively retain rule snapshots and match applicable account settings before testing venue-specific liquidation behavior. Raw snapshot hashes are in the manifest.

Independent review passed. See `/tmp/r1-inventory/critique/final.md` and `verification.txt` in the same directory. Self-rating 9/10. Proud of the verified inventory and source checks. The historical margin schedule remains the gap. No restart is required.


## Catalog batch pilot

The August 2 batch acquired and CRC-verified all four archives, 268,698,982 bytes, with zero transfer errors. Eight files across two dates now have ZIP integrity evidence. The four October 30 files and four August 2 files now have full replay evidence. The August 2 [pilot manifest](first_catalog_batch.json) preserves hashes and versions.

The catalog entry point pins the inventory SHA-256, validates all four market/symbol keys per requested day, and requires twice the selected bytes plus 1 GiB of available output space. I chose a seven-day maximum and conservative resume budget to limit resource use. The original October 30 manifest entry point is preserved. The final storage-guard changes were covered by offline tests after the live run started. The live pilot exercised the same catalog selection and transfer path. [Usage](../../../services/archive_transfer_r1/README.md)

Twenty-eight service tests passed. The catalog eval partitions the same 360 unique archives at every batch size from one to seven days. No historical margin or R2 admission flags changed.

Independent pilot review passed at `/tmp/r1-batch/critique/final.md`. Independent checks matched all four ZIP hashes, sizes and CRCs. Self-rating 9/10 for the catalog downloader and pilot. Proud of the transfer result. The pilot transfer review preceded the August 2 replay below. No restart required.


## August 2 replay and why we need the history

All four files completed replay. Independent checks matched 2,970,590 messages and coverage of all 1,440 UTC minutes per file. The replay excluded 70 post-midnight messages and reconstructed 2,970,520 in-window states. [Replay manifest](august02_replay_manifest.json) · Independent review at `/tmp/r1-aug02/critique/independent-review.md`.

The objective is to establish whether a signal retains value after realistic execution costs. Funding and price history support a cheap first screen. Depth replay adds historical spreads, displayed size and changes between leg submissions. For spot/perpetual carry, compare funding plus the change in basis against fees on entry and exit, spread, modeled slippage and any unhedged exposure. Compare the result with holding USDT over the same interval.

For multi-agent signals, use the same simulator, sizing, costs and decision times for a deterministic baseline, a single analyst, independent votes and bounded debate. Keep development history separate from the prospective evaluation. A better forecast or a more persuasive rationale only matters if it produces a measured improvement after costs.

The 90-day catalog establishes availability. Before a full 37.95 GB backfill, freeze the hypotheses, decision cadence and sampling rule. Use selected periods to check the replay and estimate cost sensitivity. Expand coverage when the experiment needs it. A sparse sample cannot validate performance across the full window. Displayed depth can inform a simulated taker fill, but the replay does not observe the user's queue position, network delays or market response to a hypothetical order. Historical liquidation also needs effective-dated margin rules and account inputs.

Self-rating 9/10. Proud of the second verified replay. The development sample covers two days, so broader execution-cost coverage remains unmeasured. No restart required.
