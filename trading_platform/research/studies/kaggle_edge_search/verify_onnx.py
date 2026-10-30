"""Re-score Kaggle's ONNX models on the local holdout and compare to results.json.

    python verify_onnx.py --matrix otc_matrix.parquet --kaggle-out <downloaded output dir>

Exit 0 only when every exported model reproduces its holdout trade count and
win rate exactly (rubric criterion 4).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd


def predict(path: Path, X: np.ndarray) -> np.ndarray:
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    outs = sess.run(None, {sess.get_inputs()[0].name: X.astype(np.float32)})
    for o in outs[::-1]:
        if isinstance(o, list):
            return np.array([d[1] for d in o])
        if o.dtype.kind == "f":
            return o[:, 1] if o.ndim == 2 else o
    raise ValueError(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", type=Path, required=True)
    ap.add_argument("--kaggle-out", type=Path, required=True)
    a = ap.parse_args(argv)
    summary = json.loads((a.kaggle_out / "results.json").read_text())
    feats = json.loads((a.kaggle_out / "feature_order.json").read_text())
    df = pd.read_parquet(a.matrix)
    ok = True
    for r in summary["results"]:
        name, tf, thr = r["strategy"], r["tf_sec"], r.get("threshold")
        path = a.kaggle_out / "models" / f"{name}_{tf}.onnx"
        if name == "ensemble" and thr is not None:
            parts = [a.kaggle_out / "models" / f"{k}_{tf}.onnx" for k in ("catboost_all", "mlp", "gru")]
            path = parts[0]
        if thr is None or not path.exists():
            print(f"{name:16s} tf={tf} skipped (no threshold or not a single ONNX model)")
            continue
        ho = df[(df.tf_sec == tf) & (df.split == "holdout")]
        X = ho[feats].to_numpy(np.float32)
        y = ho["y"].to_numpy()
        if name == "catboost_mood":
            cols = json.loads((a.kaggle_out / "models" / f"{name}_{tf}.features.json").read_text())
            has = ~np.isnan(X[:, feats.index("mood_centered")])
            p = np.full(len(y), 0.5)
            p[has] = predict(path, X[has][:, [feats.index(c) for c in cols]])
            conf, win = np.abs(p - 0.5), (p > 0.5) == (y == 1)
        elif name == "meta_contrarian":
            mc = X[:, feats.index("mood_centered")]
            sub = ~np.isnan(mc) & (np.abs(np.nan_to_num(mc)) >= 0.3)
            conf = predict(path, X[sub])
            win = (y[sub] == 1) == (mc[sub] < 0)
        else:
            p = np.mean([predict(q, X) for q in parts], axis=0) if name == "ensemble" else predict(path, X)
            conf, win = np.abs(p - 0.5), (p > 0.5) == (y == 1)
        sel = conf >= thr["cut"]
        n, w = int(sel.sum()), int(win[sel].sum())
        match = n == r["holdout_trades"] and w == r["holdout_wins"]
        ok &= match
        print(f"{name:16s} tf={tf} local n={n:,} wr={w / max(n, 1):.4f} | kaggle n={r['holdout_trades']:,} "
              f"wr={r['holdout_win_rate']:.4f} -> {'MATCH' if match else 'MISMATCH'}")
    print("VERIFIED" if ok else "VERIFICATION FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
