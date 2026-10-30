# Deterministic Pre-Trade Risk Engine

## Authority boundary

Phase 4 adds a pure Python pre-trade risk engine. It consumes an immutable
signal, proposed quantity/price/leverage, immutable account/market state, an
explicit UTC evaluation time, and immutable limits. It returns only an approved
or rejected `RiskDecision` tied to the exact signal ID and environment.

`OrderIntent` already refuses missing, rejected, mismatched, or cross-environment
risk decisions. The Phase 5 OMS must preserve that invariant and must not expose
an alternate broker-submission path.

## Ordered policies

Violations are evaluated in stable safety precedence:

1. kill switch;
2. environment and account-state freshness;
3. duplicate, abstain, future, stale, and expired signals;
4. instrument allowlist and market-data freshness;
5. open-order and drawdown limits;
6. order notional, instrument exposure, total exposure, and leverage;
7. leveraged-perpetual liquidation buffer.

Missing state rejects. Exact upper notional/exposure/leverage boundaries are
allowed; exceeding them rejects. Reaching the configured drawdown or open-order
limit rejects.

## Immutable inputs and evidence

- `RiskState` validates positive equity, peak equity, non-negative absolute
  exposure/open-order counts, and UTC timestamps, then freezes its mappings.
- `RiskLimits` validates all ranges and emits a JSON-safe approval snapshot.
- Approved decisions contain the actual limits used.
- Rejected decisions contain deterministic ordered reasons.
- No LLM or agent participates in evaluation.

## Deliberate limitations

- The current normalized notional is `quantity * reference_price`, appropriate
  for spot and linear contracts. Inverse-contract specifications require an
  instrument-metadata notional calculator before those products are enabled.
- Exposure inputs are snapshots supplied by the future ledger/reconciler; Phase
  5 must source them from reconciled broker truth rather than caller estimates.
- This phase does not size positions, reserve balances, model correlated risk,
  validate exchange precision, or wire the legacy OTC runtime into the engine.
- Liquidation buffer is an input to validate, not yet independently calculated
  from exchange maintenance-margin tiers.

## Verification

- Focused deterministic and property/boundary tests: 16 passed.
- Full repository suite: 199 passed.
- No broker/network call or trade was made.
