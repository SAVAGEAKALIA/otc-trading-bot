# 90-day depth catalog and margin evidence

On November 4, 2026, Bybit's official catalog listed all 360 expected BTC/ETH spot and perpetual depth ZIPs for August 2 through October 30, 2026 UTC. Each of the four series has 90 distinct dates. The four archive directory listings corroborated every expected filename. The full-window catalog request returned application error 10016. All 26 seven-day-or-shorter queries succeeded. [Official catalog](https://www.bybit.com/en/derivative-activity/history-data)

| Market | Files | Listed compressed bytes |
|---|---:|---:|
| Spot | 180 | 8,835,515,728 |
| Perpetual | 180 | 29,115,383,803 |
| Total | 360 | 37,950,899,531 |

The [file inventory](depth_catalog_inventory.csv) contains exact URLs and listed byte sizes. The [manifest](depth_catalog_inventory.json) records request URLs and response hashes. Validation checked unique date/symbol/market keys, positive sizes, expected filenames and archive paths. Raw catalog evidence and the acquisition and check scripts are in the ignored local directory `data/research/r1-depth-20261102/inventory/`.

The four October 30 files have passed transfer and full replay. The remaining 356 files represent 37,246,519,705 listed bytes and still require transfer, integrity checks and replay. The current downloader allowlist covers the four October 30 URLs. A broader run needs an inventory-bound allowlist and storage controls for staging, completed files and retained chunks. [October 30 replay](full_day_archive.md)

## Historical margin rules

The August 18 notice records an increase in maximum leverage from 100x to 150x for BTCUSDT and ETHUSDT by August 20 at 08:00 UTC. It supplies neither full tier tables nor an observed account transition timestamp. [August notice](https://announcements.bybit.com/en/article/risk-limit-adjustment-for-selected-perpetual-contracts-aug-20-2026--artd5e4344ee603/)

The BTC example embedded in Bybit's risk-limit help page shows an older-looking 100x first tier and several associated risk parameters. The image has no verified capture date. Its 100x tier shows a zero maintenance deduction, while the current BTC 100x tier shows 510 USDT. Even matching rates and notional limits are insufficient to carry deductions across versions. The November 4 public API snapshots provide 35 current rows per contract. Both first tiers in those snapshots show a 300,000 USDT limit, 150x maximum leverage, 0.66% initial margin and 0.33% maintenance margin. No effective interval is inferred from the snapshot. [Risk-limit guide](https://www.bybit.com/en/help-center/article/Risk-Limit-Perpetual-and-Expiry-Contracts) · [Public API contract](https://bybit-exchange.github.io/docs/v5/market/risk-limit)

The UTA guide lists a USDT collateral ratio of 100% for its cross/portfolio calculation, consistent with the November 4 public collateral snapshot. The guide values assets with an index price as well as a collateral ratio. A 100% ratio therefore does not establish a USD peg or an invariant historical account value. Spot borrowing tier notices and loan collateral schedules apply to different products. [UTA guide](https://www.bybit.com/en/help-center/article/Introduction-to-Bybit-Unified-Trading-Account)

Full effective-dated BTC/ETH tier, deduction and collateral history remains unverified. Keep historical liquidation admission closed. Prospectively retain rule snapshots and match applicable account settings before testing venue-specific liquidation behavior. Raw snapshot hashes are in the manifest.

Independent review passed. See `/tmp/r1-inventory/critique/final.md` and `verification.txt` in the same directory. Self-rating 9/10. Proud of the verified inventory and source checks. The historical margin schedule remains the gap. No restart is required.
