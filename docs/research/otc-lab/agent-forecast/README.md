# Agent-panel forecasting test (2026-11-16)

**Result: the panel made no trade. The only forecaster that traded lost.**

## Setup

- 40 random decision moments, drawn from 2026-05-16 to 06-15. This period was never shown to the agents beyond each snapshot.
- Each snapshot held 12 hours of 2-min candles for all 15 pairs, up to the decision bar, and nothing after it.
- Each moment was a 10-minute up/down call. A win paid 0.86 per 1 staked; break-even is 53.76%.
- Five coding-agent forecasters (statistician, chartist, regime analyst, cross-asset analyst, skeptic) made their own calls. A judge then reviewed all five and made the final call ([DEBATE.md](DEBATE.md)).
- The forecasts were frozen in git (`590ae76`) before the held-back answers were read.

## Results

| Forecaster | Calls | Won | Win rate (95% CI) | Return per stake |
|---|---|---|---|---|
| Statistician | 0 of 40 | | | 0 |
| Chartist | 15 of 40 | 4 | 26.7% (7.8% to 55.1%) | -0.50 |
| Regime analyst | 0 of 40 | | | 0 |
| Cross-asset | 0 of 40 | | | 0 |
| Skeptic | 0 of 40 | | | 0 |
| **Judge (final)** | **0 of 40** | | | **0** |

## What the abstainers found

Four forecasters ran tests inside their own snapshots before calling, and each abstained everywhere:
- mean-reversion and momentum rules over about 35,000 pooled samples: 46% to 53.1%;
- regime-conditioned rules over about 172,000 cases: 48% to 52.4%;
- cross-asset signals: predictive correlation indistinguishable from zero;
- shuffle tests: every asset looked like a random walk.

The judge tested the chartist's breakout-continuation rule on about 9,000 pooled cases, found 49% to 50%, and overruled all 15 calls. That was correct: the chartist went 4 for 15.

## Limits

40 moments can only detect a very large edge. The finding that holds up is that every agent's own analysis of the history found no edge to act on, which matches every earlier OTC study. OTC stays closed ([../CLOSED.md](../CLOSED.md)).
