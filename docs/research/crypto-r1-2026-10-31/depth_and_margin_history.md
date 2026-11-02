# Historical depth and margin evidence

Review completed November 2, 2026, continuing November 1 research. R1 public-data work only. No order, account access, paid data, production deployment or R2 experiment.

## Decision

Update: the later [official catalog inspection](archive_provenance.md) resolves publisher provenance for the four named archives. The observations below remain the original probe record; integrity, continuity and rule-history limitations still apply.

**Historical execution and liquidation admission remain blocked.** We now have accessible candidate depth files and a confirmed in-window leverage-change notice. Neither establishes a complete, officially sourced history of executable books and account-applied margin parameters.

Continue to use the acquired prices for explicitly hypothetical research. Do not describe an adverse-cost simulation as historical execution validation. Resolve archive provenance before a large depth backfill. If historical evidence cannot be obtained, use prospective public capture with explicit gaps and newly observed rule versions; it cannot repair the old 90-day window.

## Order-book candidate: observed, not admitted

The official [historical download page](https://www.bybit.com/en/derivative-activity/history-data) renders a filter shell in the web text tool; a direct request returned HTTP 403. We did not bypass that response. Searches of official Bybit/docs domains did not establish a link to the candidate host. Absence from these results does not prove the host is unofficial.

The third-party [downloader source](https://github.com/Anton495/bybit-data-downloader/blob/main/bybit_futures_orderbook.py) identifies `quote-saver.bycsi.com/orderbook/linear/`; its [spot counterpart](https://github.com/Anton495/bybit-data-downloader/blob/main/bybit_spot_orderbook.py) identifies the spot route. Those are implementation leads, not proof of ownership or authorization by Bybit. No third-party code was executed or installed.

We queried four candidate directory indexes and retained a 65,536-byte HTTP range prefix from each October 30 ZIP. All returned HTTP 206 with matching requested ranges. The [manifest](depth_probe_manifest.json) contains URLs, hashes, lengths, timestamps and false admission flags. The prefixes are quarantined from the admitted price dataset.

| Candidate | Complete JSON messages decoded from prefix | Snapshots observed | Locked/crossed reconstructed states |
|---|---:|---:|---:|
| BTC spot | 408 | 1 | 0 |
| ETH spot | 314 | 1 | 0 |
| BTC perpetual (`linear`) | 86 | 1 | 0 |
| ETH perpetual (`linear`) | 105 | 1 | 0 |

Each prefix begins with a snapshot, followed by deltas, and identifies `orderbook.200.<symbol>`. JSON contains `topic`, `type`, system time `ts`, matching-engine time `cts`, and symbol/bid/ask/update-ID/sequence fields. Symbol and positive-price/nonnegative-size checks passed; no backwards system timestamps were observed. This is a small schema and application check, not a full-day replay or a claim of a complete 200-level book after every update.

The bounded decoder reads the ZIP local header and partially decompresses one member without extracting files. Partial final JSON lines are discarded. It does **not** have the ZIP central directory, full-member CRC validation or a proof that messages were never omitted. No sequence-contiguity assumption was imposed: the documented cross-sequence field is an ordering reference, not a promise that every observed number increments by one.

Raw artifacts and the probe/check scripts are under `data/research/r1-depth-20261102/`, ignored by Git and locally durable only. Run the offline observed-prefix checks with:

```bash
python3 data/research/r1-depth-20261102/check_prefix.py
```

Do not use Python `-O`, which removes research assertions. These are bounded research scripts, not production collectors. The committed manifest preserves hashes and URLs; the raw bundle must be separately transferred for another host to reproduce the checks.

## What the official stream contract actually supplies

The [official WebSocket order-book contract](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook) specifies replacement on snapshot, delete-on-zero quantity, insertion and update of price levels, and reset handling. It distinguishes exchange/system and matching-engine timestamps and excludes RPI orders from this stream. A matching archive schema alone does not prove archive provenance or uninterrupted recording.

For a future public collector, preserve raw messages, receive times, subscriptions, reconnects and resets for both legs. Start replay only from a snapshot. Invalidate an interval on disconnect or uncertain state and wait for a new snapshot. Check ordering using the actual documented semantics; do not invent `seq+1` completeness. Persist matching trade/rule snapshots separately. Depth is observable liquidity, not maker queue position, hidden liquidity or guaranteed counterfactual fills.

This is a proposed fallback design. No background collection or service was started. Starting now would yield prospective data only, not an untouched strategy experiment or retroactive coverage.

## Dated margin evidence

The [official August risk-limit notice](https://announcements.bybit.com/en/article/risk-limit-adjustment-for-selected-perpetual-contracts-aug-20-2026--artd5e4344ee603/) is published August 18, 2026 and says the adjustments take effect **by August 20, 2026 at 08:00 UTC**. Its table changes the maximum leverage for BTCUSDT and ETHUSDT from 100 to 150. Preserve “by”: this is not an observed exact account-transition timestamp.

The notice does not provide every tier's notional boundary, initial/maintenance margin rate, maintenance deduction or collateral haircut. It therefore proves that parameters changed during the R1 window, not a complete historical tier schedule. Maximum permitted leverage is not the trial's chosen leverage; our conservative 1x assumption is unchanged and does not prove immunity from liquidation.

The current [risk-limit help page](https://www.bybit.com/en/help-center/article/Risk-Limit-Perpetual-and-Expiry-Contracts), labelled updated September 4, 2026, describes trial risk assessment and account-dependent application: lower-risk accounts receive adjustments directly; higher-risk accounts may receive a ten-day buffer and restrictions on increasing exposure. Treat this as a currently retrieved description, not evidence that the identical rule applied on August 2 or that a specific account used a particular transition time.

The [public risk-limit API](https://bybit-exchange.github.io/docs/v5/market/risk-limit) supplies current tiers, not a documented `as_of` history request. Today's tier table cannot be attached to all earlier candles. No complete BTC/ETH tier/haircut change history was verified by this search; this does not prove none is obtainable from the exchange.

| Required historical record | Evidence available | Admission state |
|---|---|---|
| Publication date and stated deadline for August leverage change | Official dated notice | Verified notice, not exact deployment |
| Full old and new tier tables, deductions and collateral rules | Not established | Missing |
| Effective transition per account/margin mode | Current help describes conditional application; no account record | Missing |
| Complete August 2 to October 30 rule inventory | Search results are not an exhaustive version history | Missing |
| Mark path and actual portfolio/order state during transitions | Hourly reference prices only, no account or intrabar path | Insufficient for liquidation validation |

Future rule records need: source URL/hash, publication and retrieval times, explicitly stated effective boundary, instrument/category, account/margin-mode scope, full tier version, collateral version and superseded version. Keep `effective_at` unknown when a notice only supplies a deadline. A simulator must reject an unsupported historical-rule interval for a claimed historical liquidation result; it may run a separately labelled stress assumption without pretending the assumption was observed.

## Concrete exit conditions

Historical route: obtain an official link or authenticated publisher confirmation for the archive; validate a complete day on each leg including CRC and observed replay behavior; establish full declared-window inventory and gap policy; obtain dated tier/collateral versions and account application rules. A complete ZIP only closes file integrity, not market completeness.

Prospective route: build and test an isolated public stream/rule recorder, preserve gaps and versions, and gather new observations. Account fees and permissions still require account-specific facts. The original historical research remains descriptive where rules or execution inputs are missing. This alternative needs no assumption that the user must transfer funds now.

## Validation and delivery

Independent cold review: PASS, `/tmp/crypto-r1-depth/critique/final.md`, with reproduced hash/count/source checks in `verification.txt` alongside it. Existing R1 gate suites and adverse accounting evals pass; no new runtime feature was shipped and these checks make no profitability claim.

Self-rating: 9/10; proud: yes. One point remains for evidence portability: raw artifacts and inspection scripts are local-only rather than off-host replicated. The missing historical source/rule proof is explicitly recorded as the admission outcome, not assumed away.

Next action: resolve the archive's publisher provenance and full rule history, or explicitly adopt prospective capture for execution validation. No restart required.
