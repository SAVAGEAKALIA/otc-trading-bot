"""Realized delta-neutral carry from actual funding prints, always-on vs regime-gated, net of fees.
Return is per unit of hedged notional (spot long + perp short, 1x). Funding is received by the short."""
import json, sys, numpy as np, pandas as pd
rows = pd.DataFrame(json.load(open(sys.argv[1])), columns=["venue", "sym", "ms", "rate"])
rows["t"] = pd.to_datetime(rows.ms, unit="ms", utc=True)
# Round-trip cost (enter + exit both legs, taker): Bybit spot 0.10% + perp 0.055% each way; HL spot 0.07% + perp 0.045%.
RT = {"bybit": 2 * (0.0010 + 0.00055), "hyperliquid": 2 * (0.0007 + 0.00045)}
HURDLE = float(sys.argv[2]) if len(sys.argv) > 2 else 0.08   # enter when trailing-7d funding annualizes above this
def yearly(g, v):
    g = g.sort_values("t").drop_duplicates("ms").set_index("t")
    r = g.rate
    out = []
    # regime gate on daily funding totals (decide once per day from trailing data only)
    daily = r.resample("1D").sum()
    ann7 = daily.rolling(7).mean().shift(1) * 365          # info up to previous day
    ann3 = daily.rolling(3).mean().shift(1) * 365
    state, held, switches = False, [], 0
    for d in daily.index:
        want = state
        if not state and ann7.get(d, np.nan) > HURDLE: want = True
        if state and ann3.get(d, np.nan) < 0: want = False
        switches += want != state; state = want; held.append(state)
    gate = pd.Series(held, index=daily.index)
    gated = (daily * gate) - (gate.astype(int).diff().abs().fillna(gate.astype(int)) * RT[v] / 2)
    for y, part in daily.groupby(daily.index.year):
        frac = (part.index.max() - part.index.min()).days / 365 + 1 / 365
        gy = gated[gated.index.year == y]
        out.append({"year": y, "days": len(part), "always_on_apr": part.sum() / frac,
                    "neg_print_share": (r[r.index.year == y] < 0).mean(),
                    "gated_net_apr": gy.sum() / frac, "time_in_market": gate[gate.index.year == y].mean(),
                    "worst_30d_always": part.rolling(30).sum().min()})
    return pd.DataFrame(out)
pd.set_option("display.width", 200)
for (v, s), g in rows.groupby(["venue", "sym"]):
    y = yearly(g, v)
    print(f"\n== {v} {s}  (hurdle {HURDLE:.0%}, round-trip cost {RT[v]:.2%})")
    print(y.to_string(index=False, formatters={c: "{:+.1%}".format for c in ("always_on_apr", "gated_net_apr", "worst_30d_always")} | {"neg_print_share": "{:.0%}".format, "time_in_market": "{:.0%}".format}))
