# R1 venue eligibility, costs and benchmark dossier

Research date: **2026-10-31**, Africa/Lagos client date. Public-source review only. Page effective/update dates are distinguished below from access date. No account, key, balance, order, withdrawal or private entitlement was inspected.

## Decision and confirmed context

User clarification, November 1: USDT can be moved to the selected setup. No transfer destination, current Earn status, entity, product permission or authenticated rate was supplied. This changes custody flexibility only; no funds are moved or allocated by this review.

Saviour confirmed Nigerian residence and answered the account/currency question with **USDT, Bybit, WEEX and Binance**, adding willingness to switch venues. Treat those accounts as **user-reported**, not independently verified product permissions. Switching is an option, not authorization to open or fund another account.

**Research priority: Bybit spot/USDT-linear carry first; WEEX as a conditional comparator; Binance public history as reference data only pending its regulatory question; Hyperliquid as a later comparator.** This prioritization follows existing accounts, public data/rule accessibility and minimal new settlement/bridge dependencies. It is not a legal clearance or a finding that Bybit is safer or more profitable.

**Benchmark for the initial experiment:** a no-trade, non-interest-bearing USDT holding, reported in token units and independently marked in USD. Set its nominal token interest rate to zero as an explicit experimental assumption because no Earn product was specified. This is not a risk-free USD yield, and it is not a recommendation to leave reserves on an exchange. A positive return relative to this baseline is necessary but insufficient: trading must also meet the configured risk premium, costs and loss constraints. The actual location of the baseline balance and any existing earned yield remain account-context fields.

## Admission matrix

| Candidate | What primary evidence establishes | What it does not establish | R1 disposition |
|---|---|---|---|
| **Bybit global** | Official excluded-jurisdiction page, updated October 16, 2026, does not name Nigeria in its inspected list; it also reserves service termination and account restrictions. Public APIs document spot, linear instruments and funding. [Restrictions](https://www.bybit.com/en/help-center/article/Service-Restricted-Countries) | Nigerian regulatory authorization, exact contracting entity, account derivative permissions, fees, API access or withdrawal route | First public-data research venue. Live admission remains pending entity/product confirmation and current local regulatory assessment |
| **WEEX** | Terms section 1.1(d), read October 31, names excluded jurisdictions; Nigeria is not named. The terms require lawful use and permit restrictions. [Terms](https://www.weex.com/help/articles/4417379529241) | Absence from that list is not Nigerian registration or permission for this user's product. Existing account use does not verify API eligibility or custody protection | Conditional second research venue. No live allocation until the same entity/product and account dossier is complete |
| **Binance** | SEC's July 28, 2023 circular specifically addresses binance.com and says it was not registered/regulated. No superseding Nigerian authorization was verified in this review. [SEC warning](https://home.sec.gov.ng/for-investors/keep-track-of-circulars/warning-against-investing-with-binance/) | The historical notice alone is not a complete determination of today's legal position or of individual liability | Public historical data can inform research; allocation blocked pending current authoritative resolution |
| **Hyperliquid** | Official product docs describe funding, fees and margin. Its terms endpoint returned no readable text to the research tool on October 31. [Terms endpoint](https://app.hyperliquid.xyz/terms) | Current terms eligibility could not be independently read. A third-party country list, HTTP 200 or absence of KYC is not sufficient | Defer admission. Obtain readable operative terms, precise spot-token/redemption mapping and actual account mode before any funding |
| **Busha / Quidax** | SEC's register lists Busha Digital Limited and Quidax Technologies Limited as Digital Assets Exchanges under **ARIP participants**. [SEC register](https://www.sec.gov.ng/fintech-and-innovation-hub-finport/registered-fintech-operators/) | Listing in that programme is not blanket derivatives authorization, a guarantee, or proof of API support for the proposed strategy | Candidates for a separately verified spot/off-ramp route; no derivatives assumption |

A working public API is data access only. This matrix does not recommend changing declared residence, masking location or bypassing product restrictions. No message to an exchange or regulator was sent.

### Binance account access and NGN access are different facts

Binance's own March 5, 2024 announcement, amended June 18, says NGN services were discontinued while account access remained available. It also records delisting NGN P2P pairs. That explains why an existing account is not evidence of an available NGN funding or withdrawal path. It does not resolve the SEC notice. No restored NGN service was verified here. [Binance announcement](https://www.binance.com/en-NG/support/announcement/detail/f9857dc2fea4448ba1fb8815d87d8144)

## Published fee inputs for research

Rates below are **per executed side**, percentages of the applicable trade notional. They are public base schedules, not Saviour's authenticated tariffs. Do not add a fee once for a two-leg round trip: charge each spot/perp entry and exit separately in the deterministic ledger. Maker execution and rebates are not assumed.

| Venue | Spot maker / taker | Perpetual maker / taker | Evidence and limits |
|---|---:|---:|---|
| Bybit VIP 0 | 0.1000% / 0.1000% | 0.0200% / 0.0550% | Official fee page updated September 2, 2026 explicitly says regional rates can differ and directs users to authenticated My Fee Rate. Excludes special zones, promotions, spread, funding and withdrawals. [Fee schedule](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure) |
| WEEX VIP 0, provisional help-guide values | 0.100% / 0.100% | 0.020% / 0.080% | Official guide is undated in retrieved text and warns rates may change. The linked live Rate Standards page did not expose numerical rates in the text fetch. These are provisional scenario inputs, **not verified current account rates**. [Guide](https://www.weex.com/help/articles/eku5751ygo10r1j1vom9bc18), [live rate page](https://www.weex.com/support/rate) |
| Hyperliquid base tier | 0.040% / 0.070% | 0.015% / 0.045% | Official docs distinguish spot/perp schedules and rolling volume tiers. HYPE staking, aligned-quote changes, builder fees and HIP-3 deployer charges can alter the applicable rate. Do not assume any discount or a universal fee across deployers. [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees) |
| Binance | Unset | Unset | Not needed for an executable candidate until admission is resolved. Do not silently transfer Bybit fees to Binance historical data |

Bybit provides authenticated `GET /v5/account/fee-rate` for category/symbol tariffs. The account holder can later supply a redacted export or an approved read-only integration can record it; no credential is required in chat. [Fee API contract](https://bybit-exchange.github.io/docs/v5/account/fee-rate)

The WEEX guide's generic eight-hour explanation must not become a permanent data rule. Its newer API specifies instrument `collectCycle` in minutes; record actual current and historical settlement timing. Its sample withdrawal table is also not a guaranteed future quote. Withdrawals depend on asset/network; use the live account quote at the proposed transfer time.

## Product, margin and funding facts that constrain R2

**Bybit:** the instruments endpoint exposes contract status, launch time, leverage, minimum/maximum order and quantity filters, tick size and funding interval. It describes current online instruments, not historical tradability. Spot and linear pairs must be matched by asset identity and settlement currency; the current pair intersection is a screening universe only. [Instrument API](https://bybit-exchange.github.io/docs/v5/market/instrument)

The funding-history contract returns settled records and directs callers to each instrument's interval. Do not apply three settlements per day to every coin or interval regime. [Funding API](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate)

Risk-limit metadata gives maintenance/initial margin tiers and maximum leverage; its documentation warns of increased latency during extreme volatility. These are current parameters, not a historical series. Account mode, actual collateral eligibility, haircuts and borrow settings must still be confirmed. The R1 conservative capital scenario is separately funded spot plus stablecoin-margined 1x short and reserve, not an assumed cross-margin discount. [Risk-limit API](https://bybit-exchange.github.io/docs/v5/market/risk-limit)

**WEEX:** current V3 documentation lists `/capi/v3/market/premiumIndex` (including forecast versus last funding and `collectCycle`), `/capi/v3/market/fundingRate` (settled time, rate and mark), `/capi/v3/market/apiTradingSymbols`, and `/capi/v3/market/riskLimits`. Its older V2 history-doc URL now rendered the documentation landing page, so a legacy adapter contract must be reverified instead of assumed compatible. Current symbol lists and docs are not proof of complete historical coverage or this account's API entitlement. [V3 market contract](https://www.weex.com/api-doc/catalog/core-trading-futures/api/rest-api/market-api), [API entry point](https://www.weex.com/api-doc/introduction)

**Hyperliquid:** official funding docs state hourly payments, with its computed eight-hour rate apportioned for the hourly payment. Use settled hourly records, not a forecast multiplied as if it settled eight-hourly. Margin docs describe cross as default and support isolated modes with account/DEX distinctions. Selecting leverage at entry does not prevent later liquidation. USDC collateral and tokenized spot introduce conversion and redemption dependencies for a USDT-funded investor. [Funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding), [margin](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margining), [contract specifications](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications)

## Funding, withdrawal and custody evidence required

No withdrawal was attempted. For the selected venue/account, complete these fields before funding or an executable simulation claims account-specific costs:

- Exact contracting entity, registered country/KYC, permission for spot and the chosen derivatives, API permissions, subaccount ownership and margin mode.
- For USDT deposits/withdrawals: network, actual token contract, destination ownership, deposit minimum, confirmations, withdrawal minimum, current fee and any account/security lock. A supported token ticker is not proof that two networks are interchangeable.
- Legal conversion route to/from the user's bank when needed, name matching, spreads, limits and settlement time. Do not assume P2P or NGN availability merely because crypto transfers work.
- Whether reserve funds are exchange balances or self-custodied; issuer and venue/bridge exposures must be budgeted separately. A zero-interest USDT comparator can still lose USD value or become inaccessible.
- Exportability of fills, fees, funding, transfers and taxable values; applicable tax treatment remains a user/account-specific unresolved cost rather than a guessed zero.

Bybit documents network-specific minimums and withdrawal fees shown in the withdrawal window; no universal fixed fee is inserted into R1. [Withdrawal instructions](https://www.bybit.com/en/help-center/article/How-to-submit-on-chain-withdrawal-request)

Direct Tether redemption is not a universal escape route: the issuer's fee page lists a USD 100,000 minimum and redemption fee of the greater of USD 1,000 or 0.1%, plus account verification conditions. Treat the executable exchange/bank route as a separate requirement. [Tether fees](https://tether.to/en/fees/)

## Benchmark ladder and currency treatment

| Comparator | R1 treatment | Why |
|---|---|---|
| **Hold the same USDT amount without Earn** | Primary no-trade reference, nominal token yield configured to zero; record USD mark and custody separately | Matches the user's stated unit. A token-unit gain can still be a USD loss; USDT is not fiat cash or a guaranteed USD claim |
| Existing USDT Earn, if the user actually uses one | Unknown, excluded until product/APR/amount cap/term/redemption/credit risks are supplied | A promotional headline is not the realized alternative for the full capital allocation. No Earn use was stated |
| Accessible USD bank deposit or short-duration treasury instrument | Opportunity-cost comparator pending the actual account, net quote and redemption horizon | No authenticated accessible product/rate was established. Do not insert a US Treasury headline as an investable Nigerian-resident return |
| Nigerian USD fixed-income fund | Candidate for separate due diligence, not initial cash benchmark | Stanbic IBTC Dollar Fund describes an open-ended Nigerian scheme with a minimum 70% Eurobond allocation. That entails market/credit/duration risk, and USD funding access must be verified. No yield or current minimum is assumed. [Provider product page](https://www.stanbicibtcassetmanagement.com/nigeriaassetmanagement/individual-investor/products-and-services/mutual-funds/fixed-income-funds/stanbic-ibtc-dollar-fund/stanbic-ibtc-dollar-fund) |
| NGN government savings bonds | Context only; not a live USDT hurdle | The DMO portal lists October 2026 two-/three-year issues at 13.071% / 14.071%, both **closed** in the inspected page. Those are historical offer coupons, not available cash yields, and maturities differ from liquid reserves. [Official DMO portal](https://subscribedmo.dmo.gov.ng/) |

For any later NGN alternative, compute both legs of actual USDT/NGN conversion, bank/exchange charges, time out of market and terminal FX movement. Report NGN and USD/USDT results separately with timestamped executable quotes. The CBN's [money-market indicators](https://www.cbn.gov.ng/rates/mnymktind.html) can provide macro context, but an indicated bill rate is not a retail executable quote or a substitute for a matched-maturity net return. No current bank rate or FX forecast is invented here.

## Completed versus pending

**Completed public R1 work:** existing-account shortlist, dated regulatory/terms evidence, public fee scenarios, funding/margin/API contracts, no-trade USDT benchmark definition, currency/withdrawal constraints and exact admission fields. These findings are sufficient to specify conditional research experiments; they do not clear a venue for live use.

**Pending account evidence:** current contracting entities and Nigeria product permission; authenticated fees, API entitlement and margin settings; baseline custody/Earn status; executable transfer/off-ramp quote; capital and loss limits. Only the user or an authorized read-only account review can supply these. Any exchange support answer should be retained verbatim with date/entity/product and reconciled against regulator evidence; a generic “we serve your country” chat message is not enough.

**Promotion rule:** public historical research may continue while those fields are unresolved, clearly labeled hypothetical. Live enablement and claims of account-specific investability remain blocked. The user’s approval of R1 does not approve a new exchange account, USDT movement, an Earn subscription or order placement.
