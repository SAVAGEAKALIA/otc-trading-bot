"""Standalone cloud audits for the OTC LSTM.

Upload this file, candles_export.csv, and (for --check parity) the three files
from lstm_temporal_v2_artifacts/. It does not import this bot or another script.

Examples:
  python cloud_lstm_audit.py --check causality
  python cloud_lstm_audit.py --check label-shuffle --epochs 15
  python cloud_lstm_audit.py --check embargo --epochs 60 --embargo 90
  python cloud_lstm_audit.py --check parity --artifact-dir lstm_temporal_v2_artifacts
  python cloud_lstm_audit.py --check forward --trade-log trade_log.json
"""

from __future__ import annotations

import argparse
import copy
import json
import pickle
import random
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pandas_ta as ta

SEQ = 90
SCALE = ["open_pct", "high_pct", "low_pct", "close_pct", "dist_ema_20", "atr_pct", "macd_hist", "roc_10"]
BASE = ["rsi_14", "body_ratio", "upper_wick_ratio", "lower_wick_ratio", "close_position", "stoch_k", "bb_percent_b", "hour_of_day", "day_of_week"]
PAYOUT = 0.80


def seed(value=42):
    random.seed(value); np.random.seed(value)
    import torch
    torch.manual_seed(value)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(value)


def timestamps(series):
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all():
        highest = float(numeric.abs().max())
        unit = "ns" if highest >= 1e17 else "us" if highest >= 1e14 else "ms" if highest >= 1e11 else "s"
        result = pd.to_datetime(numeric, unit=unit, utc=True)
    else:
        result = pd.to_datetime(series, utc=True, errors="coerce")
    if result.isna().any(): raise ValueError("Invalid timestamp values")
    return result


def features(frame):
    """Causal feature implementation matching training and live inference."""
    df = frame.copy()
    df["ema_20"] = ta.ema(df.close, length=20)
    df["dist_ema_20"] = (df.close - df.ema_20) / df.ema_20
    df["rsi_14"] = ta.rsi(df.close, length=14) / 100.0
    df["atr_14"] = ta.atr(df.high, df.low, df.close, length=14)
    df["atr_pct"] = df.atr_14 / df.close
    df["roc_10"] = df.close.pct_change(10) * 100.0
    df["hour_of_day"] = df.timestamp.dt.hour / 24.0
    df["day_of_week"] = df.timestamp.dt.dayofweek / 7.0
    macd, stoch, bb = ta.macd(df.close, fast=12, slow=26, signal=9), ta.stoch(df.high, df.low, df.close, k=14, d=3), ta.bbands(df.close, length=20, std=2)
    if macd is None or stoch is None or bb is None: raise ValueError("Not enough history for indicators")
    df["macd_hist"] = macd.iloc[:, 1]
    df["stoch_k"] = stoch.iloc[:, 0] / 100.0
    df["bb_percent_b"] = bb.iloc[:, 4]
    rng = df.high - df.low + 1e-8
    df["body_ratio"] = (df.close - df.open).abs() / rng
    df["upper_wick_ratio"] = np.where(df.close >= df.open, df.high - df.close, df.high - df.open) / rng
    df["lower_wick_ratio"] = np.where(df.close >= df.open, df.open - df.low, df.close - df.low) / rng
    df["close_position"] = (df.close - df.low) / rng
    for col in ("open", "high", "low", "close"): df[f"{col}_pct"] = df[col].pct_change()
    return df


def load(csv: Path, include_assets=True):
    df = pd.read_csv(csv).rename(columns={"max": "high", "min": "low"})
    needed = {"asset", "timestamp", "open", "high", "low", "close"}
    if missing := needed - set(df): raise ValueError(f"Missing CSV columns: {sorted(missing)}")
    df.timestamp = timestamps(df.timestamp)
    for col in ("open", "high", "low", "close"): df[col] = pd.to_numeric(df[col], errors="coerce")
    if df[["open", "high", "low", "close"]].isna().any().any(): raise ValueError("Non-numeric OHLC value")
    df = df.sort_values(["asset", "timestamp"]).drop_duplicates(["asset", "timestamp"]).reset_index(drop=True)
    asset_cols = [f"asset_{name}" for name in sorted(df.asset.unique())] if include_assets else []
    for col in asset_cols: df[col] = (df.asset == col.removeprefix("asset_")).astype("float32")
    cols = SCALE + BASE + asset_cols
    raw, prepared = {}, {}
    for asset, part in df.groupby("asset", sort=True):
        raw[asset] = part.reset_index(drop=True).copy()
        p = raw[asset].copy(); next_close = p.close.shift(-1)
        p["target"] = np.where(next_close.notna(), (next_close > p.close).astype("float32"), np.nan)
        prepared[asset] = features(p).replace([np.inf, -np.inf], np.nan).dropna(subset=cols + ["target"]).reset_index(drop=True)
    return raw, prepared, cols


def windows(part, cols):
    from numpy.lib.stride_tricks import sliding_window_view
    if len(part) <= SEQ: raise ValueError("split too short")
    values = part[cols].to_numpy("float32", copy=True); labels = part.target.to_numpy("float32", copy=True)
    win = np.moveaxis(sliding_window_view(values, window_shape=SEQ, axis=0), -1, 1)
    x, y = np.ascontiguousarray(win[:-1]), labels[SEQ - 1:-1].copy()
    assert len(x) == len(y)
    return x, y


def datasets(prepared, cols, embargo=0):
    xp, yp, ap = {k: [] for k in ("train", "val", "test")}, {k: [] for k in ("train", "val", "test")}, {k: [] for k in ("train", "val", "test")}
    for asset, group in prepared.items():
        n, a, b = len(group), int(len(group) * .70), int(len(group) * .85)
        parts = {"train": group.iloc[:a-embargo], "val": group.iloc[a+embargo:b-embargo], "test": group.iloc[b+embargo:]}
        for name, part in parts.items():
            x, y = windows(part, cols); xp[name].append(x); yp[name].append(y); ap[name].append(np.full(len(y), asset, object))
    return ({k: np.vstack(v) for k, v in xp.items()}, {k: np.concatenate(v) for k, v in yp.items()}, {k: np.concatenate(v) for k, v in ap.items()})


def model_fit(x, y, epochs, shuffle=False, train_assets=None):
    import torch
    import torch.nn as nn
    from sklearn.preprocessing import RobustScaler
    from torch.utils.data import DataLoader, Dataset
    class DS(Dataset):
        def __init__(self, a, b): self.a, self.b = torch.from_numpy(a), torch.from_numpy(b).unsqueeze(1)
        def __len__(self): return len(self.a)
        def __getitem__(self, i): return self.a[i], self.b[i]
    class LSTM(nn.Module):
        def __init__(self, size):
            super().__init__(); self.l = nn.LSTM(size, 64, 2, batch_first=True, dropout=.1); self.f1 = nn.Linear(64, 32); self.d = nn.Dropout(.1); self.f2 = nn.Linear(32, 1)
        def forward(self, z):
            z, _ = self.l(z); return self.f2(self.d(torch.relu(self.f1(z[:, -1]))))
    seed(); device = torch.device("cuda" if torch.cuda.is_available() else "cpu"); pin = device.type == "cuda"
    scaler = RobustScaler(); scaler.fit(x["train"][:, :, :len(SCALE)].reshape(-1, len(SCALE)))
    for name in x:
        z = scaler.transform(x[name][:, :, :len(SCALE)].reshape(-1, len(SCALE)))
        x[name][:, :, :len(SCALE)] = z.reshape(x[name].shape[0], x[name].shape[1], len(SCALE))
    train_y = y["train"].copy()
    if shuffle:
        rng = np.random.default_rng(42)
        for asset in np.unique(train_assets):
            idx = np.flatnonzero(train_assets == asset); train_y[idx] = train_y[rng.permutation(idx)]
        print("NULL TEST: labels shuffled within each asset.")
    loaders = {"train": DataLoader(DS(x["train"], train_y), 1024, True, pin_memory=pin), "val": DataLoader(DS(x["val"], y["val"]), 1024, False, pin_memory=pin), "test": DataLoader(DS(x["test"], y["test"]), 1024, False, pin_memory=pin)}
    net, loss_fn = LSTM(x["train"].shape[2]).to(device), nn.BCEWithLogitsLoss(); opt = torch.optim.AdamW(net.parameters(), lr=5e-4, weight_decay=1e-4)
    best, weights, stale, patience = float("inf"), None, 0, min(20, max(5, epochs // 3))
    for epoch in range(epochs):
        net.train()
        for a, b in loaders["train"]:
            a, b = a.to(device).clone(), b.to(device); a[:, :, :len(SCALE)] += torch.randn_like(a[:, :, :len(SCALE)]) * .005
            opt.zero_grad(set_to_none=True); loss_fn(net(a), b).backward(); torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0); opt.step()
        net.eval(); total = count = 0
        with torch.no_grad():
            for a, b in loaders["val"]:
                b = b.to(device); total += loss_fn(net(a.to(device)), b).item() * len(b); count += len(b)
        value = total / count; print(f"Epoch {epoch:03d} | validation loss: {value:.5f}")
        if value < best: best, weights, stale = value, copy.deepcopy(net.state_dict()), 0
        else:
            stale += 1
            if stale >= patience: break
    net.load_state_dict(weights); probs, targets = [], []; net.eval()
    with torch.no_grad():
        for a, b in loaders["test"]: probs.append(torch.sigmoid(net(a.to(device))).cpu().numpy().ravel()); targets.append(b.numpy().ravel())
    return np.concatenate(probs), np.concatenate(targets)


def causality(csv, samples):
    raw, _, _ = load(csv, False); diffs = []
    for asset, df in raw.items():
        full = features(df); rows = np.unique(np.linspace(200, len(df)-1, samples, dtype=int))
        for row in rows:
            prefix = features(df.iloc[:row+1]); a, b = full.iloc[row][SCALE+BASE].to_numpy(float), prefix.iloc[-1][SCALE+BASE].to_numpy(float)
            valid = np.isfinite(a) & np.isfinite(b)
            if valid.any(): diffs.append(float(np.max(np.abs(a[valid]-b[valid]))))
    return {"check":"causality", "samples":len(diffs), "max_abs_difference":max(diffs, default=float("inf")), "passed":bool(diffs) and max(diffs) <= 1e-6}


def retrain(csv, mode, epochs, embargo):
    from sklearn.metrics import accuracy_score, roc_auc_score
    _, prepared, cols = load(csv, True); x, y, assets = datasets(prepared, cols, embargo if mode == "embargo" else 0)
    prob, target = model_fit(x, y, epochs, shuffle=mode == "label-shuffle", train_assets=assets["train"])
    auc, acc = float(roc_auc_score(target, prob)), float(accuracy_score(target, prob >= .5))
    return {"check":mode, "epochs":epochs, "embargo_rows":embargo if mode == "embargo" else 0, "test_auc":auc, "test_accuracy":acc, "passed":(.45 <= auc <= .55) if mode == "label-shuffle" else True}


def parity(csv, artifact_dir, samples):
    import onnxruntime as ort
    folder = Path(artifact_dir); meta = pickle.load(open(folder / "lstm_metadata.pkl", "rb")); scaler = joblib.load(folder / "lstm_scaler.pkl")
    raw, prepared, _ = load(csv, bool(meta.get("asset_features"))); cols, asset_cols = meta["features"], meta.get("asset_features", [])
    session = ort.InferenceSession(str(folder / "deep_lstm_v1.onnx"), providers=["CPUExecutionProvider"]); name = session.get_inputs()[0].name; feature_diff=[]; output_diff=[]
    for asset, source in raw.items():
        for end in np.unique(np.linspace(max(150, int(len(source)*.85)), len(source)-1, samples, dtype=int)):
            hist = source.iloc[max(0,end-149):end+1].copy(); live = features(hist)
            for col in asset_cols: live[col] = float(col == f"asset_{asset}")
            stamp = source.iloc[end]["timestamp"]; trained = prepared[asset].loc[prepared[asset].timestamp <= stamp].tail(SEQ); live = live[cols].replace([np.inf,-np.inf],np.nan).dropna().tail(SEQ)
            if len(trained) != SEQ or len(live) != SEQ: continue
            a, b = trained[cols].to_numpy("float32"), live.to_numpy("float32"); feature_diff.append(float(np.max(np.abs(a-b))))
            idx = int(meta["scale_idx"])
            for z in (a,b): z[:,:idx] = scaler.transform(z[:,:idx])
            output_diff.append(abs(float(session.run(None,{name:a[None]})[0].ravel()[0])-float(session.run(None,{name:b[None]})[0].ravel()[0])))
    return {"check":"parity", "samples":len(feature_diff), "max_feature_difference":max(feature_diff,default=float("inf")), "max_onnx_logit_difference":max(output_diff,default=float("inf")), "passed":bool(output_diff) and max(output_diff)<1e-3}


def lower_bound(wins, total):
    if not total: return 0.0
    p, z = wins/total, 1.96; return float((p+z*z/(2*total)-z*np.sqrt((p*(1-p)+z*z/(4*total))/total))/(1+z*z/total))


def forward(log):
    rows = json.load(open(log, encoding="utf-8")); rows=[r for r in rows if r.get("result") in {"win","lose"} and str(r.get("result_method","")).lower()=="api" and "ml_lstm" in (str(r.get("strategy_used",""))+str(r.get("winning_strategy",""))).lower()]
    wins=sum(r["result"]=="win" for r in rows); lower=lower_bound(wins,len(rows)); breakeven=1/(1+PAYOUT)
    return {"check":"forward", "verified_lstm_trades":len(rows), "wins":wins, "win_rate":wins/len(rows) if rows else 0, "lower_win_rate":lower, "breakeven":breakeven, "passed":len(rows)>=300 and lower>breakeven}


def main():
    p=argparse.ArgumentParser(); p.add_argument("--check",choices=["causality","label-shuffle","embargo","parity","forward"],required=True); p.add_argument("--data-file",type=Path,default=Path("candles_export.csv")); p.add_argument("--artifact-dir",default="lstm_temporal_v2_artifacts"); p.add_argument("--trade-log",type=Path,default=Path("trade_log.json")); p.add_argument("--epochs",type=int,default=15); p.add_argument("--embargo",type=int,default=SEQ); p.add_argument("--samples",type=int,default=5); p.add_argument("--output",type=Path,default=Path("audit_result.json")); a=p.parse_args()
    result = causality(a.data_file,a.samples) if a.check=="causality" else parity(a.data_file,a.artifact_dir,a.samples) if a.check=="parity" else forward(a.trade_log) if a.check=="forward" else retrain(a.data_file,a.check,a.epochs,a.embargo)
    print(json.dumps(result,indent=2)); a.output.write_text(json.dumps(result,indent=2),encoding="utf-8")

if __name__ == "__main__": main()
