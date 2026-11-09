# Receipt-age admission regression

Failure: the original loader rejected negative ages but admitted a positive age larger than the decision timestamp. That implies a receipt before Unix epoch and could feed implausible values into preprocessing. Finite checks alone do not catch it.

1. Preserve the minimal full-schema CSV with age equal to decision plus one.
2. Preserve the registered manifest and exact CSV digest.
3. Require integer age milliseconds and a nonnegative implied receipt.
4. Enforce the quote, mood and payout age caps frozen in the export registration.
5. Keep valid boundary values admitted; missing optional mood remains missing.
6. Reject the malformed dataset before preprocessing or model fitting.
7. Retain a deterministic admission regression in `tests/test_training.py`.
8. In the periodic eval, mutate the corrected guard back to positive-only validation and require that mutant to admit the bad CSV.
9. Store BLOCKED status, error type and measured phase progress on failure.
10. Run the entire synthetic edge/null and saved-inference eval before publishing a training package. Do not turn fixture performance into a market claim.

Failure: the prior output guard only recognized `.git` metadata and allowed model output inside a bare repository. The corrected guard also recognizes bare repository HEAD, objects and refs before creating the output directory. Its gate pairs rejection with successful output in an ordinary external directory.

Failure: rejecting JSON `NaN` and `Infinity` literals did not reject legal exponent syntax such as `1e10000`. Python’s default float parser converted that finite-looking JSON number into infinity, including inside metadata arrays, and the old loader admitted the whole dataset before serialization failed after fitting. `strict_json` now applies a finite `parse_float` callback to every numeric token. Preserve the nested positive and negative overflow gates, require each corrupted full-size manifest to block before fitting, and require the old-parser mutant to admit that same input. Decimal strings remain strings; finite JSON numbers retain their existing representation.

## Observer receipt-boundary admission regression

Failure: aggregating source receipt bounds before checking each source admitted a boolean start and a reversed mood interval hidden by valid quote bounds. The exporter could allocate a plausible grid from malformed metadata.

1. Preserve the boolean-first and masked-reversed-source repros.
2. Require the registered receiver clock, product, mapping and asset universe before payload reads.
3. Require exactly the quote, mood and payout bound entries and their source-table inventories.
4. Require exactly the two registered endpoint fields for every source.
5. Require nonnegative actual integer row census values, excluding booleans.
6. Allow paired null endpoints only for a zero-row source; reject mixed null endpoints.
7. Check each nonempty interval for integer endpoints excluding booleans, nonnegative ordered values and the frozen historical end before aggregation or grid allocation.
8. Keep valid grids, zero-row sources and completely empty boundaries covered by gate tests.
9. Run the seeded 120-case corrupted-boundary eval and execute the prior aggregation-first body; require the actual regression tests to reject that mutant and retain its measured false-admission rows.
10. Compare every current opportunity ID, asset, decision and expiry with the saved matrix and preserve the original executed-source provenance. Do not rerun or rewrite valid artifacts to disguise a metadata-only repair.
