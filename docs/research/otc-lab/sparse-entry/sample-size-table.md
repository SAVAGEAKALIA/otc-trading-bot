# Sample-size engine (deterministic; services/otc_quant_lab/risk.trades_needed, one-sided, power 0.8)

| Break-even | True win rate | Edge (pt) | n, single test (alpha 0.05) | n, family of 8 (Bonferroni alpha 0.00625) | n, family of 8 + design effect 1.5 |
|---|---|---|---|---|---|
| turbo 0.84 (1-5 min) 54.35% | 55.35% | +1 | 15,320 | 27,640 | 41,460 |
| turbo 0.84 (1-5 min) 54.35% | 56.35% | +2 | 3,824 | 6,902 | 10,353 |
| turbo 0.84 (1-5 min) 54.35% | 57.35% | +3 | 1,697 | 3,064 | 4,596 |
| turbo 0.84 (1-5 min) 54.35% | 59.35% | +5 | 608 | 1,099 | 1,648 |
| turbo 0.84 (1-5 min) 54.35% | 62.35% | +8 | 236 | 427 | 640 |
| turbo 0.84 (1-5 min) 54.35% | 64.35% | +10 | 150 | 272 | 408 |
| binary 0.86 (10-15 min) 53.76% | 54.76% | +1 | 15,351 | 27,696 | 41,544 |
| binary 0.86 (10-15 min) 53.76% | 55.76% | +2 | 3,833 | 6,917 | 10,375 |
| binary 0.86 (10-15 min) 53.76% | 56.76% | +3 | 1,701 | 3,071 | 4,606 |
| binary 0.86 (10-15 min) 53.76% | 58.76% | +5 | 610 | 1,102 | 1,653 |
| binary 0.86 (10-15 min) 53.76% | 61.76% | +8 | 237 | 428 | 642 |
| binary 0.86 (10-15 min) 53.76% | 63.76% | +10 | 150 | 273 | 409 |

Design effect 1.5 = conservative allowance for same-day / cross-asset clustering of rare triggers (simultaneous triggers on correlated pairs are not independent bets).

## What a sparse trigger can detect, given how often it fires
Owner's archive: ~1.21M valid 2-min decisions (15 pairs x ~121 days). Lab-final (29 days) ~0.28M. Live-recorded period ~33k labelled 1-s decisions.

| Trigger frequency | Events in full archive | Events in lab-final | Smallest edge detectable at 54.35% (family of 8) |
|---|---|---|---|
| 0.01% of bars | 121 | 28 | +29.5 pt (true 83.8%) |
| 0.05% of bars | 606 | 141 | +14.0 pt (true 68.3%) |
| 0.10% of bars | 1,213 | 283 | +10.0 pt (true 64.3%) |
| 0.50% of bars | 6,069 | 1,419 | +4.5 pt (true 58.8%) |
| 1.00% of bars | 12,138 | 2,838 | +3.5 pt (true 57.8%) |
| 5.00% of bars | 60,690 | 14,193 | +1.5 pt (true 55.8%) |
