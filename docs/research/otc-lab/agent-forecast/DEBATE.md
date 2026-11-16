# Judge: debate and verdict

**Statistician.** Strongest: pooled tests on ~35k samples across all snapshots; no autocorrelation, mean-reversion or z-score rule clears 53.76%. Per-asset in-sample hits (e.g. S01 MR 0.53) sit inside noise. Objection (chartist): pooling may wash out pattern-specific setups. Answer: the setups were tested pooled too (below) and failed.

**Chartist.** Strongest: 15 setups with textbook confluence (EMA stack, 12h extreme, engulfing/hammer, ATR momentum), confidence 0.54-0.56. Objection (statistician, regimes): those confidences are asserted, not measured. Regime-conditioned versions hit 48-52%. My own check (judge/check.py): "at 4h extreme with EMA20>EMA50 and price beyond EMA20, call continuation 10 min" pooled over the snapshot history gave 49.2% (n=4,638) for up and 49.9% (n=4,538) for down. Even at the claimed 0.55 the expected value is +0.023 per unit, inside any reasonable error bar. Rejected.

**Regimes.** Strongest: every regime-conditioned rule (drift, post-gap, volatility state) tested in-snapshot at 48-52%. Objection: regimes are labeled from the same 12h, so the tests have low power per regime. Fair, but low power cuts against calling, not for it.

**Cross-asset.** Strongest: OTC pairs that share a currency co-move (S02 CADJPY vs AUDUSD corr +0.96), so a spread dislocation should revert. Objection: the 54.7-57.1% common-shock reversion hits came from overlapping windows, which inflates n and gives false precision. Its own OOS run shows lead-lag IC 0.016 +/- 0.025, triangle reversion 0.013 +/- 0.016, currency-strength momentum 0.004 +/- 0.013; spread reversion OOS returned no valid sample. All zero within one standard error. The analyst abstained itself.

**Skeptic.** Strongest: each asset's 12h is indistinguishable from its shuffled returns (minimum p far above the Bonferroni bar 0.0003 across 160 tests). Objection: shuffle tests miss conditional structure. But the conditional rules above were tested directly and also failed.

**Prior.** This repo's earlier OTC work (live 2026-10-30 and the quant lab 2026-11-11) found direction at chance. Nothing in this panel overturns that.

## Verdict

Abstain on all 40. A wrong call costs 1 and a right one earns 0.86, so a call is only worth making at 53.76% or better. No forecaster produced a measured, out-of-sample hit rate above that. The only directional calls (chartist, 15) rest on a pattern whose pooled hit rate is 49-50%. Taking those 15 at the measured rate would lose about 0.07 per call, so about -1.1 units over the 15.

Final: up 0, down 0, abstain 40.
