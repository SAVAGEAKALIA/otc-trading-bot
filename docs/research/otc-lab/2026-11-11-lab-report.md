# OTC Quant Lab: independent edge search on IQ Option OTC binaries

Date: 11 November 2026. Code: [services/otc_quant_lab](../../../services/otc_quant_lab/README.md).
Sources: [bibliography.md](bibliography.md) (69 sources). Frozen rubric, critic verdicts and all run
outputs: `/home/saviour/otc-quant-lab-artifacts/` (section 10). No broker connection, no orders.

**Terms used throughout.**
- *Lab-final*: the last 25% of calendar days of the 2 minute archive (Jun 29 - Jul 27 2026), scored
  once after everything was chosen on the earlier *development* days.
- *Break-even*: the win rate at which a fixed-payout bet returns zero, 1 / (1 + payout).
- *K*: the number of strategy variants tested. The bar for "real" rises with K (Bonferroni correction).
- *MHI*: the "minority/majority of the last three candles" retail strategy popular for IQ Option.
- *PBO*: probability that the variant chosen as best in-sample is below median out of sample.
- *AUC*: how well a model ranks up-moves above down-moves; 0.5 is a coin, 1.0 is perfect.
- *Wilson bound*: a confidence bound on a win rate; *BH* (Benjamini-Hochberg) and Bonferroni adjust
  for running many tests; *Kelly*: the bankroll fraction that maximises long-run growth.
- *Day-block bootstrap*: an interval made by resampling whole days, so same-day correlation is kept.
  *CSCV*: the resampling scheme used to compute PBO.
- *Calibration-in-the-large*: whether the average predicted win rate matches the realised win rate.
- *Log-loss gain in nats*: the improvement in prediction error over always predicting the base rate;
  1e-4 nats is a ten-thousandth of a unit.
- *Variance ratio (Lo-MacKinlay)*: compares the variance of multi-bar moves to single-bar moves; 1.0
  means a random walk.
- *Rubric checks*, frozen before any model was fit:
  - H1-H6 are checks on the testing machinery itself: no look-ahead, correct labels, time-ordered
    splits, a false-positive control (H4), a power control (H5), and a complete trial registry.
  - P1-P7 are the bar a strategy must clear: enough trades; win-rate bound above break-even after
    correction; positive return with a positive bootstrap bound; positive in every third of the
    period; positive on most assets; low PBO; calibrated probabilities. Section 4 lists them in full.

## Verdict

**REJECTED.** No tested model, rule or policy with at least 1,000 out-of-sample trades beat its
break-even. A few tiny samples did, all from the mean-reversion rule: 58.2% on 56 lab-final trades
(4 min), 55.8% on 43 (10 min), 64.7% on 17 (15 min), and 68.4% on 19 (10 min) in the second period. That is
noise at that size.

What was tested:
- 22 machine-learning and statistical model types, 10 rule strategies (MHI, exhaustion and others),
  2 reinforcement-learning bandit agents, online and adaptive policies, a time-series foundation
  model, the crowd-fade lead, and a real-FX lead-lag test (pending re-verification, 5.9).
- Expiries of 1, 2, 3, 4, 5, 10 and 15 minutes, on 15 OTC currency pairs.
- Round 2 repeated the main study with asset identity, minute-of-hour, quadrant position and
  time-since-restart features. It did not help: the selected policy won 49.6% on lab-final (section 5.2b).

| Result | Number |
|---|---|
| Selected policy (chosen on development only, K = 432) | 52.0% on development, **49.2%** on 3,465 lab-final trades, -9.4% per stake |
| Best of 427 lab-final configs with >= 1,000 trades (chosen after the fact) | 50.94% (round 1), 51.47% (round 2); none above its own break-even (53.76-54.35%) |
| Closest to break-even with >= 1,000 trades (after the fact) | 15 min breakout (a continuation bet), 53.37% on 1,723 lab-final trades vs 53.76%; it was 49.85% on development |
| Out-of-sample day-level AUC, every model and expiry (2 min bars) | 0.4975 to 0.5031 (0.5 = coin) |
| Model-free tests (autocorrelation, variance ratio, colour patterns, hour, cross-asset, restart) | all null |
| Frozen crowd fade | 50.03% on 18,459 trades |
| Chronos-Bolt zero shot | 50.2% |
| 1, 2, 3 minute expiries from 1 s candles | pooled AUC 0.485 to 0.515 |

**Harness acceptance (rubric H1-H6):**
- **H1-H3 hold:** gate tests cover look-ahead, labels and the main time-ordered splits with purge and
  embargo. A separate gate test runs the short-expiry study's split function on synthetic times and
  checks that the test window starts at least feature lookback + longest expiry + 1 day after the inner
  window. The test fails if that gap is removed. In that study, the train and inner windows are
  adjacent in time, but the inner window only fits the calibration and cut-offs, so this cannot leak
  test outcomes.
- **H6 holds in round 2**, where every trial was written to the registry during the run. For round 1
  and the 5 min run the complete registry was rebuilt after the run from the run's own tables
  (section 10). The trial counts are exact; only the timing of the record differs.
- **H4 (false positives) holds for the pipelines it ran on:** 0 of 37 null runs passed. Those runs used
  reduced model sets (K = 74, 98 and 110), not the full 22-model, K = 432 pipeline. A full-pipeline null was
  not run.
- **H5 (power) failed in both rounds.**
  - Round 1: 22 of 39 seeds passed, against 80% required. Its edge also matched a built-in rule
    (`trend_follow_ret10`).
  - Round 2: the edge did not match any rule and sat at the rubric boundary (57% on about 10% of
    bars), judged at K = 432. 1 of 6 seeds passed every check. In all 6 the selected config carried
    the edge and won 55.9-57.3% on lab-final. The misses were P2 (too few lab-final trades at
    K = 432), P3 and P7.

**What H5 means for the verdict:**
- The rubric says H1-H6 must hold before results are reported. **In neither round was the harness
  certified to confirm an edge.**
- With one month of lab-final, the rubric certifies an edge as small as 57% on 10% of bars only
  rarely (1 of 6 seeds; 95% interval 3-56%), even one the features can express.
- **REJECTED does not depend on H5.** The selected policies won 49.2% (round 1), 49.6% (round 2) and
  49.8% (5 min bars), and fail P2-P5 by wide margins.
- Among configs with at least 1,000 trades, only one came within a point of break-even, and it was
  chosen after the fact: the 15 min breakout (5.7), a coin on development.
- H5 limits how strongly "no edge" can be stated. A small edge, or one of a form the features cannot
  express, may go uncertified or unseen (section 8).

The supported decision for this market and these expiries is **NO TRADE**.

## 1. The question and the measurable outcome

Does any model, rule, regime, bandit or adaptive policy pick IQ Option OTC binary outcomes well enough
to beat break-even out of sample, after every trial is counted?

The outcome was fixed before building: the selected policy passes rubric P1-P7 on lab-final, or it does
not. P1-P7 are listed in section 4.

**Payouts and break-even per expiry** come from the recorded `payout_samples` (Jul 31 - Aug 20 2026):

| Expiry | Product | Median payout (range) | Break-even |
|---|---|---|---|
| 1-5 min | turbo-option | 0.84 (0.82-0.87) | 54.35% |
| 10, 15 min | binary-option | 0.86 (0.82-0.87) | 53.76% |

The recorded data distinguishes the two products but not their expiries. The mapping above (turbo
for 1-5 minutes, binary for longer) is an assumption from the platform's product layout and is not
cited in the bibliography. 10 minutes is judged at the binary payout. The rubric asks for the median
payout per asset; per-asset medians are 0.84 turbo on 13 of 14 assets (USDCHF 0.85) and 0.86 binary on
12 of 15 (EURGBP 0.83, USDJPY 0.84, GBPJPY 0.87), so the per-product median is used. The verdict is
the same under every one of these payouts.

**Stress case at 0.80** (rubric): the selected policies return -11.4% (round 1), -10.7% (round 2) and
-10.3% (5 min bars) per stake on lab-final. Section 5 tables use 0.84 for returns unless stated; using
0.86 for 10 and 15 minutes moves no result above break-even.

## 2. Data

| Source | Content | Span | Role |
|---|---|---|---|
| `data/ml/historical_candles.sqlite` | broker OTC candles, 15 FX pairs, 120 s / 300 s bars | 120 s: Mar 29 - Jul 27 2026 (1.29M bars); 300 s: Jan 27 - Jul 27 (780k) | main studies; already examined by earlier repo studies, so the best reachable verdict is PROMISING |
| `data/ml/market_context.sqlite` | live-recorded 1 s and 120 s candles, trader mood, payouts | Jul 31 - Aug 20 2026 | second out-of-sample period (strictly after the archive); crowd fade; short expiries; payouts |
| Dukascopy public ticks | real interbank EURUSD, GBPUSD, USDJPY | 15 weekdays, May 4-22 2026 | real-vs-OTC lead-lag (kept outside the repo) |

- **Ties.** The tie rate (equal close at expiry) is 0.61% at 2 min, 0.42% at 4 min and 0.28% at
  10 min. Ties are refunded.
- **Volume.** The archive's volume field is 0 in every bar, so it cannot be a feature.
- **Daily restart.** The feed restarts once a day per asset: a 6 minute gap at 08:10 UTC on 10 assets
  and 04:04 on 5. Labels never cross a gap, and the window after each restart is tested separately.

## 3. What IQ Option OTC is (bibliography)

- **How prices are made.** The broker does not publish its method. Its own posts say OTC prices come
  from "internal pricing models to simulate market conditions" and are "not linked to real-time
  exchange data". They also say the trade is "between the trader and the platform itself" (S2, S3).
- **Order flow.** A 2024 broker post says quotes are "influenced by... the number of options bought,
  and the investment amount" (S1).
- **Regulation.** Retail binaries are banned in the EU, UK, Australia, Canada and Israel. IQ Option
  offers them through an offshore entity with no named regulator.
- **Win rate is not edge.** ESMA's 2018 data: at one firm clients won 54% of trades and 83% of
  accounts still lost.
- **Literature.** Real-FX minute-horizon studies find no exploitable direction for major pairs.
  Off-the-shelf time-series foundation models sit at chance on returns. Deep-RL trading results are
  known to overfit their simulators.

## 4. Method

Every model and rule runs through one harness ([run_lab.py](../../../services/otc_quant_lab/run_lab.py)).

- **Timing.** Decision at the close of bar t, using only bars closed by then. Entry price proxy = close
  of bar t. Outcome at expiry h = close of bar t+h, over contiguous bars only.
- **Proxy check.** The proxy agrees with the outcome computed from 1 s candles on **95.3%** of 33,264
  live-recorded decisions (section 5.10).
- **Splits.** Development = the first 75% of calendar days, with four walk-forward folds inside it.
  Lab-final = the last 25%, scored once. Each split runs: train, 2-day gap (purge + embargo), 7 inner
  days, 2-day gap, test. Models fit on train only. Inner days fit the probability recalibration
  (Platt) and the coverage cut-offs: trade the most confident 100 / 50 / 20 / 10 / 5 / 2%.
- **Trades.** One open position per asset at a time. A loss loses the stake, a win pays the payout,
  a tie refunds.
- **Selection** uses development out-of-sample trades only. The winner is the config with the highest
  one-sided 95% Wilson lower bound minus break-even, among configs with at least 500 trades.
- **Multiple testing.** Every (model, expiry, coverage) is a registered trial, and lab-final win
  rates are judged with a Bonferroni Wilson bound at 1 - 0.05/K. PBO uses CSCV with 16 blocks.
- **Rubric P1-P7**, frozen before fitting:
  - P1: at least 1,000 trades on at least 15 days.
  - P2: the Bonferroni bound is above break-even.
  - P3: positive mean return, and a positive day-block bootstrap lower bound.
  - P4: positive in each calendar third.
  - P5: positive on at least 60% of the assets that received at least 50 trades.
  - P6: PBO below 0.25 within the selected config's family. The family is every expiry and coverage
    variant of the winning model type, as the rubric specifies. PBO across all configs is reported
    alongside it.
  - P7: calibrated on the traded bucket: Brier score at most 0.25, and calibration slope between 0.5
    and 1.5. The slope is how much realised win rates rise per unit of predicted probability; 1 is
    ideal.

### Model types (all under identical splits)

| Group | Members |
|---|---|
| Classical ML (11) | base rate, logistic regression, Gaussian naive Bayes, kNN (k=200), RBF-kernel SVM (Nystroem), random forest, extra trees, sklearn HistGB, LightGBM, XGBoost, CatBoost |
| Neural (5) | MLP, GRU, dilated causal TCN, CNN-LSTM, Transformer encoder (PyTorch) |
| Regime / state (5) | Markov colour tables order 3 and 5, K-means (16), Gaussian mixture (8), 3-state Gaussian HMM decoded with a forward-only filter and crossed with the 3-bar pattern |
| Ensemble (1) | mean of calibrated logistic, LightGBM, CatBoost, MLP, GRU |
| Reinforcement learning | contextual bandit over K-means x session contexts with 6 arms (up/down x 3 expiries) + abstain: greedy and pessimistic (Bonferroni lower confidence bound) |
| Online / adaptive | logistic model updated daily (each day predicted only by earlier days), Page-Hinkley drift detector that suspends trading, daily switching to the best trailing-7-day config |
| Rules (10) | MHI minority / majority (quadrant and every bar), exhaustion 4 and 6, trend following, mean reversion, breakout, false-breakout wick, RSI reversal |
| Other | Chronos-Bolt-small zero shot; frozen crowd fade on trader mood; real FX as a leading signal |

**Features (52 in round 1).**
- Normalised returns of the last 10 bars, and body / wick / range of the last 5 bars.
- Returns over 3-60 bars, distance from SMA20 and SMA50, RSI14, position in the 20-bar range, path
  efficiency, volatility ratio.
- Colour streak, 3- and 5-bar colour pattern codes, hour of day, day of week.
- The cross-asset market move excluding the asset.
- **Currency-strength residuals:** each bar the 15 pair returns are projected onto 8 currency factors,
  and the residual is how far a pair moved apart from its own currencies. If the broker generated each
  pair with independent noise around common currency factors, that residual would revert.
- **Round 2 (v2, 57 features)** adds asset identity, minute-of-hour (sine and cosine), position inside
  the 5-bar MHI quadrant, and log time since the daily restart.

## 5. Results

Every number below comes from a script over the run outputs (`report_digest.py` and the files in
section 10). Win rates exclude ties; returns count ties as refunds.

### 5.1 Model-free tests (2 min bars)

| Test | Development (Mar 29 - Jun 26) | Lab-final (Jun 29 - Jul 27) |
|---|---|---|
| Next-bar up rate | 50.061% of 911,051 (p = 0.24) | 49.945% of 283,871 (p = 0.56) |
| Sign autocorrelation, lags 1-10 | all abs(r) <= 0.0021, min BH q = 0.47 | all abs(r) <= 0.0030, min BH q = 0.41 |
| Variance ratio at q = 2, 4, 8, 16 bars (Lo-MacKinlay z*) | 1.001, 1.002, 1.003, 1.002 (all p > 0.35) | 1.000, 0.997, 0.994, 0.986 (all p > 0.09) |
| Colour-sequence tables, orders 1-5 (the MHI family) | chi-square p 0.33-0.94; min BH q over all states 0.24 | p 0.65-0.85; min q 0.95 |
| Hour of day | chi-square p = 0.10; max deviation 0.69 pt | p = 0.86 |
| Cross-asset lead-lag (210 ordered pairs) | max abs(r) = 0.014, min q = 0.35 | max abs(r) = 0.020, min q = 0.77 |
| Each feature vs next direction (52 features) | max abs(Spearman) = 0.0024, min q = 0.72 | max 0.0044, min q = 0.55 |
| Window after the daily restart (79,002 bars, all days) | reversal rate 50.1% at 2 / 4 / 10 min (p > 0.45) | |

These tests are pairwise and linear. They show the price path has no simple dependence. They do not
rule out non-linear structure; the model zoo in 5.2 tests that, but only through the features listed
above.

The variance-ratio rows in `martingale.json` of the round-1 run carry the BH q-value under the key
`q`, overwriting the lag. The values are in lag order 2, 4, 8, 16. The bug is fixed and covered by a
gate test.

### 5.2 Predictive power of every model on lab-final (rubric C1, round 1)

Day-level AUC is computed per UTC day and averaged; the 95% interval is a day-block bootstrap.
Log-loss gain is versus the train base rate, in 1e-4 nats, where positive means better than a coin.

- **Range.** Across 63 model-by-expiry cells (2, 4, 10 min; base rate excluded), day-AUC ranges from
  0.4975 to 0.5031.
- **Cells whose interval excludes 0.5: 3 of 63**, where chance would give about 3:
  - HistGB at 2 min: 0.5031 [0.5010, 0.5052].
  - GRU at 2 min: 0.4981 [0.4964, 0.4999].
  - CatBoost at 4 min: 0.4975 [0.4952, 0.4996].
- **Log-loss gain** is zero or negative in every cell. The best, HistGB at 2 min, has an interval
  including zero: -0.06 [-0.24, 0.12].

Selected cells (pooled AUC):

| Model | 2 min | 4 min | 10 min |
|---|---|---|---|
| HistGB / LightGBM / XGBoost / CatBoost | 0.5026 / 0.5013 / 0.4990 / 0.5010 | 0.4993 / 0.4985 / 0.4989 / 0.4974 | 0.5022 / 0.5008 / 0.5012 / 0.5007 |
| Logistic / naive Bayes / kNN / RBF SVM | 0.4991 / 0.5011 / 0.5012 / 0.5000 | 0.5008 / 0.5015 / 0.5017 / 0.4999 | 0.4999 / 0.5020 / 0.5019 / 0.5009 |
| Random forest / extra trees / MLP | 0.4995 / 0.5000 / 0.4994 | 0.5003 / 0.4992 / 0.5012 | 0.5004 / 0.4991 / 0.5005 |
| GRU / TCN / CNN-LSTM / Transformer | 0.4978 / 0.4982 / 0.4994 / 0.4999 | 0.5002 / 0.5015 / 0.4994 / 0.5010 | 0.5014 / 0.5012 / 0.5008 / 0.5012 |
| Markov-3 / Markov-5 / HMM x pattern | 0.5016 / 0.5000 / 0.5019 | 0.5012 / 0.4995 / 0.5012 | 0.4993 / 0.5007 / 0.4994 |
| K-means / GMM regimes / ensemble | 0.4991 / 0.4991 / 0.5001 | 0.5006 / 0.5008 / 0.4994 | 0.5008 / 0.4992 / 0.5015 |

Deep sequence models did no better than logistic regression. The one cell whose day-level interval
sits above 0.5 (HistGB at 2 min: day-AUC 0.5031, pooled 0.5026 in the table) is what chance produces
in 63 cells, and it gains nothing in log-loss.

### 5.2b Round 2: the same study with asset identity and clock features (v2, 57 features, K = 432)

| | Development OOS | Lab-final |
|---|---|---|
| Selected config | RBF SVM, 10 min, top 2% | same |
| Trades | 7,044 | 3,736 on 29 days |
| Win rate [95% CI] | 51.30% | **49.60% [47.99, 51.20]** |
| Bonferroni lower bound (K = 432) | 49.11% | 46.59% |
| Mean return per stake at 0.84 [day bootstrap 95%] | | -8.7% [-11.4, -5.7] |

- **Rubric:** fails P2, P3, P4, P5 and P7; P6 passes on the family measure (0.07; across all configs it is 0.43).
- **After the fact:** the best of 427 configs with at least 1,000 trades won 51.47% (kNN, 10 min, top
  2%, 5,645 trades); none is above its own break-even.
- **C1:** day-AUC 0.4975-0.5026, with 3 of 63 cells excluding 0.5: kNN at 10 min above, HistGB and
  CNN-LSTM at 2 min below.
- **Reading:** knowing which asset, which minute of the hour, which bar of the quadrant, or how long
  since the restart adds no measurable predictive power in these models.
- **Registry:** `trials_complete.jsonl` holds all 2,161 trial-split records (432 configs x 5 splits +
  the post hoc adaptive policy).

### 5.3 The selected strategy, scored once on lab-final

| | Development OOS | Lab-final |
|---|---|---|
| Config (selected on development only, K = 432) | logistic, 10 min, top 2% confidence | same |
| Trades / UTC days | 5,867 / 54 | 3,465 / 29 |
| Win rate [95% CI] | 52.03% [50.74, 53.30] | **49.22% [47.55, 50.89]** |
| Bonferroni lower bound (K = 432) | 49.62% | 46.10% |
| Mean return per stake at 0.84 [day bootstrap 95%] | -4.3% [-6.9, -1.8] | **-9.4% [-11.8, -6.9]** |
| Max consecutive losses / max drawdown | 11 / 280 stakes | 13 / 333 stakes |
| The model's own mean win probability on traded bets | | 50.9% |
| Assets with positive return | | 1 of 15 |

Rubric:

| Check | Result |
|---|---|
| P1 trades and days | pass |
| P2 Bonferroni bound above break-even | fail (46.1% vs 53.76%, even at the binary payout) |
| P3 positive mean and bootstrap bound | fail |
| P4 positive in each calendar third | fail (-10.8%, -7.4%, -10.3%) |
| P5 positive on 60% of assets | fail (1 of 15) |
| P6 PBO below 0.25 within the winner's family | pass (0.02 within the family; 0.12 across all configs) |
| P7 calibrated on the traded bucket | fail |

**Not PROMISING.**

The P6 pass carries little weight. In the null controls, P6 passed in 44-75% of runs. When nothing
has skill, PBO cannot tell the best variant from the rest.

Even on development, the best config's one-sided Wilson lower bound (50.95%) was 2.8 points below its
10 min break-even (53.76%; 3.4 points at the turbo 54.35%). The selection rule had nothing above water
to choose.

### 5.4 Rule baselines on lab-final (no fitting, so every period is out of sample)

| Strategy (bet direction) | 2 / 4 / 10 min trades | 2 / 4 / 10 min win rate |
|---|---|---|
| MHI minority-3, 10-min quadrant | 56,128 / 56,124 / 55,898 | 49.99% / 49.99% / 50.24% |
| MHI majority-3 (variation) | 56,128 / 56,124 / 55,898 | 50.01% / 50.01% / 49.76% |
| MHI minority-3 every bar | 280,502 / 140,595 / 56,583 | 50.03% / 50.08% / 50.02% |
| Exhaustion (4 same colours, reverse) | 34,674 / 23,276 / 17,417 | 50.20% / 50.69% / 50.30% |
| Exhaustion (6) | 8,616 / 5,772 / 4,450 | 49.99% / 49.67% / 50.09% |
| Trend following (10-bar move > 1 sd) | 90,911 / 53,428 / 28,428 | 49.56% / 49.61% / 49.32% |
| Breakout, continuation (close at 20-bar extreme) | 4,742 / 4,568 / 4,266 | 49.72% / 49.42% / 49.15% |
| False breakout, reversal (rejection wick near the extreme) | 24,904 / 22,082 / 17,569 | 49.98% / 50.25% / 50.55% |
| RSI(14) 75/25 reversal | 8,471 / 5,110 / 3,039 | 49.54% / 49.52% / 49.77% |
| Mean reversion (z > 2 vs SMA20) | 82 / 56 / 43 | too few trades to read |

Earlier repo evidence: the OTC Expiry Regime study (9 Nov) qualified 0 of 360 states. The live
practice bot won 53.2% over 250 trades against a 54.2% break-even.

### 5.5 Reinforcement learning, online learning, adaptive switching

- **Contextual bandit (64 contexts x 6 arms + abstain).** Greedy and pessimistic both chose abstain in
  every context of every split. This follows from the near-50% hit rates: at a 0.84 payout every arm
  has negative expected reward, so it is not independent evidence. Its value is the guard. A unit test
  shows that an unadjusted lower confidence bound (z = 1.645 over 100 cells) does trade on pure noise,
  which is the "agent exploits its simulator" failure, and the Bonferroni version closes it.
- **Online logistic, updated daily.** Lab-final 49.90% on 285,657 trades. Top 10% confidence, with the
  cut-off taken from the previous 7 days only: 49.66%. With Page-Hinkley suspension: 49.96% and 49.13%.
- **Adaptive switching** (each day, the config with the best trailing-7-day return, if positive) is
  registered but final-only, so it is reported as post hoc:
  - Round 1: it found a candidate on 4 of 29 days, traded 463 times and won 43.6%.
  - Round 2: 540 trades, 42.8%.
  - 5 min bars: 1,667 trades, 50.45%.

### 5.6 Second out-of-sample period: live-recorded candles, Jul 31 - Aug 20 2026

The lab-final models were applied unchanged to candles recorded after the archive ends. This is a
re-scoring of already registered configs, not new selection.
- Round 1: the best with at least 1,000 trades were RSI reversal at 4 min (52.06% on 2,828), RSI
  reversal at 2 min (51.78% on 4,621) and logistic at 2 min, top 2% (51.76% on 2,974).
- Round 2: Transformer at 2 min, top 2% (52.22% on 2,877).

These are maxima over 432 configs chosen after the fact, and all are below break-even.

### 5.7 Five-minute bars: 5 and 15 minute expiries (Jan 27 - Jul 27 2026, 660k decisions, K = 146)

- **Selected config:** GRU at 5 min, top 2%. Development 51.25% (5,870 trades), lab-final **49.78%**
  (3,266 trades, -8.4% per stake). It fails P2-P5 and P7.
- **C1:** 4 of 20 cells have day-AUC intervals excluding 0.5, where chance would give 1. All four are
  **below** 0.5: Markov-3 at 5 min and at 15 min (15 min: 0.4937 [0.490, 0.498]), Markov-5 at 15 min, and HMM x
  pattern at 15 min (0.4931). So colour patterns learned on development predict the wrong way at 15
  min in lab-final.
- **The same window, from the rules side.** Two rules did better in lab-final than on development, and
  they bet in opposite directions:
  - *Exhaustion-4* bets on **reversal** after four same-colour bars. At 15 min it won 51.69% on 10,709
    lab-final trades, against 49.6% on development.
  - *Breakout* bets on **continuation** after a close at the 20-bar extreme. At 15 min it won 53.37% on
    1,723 lab-final trades, against 49.85% on 3,277 on development (68th of 146 by win rate, 137th by
    the selection score).
- **Reading.** A reversal rule and a continuation rule both improving is not one coherent effect. Each
  is a separate post hoc observation: breakout and exhaustion-4 are the top two of the 143 lab-final
  configs with at least 1,000 trades in this run, picked after the fact. Both are below break-even even before
  correction (53.37% and 51.69% vs 53.76%), and further below after it (Bonferroni bounds 49.28% and
  50.05%). Neither would be picked by dev-only selection. The colour-pattern AUCs below 0.5 say the same: whatever 15 min
  structure the development period had did not carry into lab-final.
- **Next test:** whether either persists is a pre-registered question for fresh data (section 9).

### 5.8 Crowd fade (frozen before this lab: fade the crowd when 0.30 <= abs(call - 0.5) < 0.45)

| Variant | Trades | Days | Win rate [95% CI] | Return per stake [day bootstrap] |
|---|---|---|---|---|
| 120 s bar proxy | 18,459 | 18 | 50.03% [49.31, 50.75] | -7.9% [-8.9, -6.8] |
| 1 s candles, 2 s execution delay | 4,277 | 14 | 49.61% [48.11, 51.12] | -8.6% [-11.7, -4.0] |

The earlier "best current lead" (about 54.9%, chosen after looking at its own holdout) does not
survive a clean pre-registered test.

### 5.9 Does the real FX market lead the OTC feed? (weekdays May 4-22 2026)

**Status: UNVERIFIED.** These numbers come from a run on 9 Nov using 812 of 1,080 tick files. A machine
reboot erased that output file. A rate-limited refetch (Kaggle kernel `otc-lab-leadlag`) was still
running when this report was written. Treat this section as indicative only; nothing else in the
report depends on it.

| Pair | Overlapping 2 min bars | Corr(real return t, OTC return t+1) | Real-leads rule hit rate [95% CI] | OTC minus real level, std |
|---|---|---|---|---|
| EURUSD | 5,432 | -0.004 | 49.73% [48.38, 51.09] | 128 pips |
| GBPUSD | 2,134 | -0.013 | 50.07% [47.91, 52.23] | 223 pips |
| USDJPY | 832 | -0.028 | 51.75% [48.29, 55.20] | 1.06 yen |

Correlations at lags -3 to +3 were within plus or minus 0.06. The exception was USDJPY at lag -1
(-0.10 on 840 bars), which does not survive correction for 21 tests. OTC levels drift far from the
real market, which fits the broker's own description of an internally generated feed.

### 5.10 1, 2 and 3 minute expiries from 1 s candles (Jul 31 - Aug 20 2026, K = 27)

Setup:
- Decisions at each recorded 2 min bar close, with the same features.
- Entry = last 1 s close at or before decision + 2 s. Expiry = last 1 s close at or before entry + E.
  Both prices must be at most 3 s old.
- 1 s coverage is about 27% of the period, so the split is by labelled-decision time: 60% train, 15%
  inner, then a gap of the feature lookback (128 min) + 3 min + 1 day embargo, rest test. That leaves 5,050-7,795 test decisions per expiry over 9-10 days.

| Expiry | Up rate | Logistic AUC | LightGBM AUC | Markov-3 AUC | Best model, top 10% | Best rule (trades, win rate [95% CI]) |
|---|---|---|---|---|---|---|
| 1 min | 50.27% | 0.5150 | 0.4910 | 0.4853 | logistic 53.61% (488) | MHI quadrant 979, 50.46% [47.3, 53.6] |
| 2 min | 49.79% | 0.4974 | 0.5042 | 0.5034 | Markov-3 51.80% (699) | MHI quadrant 1,143, 51.06% [48.2, 54.0] |
| 3 min | 49.78% | 0.4968 | 0.5007 | 0.5032 | Markov-3 50.81% (998) | exhaustion-4 964, 51.82% [48.7, 55.0] |

The best "top 10%" cell (logistic, 1 min, 53.61% on 488 trades) is the maximum of 9 post hoc cells.
Its 95% interval is about plus or minus 4.4 points, and it is still below the 54.35% break-even.

Day-level AUC is unstable here because coverage is uneven across days (some days have a handful of
labels), so pooled AUC is shown. For completeness, day-level AUC with 95% intervals:
- 1 min: logistic 0.488 [0.447, 0.517], LightGBM 0.540 [0.487, 0.603], Markov-3 0.520 [0.487, 0.565].
- 2 min: 0.488 [0.462, 0.525], 0.489 [0.448, 0.530], 0.491 [0.478, 0.506].
- 3 min: 0.489 [0.338, 0.597], **0.392 [0.285, 0.480]**, 0.531 [0.433, 0.665].

One of 9 cells excludes 0.5 (LightGBM at 3 min, below 0.5, on few labels per day). That is about what
chance gives.

The bar-close proxy used everywhere else gives the same 2 min outcome as the 1 s candles on **95.3%**
of 33,264 decisions. The 4.7% that disagree come from tick-level timing between the bar close and
the second-level close. Whether they hide a systematic artefact is open (section 8).

### 5.11 Time-series foundation model (Chronos-Bolt-small, zero shot, 20,000 lab-final decisions)

- **Result:** AUC 0.5037; 50.23% overall; 50.8% in its most confident 10% (2,000 decisions).
- **Earlier run (9 Nov):** before a Hugging Face model-revision change it gave AUC 0.4996, 49.7% and
  48.4%. Both are null.

### 5.12 Can this pipeline find an edge when one exists? (rubric H4, H5)

**How the controls work.**
- *Null:* real archive returns with random signs. This keeps volatility clustering, ties, restart
  gaps and timestamps, and removes direction.
- *Round 1 positive:* the null plus a 58% continuation whenever the trailing 10-bar move exceeds one
  standard deviation (about 30% of bars). This is the same shape as the built-in `trend_follow_ret10`
  rule and the `ret10` feature, which won most positive runs.
- *Round 2 positive:* the null plus a 57% continuation when the 7-bar move exceeds 1.645 standard
  deviations of the 30-bar volatility (about 10% of bars, the rubric boundary). No built-in rule
  matches this shape. Models can only learn it through the return features. P2 is re-judged at the
  main study's K = 432.

**Round 1 (trend10 edge):**

| Lane | Data | Null passes | Positive passes | Positive runs passing P1-P6 |
|---|---|---|---|---|
| Fast (logistic, K-means, Markov) | 3 assets x 70 days | 0 / 25 | 15 / 25 | 16 / 25 |
| Full path (+ LightGBM, GRU, ensemble) | 3 assets x 70 days | 0 / 8 | 4 / 8 | 4 / 8 |
| Scale-matched (4 model types + ensemble, rules, bandit, online) | 15 assets x 121 days | 0 / 4 | 3 / 6 | 6 / 6 |
| All | | **0 / 37 (95% CI 0-9.4%)** | **22 / 39 (56%), H5 failed** | 26 / 39 |

Why the round-1 positive runs failed:
- **Small lanes (14 misses):**
  - 6 missed on sample size: low-coverage winners with about 450 lab-final trades fail P1 and the
    Bonferroni bound (one of these failed every check).
  - 4 missed on PBO (P6), one of them also on P7.
  - 2 missed on P2 plus calibration (P7).
  - 1 missed on P2 alone.
  - 1 missed on P7 alone.
- **Scale lane (3 misses), all on P7 alone:**
  - Seed 0 was calibrated in level (57.90% predicted vs 57.87% realised), but its slope was 0.09. With
    a step-shaped edge the true probability inside the traded bucket is constant, so the slope
    measures noise.
  - Seed 2 was genuinely overconfident (60.26% predicted vs 57.78% realised on 5,627 trades). A
    calibration-in-the-large check would fail it too.
  - The third failure was seed 5 of the scale lane: 57.70% on 3,668 trades.
- **What this says about P7:** it can reject a real, level-calibrated edge. It is reported here, not
  changed; the next rubric should use calibration-in-the-large.

**Round 2 (burst7 edge, 15 assets x 121 days, P2 judged at K = 432):**

| Seed | Selected config | Lab-final trades | Win rate | Failed checks |
|---|---|---|---|---|
| 0 | logistic, 2 min, top 5% | 14,368 | 56.38% | P7 |
| 1 | ensemble, 2 min, top 2% | 5,811 | 56.54% | P2 |
| 2 | ensemble, 10 min, top 2% | 3,031 | 57.31% | P2, P7 |
| 3 | ensemble, 4 min, top 2% | 3,812 | 56.25% | P2, P7 |
| 4 | ensemble, 2 min, top 2% | 5,905 | 56.77% | none (pass) |
| 5 | ensemble, 10 min, top 2% | 2,664 | 55.91% | P2, P3 |

- **Strict pass: 1 of 6. H5 fails at the rubric boundary.**
- Seeds 2 and 5 are 10 min configs, judged in the table at 54.35%. At their own 10 min break-even (53.76%),
  seed 2 also passes P2 (bound 53.97%). That makes P1-P6 pass in 3 of 6 seeds (0, 2, 4), but the
  strict pass count stays 1 of 6 because of P7.
- **Why.** The selection rule favours the most confident 2% of bets, which leaves 2,700-5,900
  lab-final trades. At the realised 55.9-57.3%, clearing 54.35% at K = 432 needs about 4,800 trades
  at 57% and 7,250 at 56.5%. Lab-final is only 29 days.
- **What it does show.** In 6 of 6 seeds, the selected config carried the edge and won 55.9-57.3% out
  of sample. The real study's selected configs won 49.2% (v1) and 49.6% (v2), and no real config with
  at least 1,000 trades reached 51.5% in the 2 min bar study's lab-final (the best anywhere with >= 1,000 trades
  was 53.37%, the 15 min breakout, still below break-even). For this edge form, under this reduced
  pipeline, the real results are far below what an edge of this size produced.
- **Limits of that comparison.** With 6 of 6 seeds, the 95% lower bound on how often the selected config
  carries the edge is about 61%. That is a different rate from the strict pass rate (1 of 6). The
  control ran 4 model types (plus their ensemble, the rules, the bandit and online policies), v1
  features and K = 144. The real round-2 study chose from 22 types (its winner was an SVM, which the
  control never ran). So this is evidence against an edge of this size and shape, not proof that every
  edge would surface.
- **What it does not show.** The harness rarely certifies an edge this small on one month of lab-final
  (1 of 6). Certification needs prospective data (section 9).

## 6. Strategy catalogue (serious candidates)

| Candidate | What it bets on | Evidence | Status |
|---|---|---|---|
| MHI minority / majority, quadrant and every bar | short colour-sequence imbalance | 49.8-50.2% on 56k-281k lab-final trades; colour tables null; 50.5-51.1% at 1-2 min | rejected |
| Exhaustion 4 / 6 | reversal after a colour run | 49.7-50.7% at 2-10 min; 51.7% at 15 min, but 49.6% on development there (5.7) | rejected |
| Trend / breakout / false breakout / RSI | momentum or reversal at extremes | 49.2-50.6% at 2-10 min; breakout 53.37% at 15 min (post hoc, 5.7) | rejected |
| Mean reversion (z > 2 vs SMA20) | reversal after a stretched move | 51.2% / 58.2% / 55.8% at 2 / 4 / 10 min on only 82 / 56 / 43 trades; 64.7% on 17 at 15 min | too few trades to read; unresolved |
| Gradient boosting, forests, kNN, SVM, NB, logistic on causal features | non-linear combinations, including cross-asset residuals and (round 2) asset and clock identity | AUC 0.4975-0.5031 | rejected |
| GRU / TCN / CNN-LSTM / Transformer on 32-bar sequences | sequential structure | AUC 0.498-0.502 | rejected |
| HMM / K-means / GMM regimes | hidden states with different direction | AUC about 0.50 at 2-10 min; HMM x pattern 0.4931 at 15 min (below 0.5, wrong-way) | rejected |
| Currency-strength residual reversion (new) | broker generating pairs with independent noise | residual features carry no direction (q > 0.5) | rejected |
| Crowd fade (frozen band) | trader-mood contrarianism | 50.03% on 18,459 | rejected |
| Real FX leads OTC (new) | OTC copying the interbank market with delay | 5.9: about 50% | not yet verified; indicative null |
| Chronos zero shot | foundation-model priors | 50.2% | rejected |
| Contextual bandit / RL | learned enter-or-abstain per context and expiry | abstains everywhere | the NO TRADE answer |
| Adaptive model switching | regime-dependent best model | 43.6% on 463 (round 1), 42.8% on 540 (round 2), 50.45% on 1,667 (5 min bars) | rejected |
| 15 min exhaustion (reversal) and 15 min breakout (continuation) | each did better in Jun-Jul than on development | post hoc only, below break-even after correction | two separate open questions for fresh data |

**Best newly discovered strategy: none qualifies.** No candidate met the specification standard the
brief set (validated entry, expiry, confirmation and no-trade rules). The policy the evidence supports
is NO TRADE on IQ Option OTC direction at 1-15 minute expiries.

## 7. Capital and risk (`risk_report.py`, every parameter in its header)

Assumptions: $20 bankroll, $1 minimum stake, 20 trades a day, stop for the day after losing 25% of
the day's opening bankroll, percent staking at 5% of bankroll floored at $1, 500 trades, payout 0.84.

| Win rate | Kelly stake | Ruin, fixed / percent stake | P(8 losses in a row) |
|---|---|---|---|
| 50.00% (coin) | -9.5% | 82% / 84% | 63% |
| 50.94% (best round-1 lab-final config with >= 1,000 trades) | -7.5% | 72% / 74% | 58% |
| 52.03% (round-1 selected config, on development) | -5.1% | 58% / 61% | 52% |
| 56.00% (hypothetical real edge) | +3.6% | 12% / 13% | 32% |

A negative Kelly stake means any positive stake has negative expected log growth. No staking plan
turns that positive, and martingale only makes ruin faster.

Trades needed to confirm an edge over the 54.35% break-even (one pre-registered test, alpha 0.05,
power 0.8):

| Edge over break-even | Trades needed |
|---|---|
| +1 pt | 15,320 |
| +2 pt | 3,824 |
| +3 pt | 1,697 |
| +5 pt | 608 |

## 8. Limitations, blind spots, and what would change the verdict

**Tested in round 2 after the critic flagged them:**
- 1 and 3 minute expiries (5.10).
- Asset identity, minute-of-hour, quadrant position and time since restart as features (5.2 v2
  result).
- Settlement timing against the bar proxy: 95.3% agreement (5.10).

**Still untested:**
- **Edges of a form the features cannot express**, for example dependence on the broker's internal
  state, or on other traders' open positions.
- **Order-flow feedback.** The broker says quotes react to "the number of options bought, and the
  investment amount". Testing needs our own practice-account trades and matched no-trade windows, so
  it waits for Saviour's go-ahead. If the broker moves prices against open retail positions, that is a
  further reason not to trade, not an edge.
- **Clock-aligned expiry.** Real expiries snap to the broker's clock (for example the next whole
  minute after a 30 s cut-off). The proxy uses decision + h. The 95.3% agreement bounds the label
  error. A systematic timing artefact at the expiry instant could hide in the remaining 4.7%; only
  broker settlement records can rule it out.
- **Spent data.** The archive was examined by earlier repo studies. One 2-asset smoke run here touched
  lab-final before two leakage fixes. No parameter was changed because of its numbers. This could only
  have produced a false positive, and none appeared.
- **Mid-run P7 reading.** One interpretation was set during the run: one-value forecasters (rules,
  bandit, online cut-offs) use a one-bin reliability check. It was fixed before any main-study result
  existed.

**Cumulative K.** Across every lab trial family:

| Family | Trials |
|---|---|
| 2 min family, round 1 | 432 |
| 2 min family, round 2 (v2 features) | 432 |
| Post hoc adaptive policy (rounds 1, 2, 5 min bars) | 3 |
| 5 min bars | 146 |
| Short expiries | 27 |
| Crowd fade | 2 |
| Lead-lag | 3 |
| Foundation model | 2 |
| **Total** | **1,047** |

The second-period re-scoring (5.6) uses already registered configs and adds no selection trials.

No config with at least 1,000 trades is above its break-even even before correction. Only tiny
samples are: mean reversion won 58.2% (32 wins, 23 losses, 1 tie; 56 trades) at 4 min and 55.8% on
43 at 10 min (the 2 min variant won 51.2%), and 64.7% on 17 at 15 min. In the second period it won
68.4% on 19 (10 min), and in the 5 min run's second period it won 3 of 3 twice. That is noise at that size.

## 9. What would justify reopening OTC

- **New information.** Only information the price path does not already contain: broker settlement
  records, or order-flow feedback measured on practice trades.
- **Fresh data for two separate hypotheses** from section 5.7, each registered with its frozen rule
  and tested only on the fresh collector cohort:
  - *15 min exhaustion-4 (reversal).* Its lab-final rate (51.7%) is 2 points below the 53.76%
    break-even.
  - *15 min breakout (continuation).* Its lab-final rate (53.4% on 1,723) is 0.4 points below.
  - The bar on fresh data is the same as here: a corrected lower bound above 53.76%. Both rules were
    below that on lab-final and near 50% on development (49.6% and 49.9%). With the two hypotheses
    corrected for each other (alpha 0.025 each), confirming even 1 point over the 53.76% break-even
    takes about 19,500 trades (one-sided, power 0.8).
  - So these are monitoring questions, not trading plans.

## Not run, and why

- **GAN / VAE / diffusion scenario generators.** A generator trained on these candles holds no
  information about the next move that the candles lack (data processing inequality). Synthetic paths
  are not evidence of profit. Their legitimate use, stress-testing the pipeline, is covered by the
  sign-randomised nulls and the injected-edge controls.
- **Deep RL (DQN, PPO, A2C, SAC).** A fixed-stake binary option does not move the market, so the
  decision problem is exactly a contextual bandit. Deep RL would learn the same values with more
  variance.
- **An LLM as a predictor, or chart-image models.** No mechanism gives them price information beyond
  the numeric candles that every model above already saw. LLM agents were used where they help:
  literature research (bibliography), one adversarial review of the harness, and the cold reviews of this
  report listed in section 10.

## 10. Evidence and provenance (outside the repo, persistent)

`/home/saviour/otc-quant-lab-artifacts/` is used instead of `/tmp`, because a reboot on 11 Nov erased
everything under `/tmp`.

**Critique and controls:**
- `critique/rubric.md`: frozen rubric.
- `critique/skeptic-round1.md`: harness attack and fixes.
- `critique/critic-round2.md`, `critic-round3.md`, `critic-round4.md`: cold reviews, with recompute
  scripts in the matching `round2/`, `round3/` and later folders. Every later `critic-round*.md`
  follows the same pattern.
- `controls/*/out/controls.jsonl` and `controls/verdict-*`: control evals.

**Run outputs:**
- `runs/<run>/digest.json`: script-extracted report numbers per run.
- `runs/main-120/out/`: round 1 2 min family. Includes `summary.json`, `martingale.json` and
  `trials.jsonl` (zoo only, written during the run). It also has `trials_complete.csv`, with all 433
  registered configs (432 selectable plus the post hoc adaptive policy). That file was rebuilt after
  the run from the run's own `dev_table.csv` and `final_table.csv`. Round 2 writes its complete
  registry during the run.
- `runs/main-v2/out/`: round 2 2 min family. Includes `trials_complete.jsonl` (every trial per split).
- `runs/main-300/out/`: 5 min bars, including `trials_complete.csv` (147, rebuilt the same way).
- `runs/short_expiry.json`, `runs/crowd.json`, `runs/foundation.json`, `runs/risk.json`.

**Provenance:**
- Source database `data/ml/historical_candles.sqlite`: sha256 `71717d8c…`.
- Its parquet exports reproduce byte for byte: 120 s `0bda5dcf…`, 300 s `f0743ae7…`. These are the
  `source_sha256` values in each run's `meta.json`.
- **Code, round 1:** Kaggle datasets `otc-quant-lab-main` and `otc-quant-lab-code-v2`. Their zips were
  not hash-pinned, because the local copies were lost with `/tmp`. Round 1 differs from the code in
  this commit by the round-2 additions, which leave round-1 behaviour unchanged when they are off:
  - the `--feature-set v2` flag;
  - the complete registry file;
  - the burst7 control and `--judge-k`.

  It also differs by one fix that is not a switch: the variance-ratio BH q-value now has its own key,
  `q_bh`. That changes the JSON field names, not any value.
- **Code, round 2:** `otc-quant-lab-code-v3`, zip sha256 `f900430e…`. This commit differs from v3 by:
  - the README;
  - two output metadata fields in `eval_controls.py` (the recorded `edge` value and a new `form` field);
  - `short_expiry.py`: its split changed from calendar days to the embargoed labelled-time split
    (`split_spans`), it skips one-class days in the day-AUC bootstrap, and it records more output
    fields. It runs only locally (5.10), never in a round-2 kernel;
  - added gate tests;
  - the new `report_digest.py`.

  None of these changes how a round-2 run computes.
- **Local runs** (`short_expiry.json`, `crowd.json`, `foundation.json`) were re-run after the last
  edit to the code they run. `short_expiry.json` was re-run after its split was moved into
  `split_spans` (output identical). `risk.json` was produced after the last edit to the modules it
  imports (`risk.py`, `metrics.py`).
- Kaggle kernels `saviourakalia/otc-lab-*` (private) hold the remote run logs.
