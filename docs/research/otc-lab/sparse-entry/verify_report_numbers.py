"""Recompute every derived number in section 5.2 and the certificate line of the sparse-entry report.
Counts and design quantities only; no trade outcomes are read."""
import sqlite3, sys
import numpy as np
from scipy import stats
sys.path.insert(0, 'services')
from otc_quant_lab.risk import trades_needed

A = 0.05 / 8; DE = 1.5; BLOCK = 29
BE_T, BE_B = 1 / 1.84, 1 / 1.86
rows = {  # id: (per_day, breakeven, payout-at-entry note)
    'H1': (31.4, BE_T), 'H2': (50.2, BE_T), 'H2b': (10.1, BE_T), 'H3': (53.8, BE_B),
    'H4': (87.5, BE_B), 'H5': (100.3, BE_T), 'H6': (30.4, BE_T), 'H7': (45.0, BE_T),
}
def need(edge, be): return int(np.ceil(trades_needed(edge, be, alpha=A) * DE))
def min_edge(n, be):
    for e10 in range(5, 400):
        if need(e10 / 1000, be) <= n: return e10 / 10
    return None
print("id | events/29d | smallest certifiable edge (pt) | days to +5pt n | +5pt n")
for k, (pd_, be) in rows.items():
    ev = round(pd_ * BLOCK); n5 = need(0.05, be)
    print(f"{k} | {ev:,} | +{min_edge(ev, be)} | {n5 / pd_:.1f} | {n5:,}")
print("live window 20.6 d: H1 events 645 -> +", min_edge(645, BE_T), "; H7 926 -> +", min_edge(926, BE_T))

def cp_pass(n, be):
    for k in range(n + 1):
        if stats.beta.ppf(A, k, n - k + 1) > be: return k
for n, be, lab in ((1648, BE_T, 'turbo 0.84'), (1653, BE_B, 'binary 0.86'), (1648, 1 / 1.80, 'turbo 0.80')):
    k = cp_pass(n, be); print(f"CP pass {lab}: n={n} needs {k} wins = {k / n:.2%} (be {be:.2%})")
t = 0.0061  # 2-min tie rate from the owner's lab report
# Ties scored as losses: a win must cover the payout break-even over ALL trades, so among non-tie trades
# the required win rate is BE / (1 - t).
print(f"tie=loss 2-min break-even among non-tie trades: {BE_T / (1 - t):.4f} (refund convention: {BE_T:.4f})")

c = sqlite3.connect('file:data/ml/market_context.sqlite?mode=ro', uri=True)
gaps = [r[0] for r in c.execute(
    "select observed_bucket_ms - lag(observed_bucket_ms) over (partition by broker_asset, instrument_type "
    "order by observed_bucket_ms) from payout_samples")]
g = np.array([x for x in gaps if x is not None]) / 1000
print("payout sample spacing s: median", np.median(g), "p10", np.percentile(g, 10), "p90", np.percentile(g, 90))
print("distinct spread values:", c.execute("select count(distinct round(spread,8)) from quote_samples").fetchone()[0],
      c.execute("select round(spread,8), count(*) from quote_samples group by 1 order by 2 desc limit 5").fetchall())
