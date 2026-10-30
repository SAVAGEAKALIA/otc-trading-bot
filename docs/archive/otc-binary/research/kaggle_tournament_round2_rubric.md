# FROZEN RUBRIC, ROUND 2: model-family tournament (written 2026-10-30, before any round-2 training)

Purpose: find out whether ANY model family beats ln 2 out of sample. The holdout
(label candle >= 2026-09-22 01:00) is spent and is NOT loaded: the kernel filters it out.

Data: the 2m matrix rebuilt with clean_mood (0/1 readings dropped) and minute features.
Folds (by label candle open, UTC): five test weeks starting Aug 18, Aug 25, Sep 1, Sep 8, Sep 15
(the last ends Sep 22 00:00). Train = every row before the test week, with a 1h purge.
"rolling" variants train only on the 14 days before the test week.

Families (K = 9): logistic, lightgbm, lightgbm_rolling14, xgboost, mlp, gru, tcn,
cross_asset_transformer, knn_pattern.

Per family:
- Thresholds: for test week f >= 2, the confidence quantile in {0, .5, .8, .9, .95, .98}
  that maximises win rate on the pooled out-of-sample predictions of weeks < f
  (>= 300 trades). Week 1 only warms up thresholds.
- Score: pooled out-of-sample trades over weeks 2-5.

CANDIDATE (earns a pre-registered forward test on post-Oct-8 data, nothing more):
  1. Pooled Wilson lower bound > 0.540541 at Bonferroni z for K = 9.
  2. >= 300 pooled trades.
  3. At least 3 of weeks 2-5 have win rate > 0.540541.
Also reported: pooled out-of-sample log-loss minus ln 2, with a day-block bootstrap 95% CI.
A family "learned something" only if the whole CI is below 0.

No family can be called an edge from this round alone.
