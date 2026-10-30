# PRE-REGISTERED: crowd-contrarian band rule (frozen 2026-10-30, before any data after 2026-10-08)

Origin: found by the adversarial critic AFTER the run-1 holdout was seen (snooped).
Train 0.508 / validation 0.532 / holdout 0.549 (n=9,794). Not evidence yet.

Data: only candles whose open is after 2026-10-08 06:10 UTC.
Mood: otc_feature_matrix.clean_mood (drop exactly 0/1, average duplicates); use the latest
      reading >= 1s before the candle opens and <= 60s old.
Rule: if 0.30 <= |call - 0.5| < 0.45, bet against the crowd (call < 0.5 -> CALL, else PUT).
      Expiry 2m (primary) and 5m. Doji = refund, excluded.
PASS, per expiry (Bonferroni k=2, z=2.241):
  1. Wilson lower bound > 0.540541
  2. >= 6,000 trades. Pre-planned look at 6,000 trades; final look at 33,000 trades.
     Any look that passes counts only if criteria 1 and 3 hold at the alpha-spent z=2.50
     for the early look and 2.241 for the final look.
  3. Both time halves > 0.540541.
Power: a true 0.549 needs ~33k trades (~55 days at ~605 band trades/day at 2m).
       A true 0.56 needs ~6.2k (~10 days).
Even a pass at 0.549 means about +1.6% ROI per trade before slippage, ties and payout changes.
