# Causal OTC price dataset

`dataset.build_rows(observations, opportunities, config)` freezes every decision feature before joining any outcome. Inputs are strict versioned dictionaries. Unknown fields, nonfinite values, changed event identities and contradictory same-source timestamps fail the batch. Every valid opportunity remains resolved, unresolved or ineligible.

The dataset tournament selected the stricter of two independently built variants. Its receipt-batch ordering and fraction validation were repaired with tests. Finite Decimal arithmetic uses a fixed 34-digit half-even context. Mood values must be in `[0,1]`, payouts in `[0,2]`, and current payout zero makes an opportunity ineligible. Missing or stale payout never receives a default.

```bash
python3 -m unittest discover -s services/otc_research/tests -p test_dataset.py -q
python3 -m services.otc_research.evals.eval_dataset --output /tmp/otc-dataset-eval.json
python3 -m services.otc_research.export \
  --snapshot /tmp/otc-observations \
  --output /tmp/otc-matrix
```

`export` verifies the observer manifest and the exact observation/lineage bytes before building. It uses a fixed two-asset universe and UTC decision grid every 120 seconds, starting at the first recorded receipt rounded upward. All intervening grid rows remain, including collection gaps. Each hypothetical expiry is decision plus 120 seconds. Modeled entry is the next receipt within 2,000ms, with no assumed acceptance delay; this is a price proxy, not an accepted order.

Before reading payload files or allocating a grid, the observer boundary must declare exactly quote, mood and payout receipt bounds and the three registered source-table inventories. Each bounds object has exactly `first_receipt_ms` and `last_receipt_ms`. Nonempty sources require actual integer endpoints, excluding booleans, with `0 <= first <= last < 2026-08-21T00:00:00Z`. Both endpoints may be null only when that source's integer row census is zero. An entirely empty boundary yields no opportunities. Receiver UTC, the two assets and the registered product mapping are required; malformed source metadata fails even when another source would mask it in the aggregate minimum or maximum. This boundary check preserves the frozen experiment and does not change valid historical rows.

The fixed source priority uses `quote_samples`, `mood_samples`, and payout `commission-stream` before `init-snapshot`. Freshness caps are 5,000ms for received quotes, 60,000ms for mood and 600,000ms for payout. Lookback is 60,000ms. The market mood mean uses only same-clock, same-broker, same-product moods actually received before the decision. Future quotes, labels, dojis or asset membership cannot change it.

The explicit `last_received_before` terminal policy uses the last fresh receiver quote at or before the hypothetical expiry. Post-expiry quotes and interpolation are forbidden. Its terminal must be at or after modeled entry. A missing entry or terminal retains decision features as unresolved. Three-way labels are `up`, `down`, and `tie`; the registered payout scenario fully refunds ties. Other broker tie rules remain unverified.

Outputs:

- `matrix.csv` and `manifest.json`: canonical feature schema with hash-verified input bytes, provenance, explicit proxy evidence and `promotable=false`.
- `decision_lineage.jsonl`: every row, reason, feature event and modeled outcome event.
- `audit.json`: admitted/resolved/tie/gap counts, source quarantine counts, a matched legacy payout-availability comparison, and null actual-contract measurements with reasons.
- `availability_comparison.csv`: old bucket-based payout joins on exactly the same grid. Its future-receipt count describes that matched population, not an earlier published study.

Ineligible rows blank all matrix features and payout. Unresolved rows keep causal features and remain in selection denominators. The combined mood age is the oldest contributing own or market mood receipt. This lets the trainer validate every contributor with its single canonical age column.

The archived period has already been explored. A trained model's accuracy, proxy returns and calibration scores from it cannot support live deployment or a future-profit claim. Actual accepted practice contracts and new confirmation data are required for those claims. No model or raw database is committed to Git.

## 7 November 2026 archive admission

The completed fixed-scope export processed 1,226,158 archived rows into 396,352 canonical observations. It retained all 29,632 grid opportunities: 1,233 resolved labels, 3,348 unresolved labels, and 25,051 ineligible rows. Four resolved labels were ties.

Every resolved label is in the training partition. The registered early-stop, calibration, policy and diagnostic partitions each contain zero resolved labels, so the focused model comparison is blocked before fitting. The first failed requirement is 50 resolved unpurged early-stop rows. The required response is new sufficiently frequent received observations covering each chronological partition. Changing freshness caps, entry deadlines or split dates after inspecting this result would define a new experiment.

On the matched receiver-clock grid, 11,338 of 29,618 legacy bucket-based payout joins used a payout that arrived after the decision. The repaired dataset measured zero future payout joins and zero future feature references. These counts apply to the reconstructed grid and cannot be substituted for an earlier published study's population.

The completed source snapshot passed SQLite `quick_check`; its SHA-256 is `a524a524fcf5d5169a9f7e4e7fe01f8f0cd11eaa6354d25110c2795977e326b1`. The matrix manifest points to that exact snapshot hash. The original archive was opened read-only. All these measurements describe data admission, not profitable binary trading.
