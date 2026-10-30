# OTC GitHub research, 2026-10-30

## Decision

Revalidate the existing IQ Option adapter behind a narrow, tested boundary; scikit-learn for null/logistic/gradient-boosting baselines; CatBoost as the first nonlinear challenger; `arch` for dependence-aware uncertainty. Build only the small broker-specific settlement/replay contract that generic backtesters do not supply. Defer full trading frameworks, reinforcement learning, language-model trade decisions, and large sequence models until simpler models demonstrate out-of-sample value. This is a recommendation from source inspection, not an observed profitable result.

## Method and evidence boundaries

Live unauthenticated GitHub API metadata, sampled recent issue/PR threads, primary README/source files and official documentation were inspected. Metadata is saved in `/tmp/otc-research/github-metadata.json`; issue samples in `/tmp/otc-research/github-issues.json`. `pushed_at` measures the last repository push, NOT necessarily the default-branch substantive code change. `open_issues_count` includes pull requests. Stars measure attention, not correctness or profit. No external bot was executed, no model weights were loaded, and no credentials were supplied to third-party repositories. Only selected code paths were inspected; this is not a full security audit. Issue samples are evidence of particular problems and responsiveness, not a complete response-time census. No independently reproducible, broker-settled OTC profitability evidence was found in the inspected examples; that does not prove none exists elsewhere.

## Repository inventory

Numbers below were returned by `https://api.github.com/repos/{owner}/{repo}` during this investigation. Null license metadata means unverified licensing, not permission to copy.

| Repository | Stars | Last push UTC | Open issues + PRs | License metadata |
|---|---:|---|---:|---|
| [iqoptionapi/iqoptionapi](https://github.com/iqoptionapi/iqoptionapi) | 276 | 2024-08-12T00:58:23Z | 55 | unverified |
| [Lu-Yi-Hsun/iqoptionapi](https://github.com/Lu-Yi-Hsun/iqoptionapi) | 391 | 2026-07-01T14:51:19Z | 230 | unverified |
| [victalejo/iqoptionapi](https://github.com/victalejo/iqoptionapi) | 2 | 2026-05-11T17:13:39Z | 1 | MIT |
| [ChipaDevTeam/BinaryOptionsTools-v2](https://github.com/ChipaDevTeam/BinaryOptionsTools-v2) | 137 | 2026-10-30T10:45:49Z | 1 | NOASSERTION |
| [microsoft/qlib](https://github.com/microsoft/qlib) | 49,830 | 2026-10-30T05:12:38Z | 511 | MIT |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 16,889 | 2026-10-25T13:49:47Z | 310 | MIT |
| [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | 9,164 | 2026-08-05T12:39:16Z | 103 | AGPL-3.0 |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 9,594 | 2026-10-28T19:18:42Z | 131 | NOASSERTION |
| [hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab) | 4,960 | 2023-10-02T03:05:19Z | 49 | NOASSERTION |
| [scikit-learn/scikit-learn](https://github.com/scikit-learn/scikit-learn) | 67,923 | 2026-10-29T23:49:06Z | 2161 | BSD-3-Clause |
| [catboost/catboost](https://github.com/catboost/catboost) | 9,183 | 2026-10-30T02:38:24Z | 747 | Apache-2.0 |
| [lightgbm-org/LightGBM](https://github.com/lightgbm-org/LightGBM) | 18,939 | 2026-10-29T20:29:33Z | 530 | MIT |
| [optuna/optuna](https://github.com/optuna/optuna) | 14,994 | 2026-10-30T08:28:36Z | 24 | MIT |
| [Nixtla/neuralforecast](https://github.com/Nixtla/neuralforecast) | 4,301 | 2026-10-27T14:47:13Z | 10 | Apache-2.0 |
| [sktime/sktime](https://github.com/sktime/sktime) | 10,081 | 2026-10-29T21:22:03Z | 2735 | BSD-3-Clause |
| [skfolio/skfolio](https://github.com/skfolio/skfolio) | 2,562 | 2026-10-29T18:45:08Z | 34 | BSD-3-Clause |
| [rishindra2005/Binary-bot](https://github.com/rishindra2005/Binary-bot) | 1 | 2025-05-17T09:11:46Z | 1 | unverified |
| [ioannisevgeniou/binary-options-research](https://github.com/ioannisevgeniou/binary-options-research) | 0 | 2024-08-04T10:46:57Z | 0 | unverified |
| [alexisselorm/binary_options_bot](https://github.com/alexisselorm/binary_options_bot) | 16 | 2026-07-27T16:59:44Z | 1 | MIT |
| [landtml/quantowl](https://github.com/landtml/quantowl) | 3 | 2026-10-29T00:55:35Z | 0 | MIT |
| [baobach/mlfinpy](https://github.com/baobach/mlfinpy) | 91 | 2026-10-11T15:24:12Z | 4 | MIT |
| [bashtage/arch](https://github.com/bashtage/arch) | 1,654 | 2026-10-30T08:35:35Z | 37 | NOASSERTION |
| [PriorLabs/TabPFN](https://github.com/PriorLabs/TabPFN) | 8,330 | 2026-10-30T11:29:26Z | 21 | Apache-2.0 |
| [LeoGrin/tabular-benchmark](https://github.com/LeoGrin/tabular-benchmark) | 511 | 2024-08-18T19:38:07Z | 7 | unverified |

## Broker adapter shortlist

1. **Revalidate the existing adapter, pin its source revision, test it against captured protocol fixtures.** [iqoptionapi/iqoptionapi](https://github.com/iqoptionapi/iqoptionapi) is unofficial and old. Its README targets Python 3.7 and websocket-client 0.56. This is a compatibility burden, not a reason to replace working ingestion blindly. User reports include [order/pair retrieval failures #102](https://github.com/iqoptionapi/iqoptionapi/issues/102), 23 comments in the sampled data, and [timeout #112](https://github.com/iqoptionapi/iqoptionapi/issues/112), still open. The [websocket upgrade/test PR #113](https://github.com/iqoptionapi/iqoptionapi/pull/113) and [reconnection PR #81](https://github.com/iqoptionapi/iqoptionapi/pull/81) are open. These are concrete contracts to test: reconnect, subscription restoration, bounded waits, request identity, forming versus closed candles, settlement retrieval.
2. **Lu-Yi-Hsun is protocol reference material, not an established upgrade.** [Repository](https://github.com/Lu-Yi-Hsun/iqoptionapi), [API not working #369](https://github.com/Lu-Yi-Hsun/iqoptionapi/issues/369). A 2026 last push does not resolve its open operational issues or prove maintenance quality.
3. **victalejo is a small experiment to inspect, not adopt wholesale.** [Repository](https://github.com/victalejo/iqoptionapi) offers async read-only data collection, exception types and tests, with MIT metadata. However, only 2 stars and three commits were visible; [issue #1](https://github.com/victalejo/iqoptionapi/issues/1) had no comments. Test useful pieces in isolation before migration. Its own README says protocol changes can break it.
4. **Reject ChipaDevTeam as an IQ Option replacement today.** [README supported platforms](https://github.com/ChipaDevTeam/BinaryOptionsTools-v2#supported-platforms) lists IQ Option as roadmap, despite iqoption tags. It is actively maintained for other brokers: [stream timeout #147](https://github.com/ChipaDevTeam/BinaryOptionsTools-v2/issues/147) was closed on the same date it opened; [multi-asset stream #141](https://github.com/ChipaDevTeam/BinaryOptionsTools-v2/issues/141) closed after user discussion. Closure does not prove resolution. Its personal-use/custom license requires review. Borrow the concept of explicit closed/forming candle separation; do not route IQ Option through an unsupported backend.

## What the ready-made bot examples actually establish

- [rishindra2005/Binary-bot](https://github.com/rishindra2005/Binary-bot) advertises about 60% accuracy and martingale recovery. [Its OTC file](https://github.com/rishindra2005/Binary-bot/blob/main/iq_try_OTC.py) sets `goal = "EURUSD"`, reverses candle direction, doubles stake after losses inside a `while p<0` loop, and does not establish an out-of-sample net-profit experiment. The signal is not proof of OTC edge; the stake escalation adds ruin exposure. The visible support issue [#1](https://github.com/rishindra2005/Binary-bot/issues/1) has no response. Reject as a foundation.
- [alexisselorm/binary_options_bot](https://github.com/alexisselorm/binary_options_bot) combines many concerns and targets Deriv/external signals. Its [LangChain orchestration PR](https://github.com/alexisselorm/binary_options_bot/pull/1) is open. This supplies neither tested IQ Option settlement compatibility nor proof that an LLM improves OTC decisions. Do not inherit its breadth.
- [ioannisevgeniou/binary-options-research](https://github.com/ioannisevgeniou/binary-options-research) is research material with effectively no adoption signal in the API snapshot. Its existence is not a reason to train on another broker/market and infer IQ OTC transfer.

## Model and validation choice

**First choice: scikit-learn plus one CatBoost challenger.** scikit-learn supplies dummy classifiers, logistic regression, histogram gradient boosting, calibration diagnostics and time-series splitting. Recent issue/PR activity demonstrates active maintenance: [#35236](https://github.com/scikit-learn/scikit-learn/pull/35236) closed after discussion. CatBoost supplies a mature tree learner, categorical handling and GPU support. A recent performance issue [#3236](https://github.com/catboost/catboost/issues/3236) closed within the sampled period. These maintenance examples do not prove OTC efficacy.

**Second choice: LightGBM** ([canonical repository](https://github.com/lightgbm-org/LightGBM), the old Microsoft URL redirects). Prefer it if it is already working in the codebase or if measured training throughput beats CatBoost at equal validation quality. Do not maintain two near-identical production model stacks merely to collect libraries.

**Challengers after baselines:** [TabPFN](https://github.com/PriorLabs/TabPFN) is current, popular and worth a bounded, local-weight experiment on a frozen subset. Verify the particular checkpoint's license separately from Apache-licensed code, and pin model revision. [NeuralForecast](https://github.com/Nixtla/neuralforecast) is a useful sequence-model reference, but forecast-error improvement is not equivalent to executable binary-option expected value. Deep learning is an experiment, not the default destination. [The original tabular benchmark](https://github.com/LeoGrin/tabular-benchmark) supports testing strong tree baselines rather than assuming neural models win; its benchmark is not OTC evidence.

**GPU caveat:** [CatBoost's own documentation](https://catboost.ai/docs/en/features/training-on-gpu) explicitly states GPU training is non-deterministic due to floating-point summation order. Meet the deterministic requirement through immutable data/splits/configuration/artifact hashes and deterministic replay of frozen predictions; do not promise bit-for-bit identical GPU training. Record devices and driver/library versions and repeat seeds when comparing small gains. Use the fastest actually available free Kaggle device, measured on the intended workload, not an assumed GPU entitlement.

**Validation: existing scikit-learn first, targeted extensions only.** [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) supplies chronological folds and a sample-count `gap`, but comparable fold durations assume equally spaced samples. A multi-asset interleaved table needs shared timestamp boundaries; row-count gap alone can leak label windows across assets. For fixed expiry, purge every training sample whose label end reaches the test interval. Fit preprocessors/calibration on training or designated calibration data only. Use an untouched final chronological lockbox and subsequent live shadow outcomes.

**Uncertainty: `arch.bootstrap` before writing a bootstrap library.** [arch](https://github.com/bashtage/arch) has stationary/circular block bootstrap and multiple-comparison tools; [official examples](https://arch.readthedocs.io/en/stable/bootstrap/bootstrap_examples.html) explain why serial dependence invalidates naive independent resampling. Resample joint time blocks across assets, not each trade independently. Pick and record block assumptions before inspecting winner results. A confidence interval is conditional on that dependence model, not a guarantee.

**Purged-validation alternatives:** [baobach/mlfinpy](https://github.com/baobach/mlfinpy) is MIT and has the relevant financial-ML concepts, but much smaller adoption and an extra dependency surface. Use as reference/second choice after checking exact boundary behavior against synthetic overlapping-label cases. [mlfinlab](https://github.com/hudson-and-thames/mlfinlab) is NOT a free open-source default: [README licensing](https://github.com/hudson-and-thames/mlfinlab#licensing-options) is all rights reserved and commercial. [landtml/finlab-ml](https://github.com/landtml/finlab-ml) redirects to quantowl; only 3 stars in the API snapshot, so do not treat an attractive feature list as established evidence.

**Search budgeting:** [Optuna](https://github.com/optuna/optuna) is maintained and appropriate only after the validation contract is frozen. Record every attempted hypothesis, feature set and threshold, including failures. Fixed trial limits, nested time validation, and untouched final evaluation matter more than search sophistication. Optuna cannot protect a repeatedly consulted holdout by itself.

## Why not import a full framework?

[Qlib](https://github.com/microsoft/qlib) is a serious, active research platform, but its asset-return/portfolio abstraction is not the fixed stake, fixed expiry, asymmetric-payout contract here. Borrow its separation of data, model, backtest and experiment records. Do not adopt its full platform simply for orchestration. [FinRL](https://github.com/AI4Finance-Foundation/FinRL) adds reward design and policy-search degrees of freedom before there is a verified signal. Defer it. [backtesting.py](https://github.com/kernc/backtesting.py) and [vectorbt](https://github.com/polakowo/vectorbt) are useful conventional trading engines, but generic mark-to-market order P&L is not binary settlement P&L. A short dedicated settlement scorer with independent fixtures is the justified first-principles exception. Reuse NumPy/pandas; avoid building a general backtester. Licenses also need checking: backtesting.py AGPL, vectorbt custom metadata.

## Research reference and falsifiable gate

A recent primary study, [Machine Learning vs. Randomness (IDEAL 2025)](https://arxiv.org/abs/2511.15960), reports that tested models did not beat ZeroR on its EUR/USD 2021-2023 dataset. This is evidence to challenge optimism, not proof that broker-specific OTC is unlearnable. The project must falsify the null on its own executable outcomes.

Proposed evidence contract:

1. Broker source, asset, server/event/receive timestamps, payout quote available at decision time, decision time, actual or precisely simulated strike, expiry and settlement rule are explicit. Historical candles without payout/entry timing only support conditional research, not an executable profit claim.
2. Compare no-trade, majority class, momentum, reversal, logistic and one nonlinear model under the identical settlement contract and chronological splits. Every candidate can abstain; report coverage and amount at risk.
3. Main metric is flat-stake net return per opportunity and per accepted trade using observed payouts. Report trade counts, fold/time-block stability, drawdown, calibration and dependence-aware uncertainty. Accuracy alone is insufficient.
4. Negative controls include shuffled targets within valid blocks, deliberately future-leaking features that must be rejected, stale/duplicate/missing candles, delayed entries, unavailable payout, label overlap, tie settlement and failed-order accounting.
5. The lockbox may be evaluated once per registered research round. Failed candidates are retained in the ledger. Passing retrospective gates permits shadow collection, not an assertion of durable profit.
6. Freeze the deterministic candidate for prospective shadow testing. LLMs may propose hypotheses and summarize evidence; they cannot override trade limits, silently change thresholds, or access the lockbox to optimize prompts. Human-agent decisions require timestamped pre-outcome recording and an identical baseline comparison.

## Scope and remaining unknowns

This subtask did not inspect the project's server data, test its code, or verify Kaggle account limits. Those determine whether the recommended evaluation can actually run. Broad library metadata was inspected for 24 available repositories, with deeper primary-source inspection focused on broker adapters, examples and validation. Repo popularity is not evidence of an edge. No production changes or live trading actions were taken.
