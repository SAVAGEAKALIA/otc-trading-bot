# Per-case agent panel (2026-11-18)

**Result: no evidence of an edge. Three of six forecasters finished above break-even and three below. Pooled over every forecaster call, the win rate was 53.5%, below the 54.2% break-even. Every interval includes a coin flip.**

## Setup

- 40 held-back moments from 2026-06-16 to 07-27, a period no agent had seen. Every decision fell on a 10-minute boundary.
- For each case the agents saw 12 h of 2-min candles and 24 h of 5-min candles for all 15 pairs, up to the decision and nothing after it.
- Each agent studied each chart on its own (no pooled backtests) and called buy, sell or abstain with a horizon of 2, 5 or 10 min. Break-even is 54.35% at 2 and 5 min and 53.76% at 10 min.
- A judge debated every case and made the final call ([DEBATE.md](DEBATE.md)).
- All calls were frozen in git (`6cd0894`) before the answers were read. Scored by [score.py](score.py), with output in [result.json](result.json).

## Results

| Forecaster | Calls | Won-lost | Win rate (95% CI) | Units won per 1 staked | Return per stake |
|---|---|---|---|---|---|
| Price action | 30 | 17-13 | 56.7% (37.4 to 74.5) | +1.30 | +4.3% |
| Trend | 26 | 13-13 | 50.0% (29.9 to 70.1) | -2.06 | -7.9% |
| Reversal | 27 | 13-14 | 48.1% (28.7 to 68.1) | -2.96 | -11.0% |
| Multi-timeframe | 20 | 11-9 | 55.0% (31.5 to 76.9) | +0.30 | +1.5% |
| Cross-asset | 24 | 14-10 | 58.3% (36.6 to 77.9) | +1.82 | +7.6% |
| **Judge (final)** | **4** | **3-1** | 75.0% (19.4 to 99.4) | +1.52 | +38% |

## How to read it

- **Pooled, the panel is at chance.** Across the five forecasters there were 127 calls and 68 wins: 53.5%, below break-even. The trend and reversal camps took opposite sides on most stretched charts and cancelled out.
- **The best scores are what chance produces.** With five agents making about 25 calls each, a pure coin gives the best of the five 58% or more about half the time. Cross-asset's 58.3% and price action's 56.7% are within that range.
- **The judge's 3 of 4 means nothing on its own.** Four calls cannot separate 75% from 50%.
- **Data quality:** several forecasters flagged one-bar level jumps in C16, C20 and C23, which look like feed breaks. Everyone abstained there.

## What would settle it

The agents took 2 to 3 minutes per 40 cases, so a 400-case rerun is practical. With the same panel and judge on fresh moments, the 95% interval for a forecaster with about 250 calls shrinks to about ±6 points. Only then can 56% be told apart from 50%.
