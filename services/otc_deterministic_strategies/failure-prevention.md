# Preserve physical broker time in strategy admission

Failure: the initial strategy boundary floored `decision_ns - quote.received_ns` to milliseconds before adding it to broker time. It admitted an option with90s minus1ns remaining under the registered minimum90s holding. The independent strategy critic reproduced this for both MHI and Exhaustion. Flooring receiver time in the signed clock-offset check also admitted a negative15s plus1ns discrepancy.

1. Name the invariant before implementation: elapsed receiver time stays integer nanoseconds through every expiry/cutoff/staleness comparison.
2. Keep broker observation milliseconds explicit at the boundary; convert once to integer nanoseconds without inventing sub-millisecond broker receipt precision. Compare the absolute signed difference to receiver nanoseconds before any flooring;15s plus1ns in either sign must reject.
3. Derive current broker nanoseconds as `broker_at_receipt_ms * 1000000 + decision_ns - quote.received_ns`.
4. Convert offered expiry and purchase deadline milliseconds once to nanoseconds.
5. Compare the full derived value to deadlines before candle features or signals can be emitted.
6. Enforce inclusive90s and150s holding bounds in nanoseconds, with90s minus1ns and150s plus1ns rejecting.
7. Apply the same exact derived value to closed-candle end and maximum staleness.
8. Run both fixed policy boundary regressions and the separate full-loss/offer evidence qualification downstream in root's practice runner.
9. Restore each old holding-floor and offset-floor expression in a safe isolated mutant and prove the regressions fail. Never run a mutant with accounts, network or orders.
10. Preserve prior source package, critic repro and immutable rule registration. Freeze the repaired source as a new version and request independent cold strategy review before integration.

# Validate every causal finalized identity before selecting a revision

Failure: v3 stored only the latest finalized candle per start. A and B contradicted at the same receipt instant; C was a later valid revision. A,B,C rejected while A,C,B emitted a signal because C replaced A before B was checked. The independent strategy critic reproduced four unsafe permutations out of six for both rules.

1. Name the invariant: every causal finalized `(start_ms, received_ns)` identity for the selected asset maps to one complete candle value.
2. Exclude future receipts, forming records and unrelated assets before inserting any identity; their unavailable OHLC must not influence decisions.
3. Validate exact nonnegative identity integers and the finalized boolean at the boundary.
4. Keep the complete identity map separate from the latest eligible revision map. Never use a selected latest revision as a substitute for identity history.
5. Reject contradictory finalized identity values before duration, clock, close-time or feature-window filters; those filters cannot repair contradictory provenance.
6. Allow identical duplicate records and distinct receipt instants. Select the latest eligible finalized revision only after identity agreement is established.
7. Test all six A/B/C input orders for both fixed policies. Assert the contradiction remains an `InvalidInput` regardless of the later revision's position.
8. Test distant identities outside the final29 feature bars, shuffled inputs, valid older revisions, identical duplicates and future/forming/unrelated payloads.
9. Restore preserved v3 source in an isolated mutant and narrow identity checks to the feature window in a second mutant. Both must fail assertions without runtime errors, accounts, network or orders.
10. Preserve the v3 package and independent repro; freeze source v4 with unchanged thresholds/slots and obtain a fresh independent cold strategy verdict before integration.

# Keep numeric failures inside the exported strategy contract

Failure: v4 let `math.isfinite(10**400)` escape as `OverflowError`. Natural finite positive Exhaustion candles scaled by1e156 also overflowed the legacy Bollinger variance square. The caller documents and catches `InvalidInput`, so neither escaping exception belonged at its boundary.

1. Name the invariant: numeric validation, legacy indicator arithmetic and canonical numeric evidence either complete normally or reject through `InvalidInput`.
2. Preserve v4 source and the independent cold critic's huge-integer and natural finite-price repros before editing.
3. Validate numeric types before calling `math.isfinite`; keep bool, NaN and infinity rejection unchanged.
4. Translate overflow from finite-range checking into `InvalidInput` with the original exception retained as its cause.
5. Preserve all legacy indicator formulas and thresholds. Translate arithmetic failures only at the exported decision boundary.
6. Translate an unrepresentable canonical JSON numeric value into the same typed rejection; never relax interpreter digit limits in production.
7. Require regression positives for both Exhaustion directions before scaling, and prove every scaled OHLC remains finite and positive.
8. Stress all numeric fields using seeded huge integers and finite price scales, while retaining maximum finite quote/payout admission semantics and deterministic repeats.
9. Restore each old number check, unprotected indicator call and unprotected JSON encoder in isolated mutants. Each must fail assertions without accounts, network, orders or unexpected test errors.
10. Freeze source v5 with unchanged rules/slots, ship regression and stress evidence, and obtain a new independent cold verdict before integration.
