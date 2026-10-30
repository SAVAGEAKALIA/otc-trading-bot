# Phase 12 Hermes Provider Contract

The optional research-agent integration is represented by an injected,
provider-neutral contract:

- versioned prompts with strict structured response parsing;
- bounded timeout and cost budgets;
- explicit read-only tool allowlists with unauthorized requests denied;
- adversarial/prompt-injection fixtures retained as inert text;
- offline evaluation reports for valid, invalid and unauthorized outputs;
- provider outage and schema failures surfaced as fail-closed errors.

No Hermes package, credentials, network connector or broker capability is
required. A provider may be added later only behind this contract.
