# FROZEN RUBRIC: OTC edge search on Kaggle (written 2026-10-30, before any training)

Contract: IQ Option OTC binary, payout 0.85, breakeven p* = 1/1.85 = 0.540541.
Target: direction of the next candle (close vs open) at 2m (primary) and 5m expiry. Dojis excluded (refund).

Time splits (UTC). These are fixed and cannot be changed after results are seen:
- TRAIN:      everything with candle_start < 2026-09-08 00:00
- VALIDATION: 2026-09-08 01:00 <= start < 2026-09-22 00:00   (1h purge before)
- HOLDOUT:    2026-09-22 01:00 <= start <= 2026-10-08 06:10  (1h purge before; touched ONCE)

Every model (strategy x timeframe) fixes its trading threshold on VALIDATION only:
the confidence quantile that maximises validation win rate, subject to >= 300 validation trades.
Candidate quantiles: 0, .5, .8, .9, .95, .98.

PASS (an edge exists), all of these on HOLDOUT:
1. Wilson lower bound of win rate > 0.540541 at a Bonferroni-adjusted z for K = number of
   (strategy x timeframe) configs evaluated on holdout (K is recorded in the results).
2. >= 300 holdout trades.
3. Both halves of the holdout (split at the median time) have point win rate > 0.540541.
4. The ONNX export reproduces native predictions (max |diff| <= 1e-4) and the local
   onnxruntime re-run reproduces the holdout win rate exactly.

Anything else is NO EDGE. A validation-only result never counts.
"Close to breakeven" is NO EDGE. Holdout numbers are never used to pick models or thresholds.
