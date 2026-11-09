"""Simulate the real binary contract on 1-second OTC closes.
Entry at second ENTRY_SEC of every second minute (non-overlapping 120s outcomes),
strike = close at entry, settle = close at entry+120s. Features use only
closes at or before entry. Gaps (missing seconds) exclude the sample."""
import sys, math, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
BE = 1/1.85; H = 120; LAGS = (5, 15, 30, 60, 120, 300)
def wilson(w,n,z=1.96):
    p=w/n; d=1+z*z/n; c=p+z*z/(2*n); m=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)); return (c-m)/d,(c+m)/d
def line(nm,w,n): lo,hi=wilson(w,n); print(f"  {nm:42s} n={n:8,d} wr={w/n:.4f} CI=[{lo:.4f},{hi:.4f}] {'CLEARS' if lo>BE else ''}")
raw = pd.read_csv(sys.argv[1], names=["asset","ms","close"])
entry_sec = int(sys.argv[2]) if len(sys.argv) > 2 else 58
rows=[]; ties=0; total=0
for a, g in raw.groupby("asset"):
    sec = (g.ms.values//1000).astype(np.int64); t0=sec.min()
    px = np.full(sec.max()-t0+1, np.nan); px[sec-t0]=g.close.values
    idx = np.arange(len(px)); tsec = idx + t0
    ent = idx[(tsec % 120) == (60 + entry_sec) % 120]
    ent = ent[(ent >= max(LAGS)) & (ent + H < len(px))]
    c0 = px[ent]; c1 = px[ent+H]
    minute_open = px[ent - (tsec[ent] % 60)]
    f = {f"r{L}": np.log(c0/px[ent-L]) for L in LAGS}
    f["r_minute"] = np.log(c0/minute_open)
    df = pd.DataFrame(f); df["y"]=np.sign(c1-c0); df["t"]=tsec[ent]; df["asset"]=a
    df = df.dropna(); total+=len(df); ties+=(df.y==0).sum()
    rows.append(df[df.y!=0])
D = pd.concat(rows).sort_values("t").reset_index(drop=True)
print(f"entry second={entry_sec}  samples={total:,}  ties(refund)={ties/total:.4f}  decided={len(D):,}  P(up)={(D.y>0).mean():.4f}")
feats=[c for c in D.columns if c.startswith("r")]
for c in feats:
    s=D[D[c]!=0]
    if s.empty: continue
    cont=int((np.sign(s[c])==s.y).sum())
    line(f"{c} continuation", cont, len(s)); line(f"{c} reversal", len(s)-cont, len(s))
    # extreme moves only (per-asset top 5% |r|)
    thr = s.groupby("asset")[c].transform(lambda x: x.abs().quantile(0.95)); e=s[s[c].abs()>=thr]
    w=int((np.sign(e[c])!=e.y).sum()); line(f"{c} top5% move reversal", w, len(e))
X = D[feats].values / (D[feats].std().values+1e-12); y=(D.y>0).astype(int).values; cut=int(len(D)*0.7)
for nm, m in [("logistic", LogisticRegression(max_iter=500)), ("gbm", HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05))]:
    p = m.fit(X[:cut],y[:cut]).predict_proba(X[cut:])[:,1]; yt=y[cut:]
    ll = -np.mean(yt*np.log(np.clip(p,1e-9,1))+(1-yt)*np.log(np.clip(1-p,1e-9,1)))
    print(f"  {nm} walk-forward test logloss={ll:.5f} (ln2=0.69315)")
    for q in (0.0, 0.8, 0.95, 0.99):
        conf=np.abs(p-0.5); sel=conf>=np.quantile(conf,q); w=int(((p[sel]>0.5)==yt[sel]).sum())
        line(f"{nm} top {100*(1-q):.0f}% confidence", w, int(sel.sum()))
