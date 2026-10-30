# Phase 11 Durable Workflow Kernel

The provider-neutral safety contract for later LangGraph integration is now in
place:

- immutable JSON-safe checkpoints with deterministic state digests;
- atomic local persistence and restart recovery;
- monotonic revisions and idempotent completed-step resume;
- explicit approval interrupts with identity matching;
- an allowlisted read-only tool registry that denies unknown tools;
- malformed-state and malformed-checkpoint rejection;
- prompt-injection text remains inert data and cannot create tool authority.

The kernel has no broker, ledger mutation or credential dependency. A future
LangGraph adapter may orchestrate these primitives, but must preserve this
contract and remain outside deterministic execution.
