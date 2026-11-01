# Crypto R1 Implementation Plan

**Goal:** produce reproducible public research evidence and a test-ready specification for broader crypto research, while keeping all live authority disabled.

**Architecture:** retain the existing trading platform unchanged. Independent `services/market_data_r1/` and `services/research_r1/` directories own bounded public collection and hypothetical cost/config validation respectively; reports communicate through versioned JSON artifacts. No exchange credentials or order endpoints.

**Tech Stack:** Python standard library, existing public Bybit V5 endpoints and existing funding evidence, Markdown/JSON/CSV reports, unittest gate tests and scenario evals.

Authorization: R1 explicitly approved. Nigeria and USDT reference confirmed; Bybit, WEEX and Binance accounts user-reported. No paid service authorized. Direct external spending ceiling is zero. Bound first collection to ten candidate assets and ninety complete UTC days, plus current metadata/quotes. Stop on missing access rather than circumvent restrictions. No full portfolio tests, installation of trading frameworks or forecast models in R1. Final scenario example uses reserve_per_notional=0.5 to match the selected 40/40/20 protocol; earlier explicit 0.2 stress/test inputs remain independent sensitivities.

The skill's suggested handoff/new-session prompts are superseded by the user's existing authorization to execute this stage. Existing shared-workspace agents own disjoint directories. Acceptance reference was frozen before implementation at `/tmp/crypto-r1/critique/rubric.md`.

### Task 1: Evidence preservation

- Preserve the old funding JSON by SHA256 under ignored `data/research/archive/`; compare bytes and hash.
- Write `docs/research/crypto-r1-2026-10-31/archive_manifest.json` with source location, archive relative path, hash and row count, clearly local-durable but not off-host replicated.
- Never commit raw data or credentials.

### Task 2: Public market-data evidence

- Agent owns `services/market_data_r1/` code, offline tests/scenario evals and README.
- Compare extending the old script against a self-contained collector; old script lacks validated API errors, coverage and timezone-safe cutoffs.
- Capture paired spot/linear current metadata, quotes, recent settled funding, daily spot/perp/mark/index and current risk tiers where available.
- Verify duplicate/conflict, missing-day/cadence, incomplete-bar and API failure behavior. Keep raw payloads with hashes under ignored data, portable summaries under docs.
- Record deterministic progress from completed request counts in `/tmp/crypto-r1/data-progress.log`.

### Task 3: Config and hypothetical economics

- Create `services/research_r1/scenarios.py`, `tests/test_scenarios.py`, `evals/eval_scenarios.py`, `config.example.json`, `README.md`.
- First test 1x short plus fully paid spot requires 2N before reserves, nonfinite/negative inputs reject, fixed cost breaks low-capital economics, null budgets prevent readiness, and research mode cannot authorize orders.
- Implement Decimal calculations and deterministic hypothetical CSV output. Formulas: `N=C/(1+1/leverage+reserve_per_notional)`; `excess=C*(net_notional_rate/(1+1/leverage+reserve_per_notional)-benchmark_rate)-annual_fixed_cost`. No idle yield assumed. Rates are hypothetical net of variable costs, not forecasts.
- Run `python3 -m unittest discover -s services/research_r1/tests -v`; expected all pass.
- Run `python3 services/research_r1/evals/eval_scenarios.py`; expected invariants pass across zero/negative funding, capital/cost and reserve cases.
- Run scenario CLI into `docs/research/crypto-r1-2026-10-31/economics_scenarios.csv`.

### Task 4: Eligibility and trial freeze

- Separate agents own `eligibility_benchmark.md` and `experiment_spec.md`.
- Treat USDT holding as reference with zero contractual holding interest, not a USD risk-free claim. Earn rates/account entitlements remain unverified until evidence.
- Compare BTC/ETH primary plus broader secondary research against a broad-primary design. Freeze method/trial budget before R2; unresolved account/cost fields cannot silently default to live-safe values.

### Task 5: Integration, cold critic and delivery

- Assemble R1 report with source manifests, data gates, hypothetical economics and actionable remaining account/budget questions.
- Update main plan with approval, actual scope and stage status.
- Run independent cold review against frozen rubric. Correct findings and rerun relevant tests.
- Rate final artifacts, commit and push. No production service restart.
