# FROZEN RUBRIC, ROUND 3: crowd follow vs fade (written 2026-10-30, before any round-3 analysis)

DISCLOSURE: the crowd-contrarian lead was found on the Sep 22-Oct 8 period, so weeks inside
that period are "previously seen". Results are reported separately for UNSEEN weeks
(test week starting before Sep 22) and SEEN weeks. Only the UNSEEN result can make a
candidate. Any candidate still needs a forward test on post-Oct-8 data before money.

Universe: 2m candles from Jul 31 to Oct 8 with a clean mood reading (clean_mood, degenerate
<= 0.001 / >= 0.999 dropped), observed >= 1s before the candle opens and <= 60s old.
Bet sides: FADE = against the crowd (call < 0.5 -> CALL); FOLLOW = with the crowd.
Payout: the latest payout sample for that asset at decision time (<= 10 min old), else 0.85.
Per-trade PnL = payout on a win, -1 on a loss; dojis are refunds and are excluded.

Walk-forward: weekly test folds starting Mon Aug 11, 18, 25, Sep 1, 8, 15 (UNSEEN), and
Sep 22, 29, Oct 6 (SEEN). Train = everything before the test week, with a 1h purge.
Week Aug 11 only warms up selection.

Strategies (K = 4):
 S1 grid: cells = |mood-0.5| band (10 bands of 0.05) x crowd trend (more vs less extreme
    than 10 min ago) x price agreement (last candle in the crowd's direction or not)
    x side (follow/fade) = 80 rules. Each week, trade every cell whose pooled prior-week
    trades are >= 300 and whose one-sided 80% Wilson lower bound beats that cell's mean
    breakeven. Overlapping cells cannot conflict: each row is in exactly one cell per side,
    and a cell pair with both sides selected is dropped.
 S2 lightgbm, S3 xgboost, S4 logistic: target = FADE wins; every feature plus crowd
    features. p > 0.5 -> fade, p < 0.5 -> follow. Confidence |p - 0.5|. The threshold
    quantile in {0, .5, .8, .9, .95, .98} is chosen on prior weeks' out-of-sample
    predictions (>= 300 trades).

CANDIDATE (UNSEEN weeks only):
 1. Pooled Wilson lower bound (Bonferroni z for K = 4, 2.498) > pooled mean breakeven.
 2. Pooled ROI > 0 and >= 300 trades.
 3. At least 4 of the 5 evaluated UNSEEN weeks (Aug 18 to Sep 15) have ROI > 0.
SEEN-week results are reported for consistency, never for passing.
