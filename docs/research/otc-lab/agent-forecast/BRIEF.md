# Forecasting task: IQ Option OTC, 10-minute direction

There are 40 decision moments in `snapshots/`. `snapshots/index.json` lists them: id, the asset to call, and the decision time.

Each `snapshots/Sxx.csv` holds 2-minute candles for all 15 OTC pairs over the 12 hours up to and including the decision bar. Columns: asset, t (bar start, UTC seconds), o, h, l, c. The decision is made at the close of the last bar of the listed asset. Nothing after that moment exists anywhere in this folder.

For each moment, call the listed asset's close 10 minutes after the decision: **up**, **down** or **abstain**.
- An up or down call wins 0.86 per 1 staked if right and loses 1 if wrong.
- Break-even is 53.76%, so only call when your analysis gives you a real edge. Abstaining costs nothing.

Rules:
- Use only these snapshot files. Do not open any other file on this machine, do not search the web, and do not fetch market data.
- Use Python at `/home/saviour/PycharmProjects/I2/IQoption/.venv-lab/bin/python` (numpy, pandas, scipy), with scratch scripts only in your own folder.
- Treat every moment on its own merits, using your own analysis of that snapshot.

Write `predictions.json` in your folder as a list of objects:

```json
{"id": "S01", "call": "up|down|abstain", "confidence": 0.0-1.0, "reason": "one or two sentences"}
```

It needs one object per id, 40 in total.
