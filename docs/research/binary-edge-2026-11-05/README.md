# Binary research evidence, 2026-11-05

This read-only bundle preserves the plan's numerical evidence and source counterexamples. It changes no runtime code and makes no trading-edge claim. Python's standard library runs the source probes and gate tests. The optional raw parquet audit also needs pandas and a parquet reader, installed in the original repository venv.

From the repository root:

```bash
python3 -m unittest discover -s docs/research/binary-edge-2026-11-05 -p 'test_evidence.py' -v
python3 docs/research/binary-edge-2026-11-05/evidence.py --repo . --output /tmp/binary-edge-plan/evidence.json
python3 docs/research/binary-edge-2026-11-05/eval_evidence.py --repo . --output /tmp/binary-edge-plan/eval-evidence.json
```

Optional independent archived arithmetic verification using the installed venv:

```bash
/home/saviour/PycharmProjects/I2/IQoption/venv/bin/python docs/research/binary-edge-2026-11-05/evidence.py --repo . --archive-root /home/saviour/PycharmProjects/I2/IQoption/data/archive/otc-binary-2026-10-30/research --output /tmp/binary-edge-plan/evidence-with-archive.json
```

`--repo` accepts any checkout with the current edge-audit source and archived tag. Source probes record exact Git commits, paths and source SHA-256. Raw checks record file hashes. Missing reports or an omitted archive root return `NOT_CHECKED`; parquet checking has a separate status so unavailable data never becomes a claimed pass.

The probes extract selected functions from actual Git source with AST, avoiding runtime imports. They reproduce the current helper accepting a 60% win ledger that loses 7% per stake because winning and losing payouts differ. They reproduce the archived expiry helper choosing 91 versus 151 seconds from identical supplied time when local wall time shifts two seconds. The deterministic eval checks neighboring payout correlations and three adjacent cutoff seconds with three clock offsets; all checks must pass. Tests intentionally preserve these findings. A future runtime fix must update expectations and pin the historical counterexample source rather than silently erase it.

The payout table assumes full-stake losses, no ties and no fees. Sample sizes are educational normal approximations for one fixed independent Bernoulli test, fixed 0.85 payout, one-sided alpha 0.05 and power 0.80. They exclude dependence, multiple trials, adaptive selection, ties, costs and variable payout. They are not a forward promotion sample budget. Actual confirmation needs the separately frozen time-block PnL protocol.

The archive audit verifies saved candle-row accounting against JSON, including variable winning payouts. It does not validate broker accepted strike, exact expiry, settlement, execution latency or causal feature provenance. No raw data or binary artifacts belong in Git; generated reports stay under `/tmp/binary-edge-plan/`.
