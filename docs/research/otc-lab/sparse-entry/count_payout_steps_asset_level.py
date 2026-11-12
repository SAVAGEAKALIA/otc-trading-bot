"""Asset-level payout step events (either product), merged within 300 s per asset. Counts only; no outcomes read."""
import sqlite3, sys
import numpy as np, pandas as pd
sys.path.insert(0, 'services')
from otc_quant_lab.risk import trades_needed
con = sqlite3.connect('file:data/ml/market_context.sqlite?mode=ro', uri=True)
p = pd.read_sql("select broker_asset a, instrument_type it, observed_bucket_ms t, payout_fraction x from payout_samples "
                "where payout_fraction is not null order by a,it,t", con)
p['d'] = p.groupby(['a', 'it']).x.diff()
days = (p.t.max() - p.t.min()) / 86400e3
m = pd.read_sql("select broker_asset a, observed_bucket_ms t, call_fraction cf from mood_samples order by t", con)
need = int(np.ceil(trades_needed(0.05, 1 / 1.84, alpha=0.05 / 8) * 1.5))
for name, mask in (("step-down <= -0.03", p.d <= -0.03 + 1e-9), ("step-up >= +0.03", p.d >= 0.03 - 1e-9)):
    ev = p[mask].sort_values(['a', 't'])
    new = ev.groupby('a').t.diff().isna() | (ev.groupby('a').t.diff() > 300_000)
    ev = ev[new]
    # mood availability: nearest prior turbo mood sample within 60 s on the same asset, not exactly 0.5
    j = pd.merge_asof(ev.sort_values('t'), m.sort_values('t'), on='t', by='a', direction='backward', tolerance=60_000)
    ok = j.cf.notna() & (j.cf != 0.5)
    n, nok = len(ev), int(ok.sum())
    print(f"{name}: asset-level events {n} ({n/days:.1f}/day); with usable mood {nok} ({nok/days:.1f}/day); "
          f"29-day block {round(nok/days*29)}; days to +5pt n={need}: {need/(nok/days):.1f}")

def min_edge(n, be=1 / 1.84):
    for e10 in range(5, 400):
        if int(np.ceil(trades_needed(e10 / 1000, be, alpha=0.05 / 8) * 1.5)) <= n: return e10 / 10
for label, n in (("H1 29-day block", 430), ("H1 live window", 305), ("H6 29-day block", 522), ("H6 live window", 370),
                 ("H1 60-day block", round(14.8 * 60)), ("H6 60-day block", round(18.0 * 60))):
    print(label, n, "-> smallest certifiable edge +", min_edge(n), "pt")

# H1 with a non-degenerate mood band (0.05 < cf < 0.95, cf != 0.5): avoids thin-participation extremes
ev = p[p.d <= -0.03 + 1e-9].sort_values(['a', 't'])
gap = ev.groupby('a').t.diff()
ev = ev[gap.isna() | (gap > 300_000)]
j = pd.merge_asof(ev.sort_values('t'), m.sort_values('t'), on='t', by='a', direction='backward', tolerance=60_000)
band = j.cf.notna() & (j.cf != 0.5) & (j.cf > 0.05) & (j.cf < 0.95)
print(f"H1 non-degenerate mood band: {int(band.sum())} ({band.sum()/days:.1f}/day)")
