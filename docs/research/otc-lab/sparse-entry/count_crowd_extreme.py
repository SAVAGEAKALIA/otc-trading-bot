"""Count crowd-extreme onsets in mood_samples. Counts only; no price outcomes are read."""
import sqlite3, pandas as pd
c = sqlite3.connect('file:data/ml/market_context.sqlite?mode=ro', uri=True)
d = pd.read_sql("select broker_asset a, instrument_type i, observed_bucket_ms t, call_fraction cf "
                "from mood_samples order by a,i,t", c)
days = (d.t.max() - d.t.min()) / 86400e3
print("samples", len(d), "days", round(days, 2), d.i.value_counts().to_dict())
d['dev'] = (d.cf - 0.5).abs()
for th in (0.40, 0.45):
    for inst in ('turbo-option', 'binary-option', None):
        x = d if inst is None else d[d.i == inst]
        hit = x.dev >= th
        prev = hit.groupby([x.a, x.i]).shift(1, fill_value=False)
        onset = hit & ~prev
        print(f"|cf-0.5|>={th} {inst or 'all'}: samples {int(hit.sum())}, onsets {int(onset.sum())}, "
              f"onsets/day {onset.sum()/days:.1f}")

# Degenerate fractions (exact 0, 1, 0.5) indicate thin or absent participation.
print("exact 0 or 1:", round(((d.cf == 0) | (d.cf == 1)).mean() * 100, 2), "%;",
      "exact 0.5:", round((d.cf == 0.5).mean() * 100, 2), "%")
nd = d[(d.cf > 0) & (d.cf < 1) & (d.cf != 0.5)]
print("non-degenerate samples", len(nd))
for q in (0.9, 0.99, 0.999):
    print(f"non-degenerate |cf-0.5| quantile {q}:", round(nd.dev.quantile(q), 4))
th = nd.dev.quantile(0.99)
x = d.assign(hit=(d.cf > 0) & (d.cf < 1) & (d.dev >= th))
prev = x.groupby(['a', 'i']).hit.shift(1, fill_value=False)
on = x.hit & ~prev
print(f"non-degenerate top-1% onsets (|cf-0.5|>={th:.4f}): {int(on.sum())}, per day {on.sum()/days:.1f}")
print("per-asset share exact 0/1:")
print(d.assign(deg=(d.cf == 0) | (d.cf == 1)).groupby('a').deg.mean().round(3).sort_values().to_string())
