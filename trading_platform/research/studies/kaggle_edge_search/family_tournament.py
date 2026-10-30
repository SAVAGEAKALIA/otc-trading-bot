"""Round 2: walk-forward tournament across model families (2m expiry).

Frozen rubric: docs/research/kaggle_tournament_round2_rubric.md. The holdout
(label candle >= 2026-09-22 01:00) is not in the shipped matrix, and rows from it
are refused here as a second guard.

Families: logistic, lightgbm, lightgbm_rolling14, xgboost, mlp, gru, tcn,
cross_asset_transformer, knn_pattern. Five weekly test folds from Aug 18. Each
fold trains on everything earlier (rolling14: 14 days), early-stops on the last 3
training days, and predicts the test week. Thresholds for week f come only from
the out-of-sample predictions of weeks < f.

Kaggle runs this file with train_edge_search.py inlined above it (see
push_tournament.sh), so the shared models and statistics are not duplicated.
Locally:  python family_tournament.py --data otc_matrix.parquet --out out --smoke
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

try:
    from train_edge_search import (BREAKEVEN, DEVICE, GRUNet, MIN_VAL_TRADES, MLP, NON_FEATURES, QUANTILES,
                                   SEED, Standardize, bonferroni_z, export_torch, logloss, onnx_predict,
                                   predict_torch, train_torch, wilson)
except ImportError:  # inlined on Kaggle: the names already exist in this module
    pass

for pkg, mod in (("lightgbm", "lightgbm"), ("xgboost", "xgboost"), ("onnxmltools", "onnxmltools")):
    try:
        __import__(mod)
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], check=True)
import lightgbm as lgb  # noqa: E402
import xgboost as xgb  # noqa: E402

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
HOLDOUT_START_MS = int(pd.Timestamp("2026-09-22T01:00Z").value // 10**6)
WEEK_STARTS = [int(pd.Timestamp(d).value // 10**6) for d in
               ("2026-08-18T00:00Z", "2026-08-25T00:00Z", "2026-09-01T00:00Z", "2026-09-08T00:00Z", "2026-09-15T00:00Z")]
FAMILIES = ("logistic", "lightgbm", "lightgbm_rolling14", "xgboost", "mlp", "gru", "tcn",
            "cross_asset_transformer", "knn_pattern")
LN2 = math.log(2)


# ---------------------------------------------------------------- extra models
class Logistic(nn.Module):
    def __init__(self, mean, std):
        super().__init__()
        self.norm = Standardize(mean, std)
        self.lin = nn.Linear(len(mean), 1)

    def forward(self, x):
        return torch.sigmoid(self.lin(self.norm(x))).squeeze(-1)


class TCN(nn.Module):
    """Causal dilated convolutions over the last 30 candles + static context."""

    def __init__(self, mean, std, seq_idx, static_idx):
        super().__init__()
        self.norm = Standardize(mean, std)
        self.register_buffer("seq_idx", torch.tensor(seq_idx, dtype=torch.long))
        self.register_buffer("static_idx", torch.tensor(static_idx, dtype=torch.long))
        layers, ch = [], 3
        for d in (1, 2, 4, 8):
            layers += [nn.ConstantPad1d((2 * d, 0), 0.0), nn.Conv1d(ch, 48, 3, dilation=d), nn.GELU()]
            ch = 48
        self.conv = nn.Sequential(*layers)
        self.head = nn.Sequential(nn.Linear(48 + len(static_idx), 128), nn.GELU(), nn.Dropout(0.2), nn.Linear(128, 1))

    def forward(self, x):
        z = self.norm(x)
        padded = torch.cat([z, torch.zeros_like(z[:, :1])], dim=1)
        seq = padded[:, self.seq_idx.flip(0)].transpose(1, 2)  # [n, 3, 30], oldest first
        h = self.conv(seq)[:, :, -1]
        return torch.sigmoid(self.head(torch.cat([h, z[:, self.static_idx]], dim=1))).squeeze(-1)


class CrossAssetTransformer(nn.Module):
    """One token per asset at the same candle time; attention across assets."""

    def __init__(self, mean, std, n_assets, d=64):
        super().__init__()
        self.norm = Standardize(mean, std)
        self.embed = nn.Linear(len(mean), d)
        self.asset = nn.Embedding(n_assets, d)
        layer = nn.TransformerEncoderLayer(d, 4, 128, dropout=0.1, batch_first=True)
        self.enc = nn.TransformerEncoder(layer, 2, enable_nested_tensor=False)
        self.head = nn.Linear(d, 1)
        self.register_buffer("asset_ids", torch.arange(n_assets))

    def forward(self, x, pad):  # x [n, A, F] raw features, pad [n, A] float (1 = missing)
        h = self.embed(self.norm(x)) + self.asset(self.asset_ids)
        h = self.enc(h, src_key_padding_mask=pad > 0.5)
        return torch.sigmoid(self.head(h)).squeeze(-1)


def to_panel(d, feats, n_assets):
    times = np.unique(d["start_ms"].to_numpy())
    ti = np.searchsorted(times, d["start_ms"].to_numpy())
    ai = d["asset_id"].to_numpy().astype(int)
    X = np.full((len(times), n_assets, len(feats)), np.nan, dtype=np.float32)
    Y = np.full((len(times), n_assets), -1, dtype=np.int64)
    X[ti, ai] = d[feats].to_numpy(np.float32)
    Y[ti, ai] = d["y"].to_numpy()
    return X, Y, (Y < 0).astype(np.float32), ti, ai


def train_transformer(model, tr, va, epochs, batch=512, lr=5e-4):
    (Xtr, Ytr, Ptr), (Xva, Yva, Pva) = tr, va
    model.to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    best, state, bad = 1e9, None, 0
    for ep in range(epochs):
        model.train()
        perm = np.random.permutation(len(Xtr))
        for i in range(0, len(perm), batch):
            b = perm[i:i + batch]
            x, y, pad = (torch.tensor(a[b]).to(DEVICE) for a in (Xtr, Ytr, Ptr))
            p = model(x, pad).clamp(1e-6, 1 - 1e-6)
            m = y >= 0
            loss = nn.functional.binary_cross_entropy(p[m], y[m].float())
            opt.zero_grad()
            loss.backward()
            opt.step()
        pv = predict_transformer(model, Xva, Pva)
        val = logloss(Yva[Yva >= 0], pv[Yva >= 0])
        print(f"    epoch {ep} val_logloss={val:.5f}", flush=True)
        if val < best - 1e-5:
            best, bad, state = val, 0, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 2:
                break
    model.load_state_dict(state)
    return model.cpu().eval()


@torch.no_grad()
def predict_transformer(model, X, P, batch=2048):
    model.eval()
    dev = next(model.parameters()).device
    return np.concatenate([model(torch.tensor(X[i:i + batch]).to(dev), torch.tensor(P[i:i + batch]).to(dev)).cpu().numpy()
                           for i in range(0, len(X), batch)])


def knn_predict(Xtr, ytr, Xte, k=100, max_train=400_000):
    """Mean label of the k nearest standardized candle-shape vectors (GPU cdist)."""
    Xtr, ytr = Xtr[-max_train:], ytr[-max_train:]
    mean, std = np.nanmean(Xtr, 0), np.nanstd(Xtr, 0) + 1e-9
    norm = lambda a: torch.tensor(np.nan_to_num((a - mean) / std), device=DEVICE)
    T, Y = norm(Xtr), torch.tensor(ytr, dtype=torch.float32, device=DEVICE)
    out = []
    for i in range(0, len(Xte), 2048):
        idx = torch.cdist(norm(Xte[i:i + 2048]), T).topk(k, largest=False).indices
        out.append(((Y[idx].sum(1) + 1) / (k + 2)).cpu().numpy())  # Laplace-smoothed
    return np.concatenate(out) if out else np.array([])


def export_onnx_tree(model, kind, n_features, path):
    from onnxmltools import convert_lightgbm, convert_xgboost
    from onnxmltools.convert.common.data_types import FloatTensorType
    spec = [("x", FloatTensorType([None, n_features]))]
    conv = convert_lightgbm(model, initial_types=spec, zipmap=False) if kind == "lgb" else \
        convert_xgboost(model, initial_types=spec)
    Path(path).write_bytes(conv.SerializeToString())


# ---------------------------------------------------------------- scoring
def pooled_score(weeks, z):
    """weeks: list of dicts (conf, win, p, y, day) per test week, in order."""
    trades, wins, per_week = 0, 0, []
    for f in range(1, len(weeks)):
        prior_conf = np.concatenate([w["conf"] for w in weeks[:f]])
        prior_win = np.concatenate([w["win"] for w in weeks[:f]])
        best = None
        for q in QUANTILES:
            cut = float(np.quantile(prior_conf, q))
            sel = prior_conf >= cut
            if sel.sum() >= MIN_VAL_TRADES and (best is None or prior_win[sel].mean() > best[1]):
                best = (cut, prior_win[sel].mean(), q)
        if best is None:
            per_week.append({"week": f + 1, "trades": 0})
            continue
        sel = weeks[f]["conf"] >= best[0]
        n, w = int(sel.sum()), int(weeks[f]["win"][sel].sum())
        trades, wins = trades + n, wins + w
        per_week.append({"week": f + 1, "quantile": best[2], "trades": n, "win_rate": w / n if n else float("nan")})
    lo, hi = wilson(wins, trades, z)
    above = sum(1 for p in per_week if p.get("trades") and p["win_rate"] > BREAKEVEN)
    return {"pooled_trades": trades, "pooled_win_rate": wins / trades if trades else float("nan"),
            "pooled_ci_bonferroni": [lo, hi], "weeks_above_breakeven": above, "per_week": per_week,
            "candidate": bool(trades >= 300 and lo > BREAKEVEN and above >= 3)}


def logloss_gap_ci(weeks, n_boot=1000):
    p = np.concatenate([w["p"] for w in weeks])
    y = np.concatenate([w["y"] for w in weeks])
    day = np.concatenate([w["day"] for w in weeks])
    keep = ~np.isnan(p)
    p, y, day = np.clip(p[keep], 1e-7, 1 - 1e-7), y[keep], day[keep]
    ll = -(y * np.log(p) + (1 - y) * np.log(1 - p)) - LN2
    days = np.unique(day)
    per_day = np.array([ll[day == d].sum() for d in days])
    counts = np.array([(day == d).sum() for d in days])
    rng = np.random.default_rng(SEED)
    boots = [per_day[i].sum() / counts[i].sum() for i in (rng.integers(0, len(days), len(days)) for _ in range(n_boot))]
    return float(ll.mean()), [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("/kaggle/working"))
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--families", nargs="+", default=list(FAMILIES))
    args = ap.parse_args()
    data = args.data or next(Path("/kaggle/input").rglob("otc_matrix.parquet"))
    out = args.out
    (out / "models").mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(data)
    df = df[df["tf_sec"] == 120]
    if (df["target_start_ms"] >= HOLDOUT_START_MS).any():
        raise SystemExit("refusing to run: holdout rows present in the matrix")
    feats = [c for c in df.columns if c not in NON_FEATURES]
    if args.smoke:
        # Every week stays populated: a thin random slice of the whole period.
        df = df[df["start_ms"] >= WEEK_STARTS[0] - 21 * DAY_MS].sample(frac=0.04, random_state=SEED)
        df = df.sort_values("target_start_ms")
    epochs, rounds = (1, 30) if args.smoke else (6, 2000)
    n_assets = int(df["asset_id"].max()) + 1
    seq_idx = [[feats.index(f"body_z_{k}"),
                feats.index(f"upper_wick_{k}") if f"upper_wick_{k}" in feats else len(feats),
                feats.index(f"lower_wick_{k}") if f"lower_wick_{k}" in feats else len(feats)] for k in range(30)]
    static_idx = [i for i in range(len(feats)) if i not in {j for r in seq_idx for j in r}]
    knn_feats = [feats.index(f) for f in feats if f.startswith(("body_z_", "upper_wick_", "lower_wick_"))
                 and int(f.rsplit("_", 1)[1]) < 10]
    print(f"device={DEVICE} gpus={torch.cuda.device_count()} rows={len(df):,} features={len(feats)} "
          f"families={args.families}", flush=True)
    json.dump(feats, open(out / "feature_order.json", "w"), indent=1)

    z = bonferroni_z(len(FAMILIES))
    oos = {f: [] for f in args.families}
    preds = []
    parity = {}
    started = time.time()
    t_all = df["target_start_ms"].to_numpy()
    for wi, ws in enumerate(WEEK_STARTS):
        we = ws + 7 * DAY_MS
        te = df[(t_all >= ws) & (t_all < we)]
        hist = df[t_all < ws - HOUR_MS]
        cut_va = ws - 3 * DAY_MS
        tr, va = hist[hist["target_start_ms"] < cut_va - HOUR_MS], hist[hist["target_start_ms"] >= cut_va]
        print(f"\n=== week {wi + 1} test={len(te):,} train={len(tr):,} early-stop={len(va):,}", flush=True)
        X = {k: v[feats].to_numpy(np.float32) for k, v in (("tr", tr), ("va", va), ("te", te))}
        y = {k: v["y"].to_numpy(np.int64) for k, v in (("tr", tr), ("va", va), ("te", te))}
        mean = np.nan_to_num(np.nanmean(X["tr"], 0))
        std = np.nan_to_num(np.nanstd(X["tr"], 0))
        std = np.where(std < 1e-9, 1.0, std)
        last = wi == len(WEEK_STARTS) - 1
        wk = pd.DataFrame({"asset": te["asset"].values, "target_start_ms": te["target_start_ms"].values,
                           "y": y["te"], "week": wi + 1})

        for fam in args.families:
            t0 = time.time()
            onnx_path = out / "models" / f"{fam}.onnx" if last else None
            p = None
            if fam in ("logistic", "mlp", "gru", "tcn"):
                net = {"logistic": lambda: Logistic(mean, std), "mlp": lambda: MLP(mean, std),
                       "gru": lambda: GRUNet(mean, std, seq_idx, static_idx),
                       "tcn": lambda: TCN(mean, std, seq_idx, static_idx)}[fam]()
                net = train_torch(net, X["tr"], y["tr"], X["va"], y["va"], epochs)
                p = predict_torch(net, X["te"])
                if onnx_path:
                    export_torch(net, len(feats), onnx_path)
            elif fam in ("lightgbm", "lightgbm_rolling14"):
                keep = slice(None) if fam == "lightgbm" else tr["target_start_ms"].to_numpy() >= ws - 14 * DAY_MS
                m = lgb.LGBMClassifier(n_estimators=rounds, learning_rate=0.02, num_leaves=63, min_child_samples=500,
                                       subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=10,
                                       random_state=SEED, verbose=-1)
                m.fit(X["tr"][keep], y["tr"][keep], eval_set=[(X["va"], y["va"])],
                      callbacks=[lgb.early_stopping(100, verbose=False)])
                p = m.predict_proba(X["te"])[:, 1]
                if onnx_path:
                    export_onnx_tree(m, "lgb", len(feats), onnx_path)
            elif fam == "xgboost":
                m = xgb.XGBClassifier(n_estimators=rounds, learning_rate=0.02, max_depth=6, min_child_weight=200,
                                      subsample=0.8, colsample_bytree=0.7, reg_lambda=10, tree_method="hist",
                                      device="cuda" if DEVICE == "cuda" else "cpu", early_stopping_rounds=100,
                                      eval_metric="logloss", random_state=SEED)
                m.fit(X["tr"], y["tr"], eval_set=[(X["va"], y["va"])], verbose=False)
                p = m.predict_proba(X["te"])[:, 1]
                if onnx_path:
                    export_onnx_tree(m, "xgb", len(feats), onnx_path)
            elif fam == "cross_asset_transformer":
                pan = {k: to_panel(v, feats, n_assets) for k, v in (("tr", tr), ("va", va), ("te", te))}
                net = train_transformer(CrossAssetTransformer(mean, std, n_assets),
                                        pan["tr"][:3], pan["va"][:3], epochs)
                Xp, Yp, Pp, ti, ai = pan["te"]
                p = predict_transformer(net, Xp, Pp)[ti, ai]
                if onnx_path:
                    torch.onnx.export(net, (torch.zeros(2, n_assets, len(feats)), torch.zeros(2, n_assets)), onnx_path,
                                      input_names=["x", "pad"], output_names=["p"], opset_version=17, dynamo=False,
                                      dynamic_axes={"x": {0: "n"}, "pad": {0: "n"}, "p": {0: "n"}})
                    sess_p = __import__("onnxruntime").InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
                    po = np.concatenate([sess_p.run(None, {"x": Xp[i:i + 2048], "pad": Pp[i:i + 2048]})[0]
                                         for i in range(0, len(Xp), 2048)])[ti, ai]
                    parity[fam] = float(np.max(np.abs(po - p)))
                    onnx_path = None  # parity done here (two inputs)
            elif fam == "knn_pattern":
                train_all = np.concatenate([X["tr"], X["va"]])[:, knn_feats]
                p = knn_predict(train_all, np.concatenate([y["tr"], y["va"]]), X["te"][:, knn_feats])
            if onnx_path is not None and onnx_path.exists():
                parity[fam] = float(np.max(np.abs(onnx_predict(onnx_path, X["te"]) - p)))
            wk[f"p_{fam}"] = p
            day = (te["target_start_ms"].to_numpy() // DAY_MS)
            oos[fam].append({"p": p, "y": y["te"], "day": day, "conf": np.abs(p - 0.5),
                             "win": (p > 0.5) == (y["te"] == 1)})
            print(f"  {fam}: test_logloss={logloss(y['te'], p):.5f} ({time.time() - t0:.0f}s)", flush=True)
        preds.append(wk)

    pd.concat(preds).to_parquet(out / "oos_predictions.parquet", index=False)
    results = []
    for fam in args.families:
        r = {"family": fam, **pooled_score(oos[fam], z)}
        r["logloss_minus_ln2"], r["logloss_minus_ln2_ci95"] = logloss_gap_ci(oos[fam])
        r["learned_something"] = r["logloss_minus_ln2_ci95"][1] < 0
        results.append(r)
    summary = {"breakeven": BREAKEVEN, "K": len(FAMILIES), "bonferroni_z": z, "minutes": round((time.time() - started) / 60, 1),
               "onnx_max_abs_diff": parity, "onnx_parity_ok": all(v <= 1e-4 for v in parity.values()),
               "any_candidate": any(r["candidate"] for r in results), "results": results}
    json.dump(summary, open(out / "tournament_results.json", "w"), indent=2, default=float)
    print("\n" + "=" * 78)
    for r in sorted(results, key=lambda r: r["logloss_minus_ln2"]):
        print(f"{r['family']:24s} ll-ln2={r['logloss_minus_ln2']:+.5f} ci={[round(c, 5) for c in r['logloss_minus_ln2_ci95']]} "
              f"trades={r['pooled_trades']:,} wr={r['pooled_win_rate']:.4f} ci={[round(c, 4) for c in r['pooled_ci_bonferroni']]} "
              f"weeks>BE={r['weeks_above_breakeven']} -> {'CANDIDATE' if r['candidate'] else 'no'}")
    print(f"ONNX parity ok: {summary['onnx_parity_ok']} {parity}")
    print(f"ANY CANDIDATE: {summary['any_candidate']}")


if __name__ == "__main__":
    main()
