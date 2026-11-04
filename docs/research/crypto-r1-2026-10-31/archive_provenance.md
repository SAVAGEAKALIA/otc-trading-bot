# Official archive provenance resolved

Research date: November 2, 2026. This addendum supersedes only the **unverified publisher provenance** conclusion in the earlier depth report. Historical margin rules, full archive integrity and execution admission remain unresolved.

## Result

November 4 update: [the four downloads and full replays are complete](full_day_archive.md). The interrupted transfer below is retained as the original attempt record.

A fresh visible Chromium session loaded the [official historical-data page](https://www.bybit.com/en/derivative-activity/history-data). Its public JavaScript calls `/quote/public/support/download/list-products`, `list-options` and `list-files` through the site's `/x-api/` route. The product response names OrderBook. The official file-list responses return the exact four October 30 BTCUSDT/ETHUSDT spot/perpetual ZIP URLs on `quote-saver.bycsi.com`, with sizes matching the earlier candidate probes.

This establishes that Bybit's public download catalog publishes these exact links. It does not establish legal ownership of every host, verify every file ever hosted there, or certify correctness and completeness of the downloaded market data. The earlier third-party lead is now corroborated by a primary-source link chain.

The [manifest](archive_provenance_manifest.json) preserves source request URLs, exact returned file URLs, metadata and local artifact hashes. Primary file-list route, with `bizType=spot` or `contract`:

```text
https://www.bybit.com/x-api/quote/public/support/download/list-files
  ?bizType=spot
  &productId=orderbook
  &symbols=BTCUSDT%2CETHUSDT
  &interval=daily
  &periods=
  &startDay=2026-10-30
  &endDay=2026-10-30
```

Direct Python requests had returned 403, while ordinary public-page browser requests succeeded. No login, account cookies, security challenge bypass or location masking was used. The Playwright skill guided the fresh-browser inspection; an already installed Playwright package was used directly after its skill wrapper could not locate that package. No package installation or repository runtime change was needed.

## Evidence and independent review

Retained artifacts are under `data/research/r1-depth-20261102/provenance/`: official-page HTML, loaded-script URLs, official history-page JavaScript, product response, spot/contract file-list response wrappers and browser script. Raw artifacts remain ignored by Git and local-only. The browser script's package path is machine-specific; reuse requires resolving the local installed Playwright path.

Independent review **PASS**: `/tmp/crypto-r1-provenance/critique/source.md`, with `source-checks.json` alongside it. The critic compared exact URLs and sizes to the previous prefix manifest and inspected the official-script catalog route. Its own direct replay received 403, so the verdict validates the retained browser evidence rather than claiming a second successful catalog fetch.

## Full-file transfer outcome

Attempted the four complete October 30 archives, totalling **704,379,826 bytes** according to the catalog. Two spot downloads started; the bounded two-worker downloader retained **10,485,760 bytes combined** before it was deliberately stopped. The two contract downloads had not started. Whole-file transfer was extremely slow; a four-request larger-range experiment encountered a read timeout. A separate 65,536-byte HTTP/2 range succeeded. These observations do not establish that the host is permanently unavailable or that a particular transfer protocol will solve it.

The two retained files now end in `.zip.partial`; their byte counts and prefix hashes are recorded. No download job remains running. Full-file CRC checking and full-day replay **did not run**. The prepared local validator has not been validated against complete real files and is not a shipped service or an executed test result.

Progress and termination evidence: `/tmp/crypto-r1-provenance/progress.log`. Partial download state: `data/research/r1-depth-20261102/complete/partial_manifest.json`. Neither a valid earlier prefix nor a verified publisher URL makes these partial files complete archives.

## Updated admission state

| Gate | Before | Now |
|---|---|---|
| Official publisher links for four named archives | Unverified third-party lead | Verified through official public catalog |
| Complete file bytes and CRC | Prefixes only | Still incomplete; larger partials retained, CRC not run |
| Full-day book replay and gap assessment | Not done | Not done |
| Full 90-day depth inventory | Not done | Not done |
| Historical margin/collateral tier versions | Incomplete | Unchanged |
| Account-specific fees, permissions and risk limits | Unresolved | Unchanged |

The immediate blocker for complete sample validation is data transfer, not missing source provenance. A future retry should use the exact catalog URLs, retain partials without overwriting evidence, verify remote size/version before resuming, and run full-file checks only after all expected bytes arrive. Do not append range data without validating the server's returned Content-Range and byte count. If the remote file changes, retain the old partial as a separate artifact and start a new version.

No funds moved, no account was accessed, and no trading or R2 experiment was started. No service restart is needed. Next: complete the four archive transfers on a working connection, then run and independently review full-file validation; margin-history admission remains a separate gate.

## Delivery checks

Final independent review PASS for the bounded provenance report: `/tmp/crypto-r1-provenance/critique/final.md`, with hashes/process checks in `final-checks.json`. Existing R1 tests and offline evals pass. This verdict does not mark archive acquisition or validation complete.

Self-rating: 8/10. Proud of the verified source audit: yes; satisfied with complete archive validation: no. The two gaps are unfinished full-file validation and local-only evidence storage. Those gaps remain explicit rather than being scored as success.
