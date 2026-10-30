# Phase 10 Crypto Research Baselines

This slice implements the offline foundation for crypto hypothesis evaluation.
`trading_platform.research.crypto` has no broker or credential dependency.

Implemented:

- immutable UTC crypto bars with exact `Decimal` prices, volume and funding;
- point-in-time universe snapshots that reject symbols before listing;
- causal momentum, breakout and mean-reversion signal baselines;
- explicit taker/maker fee, slippage, funding, leverage and gross-notional costs;
- maximum-open-position constraints;
- deterministic parameter-surface evaluation retaining every parameter result.

The module is research-only. It does not select a winner, promote artifacts,
or submit orders. Walk-forward validation, independent review and sustained
multi-regime evidence remain promotion gates.
