"""Zero-shot time-series foundation model (Amazon Chronos-Bolt) on OTC closes.

No training on OTC data: the model sees the last CONTEXT closes of one asset and forecasts the
median of the next HORIZON bars. Prediction = sign(median forecast - last close). Scored on a fixed
random sample of lab-final decisions (same final window as run_lab), seed fixed.

    .venv-lab/bin/python -m services.otc_quant_lab.foundation --sample 20000
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from . import data, features
from .features import DOWN, TIE, UP
from .metrics import auc, trade_summary
from .walkforward import in_days, lab_splits

CONTEXT = 128
MODEL = "amazon/chronos-bolt-small"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=20000)
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument("--out", default="/home/saviour/otc-quant-lab-artifacts/runs/foundation.json")
    args = parser.parse_args()
    import torch
    from chronos import BaseChronosPipeline

    torch.set_num_threads(3)
    bars = data.load_historical(120)
    frame = features.build(bars, 120, (args.horizon,))
    _, final = lab_splits(frame[frame.valid].day.to_numpy())
    pos = frame.pos.to_numpy()
    label = frame[f"y{args.horizon}"].to_numpy()
    eligible = np.flatnonzero(in_days(frame.day.to_numpy(), final.test) & (pos >= CONTEXT)
                              & ((label == UP) | (label == DOWN) | (label == TIE)))
    rng = np.random.default_rng(20261109)
    rows = np.sort(rng.choice(eligible, size=min(args.sample, len(eligible)), replace=False))
    close = bars.sort_values(["asset", "t"]).c.to_numpy()  # same row order as frame (asset, t)
    assert len(close) == len(frame)
    pipe = BaseChronosPipeline.from_pretrained(MODEL, device_map="cpu", torch_dtype=torch.float32)
    preds = []
    for start in range(0, len(rows), 256):
        batch = rows[start:start + 256]
        ctx = torch.tensor(np.stack([close[r - CONTEXT + 1:r + 1] for r in batch]), dtype=torch.float32)
        q, _ = pipe.predict_quantiles(ctx, prediction_length=args.horizon, quantile_levels=[0.1, 0.5, 0.9])
        preds.append(q[:, -1, :].numpy())
    q = np.concatenate(preds)
    last = close[rows]
    score = (q[:, 1] - last) / np.maximum(q[:, 2] - q[:, 0], 1e-12)  # signed, scale-free
    y = label[rows]
    up = score > 0
    outcome = np.where(y == TIE, -1, np.where((y == UP) == up, 1, 0))
    known = y != TIE
    top = np.abs(score) >= np.quantile(np.abs(score), 0.9)
    result = {"model": MODEL, "context": CONTEXT, "horizon_bars": args.horizon, "sample": int(len(rows)),
              "auc": auc((y[known] == UP).astype(int), score[known]),
              "flat_forecast_share": float((q[:, 1] == last).mean()),
              "all": trade_summary(outcome, frame.day.to_numpy()[rows]),
              "top10pct_confidence": trade_summary(outcome[top], frame.day.to_numpy()[rows][top])}
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2, default=float)
    print(json.dumps(result, indent=2, default=float))


if __name__ == "__main__":
    main()
