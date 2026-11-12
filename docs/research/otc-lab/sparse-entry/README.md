# Sparse-entry research: evidence files

Provenance for [2026-11-12-sparse-entry-research.md](../2026-11-12-sparse-entry-research.md). Every number in that report that comes from the owner's data is produced by a script here. All scripts read **counts and design quantities only**: no trade outcome (win or loss) is read, so none of the eight hypotheses has been looked at yet.

| File | What it produces | Used for |
|---|---|---|
| `count_trigger_frequencies.py` | Event counts for every archive trigger and the raw live payout / quote-stall counts (`trigger-frequencies.md`) | Section 5.1 frequencies, source [8] |
| `count_payout_steps_asset_level.py` | Asset-level payout step events (either product, merged within 300 s), mood availability and band, power per block | H1 / H6 rows, sections 5.1 and 5.2 |
| `count_crowd_extreme.py` | Mood-sample crowd-extreme counts and degeneracy | Section 5.4 (crowd extremes dropped), source [30] |
| `verify_report_numbers.py` | Section 5.2 power table, Clopper-Pearson pass counts, tie-as-loss break-even, payout spacing, spread values | Sections 4.4 and 5.2, sources [6] and [20] |
| `sample-size-table.md` | Owner's sample-size engine output (`services/otc_quant_lab/risk.trades_needed`) | Source [6] |
| `*.out.txt` | Saved output of each script run on 2026-11-12 | Audit trail |

Run from the repo root with the lab venv, for example:

```bash
.venv-lab/bin/python docs/research/otc-lab/sparse-entry/verify_report_numbers.py
```

The scripts read `data/ml/market_context.sqlite` read-only and the 2-minute archive through `services/otc_quant_lab/data.py`. `count_trigger_frequencies.py` loads the full archive and takes a few minutes; the others run in seconds.
