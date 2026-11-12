# Sparse, Strict-Condition Entries on IQ Option OTC Binaries: Evidence Grades and Eight Pre-Registered Tests

> Research report, 12 November 2026. Evidence-graded answer to the owner's request to trade OTC only when a strict condition is met. Companion to the [11 November lab report](2026-11-11-lab-report.md). Evidence files and the scripts behind every owner-data number: [sparse-entry/](sparse-entry/README.md). No trade outcome of the eight hypotheses has been read.

**No strict-condition entry on IQ Option OTC, or on any comparable broker-generated feed, has a logged out-of-sample win rate above break-even (54.35% at the 0.84 turbo payout, 53.76% at the 0.86 binary payout). The owner's pooled tests exclude every always-on regime strong enough to pay [1], real-FX conditional effects only straddle the payout gap [2], every high OTC win rate on record collapsed with more samples [3], and by definition abstention cannot lift a subset above its true conditional win probability [41]. Strictness raises the bar: on a 29-day block, a 1% trigger can certify only a true win rate of 57.8% or more, a 0.1% trigger only 64.3% [6]. The prior nulls cannot see rare states or broker-controller events, and IQ Option's terms say the OTC price "is formed from data for trade requests and orders of the Clients" [7]. Eight frozen hypotheses follow, led by an extreme 2-minute move fade; a crowd fade after a payout step-down is the best-grounded mechanism and the least detectable test. Each comes with an exact trigger, one expiry, a measured frequency [8] and a required sample size, certifiable only on a fresh forward cohort. Most or all should return null; the default stays NO TRADE.**

## 1. Conditional and Sparse-Signal Entry Strategies

**Break-even is 1 / (1 + payout)**: 54.35% at 0.84, 53.76% at 0.86. A selective-entry rule abstains by default and trades only when a condition holds, so it wins only if that condition selects a region whose true win probability already clears the line.

### 1.1 Evidence grades

Mechanism grades ask whether a property exists; edge grades ask whether it pays.

- **A**: legal or regulatory text, or peer-reviewed work with stated n.
- **B**: the owner's logged measurements.
- **C**: broker blogs, dated trade press, or practitioner studies with a stated method and n.
- **D**: anecdote, seller claims, untested mechanisms, and any win rate without a logged sample and an out-of-sample split.

### 1.2 Evidence by trigger family

Every family's edge grade on IQ OTC is D.

| Family | External evidence | Owner or broker-feed evidence | Status |
|---|---|---|---|
| Extreme-move exhaustion | Nasdaq-100 0.1%-quantile one-minute drops reverse 31% next minute, a ratio of means, not a hit rate [9]; profit only at constant spreads [10] | Exhaustion-4/6 49.7-50.7% [1] | Open in far tail (H2) |
| Volatility regime | Directional IC (information coefficient) only +0.0252 on EUR/USD [11]; a 4.4%-of-days classifier passed 0 of 8 directional tests [12] | HMM (hidden Markov model) null; AUC (0.5 = chance) 0.4975-0.5031 [1] | Closed |
| Support/resistance | Published levels bounced 60.8% vs 56.2% for arbitrary levels, 1-minute FX [13] | IQ blog claim, no statistics [14] | Merged into H4 |
| Round numbers | Take-profits at 00 9.3% of the time vs 4.4% for stops; bounce lift +3.4 to +4.6 pt [2] | Quotex attractor "drops to 50-70% at real expiries" [3] | Open (H4) |
| Multi-timeframe confluence | Triple-timeframe (1D/4H/1H) EUR/USD regime model: directional IC +0.0252 [11] | Inside a null model zoo [1] | No slot: multiplies trials |
| Candle-sequence extremes | Three-day reversals 62.85% on 140 events vs 44.73% base, daily stocks [15] | Colour tables p 0.33-0.94; MHI candle-colour rule 49.76-50.24% [1] | Closed |
| Time of day, news-free | Post-fix reversal of 2.5-3.5 bp per sd of order imbalance [16] | Hour-of-day p = 0.10, then 0.86 lab-final [1] | Closed |
| Post-restart, post-gap | Futures gap reversals in 5 of 7 contracts (abstract only) [17] | 50.1% on 79,002 post-restart bars [1] | Restart closed; quote gaps tested as H7 |
| Payout change, quote freeze | Payout cut once more than 55% of clients win [18]; Deriv prices on "the last valid tick" [19] | 384 asset-level step-downs, 447 step-ups of 0.03 or more in 20.6 days, untested [8] | Open (H1, H6, H7) |
| Spread, tick rate | None with logged n | IQ spread: 3 distinct non-zero values plus 13 zero-spread samples [20] | Spread anomaly not definable; tick gaps tested as H7 |

### 1.3 The rarity wall

Stricter conditions make certification more expensive, not cheaper. With Bonferroni over eight hypotheses, power 0.8 and a 1.5 design effect (variance inflation from correlated trades) for same-day and cross-asset clustering, the owner's sample-size engine needs 10,353 trades to certify +2 points over 54.35%, 1,648 for +5 and 640 for +8 [6]. On a 29-day block [6]:

| Trigger rate | Events | Smallest certifiable true win |
|---|---|---|
| 1% | 2,838 | 57.8% |
| 0.1% | 283 | 64.3% |
| 0.01% | 28 | 83.8% |

Real effects sit below that line. Under a Gaussian increment, 54.35% needs an expected move of about 0.109 standard deviations over the expiry (this report's computation), while Osler's round-number lift, read as a hit-rate gain on a coin-flip base, gives 53.4% to 54.6% [2]. Inference from [6] and [2]: the most detectable sparse trigger must carry a larger effect than any real-FX intraday effect with a reported hit-rate lift, each of which needs real order flow [2, 13]. Extreme-move evidence gives reversal size, not hit rate [9], so H2 stays open. Small samples disguise this. A Quotex reverse-engineer logged "96.4% on 56 samples, dropped to 36% next day" [3], and the owner's mean-reversion cells at 58.2% on 56 and 68.4% on 19 were noise [1].

## 2. How OTC and Synthetic Feeds Are Generated, and Which Generator Properties Create Conditional Predictability

EURUSD-OTC is priced by the broker's software, not by an interbank market, and the broker is counterparty to every trade [7, 22]. A memoryless generator leaves nothing for a condition to select. One with state (a reference level, a regime, a reaction to client orders) would leave a signature in candles, payouts or quote timing.

### 2.1 What IQ Option says

- **Legal terms (A).** The price "is formed from data for trade requests and orders of the Clients, received by the Company"; a "Non-market quote" lets the company correct or cancel results, and exploiting "errors and system failures" counts as fraud [7]. The terms are undated, and the execution policy takes prices from "reputable third-party price feeders" for regulated assets [56], so the clause makes client orders an input, not proof of a controller.
- **Blog guides (C).** OTC is "a simulated market" with "statistical noise" [14], "influenced by a bunch of factors, like the values from the weekday trading sessions, the number of options bought, and the investment amount" [22].
- **Dated profile (C, 2015).** Payouts "depend on the volatility of the market and on the time of the day" [18].
- **Audited absence.** None of IQ Option's terms, execution policy, licence page or blog holds a generator methodology, RNG certificate or feed audit; the help centre was unreachable.

The owner's data fits an internal feed: OTC EURUSD drifts from the real rate with a 128-pip level-difference standard deviation, and a real-leads-OTC rule hits 49.73%, both unverified by the lab [1]. Deriv says its generator "doesn't know if you are long or short" [23].

### 2.2 Generator properties, predictability and signatures

| Property | Exists (grade) | Predictability created | Owner-data signature | Status |
|---|---|---|---|---|
| Client order-flow feedback | T&C s.10 [7] (A) | With or against the crowd | Crowd side vs next move at payout steps | Crowd fade 50.03% on 18,459 [1]; events untested |
| Payout controller | 55% rule [18] (C) | Step-down marks winning clients | Post-step win rate vs matched windows | Untested (H1, H6) |
| Noise around a reference | Weekday values [22] (C) | Reversion from a slow anchor | Variance ratio (VR) below 1 | VR 1.000-1.003, then 0.986 at q = 16 [1]; long horizons untested (H3) |
| Bounded range | Deriv Range Break [24]; none for IQ (D) | Reflection at edges | Reversal at session extremes | Breakout 49.15-49.72%, false-breakout reversal 49.98-50.55% [1] |
| Hidden drift regime | Deriv Drift Switch [24]; none for IQ (D) | Continuation inside a regime | Sign autocorrelation | Always-on excluded; rare or per-asset open |
| Global balancer | Quotex self-report [3] (D) | Cross-asset reversal | Reversal after breadth extremes | Lead-lag max abs(r) 0.020 [1]; breadth untested (H5) |
| Weekday-path replay | One blog phrase [22] (D) | Yesterday's path repeats | Day-over-day correlation vs surrogates | Untested (G1) |
| Memoryless CSPRNG (cryptographically secure random generator) | Deriv's design [25] (A for Deriv) | None | Passes by design; real ticks only once aggregated [26] | Contrast case |

### 2.3 How much latent state the owner's data still allows

A regime active a share d of the time with hit rate p adds lag-1 sign autocorrelation of roughly d x (2p - 1)^2 (this report's approximation). One that pays at 0.84 while active two thirds of the time gives about 0.005, nearly five standard errors on 911,051 bars, against a measured abs(r) of 0.0021 or less [1]. A 2%-duty regime at 65% gives about 0.0018, invisible to pooled tests, which also average single-asset states away. Always-on regimes are closed; rare and per-asset states are not.

One weak hint points to compensation: every out-of-sample AUC interval in the owner's later runs that excluded 0.5 fell below it, five cells in all, which the lab itself read as chance [1], and under compensation effects "good backtest performance is an indicator of negative future results" [27]. The pattern motivates H3 and H5 and proves nothing.

### 2.4 The controller inference and its counterweight

This is inference from sourced premises. Client orders feed the OTC price [7, 22], and payouts were cut once more than 55% of clients won [18]. Internalising brokers' threshold controls "compress that tail into a small number of extreme events" [28], and a binary platform ran per-customer settings under which "customers would win more trades than they lost" until switched [29]. Jointly these imply that a flow-reactive generator acts in discrete, thresholded events, and the payout step is the only such event a client can see. The 55% rule counts clients in the money per asset in a 2015, pre-OTC profile with payouts up to 92%, so its nearness to today's 54.35% is coincidence, not calibration [18]. No prior test conditioned on payout steps, so H1 has the best-grounded mechanism, though at 8 events a day it is the least detectable test.

The counterweight is strong. The same profile ties lower payouts to low volatility, when the market is "more predictable" [18], so a step-down may mark a quiet state rather than a controller act, and the fade's 0.30-0.45 skew band is the middle of a bimodal mood distribution, not a sub-threshold regime [30]. If cuts follow crowd skew, H1 re-expresses the null crowd fade (50.03% on 18,459) [1] with a side read from the thin-participation mood that fails as a rare crowd state, so H1 trades only inside a mood band and must beat a matched mood-only fade. Feedback against each client's own position would, as the lab concluded, be a further reason not to trade, not an edge [1].

## 3. Evidence from Other Platforms' Synthetic Feeds: Pocket Option, Quotex, Olymp Trade, Deriv

An exploitable generator or a logged above-break-even backtest on any of these broker-controlled feeds would raise IQ Option's prior.

| Platform | Documented design | Audit | Best logged test | Grade (mech / edge) |
|---|---|---|---|---|
| Deriv | "a cryptographically secure methodology", fixed volatility per index [25]; designed regime families [24]; Boom/Crash "Each tick is independent" [31] | "rigorously audited by independent third parties", auditor unnamed [23] | 1,578 pre-registered variants, one family survived [32] | A (stated) / C, CFD (contract for difference) only |
| Quotex | Self-report: lagged Binance price x fixed scale, balancer bias -0.212% to -0.573% [3]; review cites "platform-wide user activity" [33] | None | "0 validated edges" on 181K ticks [3] | D / D |
| Pocket Option | None published; ~500 ms tick clock observed [21] | None | Flat-run continuation 49.83% vs 49.85% base, 1,493 free-sample events (this report's computation); blog win rates of 55-65% unlogged [34] | D / D |
| Olymp Trade | Trade-press claim of internal quoting engines that smooth feeds [57] | None found | None found | D / D |

**Deriv** supplies the best external test (grade C: pre-registered, Holm-corrected (step-down family-wise) at t >= 4.0, locked holdout, commercial author). On 12 IC Trading synthetics, 943 variants produced no survivor, the best in-sample t across 448 first-round tests was 2.58, "exactly what noise produces at that test count", and Deriv's volatility indices gave P(up after up) of about 0.499 [32]. Only Drift Switch, built with hidden up, down and flat regimes, passed, with walk-forward t of 12.4 to 15.5 on 2,067 to 3,546 trades at win rates of 43-51% [32]. Volatility Switch and Range Break carry designed state too and failed. The survivor earned through a stop-and-exit CFD payoff that a fixed-payout binary cannot use.

- **Quotex** has the only logged artefact hunt on a broker OTC binary feed, an anonymous self-report (grade D) in which lag trading ran at "71% base, degrades to 50% with more samples" and the verdict was "Every edge we find gets balanced out" [3].
- **Pocket Option** sells its tick data [21]; its free sample files show no flat-run effect (table above).
- **Olymp Trade** offers only a grade-D trade-press claim [57]; its official Q&A, broker reviews and vendor bot posts hold no audit or logged backtest.

**Regulators (A).** ESMA, ASIC and the FCA restricted or banned retail binaries because most retail clients lose [35, 36, 37, 38]. CFTC complaints that "the countdown to expiration is extended arbitrarily until the trade becomes a loss" [39] show outcome controls exist in this industry, though no source places them on IQ Option.

The one validated synthetic edge came from designed, disclosed hidden state. IQ Option discloses only that client orders are an input, so the record lowers its prior for candle-only triggers but not for payout events (H1, H6), and Deriv volatility data serves as a known-null control.

## 4. Methods for Finding Rare Conditional Edges Without Overfitting

Testing many conditions manufactures false winners: try enough rules and the best looks impressive by chance. The defence is to bound that error or certify only rules declared in advance.

### 4.1 Abstention certifies; it does not discover

Selective classification (a model allowed to decline to predict) sets a confidence threshold so that a binomial-tail bound on held-out risk stays below target, reaching 2% top-5 ImageNet error "with probability 99.9%, and almost 60% test coverage" on i.i.d. data [5]. Joint training of prediction and rejection does better still [40]. By the definition of selective risk [41], an accepted region's win rate is the average true conditional win probability over it, so no reject option, conformal wrapper or meta-model can exceed it. The owner measured the failure: a top-2% confidence selection won 52.03% on 5,867 development trades and 49.22% on 3,465 lab-final trades [1].

Meta-labeling (a second model deciding whether to act on a primary signal) "cannot improve the performance of a main Machine Learning model trained end-to-end on the same data" [4]. It lifted precision from 0.48 to 0.54 on a trend primary but only from 0.17 to 0.20 on a mean-reversion primary [42]. Here it is admissible only as a pre-declared filter on variables the price-only lab never used (payout, mood, quote cadence), counted in the family.

Extreme-value conditioning here means frozen empirical tail quantiles (H2, H2b, H5). Generalised extreme value fits estimate the size of intraday tails and the stability of their shape [59] but not the sign of the next move, so they can steady where a threshold sits, never supply the edge.

### 4.2 Conformal prediction under drift

Split conformal prediction (distribution-free intervals calibrated on held-out residuals) "requires exchangeability and does not automatically apply to the dependent returns", and rolling versions lost to volatility benchmarks in 42 of 52 paired comparisons [43]. Drift adds a total-variation coverage gap that cannot be estimated without assumptions [44]. Adaptive conformal inference guarantees coverage only marginally over time, not on the traded subset [45]. Pre-declared group coverage is attainable where exact conditional coverage is not [46]. Learn-then-Test treats threshold choice as family-wise testing [47]: declare each trigger in advance.

### 4.3 Multiple testing, and why overfitting costs money here

The expected best in-sample Sharpe of N skill-less strategies grows like sqrt(2 ln N), so ten tries give 1.57 with zero skill [27]. A new factor needs t > 3.0 [48]. The probability of backtest overfitting [49] and the deflated Sharpe ratio [50] price in the trial count. Technical rules selected under FDR (false discovery rate) control lost their edge to costs smaller than any binary payout haircut [51].

Without memory, overfitting need not lose money in a market [27], but binaries differ: an overfit rule regresses to 50%, and 50% at 0.84 loses 8% per stake. The owner measured -7.9% per stake on the crowd fade and -9.4% on the selected policy [1].

### 4.4 The protocol every hypothesis follows

1. **Freeze.** A dated file fixes each trigger, side, single expiry and payout rule, with family alpha 0.05 and Bonferroni alpha 0.00625; amendments are time-stamped before affected data is opened.
2. **Three blocks.**
   - The Mar-Jul 2026 archive, already searched, freezes thresholds and frequencies but never certifies.
   - The Jul 31-Aug 20 live window is partly spent, since its outcomes were read for the crowd fade and the 1-second models [1], so it calibrates and sets futility.
   - Only a fresh forward cohort certifies, split by contiguous days with an embargo (a dropped gap so labels cannot leak) of at least expiry plus feature lookback.
3. **Nulls (this report's design).** Round-number triggers must beat the 99th percentile of 1,000 same-spacing random lattices; event triggers face time-matched placebo events; time-order statistics face day-shuffled and spectral surrogates, never bar shuffles [52]. The same pipeline must pass nothing on Deriv volatility ticks [25].
4. **Power.** In the lab's power control the selected configuration carried a 57% edge planted on about 10% of bars and won 55.9-57.3% out of sample in 6 of 6 seeds. Only 1 of 6 passed every strict check. The rest failed on too few lab-final trades at K = 432 and on a calibration-slope check that rejects real step edges [1]. Repair: replace the slope check with calibration-in-the-large and plant +5-point edges on 0.5-1% of bars, the sizes targeted here, which the control never tested.
5. **Certificate.** The one-sided Clopper-Pearson (exact binomial) lower bound at alpha 0.00625 must exceed the break-even in force at entry. A day-block bootstrap of return per stake must stay positive, and the sign must hold in each third of the block. 1,648 turbo trades need at least 947 wins (57.46%), or 967 (58.68%) at a 0.80 payout; 1,653 binary trades need 940 (56.87%) [6].
6. **Ties.** The lab refunds ties (0.61% at 2 minutes) [1]; so does IQ's binary guide: "If the closing and opening prices are the same, you neither win nor lose" [58]. The terms make an at-strike Digital Option a loss [7], so certificates must also pass with ties as losses, which lifts the 2-minute break-even to about 54.68%.
7. **Outcomes.** **CERTIFIED**, **NULL-INFORMATIVE** (n reached, planning edge excluded) or **UNDERPOWERED** (n not reached), abstaining in the last two, with a futility stop once the running upper bound falls below break-even. A certified row trades only while a rolling lower bound on shadow results stays above break-even, the Deriv survivor's gate [32].

## 5. Ranked Pre-Registerable Sparse-Entry Hypotheses for Our Data

Rank is mechanism grounding times detectability on the forward block, with diagnostic and monitor rows last, which puts H1 fifth. Frequencies are measured counts with outcomes unread [8]; required n is the engine's family-of-8 figure at design effect 1.5 [6].

### 5.1 The frozen family

| Rank | ID | Exact trigger | Side | Expiry (break-even) | Measured frequency | n at +5 / +8 pt | Grade (mech / edge) | Evidence |
|---|---|---|---|---|---|---|---|---|
| 1 | H2 Extreme 2-min move fade | abs(z0) >= per-asset 99.5% quantile of z0; nested H2b at 99.9%, opened only if H2 certifies (fixed sequence, no extra alpha) | Reverse the move | 2 min turbo (54.35%) | 6,079, 50.2/day, 0.501%; H2b 1,223, 10.1/day | 1,648 / 640 | C / D | [9, 10, 1] |
| 2 | H3 Anchor-gap reversion | abs(gap) > 2.5, first bar of the excursion | Toward the mean | 10 min binary (53.76%) | 6,515, 53.8/day, 0.537% | 1,653 / 642 | C / D | [22, 14, 1] |
| 3 | H4 Round-number first-touch fade | Within 0.01% of a 0.0050 lattice level (0.50 for JPY), approach of 8 pips or more, no touch in prior 60 min; must beat 1,000 placebo lattices | Against the approach | 10 min binary (53.76%) | 10,587, 87.5/day, 0.872% | 1,653 / 642 | A in one FX order book, contested / D | [13, 2, 3] |
| 4 | H5 Breadth-extreme fade | abs(mkt0) >= 99.0% quantile pooled over all asset-bars, mkt0 being the leave-one-out mean of the other pairs' z0 at the same bar [53]; trade assets whose own z0 has the same sign | Against the sign of mkt0 | 2 min turbo (54.35%) | 12,139 asset-bars, 100.3/day, 1.000% | 1,648 / 640, as timestamp clusters | D / D | [3, 1] |
| 5 | H1 Payout step-down fade | Turbo or binary payout on the asset falls 0.03 or more vs that product's previous sample, steps within 300 s merged; nearest prior turbo mood sample within 60 s has call fraction between 0.05 and 0.95, not exactly 0.5; enter at next 1-s close + 2 s | Against the mood majority; must beat a matched mood-only fade | 5 min turbo, at the turbo payout in force (about 55.25-55.56%) | 167 in 20.6 days, 8.1/day | 1,648 / 640 | A-C / D | [7, 18, 22] |
| 6 | H6 Payout step-up mirror | Payout rises 0.03 or more, merged as for H1 | With the mood majority | 5 min turbo, at the new payout | 370 with usable mood (no band), 18.0/day | 1,648 / 640 | C / D | [18]; mirror of H1 |
| 7 | H7 Quote-stall resume fade (diagnostic, not tradable) | Gap of 60 s or more between received quote timestamps; first tick after | Against the jump across the gap | 2 min turbo (54.35%) | 926, 45.0/day | 1,648 / 640 | D / D | [19, 7] |
| 8 | H8 15-min breakout continuation (monitor) | (close - 20-bar low) / (20-bar high - 20-bar low) >= 0.999 (<= 0.001) on 5-min bars | With the break | 15 min binary (53.76%) | 1,723 in the 29-day lab-final, about 59/day | 1,653 / 642; +1 pt 41,544 | B / D | 53.37% on 1,723 lab-final, 49.85% on 3,277 development, bound 49.28% [1] |

- **z0** is the 2-min log return over vol60, the standard deviation of the previous 60 two-minute log returns on the asset (none on the first bar after a restart).
- **H3's gap** is (log close - 1-day mean) / (vol60 x sqrt(720)), the mean taken over the last 720 bars.
- **H4's approach** is the maximum distance from the level over the prior 5 bars, a pip being 0.0001 (0.01 for JPY).

### 5.2 Power and calendar

From the measured daily rates [8] and the same engine [6]:

| ID | Events per 29-day forward block | Smallest certifiable edge per block | Days to the +5 pt n | Live window alone |
|---|---|---|---|---|
| H2 / H2b | 1,456 / 293 | +5.4 / +11.8 pt | 32.8 / 163 | Archive trigger |
| H3 | 1,560 | +5.2 pt | 30.7 | Archive trigger |
| H4 | 2,538 | +4.1 pt | 18.9 | Archive trigger |
| H5 | 2,909 asset-bars | +3.8 pt, less if clusters bind | 16.4 | Archive trigger |
| H1 | 235 | +13.2 pt | about 204 | UNDERPOWERED (167 events) |
| H6 | 522 | +8.9 pt | 91.7 | UNDERPOWERED (needs about +10.5 pt) |
| H7 | 1,305 | +5.7 pt | 36.6 | UNDERPOWERED (needs about +6.7 pt) |
| H8 | about 1,723 | about +5 pt | about 28 | Years at +1 pt |

A 60-day frozen forward collection therefore:

- powers H2 to H5 and H7 at about +5 pt;
- reaches H2b only at about +8 pt;
- certifies H1 only at about +9.2 pt (486 events) and H6 at about +6.2 pt;
- leaves H8 as a long-run monitor.

### 5.3 Notes that change how rows run

- **H1 and H6 are a pair.** Certification in opposite directions (fade the crowd after a cut, follow it after a raise) is a controller signature; same-side success points to payout-level selection, not flow.
- **H4 is contested.** Thirty large stocks show "no consistent psychological barriers" near round numbers [60], and Osler's bounce needs real take-profit orders [2]; it can reach OTC only through client orders entering the price [7].
- **H5 counts clusters.** When the 15 pairs fire together, effective n can shrink up to 15-fold; the day-block bootstrap governs.
- **H7 is never an entry.** A win on a stalled quote invites the non-market-quote correction [7], and a 60-second gap may be the owner's connection; a certified H7 becomes a no-trade filter.

### 5.4 Gates and a dropped candidate

- **G1 Weekday-path replay.** One cross-day path-correlation statistic per asset at lags of 1 and 5 days, against day-shuffled and circularly shifted surrogates, Holm over 15 assets [52]; a pass unlocks a separately registered family.
- **G2 and G3** run the planted-edge check and the Deriv known null as gates before any null is called informative.

**Crowd extremes, dropped on measured counts.** abs(call fraction - 0.5) >= 0.45 holds on 33.0% of 957,521 turbo mood samples (2,602 onsets a day), 25.92% sit at exactly 0.5, and the 90th percentile of the rest is 0.4999 [30]. Thin participation dominates, and with no participation count in the feed, mood cannot define a rare crowd state.

### 5.5 What each dataset can test

- The **2-minute archive** (1,213,807 valid decisions) freezes H2 to H5 thresholds and frequencies and runs G1 [8].
- The **5-minute archive** carries H8.
- **Live 1-second candles, mood and payout samples** define and label H1, H6 and H7.

Payout samples sit 300 s apart at the median, 10th and 90th percentiles [20], so a step is timed only to within five minutes. Raise sampling to 30 s before the forward block. One-second candles cover about 27% of the live window, and the bar-close proxy matches the 1-second outcome on 95.3% of 33,264 decisions [1], so certification should use 1-second labels or broker settlement records.

**Decision rule:** no stake on any hypothesis until it is CERTIFIED on the forward block, then practice account only, with the owner's go-ahead. Nothing here licenses real capital.

## 6. What the In-House Null Already Rules Out, and the Evidence Grade of Each Idea

*Ruled out* means tested with enough power at the stated expiry to exclude an edge that pays, not shown impossible. The nulls exclude edges of about +3 points or more on large slices, not every edge; a planted 57% edge was carried in 6 of 6 seeds but passed every strict check in only 1 [1].

### 6.1 Ruled out and not ruled out

| Ruled out (grade B, logged [1]) | Not ruled out (source of the frozen family) |
|---|---|
| Unconditional direction: up rate 50.061% on 911,051 bars | Strong states on 2% of bars or fewer (H2, H2b) |
| Always-on regimes: autocorrelation, VR, HMM | Single-asset states diluted by pooling |
| Broad rules (MHI, trend, breakout, RSI (relative strength index), exhaustion) and colour tables | Payout-step controller events (H1, H6) |
| Model-confidence top-q% selection | Long-horizon anchor reversion (H3) |
| Hour of day; restart window | Breadth extremes (H5) |
| Crowd-level fade | Quote stalls (H7, diagnostic) |
| Earlier fixed-state search (0 of 360 states qualified) | Weekday replay (G1); own-position feedback; live practice (53.2% on 250 trades, 95% CI about 47-59%, underpowered) |

Strict-condition entry itself has an in-house null. The OTC Expiry Regime study (9 Nov 2026) fixed 360 geometric states before seeing targets, abstained by default, required a 99% Wilson lower bound above break-even + 0.02 in both train and calibration blocks, and qualified 0 of 360 [1]. Beyond the tables above, ML direction at minute horizons is ruled out (A against [54, 55]), abstention or meta-labeling is retired as an edge source (A, theory [4, 5]), and multi-timeframe and spread triggers grade D / D.

### 6.2 Expected result and what would change it

This report's judgement puts the chance that all eight return NULL-INFORMATIVE or UNDERPOWERED at about 70-85%. Separate assessments of the event, latent-state and real-FX families gave about 70%, 85% and 75%; they share one feed and one null pipeline, so they are not multiplied. A CERTIFIED forward row that also passes the ties-as-losses sensitivity and a repaired planted-edge check would change the call. A G1 pass in three or more assets would justify a new, separately registered family.

If all eight return null, OTC is closed at the protocol level on candle-observable information, leaving only practice-account probes of own-position feedback, if the owner authorises them. Adding triggers is the wrong response, since each added hypothesis raises the bar for the rest [27, 48].

## Sources

[1] Owner's prior lab report: OTC Quant Lab, independent edge search on IQ Option OTC binaries (verdict REJECTED, 11 November 2026). Internal analysis. docs/research/otc-lab/2026-11-11-lab-report.md
[2] Osler, C. L. "Currency Orders and Exchange-Rate Dynamics: Explaining the Success of Technical Analysis." FRBNY Staff Report 125, 2001. https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.pdf
[3] Anonymous. "I am reverse-engineering a synthetic OTC binary options price feed" (Quotex). Artificial Analysis MicroEval. https://artificialanalysis.ai/microevals/i-am-reverse-engineering-a-synthetic-otc-binary-options-pric-1785409957304
[4] "Why Meta-Labeling Is Not a Silver Bullet." QuantConnect forum. https://www.quantconnect.com/forum/discussion/14706/why-meta-labeling-is-not-a-silver-bullet/
[5] Geifman, Y., El-Yaniv, R. "Selective Classification for Deep Neural Networks." NeurIPS, 2017. https://arxiv.org/abs/1705.08500
[6] Owner's sample-size engine output (services/otc_quant_lab/risk.trades_needed; one-sided, power 0.8) and exact Clopper-Pearson win counts. Internal analysis. docs/research/otc-lab/sparse-entry/sample-size-table.md; verified by docs/research/otc-lab/sparse-entry/verify_report_numbers.py
[7] IQ Option (Digital Invest Ltd). "General Terms and Conditions." https://static.cdnroute.io/files/storage/public/cc/i5/g32cpif6r6n5vlrg.pdf
[8] Owner's measured trigger frequencies (counts only, outcomes not read). Internal analysis. docs/research/otc-lab/sparse-entry/trigger-frequencies.md; scripts docs/research/otc-lab/sparse-entry/count_trigger_frequencies.py and count_payout_steps_asset_level.py
[9] Rif, A., Utz, S. "Short-term stock price reversals after extreme downward price movements." Quarterly Review of Economics and Finance, 2021. https://opus.bibliothek.uni-augsburg.de/opus4/files/94257/1-s2.0-S1062976921000922-main.pdf
[10] Zawadowski, A. G., Andor, G., Kertesz, J. "Short-term market reaction after extreme price changes of liquid stocks." 2004. https://arxiv.org/pdf/cond-mat/0406696
[11] Chaudhary. "Multi-Scale Markov-Switching GARCH" (EUR/USD). 2026. https://arxiv.org/abs/2606.06190
[12] Mesfin. "A Validated Volatility-Volume-Gap Classifier for Regime Identification in MNQ Intraday Data." 2026. https://arxiv.org/abs/2605.11423
[13] Osler, C. L. "Support for Resistance: Technical Analysis and Intraday Exchange Rates." FRBNY Economic Policy Review, July 2000. https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf
[14] "OTC Trading on IQ Option: How to Trade on Weekends." IQ Option Official Blog. https://blog.iqoption.com/en/otc-trading-on-iq-option-how-to-trade-securities-over-the-counter/
[15] Caginalp, G., Laurent, H. "The predictive power of price patterns." Applied Mathematical Finance, 1998. https://c.mql5.com/forextsd/forum/210/The%20Predictive%20Power%20of%20Price%20Patterns.pdf
[16] Krohn, I., Mueller, P., Whelan, P. "Foreign Exchange Fixings and Returns Around the Clock." Bank of Canada Staff Working Paper 2021-48. https://www.bankofcanada.ca/wp-content/uploads/2021/10/swp2021-48.pdf
[17] Rentzler, J., Tandon, K., Yu, S. "Intraday price-reversal patterns in the currency futures market." Journal of Futures Markets, 2006. https://ideas.repec.org/a/wly/jfutmk/v26y2006i11p1089-1130.html
[18] "IQ Option Delivers Own HTML5 Binary Options Platform With CySEC License." Finance Magnates, 13 February 2015. https://financemagnates.com/forex/brokers/iq-option-delivers-html5-binary-options-platform-cysec-license/amp
[19] "Trading terms, conditions, and official guidelines." Deriv. https://deriv.com/terms-and-conditions/trading-terms
[20] Owner's measurements of live payout and quote samples, Jul 31-Aug 20 2026 (payout spacing 300 s at median, p10 and p90; spread: 3 distinct non-zero values plus 13 zero-spread samples; counts only, outcomes not read). Internal analysis. data/ml/market_context.sqlite; docs/research/otc-lab/sparse-entry/verify_report_numbers.py
[21] PHCStanton. "pocket-option-otc-dataset." GitHub. https://github.com/PHCStanton/pocket-option-otc-dataset
[22] "OTC Trading on IQ Option: Full Guide." IQ Option Official Blog. https://blog.iqoption.com/en/what-is-otc-trading-a-guide-for-weekend-and-off-hours-traders/
[23] "Do brokers manipulate synthetic indices?" Deriv Experts. https://experts.deriv.com/insights/do-brokers-manipulate-synthetic-indices
[24] "Synthetic indices trading: Derived indices." Deriv. https://deriv.com/markets/derived-indices/synthetic-indices
[25] Deriv. "Key Information Document: CFDs on Derived Indices (Volatility Indices)." https://docs.deriv.com/regulatory/kid/kid_deriv_volatility.pdf
[26] Onofri, Shternshis, Marmi. "Emergence of Randomness in Temporally Aggregated Financial Tick Sequences." https://arxiv.org/abs/2511.17479
[27] Bailey, D. H., Borwein, J. M., Lopez de Prado, M., Zhu, Q. J. "Pseudo-Mathematics and Financial Charlatanism." Notices of the AMS, 2014. https://www.ams.org/notices/201405/rnoti-p458.pdf
[28] "B-Book Challenge: How Delayed Hedging, Threshold-Based Controls Create Non-Linear Losses." Finance Magnates. https://www.financemagnates.com/forex/b-book-challenge-how-delayed-hedging-threshold-based-controls-create-non-linear-losses/amp
[29] CFTC v. Yukom Communications et al. Complaint, N.D. Ill. 1:19-cv-05416, 2019. https://cftc.gov/media/2331/enfyukombinaryperetzcomplaint08122019/download
[30] Owner's count of mood-sample crowd extremes (957,521 turbo samples over 20.58 days; counts only, outcomes not read). Internal analysis. data/ml/market_context.sqlite (mood_samples); count script docs/research/otc-lab/sparse-entry/count_crowd_extreme.py
[31] "Stop-Loss Slippage on Boom & Crash Indices Explained." Deriv Traders Academy. https://traders-academy.deriv.be/trading-guides/stop-loss-execution-boom-crash-indices
[32] "1,578 Strategy Variants on Synthetic Indices: Why Only One Survived (AureusAI Synthetic Drift Sentinel)." MQL5 Traders' Blogs, 3 November 2026. https://www.mql5.com/en/blogs/post/779132
[33] "Quotex OTC Market: Signals, Bots, Patterns And Strategies." Traders Union. https://tradersunion.com/brokers/binary/view/quotex/otc-market/
[34] "Pocket Option AI Trading Success Rate: What Real Data Shows." Pocket Option blog. https://pocketoption.com/blog/en/interesting/trading-platforms/pocket-option-ai-trading-success-rate/
[35] ESMA. "ESMA50-162-214: Product intervention analysis, binary options." 1 June 2018. https://www.esma.europa.eu/sites/default/files/library/esma50-162-214_product_intervention_analysis_binary_options.pdf
[36] ASIC. "Regulation Impact Statement: Product intervention, OTC binary options." April 2021. https://oia.pmc.gov.au/sites/default/files/posts/2021/04/ris-product-intervention-otc-binary-options-published-1-april-2021.pdf
[37] ASIC. "Report 736: Response to submissions on CP 362." September 2022. https://download.asic.gov.au/media/pcilau51/rep736-published-5-september-2022.pdf
[38] FCA. "PS19/11: Product intervention measures for retail binary options." https://www.fca.org.uk/publications/policy-statements/ps19-11-product-intervention-measures-retail-binary-options
[39] CFTC/SEC. "Investor Alert: Binary Options and Fraud." https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/fraudadv_binaryoptions.html
[40] Geifman, Y., El-Yaniv, R. "SelectiveNet: A Deep Neural Network with an Integrated Reject Option." 2019. https://arxiv.org/abs/1901.09192
[41] El-Yaniv, R., Wiener, Y. "On the Foundations of Noise-free Selective Classification." Journal of Machine Learning Research 11, 2010. https://jmlr.org/papers/volume11/el-yaniv10a/el-yaniv10a.pdf
[42] "Does Meta Labeling Add to Signal Efficacy?" Hudson & Thames. https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy/
[43] Aich et al. "Temporal Conformal Prediction (TCP): Rolling Calibration for Financial Return Intervals." https://arxiv.org/abs/2507.05470
[44] Barber, R. F., Candes, E., Ramdas, A., Tibshirani, R. "Conformal Prediction Beyond Exchangeability." https://arxiv.org/abs/2202.13415
[45] Gibbs, I., Candes, E. "Adaptive Conformal Inference Under Distribution Shift." https://arxiv.org/abs/2106.00170
[46] Gibbs, I., Cherian, J., Candes, E. "Conformal Prediction with Conditional Guarantees." https://arxiv.org/abs/2305.12616
[47] Angelopoulos, A., Bates, S., Candes, E., Jordan, M., Lei, L. "Learn then Test: Calibrating Predictive Algorithms to Achieve Risk Control." https://arxiv.org/abs/2110.01052
[48] Harvey, C., Liu, Y., Zhu, H. "... and the Cross-Section of Expected Returns." NBER Working Paper 20592. https://www.nber.org/papers/w20592
[49] Bailey, D. H., Borwein, J. M., Lopez de Prado, M., Zhu, Q. J. "The Probability of Backtest Overfitting." https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
[50] Bailey, D. H., Lopez de Prado, M. "The Deflated Sharpe Ratio." Journal of Portfolio Management, 2014. https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
[51] Bajgrowicz, P., Scaillet, O. "Technical trading revisited: False discoveries, persistence tests, and transaction costs." https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Bajgrowicz_Scaillet.pdf
[52] "Surrogate Data Testing: A Null Model for Any Statistic, and Why Shuffling Bars Is Not One." MQL5 Articles. https://www.mql5.com/en/articles/24260
[53] Owner's feature code: cross-asset breadth statistic mkt0 (leave-one-out mean of other pairs' z0). Internal analysis. services/otc_quant_lab/features.py (cross_asset, line 134)
[54] Arantes et al. "Machine Learning vs. Randomness: Challenges in Predicting Binary Options Movements." https://arxiv.org/abs/2511.15960v1
[55] "Intraday trading strategy selection under transaction costs with machine learning." Frontiers in Applied Mathematics and Statistics, 2026. https://www.frontiersin.org/journals/applied-mathematics-and-statistics/articles/10.3389/fams.2026.1888767/full
[56] IQ Option. "Order Execution Policy" (global). https://files.iqoption.com/storage/public/5a/c3/aadcad3f1/order_execution_policy_global.pdf
[57] "Best Time To Trade On Olymp Trade & Fixed Time Tips." Traders Union. https://tradersunion.com/brokers/forex/view/olymptrade/best-time-to-trade/
[58] "How to Trade Binary Options: Facts, Tips, Strategies." IQ Option Official Blog. https://blog.iqoption.com/en/how-to-trade-binary-options-an-a-z-guide-from-iq-option/
[59] Lin, S., Kong, A., Azencott, R. "Can Generalized Extreme Value Model Fit the Real Stocks." 2024. https://arxiv.org/abs/2412.06226
[60] Lobão, J., Fernandes, J. "Psychological Barriers at Round Numbers in Single Stock Prices." https://repositorio-aberto.up.pt/bitstream/10216/121036/2/206001.pdf
