# IQ Option Settlement Adapter Boundary

## Implemented contract

`IQOptionSettlementGateway` converts one exact closed-option history record into
the platform's authoritative `BinarySettlement`. It validates the exact broker
order ID and stake, recognized outcome, outcome-consistent cash flow, and a
broker-supplied close or expiration timestamp.

An absent record or empty status returns `None`, leaving the order pending for
a later restart-safe pass. Contradictory evidence raises an error and is never
persisted.

## Why legacy result methods are excluded

The bundled unofficial client methods such as `check_win_v4` wait on
process-local WebSocket state and may block indefinitely. That state is absent
after restart. Balance comparison and forced determination are estimates and
cannot become authoritative settlement or training labels.

The adapter therefore depends on an asynchronous exact-order port:

```text
find_closed_option(broker_order_id) -> closed record or None
```

The future transport owns pagination, bounded timeouts, retries, rate limits
and reconnect behavior. Exact lookup avoids silently stranding an old order
outside a fixed recent-history window.

## Deliberately not implemented

- no bridge to the legacy `stable_api` client;
- no worker startup task or automatic polling;
- no credentials, broker call, or live-server deployment;
- no balance-derived fallback.

Before practice integration, capture and redact representative responses,
establish pagination behavior, implement the bounded transport, and run replay
plus practice-account tests. Response drift remains an explicit risk because
the integration is unofficial.
