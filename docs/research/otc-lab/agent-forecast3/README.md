# 400-case agent panel (2026-11-19)

**Result: no edge. Every forecaster and the judge lost money. Pooled over 1,268 forecaster calls, the win rate was 49.9% (628 won, 631 lost), a coin flip against a 54.2% break-even. Nothing certified.**

## Setup

- 400 fresh moments from 2026-03-30 to 07-27, each on a 10-minute boundary and at least 1 day from every earlier panel moment.
- Per case, the agents saw 12 h of 2-min candles and 24 h of 5-min candles for all 15 pairs, up to the decision.
- Each forecaster read each chart on its own and called buy, sell or abstain with a 2, 5 or 10 min horizon. The judge debated every case ([DEBATE_TABLE.md](DEBATE_TABLE.md)).
- Plan pre-registered in `7571b8a`; calls frozen in `7c73c37` before any answer was read; scored once by [score.py](score.py), output in [result.json](result.json).

## Results

| Forecaster | Calls | Won-lost | Win rate | One-sided lower bound | Units won | Return per stake | Certified |
|---|---|---|---|---|---|---|---|
| Price action | 341 | 170-168 | 50.3% | 43.9% | -25.2 | -7.4% | no |
| Trend | 294 | 141-151 | 48.3% | 41.4% | -31.8 | -10.8% | no |
| Reversal | 194 | 99-94 | 51.3% | 42.7% | -10.8 | -5.5% | no |
| Multi-timeframe | 100 | 52-48 | 52.0% | 40.0% | -4.2 | -4.2% | no |
| Cross-asset | 339 | 166-170 | 49.4% | 43.0% | -29.8 | -8.8% | no |
| **Judge (primary)** | **84** | **40-44** | **47.6%** | 38.2% | **-10.4** | **-12.4%** | **no** |

The lower bound for each forecaster is at one-sided 99%; for the judge it is at 95%.

## What it means

- **The last round's leaders fell back to a coin flip.** Cross-asset went from 58.3% on 24 calls to 49.4% on 339, and price action from 56.7% to 50.3% on 341. The small-sample leads were luck, as best-of-five chance predicted.
- **Debate did not help.** The judge's highest-conviction calls won 47.6%.
- **No horizon helps.** Every 2, 5 and 10 min breakdown in result.json sits at a coin flip.
- **Every style ends at about 50%.** Price action, trend following, mean reversion, multi-timeframe confluence and cross-asset strength are all at a coin flip. Before the 54% break-even, each loses about 5 to 12% per stake.

OTC stays closed ([../CLOSED.md](../CLOSED.md)).
