# Per-case trading calls: IQ Option OTC

`snapshots/index.json` lists 400 cases: id, asset and decision time (UTC). For each case `Kxxx` you have:
- `snapshots/Kxxx_2min.csv`: 2-minute candles for all 15 pairs, the last 12 hours up to the decision;
- `snapshots/Kxxx_5min.csv`: 5-minute candles for all 15 pairs, the last 24 hours up to the decision.

Columns: asset, t (bar start, UTC seconds), o, h, l, c. The last bar of the listed asset closes exactly at the decision time. Nothing after the decision exists anywhere in this folder.

## Your job

For EACH case, study that chart on its own, the way a trader does. Look at the listed asset's recent candles and structure: trend, swings, support and resistance, ranges, momentum, candle patterns, volatility, and what the other pairs are doing at that moment. Then decide for that case:
- **call**: `buy` (price higher at expiry), `sell` (lower) or `abstain`;
- **horizon**: 2, 5 or 10 minutes, whichever fits the setup you see.

Payoff: a right call pays 0.84 per 1 staked (2 or 5 min) or 0.86 (10 min); a wrong call loses 1; an equal close refunds the stake. Break-even is 54.35% (2 and 5 min) and 53.76% (10 min).

Make a call wherever you see a setup in that chart. Abstain only when that chart truly shows nothing.

## Rules

- **One case at a time.** Do not build one rule and apply it to all cases, and do not run pooled backtests across the cases. Each call must come from that case's own chart. You may write code to compute indicators or print the candles for a case.
- Use only the files in `/tmp/agent-forecast3`. Do not open any other file on this machine, search the web, or fetch market data.
- Python: `/home/saviour/PycharmProjects/I2/IQoption/.venv-lab/bin/python` (numpy, pandas, scipy). Put scratch files only in your own folder.

## Output

Write `predictions.json` in your folder: a list of 400 objects, one per case.

```json
{"id": "K001", "call": "buy|sell|abstain", "horizon_min": 2|5|10, "confidence": 0.0-1.0,
 "reason": "two or three sentences naming what you saw in THIS chart (levels, pattern, trend)"}
```

For an abstain, `horizon_min` can be any of the three.
