# Sparse-entry family: historical test result (2026-11-13)

**Verdict: no hypothesis certified. Four of the eight are retired on the data already collected. The other four could not be tested here: three because the live window has too few labelable trades, and H3 because its rule fired only 115 times. NO TRADE stands.**

The owner chose to test the frozen family on existing data rather than wait months for forward data. The plan (`sparse-entry/historical/plan.json`, plan SHA-256 `b1fe3f08...`) was committed and pushed in `bdbaec1` before any outcome of these rules was read. The run then happened once (`sparse-entry/historical/result.json`, write-once):
- **Candle rules:** thresholds from 2026-03-29 to 05-15; outcomes read only for 2026-05-16 to 07-27, using a close-to-close proxy at nominal payout.
- **Event rules:** the Jul 31 to Aug 20 live window, with 1-s labels and real payouts.

The certificate and alpha are the same as the forward block: Clopper-Pearson at 0.05 / 8, under both tie conventions.

| Rank | Rule | Trades scored | Win rate | Break-even | 99.375% CP bounds | Mean return per stake | State |
|---|---|---|---|---|---|---|---|
| 1 | H2 extreme 2-min move fade | 1,648 (of 3,660) | 51.82% | 54.35% | 48.71% to 54.92% | -4.6% | NULL-INFORMATIVE |
| 1b | H2b strict 99.9% fade | not opened | | | | | H2 did not certify |
| 2 | H3 anchor-gap reversion, 10 min | 115 | 46.96% | 53.76% | 35.22% to 58.94% | -12.7% | UNDERPOWERED |
| 3 | H4 round-number first touch, 10 min | 1,653 (of 11,550) | 50.76% | 53.76% | 47.66% to 53.86% | -5.6% | NULL-INFORMATIVE (placebo 99th pct 52.87%) |
| 4 | H5 breadth-extreme fade | 700 | 50.65% | 54.35% | 45.85% to 55.44% | -6.8% | NULL-INFORMATIVE |
| 5 | H1 payout step-down crowd fade | 7 | 28.6% | 54.6% | 1.8% to 78.7% | -47.7% | UNDERPOWERED (control not beaten, p = 0.85) |
| 6 | H6 payout step-up mirror | 11 | 45.5% | 54.6% | 12.1% to 82.3% | -16.7% | UNDERPOWERED |
| 7 | H7 quote-stall resume (diagnostic) | 13 | 61.5% | 54.4% | 25.4% to 90.1% | +13.2% | UNDERPOWERED |
| 8 | H8 15-min breakout continuation | 1,653 (of 2,903) | 51.94% | 53.76% | 48.83% to 55.03% | -3.4% | NULL-INFORMATIVE |

NULL-INFORMATIVE means the upper bound is below break-even + 5 points, so an edge of the size the protocol was built to find is excluded. H5 is NULL-INFORMATIVE on only 700 trades: its upper bound (55.44%) already sits under 59.35%. H4 also failed its own placebo, scoring below the 99th percentile of 1,000 shifted lattices.

## What this settles and what it does not

- **Retired:**
  - extreme-move fades (H2, and H2b with it);
  - round-number touches (H4);
  - breadth extremes (H5);
  - the 15-minute breakout (H8).

  Each gives 50.7% to 51.9%, the same coin-flip band as every earlier OTC test.
- **Untested here:**
  - H3 fires too rarely under its first-bar rule: 115 trades in 73 days.
  - H1, H6 and H7 sit in the live window, where 1-s candles cover about 27% of the time. Of 132 H1 events only 7 had both prices, and H6 and H7 kept 11 and 13. Their numbers above are noise.
- **What testing the rest would take:** only the payout-event rules (H1, H6) remain as tradable candidates. On forward data H1 needs about 200 days to reach n, and H6 about 92.
- **Evidence grade: development.** The archive was mined earlier for other rules, and candle labels are a close-to-close proxy (95.3% agreement with 1-s outcomes in the earlier lab). A proxy that agrees 95% of the time cannot move 51% to 59%, so the retirements stand.

## Reproduce

```bash
.venv-lab/bin/python -m unittest discover -s services/otc_sparse_prereg/tests -t . -q
.venv-lab/bin/python -m services.otc_sparse_prereg.evals.eval_power
# historical.py --run refuses a second run while result.json exists (write-once).
```
