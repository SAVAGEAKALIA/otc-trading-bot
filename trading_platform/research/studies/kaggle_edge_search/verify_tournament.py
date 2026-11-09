"""Re-score the round-2 tournament: recompute pooled results from oos_predictions.parquet and
re-run every tabular ONNX model on week 5.

    python verify_tournament.py <kaggle_edge_search dir> <kaggle output dir> <otc_matrix.parquet>
"""
import json, sys, numpy as np, pandas as pd
sys.path.insert(0, sys.argv[1])
import family_tournament as ft
from train_edge_search import onnx_predict, bonferroni_z
R = sys.argv[2]
res = {r["family"]: r for r in json.load(open(f"{R}/tournament_results.json"))["results"]}
oos = pd.read_parquet(f"{R}/oos_predictions.parquet")
z = bonferroni_z(len(ft.FAMILIES)); ok = True
for fam, r in res.items():
    weeks = []
    for w, g in oos.groupby("week"):
        p = g[f"p_{fam}"].to_numpy(); y = g["y"].to_numpy()
        weeks.append({"p": p, "y": y, "day": g["target_start_ms"].to_numpy() // ft.DAY_MS, "conf": np.abs(p - .5), "win": (p > .5) == (y == 1)})
    mine = ft.pooled_score(weeks, z)
    same = mine["pooled_trades"] == r["pooled_trades"] and abs(mine["pooled_win_rate"] - r["pooled_win_rate"]) < 1e-12
    ok &= same
    print(f"{fam:24s} recomputed trades={mine['pooled_trades']:,} wr={mine['pooled_win_rate']:.4f} -> {'MATCH' if same else 'MISMATCH'}")
feats = json.load(open(f"{R}/feature_order.json"))
m = pd.read_parquet(sys.argv[3], columns=[*feats, "asset", "target_start_ms", "y"], filters=[("target_start_ms", ">=", ft.WEEK_STARTS[-1]), ("tf_sec", "==", 120)])
m = m[m.target_start_ms < ft.WEEK_STARTS[-1] + 7 * ft.DAY_MS]
w5 = oos[oos.week == 5].merge(m, on=["asset", "target_start_ms", "y"], how="inner")
print("week-5 rows joined:", len(w5), "of", (oos.week == 5).sum())
for fam in ("logistic", "lightgbm", "lightgbm_rolling14", "xgboost", "mlp", "gru", "tcn"):
    d = np.max(np.abs(onnx_predict(f"{R}/models/{fam}.onnx", w5[feats].to_numpy(np.float32)) - w5[f"p_{fam}"].to_numpy()))
    ok &= d <= 1e-4; print(f"  onnx {fam:20s} max|diff| vs kaggle = {d:.2e}")
print("VERIFIED" if ok else "VERIFICATION FAILED")
