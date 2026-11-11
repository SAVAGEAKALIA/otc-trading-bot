"""Model-free predictability tests: is the next-bar direction distinguishable from a coin flip?

All p-values are two-sided. `bh` applies Benjamini-Hochberg across a family of tests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .features import DOWN, UP


def bh(pvalues: np.ndarray) -> np.ndarray:
    p = np.asarray(pvalues, dtype=float)
    order = np.argsort(p)
    ranked = p[order] * len(p) / (np.arange(len(p)) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(q)
    out[order] = np.minimum(q, 1.0)
    return out


def _binary_rows(frame: pd.DataFrame, rows: np.ndarray, horizon: int = 1):
    y = frame[f"y{horizon}"].to_numpy()[rows]
    keep = (y == UP) | (y == DOWN)
    return rows[keep], (y[keep] == UP).astype(np.int8)


def up_rate_test(y: np.ndarray) -> dict:
    n, k = len(y), int(y.sum())
    p = stats.binomtest(k, n, 0.5).pvalue if n else 1.0
    return {"n": n, "up_rate": k / n if n else None, "p": float(p)}


def sign_autocorrelation(frame: pd.DataFrame, rows: np.ndarray, lags=range(1, 11)) -> list[dict]:
    """Corr(sign r_{t+1}, sign r_{t+1-k}) pooled over assets via the next-bar label."""
    rows, y = _binary_rows(frame, rows)
    out = []
    color = frame.color.to_numpy()
    run = frame.asset_id.to_numpy().astype(np.int64) * 10_000_000 + frame.run.to_numpy()
    s_next = 2.0 * y - 1
    for k in lags:
        prev = rows - (k - 1)
        ok = (prev >= 0) & (run[np.clip(prev, 0, None)] == run[rows])  # same asset and no gap
        s_prev = color[prev[ok]].astype(float)
        mask = s_prev != 0
        a, b = s_next[ok][mask], s_prev[mask]
        r = float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 else np.nan
        z = r * np.sqrt(len(a))
        out.append({"lag": k, "n": int(len(a)), "corr": r, "p": float(2 * stats.norm.sf(abs(z)))})
    q = bh(np.array([o["p"] for o in out]))
    for o, qq in zip(out, q):
        o["q"] = float(qq)
    return out


def variance_ratio(frame: pd.DataFrame, rows: np.ndarray, qs=(2, 4, 8, 16)) -> list[dict]:
    """Lo-MacKinlay (1988) heteroskedasticity-robust z* per asset, pooled by averaging z."""
    out = []
    for q in qs:
        zs, vrs = [], []
        for _, g in frame.iloc[rows].groupby("asset_id"):
            r = g.r0.to_numpy(np.float64)
            r = r[np.isfinite(r)]
            if len(r) < 10 * q:
                continue
            mu = r.mean()
            dev = r - mu
            var1 = (dev ** 2).mean()
            rq = np.convolve(r, np.ones(q), "valid")
            varq = ((rq - q * mu) ** 2).mean() / q
            vr = varq / var1
            n = len(r)
            delta = [((dev[j:] ** 2) * (dev[:-j] ** 2)).sum() / ((dev ** 2).sum() ** 2) * n for j in range(1, q)]
            theta = sum((2 * (q - j) / q) ** 2 * delta[j - 1] for j in range(1, q))
            zs.append((vr - 1) / np.sqrt(theta / n))
            vrs.append(vr)
        z = float(np.mean(zs) * np.sqrt(len(zs))) if zs else np.nan
        out.append({"q": q, "assets": len(zs), "mean_vr": float(np.mean(vrs)) if vrs else None,
                    "min_vr": float(np.min(vrs)) if vrs else None, "max_vr": float(np.max(vrs)) if vrs else None,
                    "pooled_z": z, "p": float(2 * stats.norm.sf(abs(z))) if zs else None})
    q = bh(np.array([o["p"] if o["p"] is not None else 1.0 for o in out]))
    for o, qq in zip(out, q):
        o["q_bh"] = float(qq)  # "q" is the aggregation lag; do not overwrite it
    return out


def pattern_table(frame: pd.DataFrame, rows: np.ndarray, column: str, horizon: int = 1,
                  min_n: int = 200) -> pd.DataFrame:
    """Up rate of the next `horizon` bars per categorical state (e.g. 3/5-bar colour pattern, hour)."""
    rows, y = _binary_rows(frame, rows, horizon)
    state = frame[column].to_numpy()[rows]
    ok = np.isfinite(state.astype(float))
    df = pd.DataFrame({"state": state[ok], "y": y[ok]})
    g = df.groupby("state").y.agg(["sum", "count"]).reset_index()
    g = g[g["count"] >= min_n]
    g["up_rate"] = g["sum"] / g["count"]
    g["edge"] = (g.up_rate - 0.5).abs() + 0.5  # best side's win rate
    g["p"] = [stats.binomtest(int(s), int(n), 0.5).pvalue for s, n in zip(g["sum"], g["count"])]
    g["q"] = bh(g.p.to_numpy()) if len(g) else []
    return g.sort_values("p")


def chi_square_independence(table: pd.DataFrame) -> dict:
    if len(table) < 2:
        return {"chi2": None, "p": None}
    obs = np.stack([table["sum"], table["count"] - table["sum"]], axis=1)
    chi2, p, dof, _ = stats.chi2_contingency(obs)
    return {"chi2": float(chi2), "dof": int(dof), "p": float(p)}


def lead_lag(frame: pd.DataFrame, rows: np.ndarray) -> pd.DataFrame:
    """Corr(z0 of asset j at bar t, next-bar direction of asset i). All ordered pairs i != j."""
    sub = frame.iloc[rows]
    z = sub.pivot(index="t", columns="asset", values="z0")
    y = sub.pivot(index="t", columns="asset", values="y1")
    out = []
    for i in y.columns:
        yi = y[i]
        keep_i = yi.isin([UP, DOWN])
        target = (2.0 * (yi[keep_i] == UP) - 1)
        for j in z.columns:
            if i == j:
                continue
            x = z[j][keep_i]
            ok = x.notna()
            if ok.sum() < 1000:
                continue
            r = float(np.corrcoef(x[ok], target[ok])[0, 1])
            zstat = r * np.sqrt(ok.sum())
            out.append({"target": i, "leader": j, "n": int(ok.sum()), "corr": r,
                        "p": float(2 * stats.norm.sf(abs(zstat)))})
    df = pd.DataFrame(out)
    if len(df):
        df["q"] = bh(df.p.to_numpy())
    return df.sort_values("p")


def feature_direction_corr(frame: pd.DataFrame, rows: np.ndarray, columns: list[str]) -> pd.DataFrame:
    """Spearman corr of each causal feature with the next-bar direction; BH across features."""
    rows, y = _binary_rows(frame, rows)
    out = []
    for col in columns:
        x = frame[col].to_numpy()[rows]
        ok = np.isfinite(x)
        if ok.sum() < 1000:
            continue
        r, p = stats.spearmanr(x[ok], y[ok])
        out.append({"feature": col, "n": int(ok.sum()), "spearman": float(r), "p": float(p)})
    df = pd.DataFrame(out)
    df["q"] = bh(df.p.to_numpy())
    return df.sort_values("p")


def markov_orders(frame: pd.DataFrame, rows: np.ndarray, orders=(1, 2, 3, 4, 5)) -> dict:
    """Colour-sequence tables of order k (k-bar MHI-style patterns), BH across all states of all orders."""
    pat5 = frame.pat5.to_numpy()
    tables = {}
    for k in orders:
        frame[f"_pat{k}"] = np.where(np.isfinite(pat5), np.mod(pat5, 3 ** k), np.nan)
        tables[k] = pattern_table(frame, rows, f"_pat{k}")
        frame.drop(columns=f"_pat{k}", inplace=True)
    allp = np.concatenate([t.p.to_numpy() for t in tables.values()])
    allq = bh(allp)
    out, i = {}, 0
    for k, t in tables.items():
        t = t.assign(q_all_orders=allq[i:i + len(t)])
        i += len(t)
        out[k] = {"states": int(len(t)), "chi2": chi_square_independence(t),
                  "min_q_all_orders": float(t.q_all_orders.min()) if len(t) else None,
                  "best": t.sort_values("p").head(5).to_dict("records")}
    return out


def restart_window(frame: pd.DataFrame) -> dict:
    """Bars right after the broker's daily feed restart (the 2 h the main study excludes)."""
    pos = frame.pos.to_numpy()
    rows = np.flatnonzero((pos >= 1) & (pos < 64))
    first = np.flatnonzero(pos == 0)
    out = {"rows": int(len(rows)), "after_restart_up": up_rate_test(_binary_rows(frame, rows)[1]),
           "first_bar_up": up_rate_test(_binary_rows(frame, first)[1])}
    for h in (1, 2, 5):
        if f"y{h}" in frame:
            r, y = _binary_rows(frame, rows, h)
            prev = frame.color.to_numpy()[r]
            m = prev != 0
            out[f"reversal_rate_h{h}"] = up_rate_test(((2 * y[m] - 1) != prev[m]).astype(np.int8))
    return out


def tie_rate(frame: pd.DataFrame, rows: np.ndarray, horizon: int) -> float:
    y = frame[f"y{horizon}"].to_numpy()[rows]
    known = y != -2
    return float((y[known] == -1).mean())
