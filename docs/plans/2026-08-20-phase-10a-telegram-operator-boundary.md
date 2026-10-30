# Phase 10A Telegram Operator Boundary

The first Telegram slice is transport-agnostic and keeps the operator console
outside the execution critical path. It implements:

- viewer/operator/admin action authorization;
- user-bound HMAC callback tokens with expiry and one-time replay protection;
- typed application-port dispatch for pause, reconcile, cancel and reduce-only
  requests without importing a broker adapter;
- immutable audit events for accepted, denied, expired, replayed and failed
  callbacks;
- permanent denial of live enablement, arbitrary orders, leverage and risk
  changes through Telegram.

The actual Bot API connector, durable audit persistence and paper/testnet E2E
transport remain pending. No Telegram token is loaded and no network call is
made by this slice.
