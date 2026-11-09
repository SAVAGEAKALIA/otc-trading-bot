# Two deterministic binary development policies

Outcome: propose falsifiable binary signals from freshly received events, with an observed offer and fixed payout floor. This package contains no account, network, order, sizing or LLM call. Neither policy has established an economic edge.

The frozen tournament uses slots4 and5. Slot4 (`leader_burst_flat_target_v1`) follows three consecutive same-direction price changes in the other named OTC feed while the target's last four genuine quotes remain flat. The leader's final receipt must strictly precede the target's final receipt; its source timestamp cannot be ahead of the target's. The target's flat window starts at/beyond the leader's burst window. Slot5 (`three_step_burst_fade_v1`) trades against three consecutive same-direction changes in the target's own latest four genuine quotes. A zero change breaks the pattern. Both tails span at most five seconds, have advancing broker source stamps and belong to one known physical session. Paired tails also require the same physical session and globally distinct contributing quote IDs. Cached, simultaneous unordered, stale or clock-invalid quotes abstain. No signal is claimed to be a calibrated probability.

The policy scope remains EURUSD-OTC/GBPUSD-OTC. Root may expand the running baseline's universe separately; these paired-feed policies need a separate prospective registration before an asset expansion. The three-change/five-second choices are fixed exploratory design choices, not empirically optimized OTC parameters. Source-clock freshness and the signed broker/receiver clock-offset limit use integer nanoseconds without truncating a fractional age or offset into eligibility.

`contracts.py` defines frozen `Quote`, `Clock`, `Offer`, `Context`, `Pattern` and `Decision` data. `decide(policy, context)` requires the latest causally received explicit open turbo offer for a two-minute request, observed payout at least0.80, fresh synchronized broker time and a proposed expiry explicitly present in that offer. The actual remaining expiry must be90–150 seconds by the received broker clock. `Context.proposed_expiry_ms` is supplied by the root's contract-aware transport; this module never invents an expiry from a candle close. A newer negative/unknown offer invalidates the previous payout immediately, even while the old offer remains within its ten-minute age cap. Exact simultaneous conflicting offers or clocks abstain. Reusing a causal offer ID for contradictory evidence also abstains.

Future quote, offer and clock payloads with known receiver timestamps are ignored before body validation. Present malformed timestamps fail closed. Quote evidence is local to the past60-second window; decisions retain the four or eight contributing IDs. The root transport must maintain the source's full immutable identity ledger, validate an explicit practice balance and minimum permitted stake, enforce one global position, handle unknown order outcomes without retry, and reconcile actual cash settlements. A `Decision` is a proposal, never permission to execute by itself.

`pattern_signal()` returns a distinct `Pattern` marked `preoffer_mechanism_only`. It has no expiry or payout and cannot be used as an order proposal. This supports explicit source diagnostics without manufacturing offer coverage. `unit_return()` is optional quote-proxy accounting with row-specific payouts, full-refund ties and full-loss unresolved outcomes. Authoritative broker cash supersedes that assumed tie/proxy arithmetic.

Run local gates from the package root:

```bash
python3 -m unittest services.otc_deterministic_strategies_new.tests.test_policies
```

Run the larger deterministic causal/accounting eval:

```bash
python3 -m services.otc_deterministic_strategies_new.evals.eval_causality --output /tmp/otc-new-strategy-eval
```

The100% pass threshold applies to causal invariance, negative-offer handling and exact arithmetic. It does not grade real profitability. No model behavior exists to measure through paid LLM evals.

The old archive lacks explicit open/negative offer state, actual offered/accepted expiries, accepted strikes, cash settlement and physical receiver-session IDs. Therefore these exact event policies cannot receive historical economic scores from it. The archive's existing next-source-tick associations measure a different horizon. Sparse later quotes cannot repair that mismatch by choosing longer freshness limits. See `sources.md` for the primary-source search and `failure-prevention.md` for regression prevention.

Deploy requires no service restart for this standalone library. Root must freeze any selected source version into a separate prospective practice configuration before calling it from the running bot.
