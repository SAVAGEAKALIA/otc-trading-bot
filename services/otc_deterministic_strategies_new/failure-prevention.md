# Freshness arithmetic and unsupported economic evidence

Failure: flooring a receiver timestamp to milliseconds before comparing it with a broker source timestamp can admit a source age five seconds plus one nanosecond as five seconds. The first pre-score implementation had this defect. Its frozen artifact is preserved outside the repo. No policy scoring or deployment had occurred.

Permanent constraint: source age is `received_at_ns + clock_offset_ms*1000000 - source_at_ms*1000000`. Its exact integer value must lie in `[0,5000000000]`. The source's millisecond resolution remains explicit; the computation does not invent an additional observed broker digit.

Regression: `test_fractional_source_age_cannot_be_truncated_into_freshness` rejects the one-nanosecond overrun. Existing future-payload, exact receiver order, source-cache and clock-invalid tests exercise neighboring inputs. The causal eval adds seeded fractional-boundary perturbations. Gate and eval stay in the same source package.

Review flow: define exact unit and inequality, freeze the pre-score algorithm, write the boundary counterexample, change only deterministic admission, rerun regression and held-input perturbations, preserve both hashes, and freeze the corrected source before any historical/future economic comparison. Safety repair never authorizes a threshold sweep or new development slot.

Evidence constraint: absent historical offer/session/accepted-contract fields must yield `BLOCKED_FOR_ECONOMIC_EVIDENCE`, with return fields null. Do not synthesize `state='open'`, a physical session, an expiry or cash settlement just to make a policy replay run. A mechanism-only Pattern and an order proposal are different typed contracts.

Cold review found the same failure pattern in the separate broker/receiver offset check: a negative offset of15 seconds plus1 nanosecond passed after receiver-time flooring. Permanent constraint: `abs(broker_at_receipt_ms*1000000-received_at_ns) <=15000000000`. The gate and seeded eval test both signs at the exact bound and fractional overruns. A separate mutation proof reintroduces the floor and confirms the negative-overrun counterexample selects an unsafe proposal. These changes preserve the original clock limit, policy rules, assets and trial slots.

The reusable prevention checklist is: (1) enumerate every mixed-unit comparison; (2) declare the finest observed receiver unit; (3) convert coarser timestamps by multiplication; (4) write the signed exact inequality; (5) test the inclusive boundary; (6) test one unit beyond it in both signs; (7) randomize fractional overruns in the eval; (8) reintroduce every old floor as a rejected mutant; (9) freeze the repaired source before any economic score; (10) send the exact package and old repro to the independent critic. Searching only the first faulty function is insufficient.
