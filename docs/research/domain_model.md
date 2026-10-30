# Phase 1 Domain Model

## Scope

Phase 1 adds immutable, broker-independent value objects under `src/trading_platform/domain`. It does not replace or modify `iqoption_bot` runtime models yet.

## Invariants

- Every financially relevant record carries an explicit `TradingEnvironment`.
- Combining different environments fails with `EnvironmentMismatchError`.
- Money and quantity use finite `Decimal` values; money cannot be negative and order quantity must be positive.
- Instrument identity includes venue, product type, symbol and settlement asset.
- Event timestamps must be timezone-aware UTC, and receive time cannot precede event time.
- Signal confidence is finite and bounded to `[0, 1]`; signal expiry must follow decision time.
- An approved risk decision must preserve a non-empty limits snapshot.
- A rejected risk decision must include reasons.
- An order intent requires an approved risk decision for the exact signal and environment.
- Limit orders require a limit price; market orders reject one.
- Illegal order-state transitions fail closed.
- Domain event and order intent records have explicit JSON-safe codecs for durable boundaries.

## Current types

- environments: research, backtest, shadow, paper, testnet, micro-live and live;
- products: binary option, spot, linear perpetual and inverse perpetual;
- signals: abstain, CALL, PUT, buy, sell, open long, open short and close;
- order types: market, limit, stop-market, stop-limit and binary;
- lifecycle: intent recorded, submission started, acknowledged, partially filled, filled, canceled, rejected, expired and unknown.

## Compatibility strategy

Legacy `TradeSignal`, `TradeRequest`, `ScannerSignal` and related classes remain unchanged. Phase 2 will introduce adapters/facades that translate them into the new domain records. This prevents a flag-day rewrite and preserves the 143-test Phase 0 baseline while the new model is validated independently.

## Verification

- Phase 1 domain tests: 22 passed.
- Full repository suite after Phase 1: 165 passed.
- Bytecode compilation: passed for `src/trading_platform`.
- Existing pandas-ta deprecation warning remains unchanged.

