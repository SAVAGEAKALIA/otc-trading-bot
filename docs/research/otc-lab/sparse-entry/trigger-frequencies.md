# Trigger frequencies (counts only, outcomes not read)

2-min archive: 1,213,807 valid decisions, 121 days, 15 pairs.

| Trigger | Events in archive | Per day | Share of bars |
|---|---|---|---|
| extreme 2-min move |z0| >= per-asset 99.9% quantile | 1,223 | 10.1 | 0.101% |
| extreme 2-min move |z0| >= per-asset 99.8% quantile | 2,433 | 20.1 | 0.200% |
| extreme 2-min move |z0| >= per-asset 99.5% quantile | 6,079 | 50.2 | 0.501% |
| anchor gap |log(c/1-day mean)| > 2.0 sd-of-day | 14,629 | 120.9 | 1.205% |
| anchor gap |log(c/1-day mean)| > 2.5 sd-of-day | 6,515 | 53.8 | 0.537% |
| anchor gap |log(c/1-day mean)| > 3.0 sd-of-day | 3,315 | 27.4 | 0.273% |
| round-number first touch (0.0050 / 0.50 lattice, within 0.01%, approach >= 8 pips, none in prior 60 min) | 10,587 | 87.5 | 0.872% |
| breadth extreme |mkt0| >= 99.9% quantile (per asset-bar) | 1,214 | 10.0 | 0.100% |
| breadth extreme |mkt0| >= 99.0% quantile (per asset-bar) | 12,139 | 100.3 | 1.000% |
| first 30 min after daily feed restart (pos 1-15) | 18,810 | 155.5 | 1.550% |

Live-recorded period (20.6 days):

| Trigger | Events | Per day |
|---|---|---|
| payout step-down <= -0.02 (any asset/product) | 879 | 42.7 |
| payout step-up >= +0.02 | 872 | 42.4 |
| payout step-down <= -0.03 (any asset/product) | 645 | 31.4 |
| payout step-up >= +0.03 | 625 | 30.4 |
| payout step-down <= -0.04 (any asset/product) | 571 | 27.8 |
| payout step-up >= +0.04 | 565 | 27.5 |
| quote stall: gap >= 30 s between received quotes (all 15 assets) | 325,930 | 15842.7 |
| quote stall: gap >= 60 s between received quotes (all 15 assets) | 926 | 45.0 |
