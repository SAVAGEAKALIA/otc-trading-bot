import sys; sys.path.insert(0, ".")  # run from the repo root
"""Trigger event COUNTS only (no outcomes read) on the owner's 2-min archive and live-recorded tables."""
import numpy as np, pandas as pd, sqlite3
from services.otc_quant_lab import data, features
b = data.load_historical(120)
f = features.build(b, 120, (1,))
v = f[f.valid].copy()
n = len(v); days = v.day.nunique()
print(f"# Trigger frequencies (counts only, outcomes not read)\n\n2-min archive: {n:,} valid decisions, {days} days, 15 pairs.\n")
rows = []
# H4 extreme 2-min move: |z0| above per-asset 99.9th pct of |z0| (trailing quantile approximated by full-sample per asset: frequency is 0.1% by construction)
for q in (0.999, 0.998, 0.995):
    thr = v.groupby('asset').z0.transform(lambda s: s.abs().quantile(q))
    rows.append((f"extreme 2-min move |z0| >= per-asset {q:.1%} quantile", int((v.z0.abs() >= thr).sum())))
# H3 anchor gap: deviation from 720-bar (1-day) mean in vol units
lc = np.log(b.sort_values(['asset','t']).c.to_numpy())
f['lc'] = lc
f['anchor'] = f.groupby('asset').lc.transform(lambda s: s.rolling(720, min_periods=720).mean())
f['gap'] = (f.lc - f.anchor) / (f.vol60 * np.sqrt(720))
g = f[f.valid & f.gap.notna()]
for k in (2.0, 2.5, 3.0):
    rows.append((f"anchor gap |log(c/1-day mean)| > {k} sd-of-day", int((g.gap.abs() > k).sum())))
# H5 round-number first touch: 0.0050 lattice (0.50 for JPY), within 0.01%, first touch in 60 min (30 bars), approach >= 8 pips in prior 10 min (5 bars)
cnt = 0
for a, s in b.sort_values(['asset','t']).groupby('asset'):
    c = s.c.to_numpy(); hi = s.h.to_numpy(); lo = s.l.to_numpy()
    step = 0.5 if 'JPY' in a else 0.005; pip = 0.01 if 'JPY' in a else 0.0001
    lvl = np.round(c / step) * step
    near = np.abs(c - lvl) <= c * 1e-4
    far = pd.Series(np.abs(c - lvl)).rolling(5).max().shift(1).to_numpy() >= 8 * pip
    prev_touch = pd.Series(near.astype(int)).rolling(30).max().shift(1).fillna(0).to_numpy() > 0
    cnt += int((near & far & ~prev_touch).sum())
rows.append(("round-number first touch (0.0050 / 0.50 lattice, within 0.01%, approach >= 8 pips, none in prior 60 min)", cnt))
# H8 breadth extreme: >= 12 of 15 pairs moved the same USD-adjusted direction in the bar (use market mean mkt0 extremes)
for q in (0.999, 0.99):
    thr = v.mkt0.abs().quantile(q)
    rows.append((f"breadth extreme |mkt0| >= {q:.1%} quantile (per asset-bar)", int((v.mkt0.abs() >= thr).sum())))
# restart window
rows.append(("first 30 min after daily feed restart (pos 1-15)", int(((f.pos >= 1) & (f.pos <= 15)).sum())))
print("| Trigger | Events in archive | Per day | Share of bars |\n|---|---|---|---|")
for name, c in rows:
    print(f"| {name} | {c:,} | {c/days:.1f} | {c/n:.3%} |")
# live tables
con = sqlite3.connect('file:data/ml/market_context.sqlite?mode=ro', uri=True)
p = pd.read_sql("select broker_asset a, instrument_type it, observed_bucket_ms t, payout_fraction x from payout_samples where payout_fraction is not null order by a,it,t", con)
p['d'] = p.groupby(['a','it']).x.diff()
ld = (p.t.max()-p.t.min())/86400000
print(f"\nLive-recorded period ({ld:.1f} days):\n\n| Trigger | Events | Per day |\n|---|---|---|")
for k in (0.02, 0.03, 0.04):
    print(f"| payout step-down <= -{k:.2f} (any asset/product) | {int((p.d <= -k+1e-9).sum()):,} | {(p.d <= -k+1e-9).sum()/ld:.1f} |")
    print(f"| payout step-up >= +{k:.2f} | {int((p.d >= k-1e-9).sum()):,} | {(p.d >= k-1e-9).sum()/ld:.1f} |")
q = pd.read_sql("select broker_asset a, received_at_ms r from quote_samples order by a, received_at_ms", con)
q['gap'] = q.groupby('a').r.diff()
for s in (30_000, 60_000):
    print(f"| quote stall: gap >= {s//1000} s between received quotes (all 15 assets) | {int((q.gap >= s).sum()):,} | {(q.gap >= s).sum()/ld:.1f} |")