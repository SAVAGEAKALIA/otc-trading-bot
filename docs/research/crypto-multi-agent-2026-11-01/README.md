# Multi-agent signal production and selection

Research date: 2026-11-01. User clarified that both signal production and signal selection are in scope. Status: research complete with independent review PASS; experiment remains proposed. No framework installed, model experiment run, performance reproduced, or trading permission changed.

## Decision

Test a small, bounded research team against deterministic signals and a single analyst. Specialists first work independently, then exchange source-backed challenges through a coordinator. A fixed rule selects or rejects proposals. Agents do not negotiate risk limits or place orders. Start with independent voting as the comparison that debate must beat. This is our engineering recommendation, not a measured crypto result.

For implementation references, TradingAgents is the closest debate architecture; WebCryptoAgent is the closest crypto-specific separation of slow research and fast risk. Neither is a drop-in match for this project's local-Claude-Code requirement. FinCon contributes a hierarchy and memory design, but its official implementation remains unavailable. Reuse existing repository contracts before adopting another orchestration runtime.

The measurable objective is incremental net performance at the same portfolio risk, with fewer unsupported decisions and an auditable explanation of changes. Agent count, agreement, eloquence and self-reported confidence are not objectives.

## Evidence that changes the design

Sources below were accessed on the research date. Paper results are authors' reports, not our replications. Paper architectures, released repositories and deployed products are separate claims.

| Source | Finding and evidence level | Consequence for this project |
|---|---|---|
| [TradingAgents, paper v7](https://arxiv.org/abs/2412.20138v7), [previous pinned source review](../crypto-ecosystem-2026-10-30/ai_analysis_bots.md) | Analysts feed bull/bear researchers, a trader and a risk discussion. Historical financial experiments report improvements. Existing source review found simulated execution and no verified local Claude Code provider at its pin. | Best debate reference, not proof of transferable crypto alpha. Reuse the role boundaries; do not inherit its portfolio authority. |
| [FinCon paper](https://arxiv.org/abs/2407.06567), [official repository](https://github.com/The-FinAI/FinCon) | Manager/analyst hierarchy with selectively propagated verbal feedback. Historical stock/portfolio experiments. Official README still says full code release is delayed by commercial data dependencies; visible root contains README and license. | Useful conceptual alternative to everyone talking to everyone. Do not label an unofficial reimplementation a reproduction of the original. |
| [WebCryptoAgent v2](https://arxiv.org/abs/2601.04687v2), [official repository](https://github.com/AIGeeksGroup/WebCryptoAgent) | Modality-specific agents consolidate evidence; slower reasoning is separated from fast risk response. Current repository supplies offline Python backtests, asks for model API keys and says fuller Node/news integration requires contacting authors. | Strong crypto architecture reference, incomplete public parity with the described full system. Existing API instructions conflict with our model-access constraint. No code run or source-level security audit here. |
| [Debate or Vote, v2](https://arxiv.org/abs/2508.17536v2) | Separates voting from discussion and finds simple ensembles strong alternatives; interventions can improve debate. Reasoning-task evidence, not trading returns. | Include independent voting and equal-compute self-review controls. Do not credit debate for gains supplied by extra samples. |
| [Voting or Consensus, v4](https://arxiv.org/abs/2502.19130v4) | Protocol effectiveness differs by task; additional discussion is not automatically beneficial. Reasoning/knowledge benchmarks, not financial validation. | Bound rounds and retain abstention. Do not infer that unanimity is reliable evidence. |
| [Market-Dependent Communication, v1](https://arxiv.org/html/2511.13614v1) | Authors compare five-agent structures in historical US-equity alpha generation. Benefits differ by universe; discussion-quality scores do not track returns. Limitations include a mostly bullish period and limited generalization. Appendix describes both GPT-4o-mini and GPU-hour infrastructure without establishing how those costs relate. | A useful hypothesis source, lower confidence as a deployment guide. Do not transfer its sector findings or headline returns to crypto. Runtime and cost accounting need clarification before reproduction. |
| [Test-Time Communication in Trading Agent Swarms, v1](https://arxiv.org/html/2610.37448v1) | Recent author prospective paper-account study covers seven US trading days, multiple model families and communication regimes. Some communicating groups increased common holdings. One group per model/regime, shared research models, bundled channel/framing incentives and initially absent scores limit causal comparisons. | Measure excess overlap relative to isolated agents. This short study cannot rank protocols for our strategy or establish durable alpha. This is paper-account evidence, not real-money settlement evidence. |
| [Poisoning Agentic Alpha, v2](https://arxiv.org/abs/2608.24069v2) | Authors test malicious source content and compromised roles across trading architectures. Voting protection is conditional; compromising the terminal decision role can bypass upstream deliberation. | Agent agreement is not a security boundary. Preserve source identities and put enforcement outside the language-model chain. |

The reviewed evidence does not establish that communicating agents produce better net crypto returns for this user. That is an evidence limit, not a finding that the approach cannot work. Prior broader [ecosystem research](../crypto-ecosystem-2026-10-30/README.md) remains relevant for RD-Agent, Vibe-Trading, Qlib and paper accounting; this report adds communication mechanisms rather than repeating the full repository survey.

## How agents would produce signals

Use separate hypotheses with explicit inputs, not several personas interpreting the same chart:

- Market-structure analyst: inspect code-computed trend, volatility, spread and liquidity features. Emit a directional proposal or abstention, with horizon and invalidation evidence. No invented indicator arithmetic.
- Carry analyst: inspect funding, basis, collateral and fee scenarios. Emit a paired carry proposal or rejection. A carry proposal is not a bullish vote on the coin.
- Event analyst: extract timestamped exchange notices, unlocks, incidents and relevant news. Distinguish original publication, ingestion and revision time. Return unknown when event data is unavailable.
- Independent critic: challenge evidence and assumptions after proposals are sealed. Request a source correction, identify contradictory facts or mark an unsupported claim. It cannot loosen a threshold.

These are possible roles, not all mandatory voters. In the first directional comparison the three voters are independent instances of the same analyst specification, each with the same complete evidence packet; specialist role diversification is a later separate ablation. The first controlled directional experiment uses a common candidate menu and action space. Carry remains a separate experiment with its own accounting. Missing order-book/news history in the current R1 daily dataset must be recorded as missing; do not simulate agents having it.

A useful disagreement: the price analyst sees upward momentum, the event analyst identifies a trading suspension notice, and the critic verifies the notice's timestamp and instrument. The result can be reject despite bullish votes. This is a hypothetical workflow example, not an observed trade.

## Communication and selection protocol

1. Coordinator freezes the data snapshot, decision time, candidate universe, model/prompt versions, budgets and deadline. Same snapshot for every arm.
2. Analysts submit independent first answers without seeing each other's proposals. Store originals before exposing peer messages.
3. In B, the critic sees all three sealed answers and the same frozen evidence packet. It emits one common candidate-specific challenge message, containing the cited conflicting claims, delivered identically to all three analysts. Each analyst revises once, seeing its own original answer and that message. The critic cannot fetch extra evidence. Allow one challenge and one response round. No unconstrained group chat or persistent shared scratchpad in the first experiment.
4. Preserve initial and revised answers. Revision must identify the evidence that changed it; textual persuasion alone is not a new source.
5. Deterministic validation rejects unsupported instruments, expired decisions, future-available sources, malformed numbers and unauthorized tool requests. No parsing a prose sentence into an order.
6. In the voting arm, three comparable directional analysts vote buy/flat/reduce on each frozen candidate. Two matching valid votes select that action; no majority, any missing voter, or a verified eligibility failure yields abstention for that decision. Do not shrink the denominator on timeouts. In the debate arm the identical rule applies to the revised answers.
7. Candidate ranking and sizing use the same frozen deterministic policy in every arm. First experiment uses equal capital caps across eligible candidates; no self-reported confidence weights. Correlated symbols still share portfolio exposure limits.
8. Save a research signal, including rejections and reasons. Future execution remains a separate authorization and service boundary.

“Flat” means no new directional exposure; “reduce” references an existing simulated holding. Define those states before evaluation. Equal votes are a deliberately simple baseline, not a claim that different specialists are equally accurate. Specialised event/risk checks are evidence filters, not extra votes that double-count a source. Accuracy-based weights may be a later registered variant trained only on past resolved outcomes.

Proposed boundary fields: schema_version, run_id, message_id, sender_role, parent_message_ids, candidate_id, venue, instrument, strategy_family, decision_time_utc, data_cutoff_utc, horizon_end_utc, expires_at_utc, action, evidence_ids, invalidation_conditions, uncertainty_reason, model_version and prompt_hash. Evidence records include source URL/artifact hash, publication time, observed/available time and revision ID. Every received message binds to one run and candidate. Reject duplicates, unknown senders and cross-run replays. These fields are a design contract, not an implemented schema.

Source text stays untrusted even if another agent repeats it. Count unique underlying sources, not citations copied between agents. A shared rumour repeated by three roles is one rumour. Model memory updates use only outcomes resolved by the next decision time; holdout outcomes never rewrite an earlier prompt.

## Protocol tournament proposed for a later authorized experiment

| Arm | Purpose | Decision mechanism |
|---|---|---|
| D: deterministic | Establish whether LLMs add value at all | Frozen R1/R2 baseline rules |
| S: single analyst | Measure ordinary model assistance | One analyst, same evidence menu |
| V: independent ensemble | Isolate sampling/diversity benefits | Three sealed answers, fixed majority/abstain rule |
| B: bounded debate | Isolate value of communication | Same initial V answers, one critique/response round, same selector |
| C: compute control | Isolate extra inference budget | Three analysts reuse the same sealed V answers, independently self-review without peer messages, then use the same majority/abstain selector. The aggregate token/time ceiling equals B, including B critic overhead. |

B and C receive identical source packets and initial answers. C may use the budget allocated to B's critic for additional private checking, but receives no other analyst's answer. Record actual tokens/time, not just ceilings; report any unmatched usage rather than claiming exact compute equivalence.

Evaluate generation and selection separately. For generation, score each initial buy proposal as a hypothetical fixed-notional spot lot entered at the first executable quote after its completion and exited four hours after that entry, net of the frozen fees/spread/slippage model. Score net return per notional, accepted coverage and unsupported-evidence rate; report abstentions separately rather than treating them as wins. Reduce proposals are evaluated only in portfolio replay with an actual holding. No proposer chooses its own scoring rule. For selection, replay an identical frozen candidate set through S/V/B/C. Then evaluate the combined pipeline as a separate registered trial. Otherwise a better candidate pool can be mistaken for a better voting rule.

Proposed pilot defaults, to freeze before any model run:

- Hourly decisions, four-hour maximum spot holding, with isolated carry comparison later. One position per symbol, no overlapping lots, no leverage. With no position, buy opens a lot; with a position, buy holds without topping up or refreshing expiry. Flat and abstention leave state unchanged. Reduce closes the entire existing lot; with no holding it is a no-op. Expiry closes the lot at the first executable quote at or after entry plus four hours, independently of model availability; a missing quote delays the simulated fill and is logged. Do not assume a guaranteed stop price. Each fixed-universe symbol has a cap of initial trial capital divided by the frozen symbol count, limited further by available cash and risk checks; unused allocations stay USDT and are not redistributed. Process exits before entries at a timestamp. Risk rejection prevents entry but never cancels an already scheduled expiry exit. BTC and ETH are controls, with the wider R1 seed universe evaluated under eligibility/data rules, not automatically traded.
- Start with a chronological development window, validation window and untouched final window specified by UTC boundaries and artifact hashes. Purge overlapping horizon labels at boundaries and freeze thresholds before final testing. Current daily R1 files cannot support hourly execution claims; required intraday data is an admission blocker.
- Historical LLM evaluation is diagnostic because model training may contain the future being tested. Masking dates/tickers is a sensitivity test, not a cure. Prospective timestamped shadow signals are required for promotion.
- At least 100 adversarial/schema cases before any strategy experiment; require all unauthorized actions blocked, all malformed/expired records rejected and at least 99% valid outputs on the separately labelled benign set. These are proposed gates, not tests already passed.
- At least 12 weeks prospective observation under the existing plan; duration alone never establishes statistical sufficiency. Freeze a minimum economically useful improvement and required precision before collection; if interval width is too large, remain inconclusive within the approved budget.
- Main comparison: paired daily net equity-return difference B versus V, with the same capital, fill model, data and fees; also compare each agent arm to D. Use a predeclared seven-day moving-block bootstrap, 10,000 resamples, fixed recorded RNG seed, with three- and fourteen-day sensitivity blocks. Report dependence/short-sample limitations. Correct exploratory arm comparisons with Holm adjustment; do not select a winner then report its unadjusted interval.
- For promotion of B, require its net mean daily equity-return improvement over both V and D to exceed the pre-registered minimum economically useful improvement delta: the simultaneous lower confidence bounds must exceed delta, not merely zero. Use one-sided 97.5% lower bootstrap bounds for each of these two co-primary comparisons (Bonferroni family error ceiling 5%); report bootstrap assumptions and finite-sample limitations. Delta, capital, fees, dates, model limits and risk thresholds are mandatory numeric registration fields before any run; no default zero delta. Require unchanged portfolio risk constraints, maximum drawdown no worse than either comparator, and improvement above delta under adverse spread/slippage assumptions. An interval crossing zero means inconclusive. These defaults require independent review and final pre-registration, not retroactive tuning.

Report capital-normalized net P&L, drawdown, turnover, exposure, number of independent decision blocks, source errors, abstentions, rejected/timeout decisions, p50/p95 latency, model tokens, measured resource/account charges, position overlap and pairwise error correlation. Record pre/post-debate correctness changes on objectively resolved claims. Do not call schema validity “accuracy.” Subscription access does not make inference free: include measured limits, runtime and allocated operating cost, without inventing an API-equivalent bill.

Use deterministic simulated fills after signal completion with conservative costs; never fill a delayed signal at its earlier observation price. Include stablecoin/custody assumptions and USDT capital accounting from R1. Use the identical exposure and rejection policy across arms; otherwise an abstaining arm can appear safer merely by taking less risk. Report exposure-matched sensitivity separately without selecting it after seeing the winner.

## Repository fit and implementation gaps

Inspected locally: `trading_platform/research/agents/hermes.py`, `agents/connector.py`, and `workflows/kernel.py`. Existing contracts support versioned prompts, structured accept/reject/abstain output, tool-request rejection and checkpointed workflow state. The HTTP connector is intentionally disabled; a mock provider exists. This is not a functioning local Claude multi-agent runtime.

Do not treat those primitives as complete enforcement: `HermesAdapter` passes a timeout to its provider rather than enforcing cancellation itself; the default cost estimator reads the returned payload; the tool registry only ensures registration, not that a function is read-only. These observations are static inspection, not exploit tests. `accuracy_proxy` measures acceptable responses, not investment accuracy. The future service must enforce subprocess timeouts, resource accounting and OS isolation externally.

If implemented after approval, place the local Claude runner in `services/llm/`, and the signal research coordinator in a separate service with shared versioned contracts, own tests/evals and no exchange credentials. Use the best explicitly recorded available model without silent downgrades. No hosted model API or substitute local model is implicitly authorized. Existing deterministic accounting/risk/OMS remain intact. A framework is only justified if it materially reduces the work needed to meet these contracts.

Required future failure cases: stale/future evidence, duplicated sources, tampered sender, all agents repeating an injected instruction, an unavailable critic, truncated JSON, contradictory horizons, a carry vote mixed into directional voting, correlation during market stress, cost/latency overrun, cross-run replay and a unanimous request to bypass risk. Assert fail-closed outputs and unchanged execution authority.

## Review and delivery state

This is research/documentation only. No new runtime, backtest return, paid model evaluation or live result is claimed. The acceptance rubric is `/tmp/crypto-multi-agent/critique/rubric.md`. Two delegated research attempts failed due to account usage limits. A later independent critic ran, verified the principal source claims and rejected three ambiguities in experiment design. Position state, scoring/promotion and message routing/compute controls were revised. A fresh independent critic returned PASS: `/tmp/crypto-multi-agent/critique/final-review.md`. The first critique is retained at `/tmp/crypto-multi-agent/critique/cold-review.md`. Existing R1 gate tests and evals pass; these validate existing utilities, not the proposed agent experiment. Proposed evaluation details are not an approved R2 lock.

Self-rating: 9/10, proud of the research: yes. The remaining point is lack of independent reproduction of the published financial results; recommendations therefore remain experimental.

Next action: resolve the original R1 account/configuration/data gates and separately register any multi-agent pilot before implementation or model runs. No service restart is required.
