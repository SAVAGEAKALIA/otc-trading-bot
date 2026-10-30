# IQ Option Binary Execution Adapter Contract

## Scope

Phase 2 introduces a narrow asynchronous port for IQ Option fixed-expiry OTC
order submission. It deliberately does not generalize binary options into the
future spot/perpetual order interface.

The legacy call chain is now:

`APIWorker._place_trade` → `AssetResolver.place_trade` →
`BinaryExecutionPort.place_binary_order` → IQ Option `api.buy`.

No strategy, scanner, sizing, settlement, or live-account behavior was changed.

## Deterministic behavior

- A command uses `Decimal` for stake and an enum for CALL/PUT direction.
- Symbols are normalized to a base pair.
- `-OTC` is attempted before the legacy `-op` alias.
- Dynamic IDs may be supplied by the resolver cache when the library's static
  active-code map is incomplete.
- The entire blocking fallback sequence runs outside the asyncio event loop.
- A connection/closed exception returns `Connection lost` and invokes the
  worker's disconnect callback.
- Missing variants and rejected orders return structured failures.
- `AssetResolver` converts the structured result back to the existing
  `(success, order_id_or_error)` tuple.

## Runtime packaging

Docker copies `src/` and sets `PYTHONPATH=/app/src`. The transitional local
`python main.py` entry point adds its sibling `src/` directory before importing
the bot. A later packaging phase should replace this bootstrap with an installed
project package.

## Verification

- Contract tests: 7 passed using only fakes; no broker/network calls.
- Full repository suite: 172 passed.
- Bytecode compilation: passed.
- Local entry-point import smoke test: passed.

An authenticated IQ Option practice-account smoke test remains an operational
deployment gate. It must not be inferred from fake-based contract tests and no
live or practice order was placed during this phase.
