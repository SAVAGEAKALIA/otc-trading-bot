"""Round 3: is there an edge in following or fading the IQ Option crowd?

Frozen rubric: docs/research/round3_crowd_rubric.md. Every decision for a test week
uses only earlier weeks. Weeks from Sep 22 on were seen when the lead was found,
so they are reported separately and never count toward a pass.

    python -m trading_platform.research.studies.otc_crowd_study \
        --matrix otc_matrix_raw.parquet --mood mood.csv.gz --payout payout.csv.gz --out out/
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from trading_platform.research.studies.otc_feature_matrix import MOOD_MAX_AGE_MS, clean_mood

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
START_MS = int(pd.Timestamp("2026-07-31T00:00Z").value // 10**6)
WEEKS = [int(pd.Timestamp(d).value // 10**6) for d in (
    "2026-08-11", "2026-08-18", "2026-08-25", "2026-09-01", "2026-09-08", "2026-09-15",  # unseen
    "2026-09-22", "2026-09-29", "2026-10-06")]  # seen
SEEN_FROM_MS = int(pd.Timestamp("2026-09-22").value // 10**6)
PAYOUT_MAX_AGE_MS = 600_000
DEFAULT_PAYOUT = 0.85
QUANTILES = (0.0, 0.5, 0.8, 0.9, 0.95, 0.98)
MIN_TRADES = 300
K = 4
BANDS = np.arange(0.0, 0.5001, 0.05)


def wilson_lower(w: float, n: float, z: float) -> float:
    if n <= 0:
        return 0.0
    p = w / n
    d = 1 + z * z / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d


# ---------------------------------------------------------------- features
def _asof(left: pd.DataFrame, right: pd.DataFrame, key: str, rkey: str, cols: list[str], tol: int) -> pd.DataFrame:
    out = pd.merge_asof(left.sort_values(key), right[["asset", rkey, *cols]].sort_values(rkey),
                        left_on=key, right_on=rkey, by="asset", direction="backward", tolerance=tol)
    return out.drop(columns=rkey)


def crowd_features(rows: pd.DataFrame, mood: pd.DataFrame, payout: pd.DataFrame) -> pd.DataFrame:
    """Add causal crowd columns. rows need asset, target_start_ms, body_z_0.

    Every value is computed from mood/payout samples observed at least 1s before
    the target candle opens (key = target_start_ms - 1000).
    """
    m = mood.sort_values(["asset", "mood_ms"]).copy()
    ts = pd.to_datetime(m["mood_ms"], unit="ms")
    parts = []
    for _, g in m.assign(ts=ts).groupby("asset", sort=False):
        s = g.set_index("ts")["call"]
        g = g.copy()
        # Time-window stats over samples at or before each sample (causal).
        g["m_max10"] = s.rolling("600s").max().to_numpy()
        g["m_min10"] = s.rolling("600s").min().to_numpy()
        g["m_std10"] = s.rolling("600s").std().to_numpy()
        mu, sd = s.rolling("86400s", min_periods=50).mean(), s.rolling("86400s", min_periods=50).std()
        g["m_z24h"] = ((s - mu) / sd).to_numpy()
        parts.append(g.drop(columns="ts"))
    m = pd.concat(parts, ignore_index=True)

    out = rows.copy()
    out["key"] = out["target_start_ms"] - 1000
    out = _asof(out, m.rename(columns={"call": "m0"}), "key", "mood_ms",
                ["m0", "m_max10", "m_min10", "m_std10", "m_z24h"], MOOD_MAX_AGE_MS)
    for lag in (60, 120, 300, 600):
        out[f"k{lag}"] = out["key"] - lag * 1000
        out = _asof(out, m.rename(columns={"call": f"m_{lag}"}), f"k{lag}", "mood_ms", [f"m_{lag}"], MOOD_MAX_AGE_MS)
        out = out.drop(columns=f"k{lag}")
    out = out[out["m0"].notna() & (out["m0"] != 0.5)].copy()
    out["crowd_side"] = np.where(out["m0"] > 0.5, 1, -1)  # +1 crowd long (CALL)
    out["crowd_ext"] = (out["m0"] - 0.5).abs()
    out["crowd_ext_trend"] = out["crowd_ext"] - (out["m_600"] - 0.5).abs()
    for lag in (60, 120, 300, 600):
        out[f"m_delta_{lag}"] = out["m0"] - out[f"m_{lag}"]
    out["market_mood"] = out.groupby("target_start_ms")["m0"].transform("mean") - 0.5
    out["crowd_vs_market"] = (out["m0"] - 0.5) - out["market_mood"]
    out["crowd_agrees_price"] = (np.sign(out["body_z_0"]) == out["crowd_side"]).astype(np.int8)
    p = payout.rename(columns={"payout_ms": "pay_ms"})
    out = _asof(out, p, "key", "pay_ms", ["payout"], PAYOUT_MAX_AGE_MS)
    out["payout"] = out["payout"].fillna(DEFAULT_PAYOUT)
    return out.drop(columns="key").sort_values(["target_start_ms", "asset"]).reset_index(drop=True)


def fade_wins(df: pd.DataFrame) -> np.ndarray:
    """1 when betting against the crowd wins (crowd long -> PUT wins when the candle closes down)."""
    return ((df["y"].to_numpy() == 1) == (df["crowd_side"].to_numpy() == -1)).astype(np.int8)


def grid_cell(df: pd.DataFrame) -> np.ndarray:
    band = np.clip(np.digitize(df["crowd_ext"].to_numpy(), BANDS) - 1, 0, len(BANDS) - 2)
    trend = (df["crowd_ext_trend"].fillna(0).to_numpy() > 0).astype(int)
    agree = df["crowd_agrees_price"].to_numpy().astype(int)
    return band * 4 + trend * 2 + agree


# ---------------------------------------------------------------- strategies
def trades_frame(df: pd.DataFrame, fade: np.ndarray, week: int) -> pd.DataFrame:
    """fade: bool per row, True = bet against the crowd."""
    fw = fade_wins(df).astype(bool)
    win = np.where(fade, fw, ~fw)
    pay = df["payout"].to_numpy()
    return pd.DataFrame({"week": week, "target_start_ms": df["target_start_ms"].to_numpy(),
                         "asset": df["asset"].to_numpy(), "fade": fade, "win": win,
                         "payout": pay, "pnl": np.where(win, pay, -1.0)})


def grid_select(prior: pd.DataFrame) -> dict[int, bool]:
    """Cells (-> fade?) whose prior record beats breakeven at a one-sided 80% bound."""
    z = NormalDist().inv_cdf(0.80)
    fw = fade_wins(prior)
    cells = grid_cell(prior)
    be = 1 / (1 + prior["payout"].to_numpy())
    chosen = {}
    for c in np.unique(cells):
        m = cells == c
        n = int(m.sum())
        if n < MIN_TRADES:
            continue
        wins_fade = int(fw[m].sum())
        ok_fade = wilson_lower(wins_fade, n, z) > be[m].mean()
        ok_follow = wilson_lower(n - wins_fade, n, z) > be[m].mean()
        if ok_fade != ok_follow:  # both selected = contradictory, drop
            chosen[int(c)] = ok_fade
    return chosen


def run_grid(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    t = df["target_start_ms"].to_numpy()
    for wi, ws in enumerate(WEEKS):
        prior = df[t < ws - HOUR_MS]
        test = df[(t >= ws) & (t < ws + 7 * DAY_MS)]
        if wi == 0 or test.empty:
            continue
        chosen = grid_select(prior)
        cells = grid_cell(test)
        mask = np.isin(cells, list(chosen))
        if mask.any():
            fade = np.array([chosen[c] for c in cells[mask]])
            out.append(trades_frame(test[mask], fade, wi))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["week", "win", "payout", "pnl"])


def run_model(df: pd.DataFrame, feats: list[str], kind: str, seed: int = 20261030) -> pd.DataFrame:
    """Walk-forward meta-model: P(fade wins). Thresholds from prior weeks' OOS only."""
    t = df["target_start_ms"].to_numpy()
    y = fade_wins(df)
    oos = []  # (week, row index, p)
    trades = []
    for wi, ws in enumerate(WEEKS):
        tr_mask = t < ws - HOUR_MS
        te_mask = (t >= ws) & (t < ws + 7 * DAY_MS)
        if not te_mask.any() or tr_mask.sum() < 1000:
            continue
        Xtr, ytr = df.loc[tr_mask, feats].to_numpy(np.float32), y[tr_mask]
        Xte = df.loc[te_mask, feats].to_numpy(np.float32)
        p = _fit_predict(kind, Xtr, ytr, Xte, seed)
        idx = np.flatnonzero(te_mask)
        if wi > 0 and oos:
            prior_p = np.concatenate([o[2] for o in oos])
            prior_idx = np.concatenate([o[1] for o in oos])
            conf = np.abs(prior_p - 0.5)
            fade_p = prior_p > 0.5
            fw = y[prior_idx].astype(bool)
            win = np.where(fade_p, fw, ~fw)
            pay = df["payout"].to_numpy()[prior_idx]
            best = None
            for q in QUANTILES:
                cut = float(np.quantile(conf, q))
                sel = conf >= cut
                if sel.sum() < MIN_TRADES:
                    continue
                roi = float(np.where(win[sel], pay[sel], -1.0).mean())
                if best is None or roi > best[1]:
                    best = (cut, roi)
            if best is not None:
                sel = np.abs(p - 0.5) >= best[0]
                if sel.any():
                    trades.append(trades_frame(df.iloc[idx[sel]], p[sel] > 0.5, wi))
        oos.append((wi, idx, p))
    return pd.concat(trades, ignore_index=True) if trades else pd.DataFrame(columns=["week", "win", "payout", "pnl"])


def _fit_predict(kind, Xtr, ytr, Xte, seed):
    if kind == "logistic":
        from sklearn.linear_model import LogisticRegression
        mu, sd = np.nanmean(Xtr, 0), np.nanstd(Xtr, 0) + 1e-9
        f = lambda a: np.clip(np.nan_to_num((a - mu) / sd), -8, 8)
        return LogisticRegression(C=0.1, max_iter=500).fit(f(Xtr), ytr).predict_proba(f(Xte))[:, 1]
    cut = int(len(Xtr) * 0.9)  # last 10% of training time for early stopping
    if kind == "lightgbm":
        import lightgbm as lgb
        m = lgb.LGBMClassifier(n_estimators=1000, learning_rate=0.02, num_leaves=31, min_child_samples=300,
                               subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=10,
                               random_state=seed, verbose=-1)
        m.fit(Xtr[:cut], ytr[:cut], eval_set=[(Xtr[cut:], ytr[cut:])], callbacks=[lgb.early_stopping(100, verbose=False)])
        return m.predict_proba(Xte)[:, 1]
    if kind == "xgboost":
        import xgboost as xgb
        m = xgb.XGBClassifier(n_estimators=1000, learning_rate=0.02, max_depth=5, min_child_weight=100,
                              subsample=0.8, colsample_bytree=0.7, reg_lambda=10, tree_method="hist",
                              early_stopping_rounds=100, eval_metric="logloss", random_state=seed)
        m.fit(Xtr[:cut], ytr[:cut], eval_set=[(Xtr[cut:], ytr[cut:])], verbose=False)
        return m.predict_proba(Xte)[:, 1]
    raise ValueError(kind)


# ---------------------------------------------------------------- scoring
def score(trades: pd.DataFrame) -> dict:
    z = NormalDist().inv_cdf(1 - 0.05 / (2 * K))
    res = {}
    seen_week = {wi: ws >= SEEN_FROM_MS for wi, ws in enumerate(WEEKS)}
    for name, part in (("unseen", trades[~trades["week"].map(seen_week).astype(bool)]),
                       ("seen", trades[trades["week"].map(seen_week).astype(bool)])):
        n, w = len(part), int(part["win"].sum()) if len(part) else 0
        be = float((1 / (1 + part["payout"])).mean()) if n else float("nan")
        weekly = part.groupby("week").agg(trades=("pnl", "size"), win_rate=("win", "mean"), roi=("pnl", "mean"))
        res[name] = {"trades": n, "win_rate": w / n if n else float("nan"), "mean_breakeven": be,
                     "wilson_lower_bonferroni": wilson_lower(w, n, z), "roi": float(part["pnl"].mean()) if n else float("nan"),
                     "weeks_roi_positive": int((weekly["roi"] > 0).sum()), "weeks": int(len(weekly)),
                     "fade_share": float(part["fade"].mean()) if n else float("nan"),
                     "weekly": {str(k): v for k, v in weekly.round(4).to_dict("index").items()}}
    u = res["unseen"]
    res["candidate"] = bool(u["trades"] >= MIN_TRADES and u["wilson_lower_bonferroni"] > u["mean_breakeven"]
                            and u["roi"] > 0 and u["weeks_roi_positive"] >= 4)
    return res


def describe(df: pd.DataFrame) -> pd.DataFrame:
    """Whole-period follow/fade table by crowd extremeness band (descriptive, not a test)."""
    fw = fade_wins(df)
    band = pd.cut(df["crowd_ext"], BANDS, right=False)
    t = pd.DataFrame({"band": band, "fade_win": fw, "payout": df["payout"].to_numpy(),
                      "seen": df["target_start_ms"].to_numpy() >= SEEN_FROM_MS})
    g = t.groupby(["band", "seen"], observed=True).agg(n=("fade_win", "size"), fade_wr=("fade_win", "mean"),
                                                       payout=("payout", "mean"))
    g["follow_wr"] = 1 - g["fade_wr"]
    g["breakeven"] = 1 / (1 + g["payout"])
    return g.round(4)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matrix", type=Path, required=True)
    ap.add_argument("--mood", type=Path, required=True)
    ap.add_argument("--payout", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--strategies", nargs="+", default=["grid", "lightgbm", "xgboost", "logistic"])
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    rows = pd.read_parquet(a.matrix, filters=[("tf_sec", "==", 120), ("target_start_ms", ">=", START_MS)])
    rows = rows.drop(columns=[c for c in rows.columns if c.startswith("mood_")])  # rebuilt below
    mood = clean_mood(pd.read_csv(a.mood, names=["asset", "itype", "mood_ms", "call"]))
    pay = pd.read_csv(a.payout, names=["asset", "itype", "payout_ms", "payout", "source"])
    pay = pay[pay["itype"] == "turbo-option"].groupby(["asset", "payout_ms"], as_index=False)["payout"].mean()
    df = crowd_features(rows, mood, pay)
    print(f"crowd rows={len(df):,} assets={df.asset.nunique()} fade P(win)={fade_wins(df).mean():.4f}", flush=True)
    desc = describe(df)
    print(desc.to_string(), flush=True)
    desc.to_csv(a.out / "follow_fade_by_band.csv")
    skip = {"y", "split", "asset", "start_ms", "target_start_ms", "tf_sec"}
    feats = [c for c in df.columns if c not in skip and df[c].dtype.kind in "fiub"]
    results = {}
    for s in a.strategies:
        tr = run_grid(df) if s == "grid" else run_model(df, feats, s)
        tr.to_parquet(a.out / f"trades_{s}.parquet", index=False)
        results[s] = score(tr)
        u, se = results[s]["unseen"], results[s]["seen"]
        print(f"{s:9s} UNSEEN n={u['trades']:,} wr={u['win_rate']:.4f} be={u['mean_breakeven']:.4f} "
              f"lowerB={u['wilson_lower_bonferroni']:.4f} roi={u['roi']:+.4f} weeks+={u['weeks_roi_positive']}/{u['weeks']} "
              f"fade={u['fade_share']:.2f} | SEEN n={se['trades']:,} wr={se['win_rate']:.4f} roi={se['roi']:+.4f} "
              f"-> {'CANDIDATE' if results[s]['candidate'] else 'no'}", flush=True)
    json.dump({"features": feats, "results": results}, open(a.out / "crowd_results.json", "w"), indent=2, default=float)
    print("ANY CANDIDATE:", any(r["candidate"] for r in results.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
