# OTC records v1

Frozen dataclasses carry product, source, receipt clock and provenance across the observer/research boundary. Decimal strings preserve the supplied value; they cannot recover precision already lost upstream. Observation receipt and source timestamps are distinct. Unknown availability remains unknown. The receiver-clock price experiment is explicitly a proxy; it cannot construct broker settlements. Fees are separately charged amounts only, so already-net cash must use fee zero.

Run from the repository root:

```bash
python3 -m unittest discover -s contracts/otc_v1/tests -v
```

Changes to serialized fields require a new boundary version. No broker connection or order submission is implemented here.

Normalized observations require source time at or before receipt. Unknown receipt remains null.
Cash arithmetic uses a fixed 34-digit half-even Decimal context, so caller rounding settings cannot change a result.
Run the neighboring-case eval separately:

```bash
python3 -m contracts.otc_v1.evals.eval_records --output /tmp/binary-training/contract-eval.json
```

All checks must pass, including the old ambient-rounding counterexample. Reported tie/void cash is preserved, including partial refunds.
