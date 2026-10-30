"""Kaggle kernel: search for a next-candle edge on IQ Option OTC, export ONNX.

Frozen rubric: docs/plans/2026-10-30-direction-reset.md section 1c. Splits are
precomputed in the matrix. Thresholds are chosen on validation only; holdout is
scored once, after every model is trained.

Strategies per timeframe (120s, 300s):
  catboost_all     gradient boosting on every feature
  catboost_recent  same, trained only on the realtime period (regime recency)
  catboost_mood    crowd mood + time + last 5 bodies, rows with mood only
  meta_contrarian  bet against the crowd; model predicts when that bet wins
  mlp              3-layer MLP, standardisation baked into the graph
  gru              GRU over the last 30 candles + static context
  ensemble         mean of catboost_all, mlp, gru probabilities

Run locally:  python train_edge_search.py --data otc_matrix.parquet --out out --smoke
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import onnx  # noqa: F401
    import onnxruntime as ort
except ImportError:  # Kaggle images may lack them; internet is enabled in metadata
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "onnx", "onnxruntime"], check=True)
    import onnxruntime as ort

import torch
from catboost import CatBoostClassifier
from torch import nn

PAYOUT = 0.85
BREAKEVEN = 1 / (1 + PAYOUT)
QUANTILES = (0.0, 0.5, 0.8, 0.9, 0.95, 0.98)
MIN_VAL_TRADES = 300
REALTIME_START_MS = int(pd.Timestamp("2026-07-31T00:00Z").value // 10**6)
SEED = 20261030
NON_FEATURES = {"y", "split", "asset", "start_ms", "target_start_ms", "tf_sec"}
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
N_GPU = torch.cuda.device_count()
# Kaggle free tier: T4 x2. CatBoost trains on every visible GPU.
CATBOOST_DEVICE = {"task_type": "GPU", "devices": f"0:{N_GPU - 1}" if N_GPU > 1 else "0"} if N_GPU else {"task_type": "CPU"}
torch.manual_seed(SEED)
np.random.seed(SEED)


def wilson(w: int, n: int, z: float) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def bonferroni_z(k: int) -> float:
    from statistics import NormalDist
    return NormalDist().inv_cdf(1 - 0.05 / (2 * k))


def logloss(y, p):
    p = np.clip(p, 1e-7, 1 - 1e-7)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# ---------------------------------------------------------------- models
class Standardize(nn.Module):
    def __init__(self, mean, std):
        super().__init__()
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32))
        self.register_buffer("std", torch.tensor(std, dtype=torch.float32))

    def forward(self, x):
        return torch.nan_to_num((x - self.mean) / self.std, nan=0.0, posinf=0.0, neginf=0.0).clamp(-8, 8)


class MLP(nn.Module):
    def __init__(self, mean, std):
        super().__init__()
        d = len(mean)
        self.norm = Standardize(mean, std)
        self.net = nn.Sequential(nn.Linear(d, 256), nn.GELU(), nn.Dropout(0.2), nn.Linear(256, 128), nn.GELU(),
                                 nn.Dropout(0.2), nn.Linear(128, 1))

    def forward(self, x):
        return torch.sigmoid(self.net(self.norm(x))).squeeze(-1)


class GRUNet(nn.Module):
    """Sequence of (body_z, upper_wick, lower_wick) for the last 30 candles + static context."""

    def __init__(self, mean, std, seq_idx, static_idx):
        super().__init__()
        self.norm = Standardize(mean, std)
        self.register_buffer("seq_idx", torch.tensor(seq_idx, dtype=torch.long))  # [30, 3], -1 = zero
        self.register_buffer("static_idx", torch.tensor(static_idx, dtype=torch.long))
        self.gru = nn.GRU(3, 64, num_layers=2, batch_first=True, dropout=0.1)
        self.head = nn.Sequential(nn.Linear(64 + len(static_idx), 128), nn.GELU(), nn.Dropout(0.2), nn.Linear(128, 1))

    def forward(self, x):
        z = self.norm(x)
        padded = torch.cat([z, torch.zeros_like(z[:, :1])], dim=1)  # index -1 -> zero column
        seq = padded[:, self.seq_idx.flip(0)]  # oldest first
        _, h = self.gru(seq)
        return torch.sigmoid(self.head(torch.cat([h[-1], z[:, self.static_idx]], dim=1))).squeeze(-1)


def train_torch(model, Xtr, ytr, Xva, yva, epochs, batch=4096, lr=1e-3):
    model.to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    Xtr_t, ytr_t = torch.tensor(Xtr), torch.tensor(ytr, dtype=torch.float32)
    best, best_state, bad = 1e9, None, 0
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(Xtr_t))
        for i in range(0, len(perm), batch):
            idx = perm[i:i + batch]
            p = model(Xtr_t[idx].to(DEVICE))
            loss = nn.functional.binary_cross_entropy(p.clamp(1e-6, 1 - 1e-6), ytr_t[idx].to(DEVICE))
            opt.zero_grad()
            loss.backward()
            opt.step()
        val = logloss(yva, predict_torch(model, Xva))
        print(f"    epoch {ep} val_logloss={val:.5f}", flush=True)
        if val < best - 1e-5:
            best, bad = val, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 2:
                break
    model.load_state_dict(best_state)
    return model.cpu().eval()


@torch.no_grad()
def predict_torch(model, X, batch=65536):
    model.eval()
    out = [model(torch.tensor(X[i:i + batch]).to(next(model.parameters()).device)).cpu().numpy()
           for i in range(0, len(X), batch)]
    return np.concatenate(out) if out else np.array([])


def export_torch(model, n_features, path):
    dummy = torch.zeros(2, n_features)
    torch.onnx.export(model, dummy, path, input_names=["x"], output_names=["p"],
                      dynamic_axes={"x": {0: "n"}, "p": {0: "n"}}, opset_version=17, dynamo=False)


def train_catboost(Xtr, ytr, Xva, yva, iterations):
    m = CatBoostClassifier(iterations=iterations, learning_rate=0.03, depth=6, l2_leaf_reg=10,
                           loss_function="Logloss", random_seed=SEED, od_type="Iter", od_wait=100,
                           verbose=200, **CATBOOST_DEVICE)
    m.fit(Xtr, ytr, eval_set=(Xva, yva), use_best_model=True)
    return m


def onnx_predict(path, X):
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    outs = sess.run(None, {name: X.astype(np.float32)})
    for o in outs[::-1]:  # catboost: [label, probabilities]; torch: [p]
        arr = o if isinstance(o, np.ndarray) else None
        if arr is None and isinstance(o, list):  # list of {0: p0, 1: p1}
            return np.array([d[1] for d in o], dtype=np.float64)
        if arr is not None and arr.dtype.kind == "f":
            return arr[:, 1].astype(np.float64) if arr.ndim == 2 else arr.astype(np.float64)
    raise ValueError(f"no probability output in {path}")


# ---------------------------------------------------------------- evaluation
def select_threshold(conf_val, win_val):
    best = None
    for q in QUANTILES:
        cut = float(np.quantile(conf_val, q)) if len(conf_val) else 0.0
        sel = conf_val >= cut
        n = int(sel.sum())
        if n < MIN_VAL_TRADES:
            continue
        wr = float(win_val[sel].mean())
        if best is None or wr > best["val_win_rate"]:
            best = {"quantile": q, "cut": cut, "val_trades": n, "val_win_rate": wr}
    return best


def score(name, tf, val, hold, z):
    """val/hold: dicts with conf (bet confidence) and win (bool: bet would win) and t (ms)."""
    thr = select_threshold(val["conf"], val["win"])
    res = {"strategy": name, "tf_sec": tf, "threshold": thr}
    if thr is None:
        res["verdict"] = "NO_VAL_THRESHOLD"
        return res
    sel = hold["conf"] >= thr["cut"]
    w, n = int(hold["win"][sel].sum()), int(sel.sum())
    lo, hi = wilson(w, n, z)
    t = hold["t"][sel]
    mid = np.median(hold["t"]) if len(hold["t"]) else 0
    halves = [float(hold["win"][sel][t < mid].mean()) if (t < mid).any() else float("nan"),
              float(hold["win"][sel][t >= mid].mean()) if (t >= mid).any() else float("nan")]
    res.update({
        "holdout_trades": n, "holdout_wins": w, "holdout_win_rate": w / n if n else float("nan"),
        "holdout_ci_bonferroni": [lo, hi], "holdout_halves_win_rate": halves,
        "holdout_roi": (w * PAYOUT - (n - w)) / n if n else float("nan"),
        "pass": bool(n >= 300 and lo > BREAKEVEN and all(h > BREAKEVEN for h in halves)),
    })
    res["verdict"] = "EDGE" if res["pass"] else "NO_EDGE"
    return res


def direction_eval(p, y, t):
    return {"conf": np.abs(p - 0.5), "win": (p > 0.5) == (y == 1), "t": t}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("/kaggle/working"))
    ap.add_argument("--smoke", action="store_true", help="tiny sample, few iterations")
    args = ap.parse_args()
    data = args.data or next(Path("/kaggle/input").rglob("otc_matrix.parquet"))
    out = args.out
    (out / "models").mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(data)
    if args.smoke:
        df = pd.concat([g.tail(6000) for _, g in df.groupby(["tf_sec", "split"])], ignore_index=True)
    iters, epochs = (60, 1) if args.smoke else (3000, 8)
    feats = [c for c in df.columns if c not in NON_FEATURES]
    print(f"device={DEVICE} gpus={N_GPU} {[torch.cuda.get_device_name(i) for i in range(N_GPU)]} rows={len(df):,} features={len(feats)}", flush=True)
    json.dump(feats, open(out / "feature_order.json", "w"), indent=1)

    configs = 7 * df["tf_sec"].nunique()
    z = bonferroni_z(configs)
    results, holdout_preds, parity = [], {}, {}
    started = time.time()

    for tf, d in df.groupby("tf_sec"):
        tr, va, ho = (d[d.split == s] for s in ("train", "validation", "holdout"))
        X = {k: v[feats].to_numpy(np.float32) for k, v in (("tr", tr), ("va", va), ("ho", ho))}
        y = {k: v["y"].to_numpy(np.int64) for k, v in (("tr", tr), ("va", va), ("ho", ho))}
        t = {k: v["target_start_ms"].to_numpy(np.int64) for k, v in (("va", va), ("ho", ho))}
        print(f"\n=== tf={tf} train={len(tr):,} val={len(va):,} holdout={len(ho):,}", flush=True)
        probs = {}
        hp = pd.DataFrame({"asset": ho["asset"].values, "target_start_ms": t["ho"], "y": y["ho"]})

        def finish(name, p_va, p_ho, onnx_path=None, X_ho=None):
            probs[name] = (p_va, p_ho)
            hp[f"p_{name}"] = p_ho
            results.append(score(name, int(tf), direction_eval(p_va, y["va"], t["va"]),
                                 direction_eval(p_ho, y["ho"], t["ho"]), z))
            results[-1]["val_logloss"] = logloss(y["va"], p_va)
            results[-1]["holdout_logloss"] = logloss(y["ho"], p_ho)
            if onnx_path is not None:
                diff = float(np.max(np.abs(onnx_predict(onnx_path, X_ho) - p_ho))) if len(p_ho) else 0.0
                parity[f"{name}_{tf}"] = diff
            print(f"  {name}: val_ll={results[-1]['val_logloss']:.5f} -> {results[-1]['verdict']}", flush=True)

        # catboost_all
        m = train_catboost(X["tr"], y["tr"], X["va"], y["va"], iters)
        path = out / "models" / f"catboost_all_{tf}.onnx"
        m.save_model(str(path), format="onnx")
        finish("catboost_all", m.predict_proba(X["va"])[:, 1], m.predict_proba(X["ho"])[:, 1], path, X["ho"])

        # catboost_recent
        rec = tr["start_ms"].to_numpy() >= REALTIME_START_MS
        m = train_catboost(X["tr"][rec], y["tr"][rec], X["va"], y["va"], iters)
        path = out / "models" / f"catboost_recent_{tf}.onnx"
        m.save_model(str(path), format="onnx")
        finish("catboost_recent", m.predict_proba(X["va"])[:, 1], m.predict_proba(X["ho"])[:, 1], path, X["ho"])

        # catboost_mood: mood rows, small feature set
        mood_feats = [f for f in feats if f.startswith("mood_") or f in
                      ("hour_sin", "hour_cos", "dow", "asset_id", *(f"body_z_{k}" for k in range(5)))]
        mi = [feats.index(f) for f in mood_feats]
        has = {k: ~np.isnan(X[k][:, feats.index("mood_centered")]) for k in X}
        if has["tr"].sum() > 1000:
            m = train_catboost(X["tr"][has["tr"]][:, mi], y["tr"][has["tr"]], X["va"][has["va"]][:, mi],
                               y["va"][has["va"]], iters)
            path = out / "models" / f"catboost_mood_{tf}.onnx"
            m.save_model(str(path), format="onnx")
            p_va = np.full(len(y["va"]), 0.5)
            p_ho = np.full(len(y["ho"]), 0.5)  # no mood -> no trade (confidence 0)
            p_va[has["va"]] = m.predict_proba(X["va"][has["va"]][:, mi])[:, 1]
            p_ho[has["ho"]] = m.predict_proba(X["ho"][has["ho"]][:, mi])[:, 1]
            finish("catboost_mood", p_va, p_ho)
            parity[f"catboost_mood_{tf}"] = float(np.max(np.abs(
                onnx_predict(path, X["ho"][has["ho"]][:, mi]) - p_ho[has["ho"]]))) if has["ho"].any() else 0.0
            json.dump(mood_feats, open(out / "models" / f"catboost_mood_{tf}.features.json", "w"))

            # meta_contrarian: primary bet = against the crowd; label = that bet wins
            mc = feats.index("mood_centered")
            sub = {k: has[k] & (np.abs(np.nan_to_num(X[k][:, mc])) >= 0.3) for k in X}
            bet_up = {k: X[k][:, mc] < 0 for k in X}  # crowd short -> CALL
            win = {k: (y[k] == 1) == bet_up[k] for k in X}
            if sub["tr"].sum() > 1000 and sub["va"].sum() > MIN_VAL_TRADES:
                m = train_catboost(X["tr"][sub["tr"]], win["tr"][sub["tr"]].astype(int), X["va"][sub["va"]],
                                   win["va"][sub["va"]].astype(int), iters)
                path = out / "models" / f"meta_contrarian_{tf}.onnx"
                m.save_model(str(path), format="onnx")
                ev = {}
                for k in ("va", "ho"):
                    pw = m.predict_proba(X[k][sub[k]])[:, 1]
                    ev[k] = {"conf": pw, "win": win[k][sub[k]], "t": t[k][sub[k]]}
                results.append(score("meta_contrarian", int(tf), ev["va"], ev["ho"], z))
                base = {k: float(win[k][sub[k]].mean()) for k in ("va", "ho")}
                results[-1]["plain_contrarian_win_rate"] = base
                if sub["ho"].any():
                    parity[f"meta_contrarian_{tf}"] = float(np.max(np.abs(onnx_predict(path, X["ho"][sub["ho"]]) - ev["ho"]["conf"])))
                print(f"  meta_contrarian -> {results[-1]['verdict']} (plain contrarian {base})", flush=True)

        # torch models
        mean = np.nanmean(X["tr"], axis=0)
        std = np.nanstd(X["tr"], axis=0)
        mean, std = np.nan_to_num(mean), np.where(np.nan_to_num(std) < 1e-9, 1.0, np.nan_to_num(std))
        mlp = train_torch(MLP(mean, std), X["tr"], y["tr"], X["va"], y["va"], epochs)
        path = out / "models" / f"mlp_{tf}.onnx"
        export_torch(mlp, len(feats), path)
        finish("mlp", predict_torch(mlp, X["va"]), predict_torch(mlp, X["ho"]), path, X["ho"])

        seq_idx = [[feats.index(f"body_z_{k}"),
                    feats.index(f"upper_wick_{k}") if f"upper_wick_{k}" in feats else len(feats),
                    feats.index(f"lower_wick_{k}") if f"lower_wick_{k}" in feats else len(feats)]
                   for k in range(30)]
        seq_cols = {i for row in seq_idx for i in row}
        static_idx = [i for i in range(len(feats)) if i not in seq_cols]
        gru = train_torch(GRUNet(mean, std, seq_idx, static_idx), X["tr"], y["tr"], X["va"], y["va"], epochs)
        path = out / "models" / f"gru_{tf}.onnx"
        export_torch(gru, len(feats), path)
        finish("gru", predict_torch(gru, X["va"]), predict_torch(gru, X["ho"]), path, X["ho"])

        ens_va = np.mean([probs[k][0] for k in ("catboost_all", "mlp", "gru")], axis=0)
        ens_ho = np.mean([probs[k][1] for k in ("catboost_all", "mlp", "gru")], axis=0)
        finish("ensemble", ens_va, ens_ho)
        holdout_preds[tf] = hp

    pd.concat(holdout_preds.values(), keys=list(holdout_preds), names=["tf_sec", "row"]).reset_index(level=0) \
        .to_parquet(out / "holdout_predictions.parquet", index=False)
    summary = {
        "breakeven": BREAKEVEN, "configs_K": configs, "bonferroni_z": z, "device": DEVICE,
        "minutes": round((time.time() - started) / 60, 1), "onnx_max_abs_diff": parity,
        "onnx_parity_ok": all(v <= 1e-4 for v in parity.values()),
        "any_edge": any(r.get("pass") for r in results), "results": results,
    }
    json.dump(summary, open(out / "results.json", "w"), indent=2, default=float)
    print("\n" + "=" * 70)
    for r in results:
        thr = r.get("threshold") or {}
        print(f"{r['strategy']:16s} tf={r['tf_sec']} q={thr.get('quantile')} val_wr={thr.get('val_win_rate', float('nan')):.4f} "
              f"hold_n={r.get('holdout_trades', 0):,} hold_wr={r.get('holdout_win_rate', float('nan')):.4f} "
              f"ci={[round(x, 4) for x in r.get('holdout_ci_bonferroni', [])]} -> {r['verdict']}")
    print(f"ONNX parity ok: {summary['onnx_parity_ok']}  max diffs: {parity}")
    print(f"ANY EDGE: {summary['any_edge']}")


if __name__ == "__main__":
    main()
