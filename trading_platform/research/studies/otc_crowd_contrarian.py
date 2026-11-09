"""Crowd mood (call fraction) observed strictly before a 2m candle opens vs that candle's direction."""
import sys, math, numpy as np, pandas as pd
BE=1/1.85
def wilson(w,n,z=1.96):
    p=w/n; d=1+z*z/n; c=p+z*z/(2*n); m=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)); return (c-m)/d,(c+m)/d
c = pd.read_parquet(sys.argv[1]); c = c[c.timeframe==120].copy()
c["ms"] = (c.timestamp - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)
c = c[c.close != c.open]; c["up"] = c.close > c.open
m = pd.read_csv(sys.argv[2], names=["asset","itype","ms","call"])
print("mood instrument types:", m.itype.value_counts().to_dict())
m = m.groupby(["asset","ms"], as_index=False).call.mean()
c["key"] = c.ms - 1000
out = pd.merge_asof(c.sort_values("key"), m.sort_values("ms").rename(columns={"ms":"mood_ms"}), left_on="key", right_on="mood_ms", by="asset", direction="backward", tolerance=60_000).dropna(subset=["call"])
print(f"2m candles with mood <=60s old: {len(out):,}  corr(call, up)={np.corrcoef(out.call, out.up)[0,1]:+.4f}")
out["q"] = pd.qcut(out.call.rank(method="first"), 10, labels=False)
print(out.groupby("q").agg(call_mean=("call","mean"), p_up=("up","mean"), n=("up","size")).round(4).to_string())
for nm, mask, bet_up in [("crowd most long (top 10%) -> PUT", out.q==9, False), ("crowd most short (bottom 10%) -> CALL", out.q==0, True)]:
    s=out[mask]; w=int((s.up==bet_up).sum()); lo,hi=wilson(w,len(s)); print(f"  {nm}: n={len(s):,} wr={w/len(s):.4f} CI=[{lo:.4f},{hi:.4f}] BE={BE:.4f}")
out["contra_win"] = np.where(out.q>=8, ~out.up, np.where(out.q<=1, out.up, np.nan))
x = out.dropna(subset=["contra_win"]).copy(); x["contra_win"]=x.contra_win.astype(bool)
x["hour"] = pd.to_datetime(x.ms, unit="ms", utc=True).dt.hour
k = x.asset.nunique() + 24
zb = abs(__import__("scipy").stats.norm.ppf(0.025/k))  # Bonferroni across all slices tested
print(f"\ncontrarian on top/bottom 20% mood, Bonferroni z={zb:.2f} over {k} slices")
for col in ("asset","hour"):
    for key, s in x.groupby(col):
        w=int(s.contra_win.sum()); n=len(s); lo,hi=wilson(w,n,zb)
        flag = "CLEARS" if lo>BE else ("best" if w/n>0.52 else "")
        print(f"  {col}={key!s:12s} n={n:6,d} wr={w/n:.4f} CI=[{lo:.4f},{hi:.4f}] {flag}")
mid = x.ms.median()
print("\ntime-split stability (first half / second half), 95% CI")
for nm, s in [("ALL", x), ("EURUSD-OTC", x[x.asset=="EURUSD-OTC"]), ("hour 0", x[x.hour==0])]:
    parts=[]
    for h in (s[s.ms<mid], s[s.ms>=mid]):
        w=int(h.contra_win.sum()); n=len(h); lo,hi=wilson(w,n); parts.append(f"n={n:6,d} wr={w/n:.4f} [{lo:.4f},{hi:.4f}]")
    print(f"  {nm:11s} H1 {parts[0]}  |  H2 {parts[1]}")
