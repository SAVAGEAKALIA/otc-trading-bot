# Multi-Market Platform Risk Register

Ratings are preliminary Phase 0 assessments. `Owner` names a responsibility, not a person.

| ID | Risk | Likelihood | Impact | Current evidence | Mitigation / gate | Owner |
|---|---|---:|---:|---|---|---|
| R-001 | Apparent OTC edge is leakage or multiple-testing noise | High | Critical | Many strategies/models and evolving filters | Immutable datasets, trial registry, purged walk-forward, untouched test, shadow evidence | Quant research |
| R-002 | Collector fills remaining disk | Medium | Critical | 2.79 GB DB; 17 GB free; ongoing growth | Health alerts, retention/downsampling, snapshots, protective degradation | Data operations |
| R-003 | Live SQLite snapshot is inconsistent | Medium | High | WAL-mode live collection | SQLite online backup; manifest/checksum validation; never copy main file alone | Data engineering |
| R-004 | IQ Option integration changes or violates applicable terms | Medium | Critical | Community/vendored protocol implementation | Legal/terms review; isolate adapter; practice/shadow first | Product/legal |
| R-005 | Restart loses in-memory trades/state | High | Critical | `active_trades` and session state in memory | PostgreSQL ledger, intent-before-submit, recovery-only startup and reconciliation | Execution |
| R-006 | Balance fallback misclassifies settlement | Medium | High | Existing result fallback under concurrency | Direct settlement authority; mark unverified; exclude from learning | OTC adapter |
| R-007 | Martingale amplifies loss | Medium | Critical | Reachable legacy commands and modules | Disabled migration profile; remove from future live path | Risk |
| R-008 | Telegram enables unsafe mode/risk mutation | Medium | Critical | Account switch, dry-run and martingale commands exist | New role/approval console; no direct broker or limit-raising tools | Security/operations |
| R-009 | Duplicate crypto order after timeout/retry | Medium | Critical | Normal exchange failure mode | Durable client IDs, unknown-state reconciliation, no blind retry | OMS |
| R-010 | Partial fill/local position mismatch | Medium | Critical | Crypto lifecycle differs from OTC | Execution-driven state machine and continuous venue reconciliation | OMS |
| R-011 | Perpetual liquidation from leverage/margin error | Medium | Critical | Planned new product | Isolated low leverage, maintenance-margin data, liquidation buffer and reduce-only exits | Risk |
| R-012 | Stale/gapped WebSocket data triggers trades | Medium | High | Disconnects expected; current client reconnect complexity | Sequence/freshness validation; fail-closed trading suspension | Market data |
| R-013 | Hermes prompt injection reaches privileged actions | Medium | Critical | General agent can use tools/memory/content | Separate secretless host, allowlists, schemas, opaque actions, no direct broker tool | Agent security |
| R-014 | Agent outage blocks trading safety | Low | High | Potential orchestration dependency | Agent remains outside critical path; deterministic safety continues | Architecture |
| R-015 | Testnet behavior differs from production | High | High | Common exchange limitation | Micro-live with strict limits; execution-quality comparison | Execution research |
| R-016 | Dirty worktree obscures provenance | High | High | Extensive pre-existing modifications/untracked files | Preserve changes; inventory; small additive phases; no broad rewrites | Engineering |
| R-017 | Test suite cannot establish baseline | High | High | `pytest` initially absent | Pinned dev requirements; run/classify suite before refactor | Engineering |
| R-018 | Ambiguous Docker data mount writes to wrong location | Medium | High | Bind mount and anonymous relative volume observed | One absolute `DATA_DIR`; one volume; deployment path test | Operations |
| R-019 | Cloud dataset upload leaks secrets/account data | Low | Critical | Manual/cloud export planned | Explicit allowlist export, forbidden-file tests, private dataset, manifest review | Data security |
| R-020 | Research scripts diverge between Kaggle/local/live | High | High | Multiple large standalone trainers | Portable training CLI, shared features, artifact parity fixtures | ML engineering |

## Immediate stop conditions

- unresolved broker/local position mismatch;
- database write failure during order intent or execution processing;
- stale private stream while exposure exists;
- unknown order submission result without successful reconciliation;
- model/artifact/schema mismatch;
- clock drift outside declared venue tolerance;
- disk safety threshold or snapshot integrity failure;
- any evidence that credentials or sessions entered a research bundle;
- any attempt by an agent or Telegram layer to bypass deterministic risk.

