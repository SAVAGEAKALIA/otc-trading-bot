# Deterministic Simulated Broker Contract

## Purpose

The Phase 3 simulator provides a safe execution target for unit tests,
historical replay, paper workflows, and later risk/OMS development. It is an
execution test double, not evidence that a strategy is profitable and not yet a
full exchange microstructure simulator.

## Supported behavior

- manual UTC clock with monotonic advancement;
- spot/perpetual-style market and limit orders;
- bid/ask-aware deterministic fills;
- configurable side-aware slippage and maker/taker fees;
- deterministic partial-fill fractions;
- idempotent `client_order_id` handling;
- scripted rejection, disconnect, and timeout failures;
- signed perpetual funding cashflows;
- separate fixed-expiry CALL/PUT binary contracts with payout-dependent PnL;
- stable event sequence, order IDs, fill IDs, timestamps, fills and PnL for
  identical configuration and inputs.

## Fail-closed boundaries

- `live` and `micro_live` environments are refused;
- generic binary, stop-market, and stop-limit intents are rejected because
  their semantics are not implemented;
- a market order without a current quote is rejected;
- malformed quotes, non-positive marks/settlement prices, zero stakes, early
  binary settlement, invalid payout ratios, and backwards clock movement fail;
- binary options travel through an explicit fixed-expiry interface rather than
  pretending to be ordinary spot/perpetual orders.

## Deliberate limitations

The simulator does not yet model queue priority, order-book depth, latency,
liquidation, maintenance margin, cross/isolated margin, reduce-only position
validation, portfolio balances, cancellations, stop triggering, or exchange
precision filters. Those belong in later vertical slices and must be added with
fixtures before their results are considered realistic.

## Verification

- Phase 3 focused tests: 11 passed.
- Full repository suite: 183 passed.
- No network call or trade was made.
