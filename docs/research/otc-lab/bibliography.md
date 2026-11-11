# OTC Lab Bibliography: IQ Option OTC binary options

Research date: 2026-11-09. Web research only. No code was run against any broker, no account was touched.

Scope: IQ Option OTC feeds (EURUSD-OTC and similar, offered when the real market is closed or alongside it), fixed-payout up/down contracts, 1 to 15 minute expiries.

Source quality key:

- **A**: peer reviewed paper, academic monograph, or regulator document.
- **A-pre**: academic preprint (arXiv/SSRN) not yet peer reviewed. Treat as A minus.
- **B**: broker official (IQ Option site, blog, legal pages).
- **C**: reputable press, law-firm summary, encyclopedia, or a maintained repository.
- **D**: anecdote (forum post, vendor advert, self-reported experiment).

Numbers in the "break-even" and "sample size" tables were computed with a script (normal approximation), not by hand.

---

## 1. How IQ Option OTC prices are generated and settled

### 1.1 What the broker says about OTC quote formation

The broker does not publish a technical specification, an algorithm, a seed policy, an audit, or a regulator filing describing how OTC quotes are generated. Everything below comes from marketing blog posts written by staff analysts. These are the only first-party statements found. I could not retrieve the Terms and Conditions text: `iqoption.com/en/terms-and-conditions` renders client side and returned only a page heading to the fetcher, and no mirrored copy turned up in search.

**[S1] "What Is OTC Trading? A Guide for Weekend and Off-Hours Traders"**
- Author/org: Alexandre Raider (Derivatives & Risk Management Specialist), reviewed by "Nikolas, Chief Market Analyst"; IQ Option blog
- Date: 16 Sep 2024
- URL: https://blog.iqoption.com/en/what-is-otc-trading-a-guide-for-weekend-and-off-hours-traders/
- Quality: B
- Finding (verbatim): "So, the quotes in OTC trading are unique to the platform because they don't go through a public exchange." and "They're influenced by a bunch of factors, like the values from the weekday trading sessions, the number of options bought, and the investment amount." Also: OTC is "a direct deal between the trader and the broker, without going public", "the market can be a bit more volatile during the weekend", and "OTC assets have less trade liquidity due to low volume, which may lead to delays and wider spreads."
- Limitation: a blog post, not a contract. It does not say how "the number of options bought, and the investment amount" enter the price. Read literally, it says client order flow is an input to the quote that settles client contracts. That is the single most important sentence in this bibliography for the lab, because it makes the price process potentially reactive to positions, which no market-efficiency literature covers.

**[S2] "OTC Trading on IQ Option: How to Trade Securities Over the Counter"**
- Author/org: Artem Goryushin (Senior Technical Analyst); IQ Option blog
- Date: 30 Jun 2025
- URL: https://blog.iqoption.com/en/otc-trading-on-iq-option-how-to-trade-securities-over-the-counter/
- Quality: B
- Finding (verbatim): "the platform uses internal pricing models to simulate market conditions". Listed inputs: "Historical price patterns of the underlying asset", "Volatility models based on previous market behavior", "Internal liquidity simulations", "Statistical noise to introduce natural fluctuations". Also: "Because OTC prices are not linked to real-time exchange data" they may differ from other platforms on weekdays; the setup is "a simulated market"; "IQ Option maintains control over price feeds to ensure consistent and fair execution across all users"; trades occur "between the trader and the platform itself."
- Limitation: no parameters, no description of the noise process, no statement about whether the generator is seeded, replayed, or path dependent. Note this 2025 text does not repeat the 2024 "number of options bought" language; it is unclear whether the method changed or the copywriter did.

**[S3] Thai-language version of S2 ("เทรด IQ Option OTC เรียนรู้วิธีเทรด Over-the-Counter")**
- Author/org: Artem Goryushin; IQ Option blog (Thai)
- Date: 30 Jun 2025, last updated 31 Aug 2026
- URL: https://blog.iqoption.com/th/เทรด-iq-option-otc-เรียนรู้วิธีเทรด-over/
- Quality: B
- Finding (translated by the fetch tool, not verbatim): OTC prices "are created by the platform's proprietary algorithms, not global supply and demand"; "The platform uses an internal pricing model to offer prices independent of outside market activity"; "Because the broker sets internal OTC prices, pricing is less transparent than exchange-traded assets."
- Limitation: machine translation. Confirms S2 and was updated in 2026, so it is the most recent first-party description found.

**[S4] Forex Peace Army forum posts by the "IQ Option" account (official representative)**
- Author/org: IQ Option staff account on forexpeacearmy.com
- Date: various, approx. 2016 to 2019
- URL: https://www.forexpeacearmy.com/community/members/iq-option.172083/recent-content
- Quality: D (company voice, but forum, not a legal document)
- Finding (as surfaced in search snippets): charts on demo and real accounts "are based on the same quotes provided by our official quotes providers", naming Thomson Reuters, Bitstamp, Bitfinex, Bittrex and NASDAQ Basic; and that the company may block an account or decline a withdrawal "without giving any reason" under its terms.
- Limitation: these statements concern regular (non-OTC) instruments and predate the OTC blog posts. They do not describe OTC. I could not open the threads directly (HTTP 403), so the quotes come from search snippets.

### 1.2 Settlement and payouts the broker advertises

**[S5] "How to Trade Binary Options: An A-Z Guide from IQ Option"**
- Author/org: "Nikolas, Chief Market Analyst"; IQ Option blog
- Date: 18 Jun 2024
- URL: https://blog.iqoption.com/en/how-to-trade-binary-options-an-a-z-guide-from-iq-option/
- Quality: B
- Finding (verbatim): binary options "can yield up to 95% profit in as little as one minute"; "At IQ Option, options can last from 1 minute to 1 month"; "If the closing and opening prices are the same, you neither win nor lose, and your investment is returned to your balance." Each asset shows its own preset profitability percentage. Suggests risking no more than 2 to 5% per trade. OTC assets are listed inside the Binary Options category.
- Limitation: "up to 95%" is a ceiling, not the typical OTC payout. The actual payout per asset and time is shown only in the trade room and changes. The tie rule (refund) matters for the break-even math: ties remove trades from the denominator rather than counting as losses.

**[S6] "How to Trade Digital Options? An Advanced Version of Binary Options"**
- Author/org: Alexandre Raider; IQ Option blog
- Date: 28 Jun 2024
- URL: https://blog.iqoption.com/en/how-to-trade-digital-options-an-advanced-version-of-binary-options
- Quality: B
- Finding (verbatim table): Binary "Potential profitability: Up to 95%", expirations "From 1 minute to 1 month"; Digital "Up to 900%", expirations "1, 5, 15 minutes"; digital payout "isn't fixed; it depends on how far the asset's price moves from your strike price at expiration."
- Limitation: digital options are a different payoff (strike-distance dependent), so their payouts are not comparable with fixed-payout binaries. The lab should not mix the two.

### 1.3 Entities and jurisdiction

**[S7] IQ Option "Licenses and Safeguards" (regulation page)**
- Author/org: IQ Option
- Date: page footer "© 2013-2026", fetched 2026-11-09
- URL: https://iqoption.com/en/regulation
- Quality: B
- Finding: two entities. "SKY LADDER LLC", Antigua and Barbuda, registration no. ILLC 004, provides services outside the EEA; no regulator named. "IQBroker Europe Ltd (formerly IQOption Europe Ltd)", Cyprus, company no. HE327751, CySEC licence 247/14, EEA residents only. Products are described as CFDs and "other complex financial products"; binary/digital options are not mentioned on this page.
- Limitation: does not say which entity offers binaries. By elimination with S9 to S14 (EU/Cyprus retail ban), retail binaries and OTC binaries can only lawfully come from the non-EEA entity, which names no regulator.

**[S8] "Is IQ Option Legit? 5 Criteria for Evaluating Trustworthiness"**
- Author/org: "Nikolas, Chief Market Analyst"; IQ Option blog
- Date: 19 Aug 2025
- URL: https://blog.iqoption.com/en/is-iq-option-legit-5-criteria-for-evaluating-trustworthiness
- Quality: B
- Finding: outside the EEA "services are provided by IQ Option LLC, registered in St. Vincent and the Grenadines, where regulation is less stringent"; elsewhere in the same text the entity is "SKY LADDER LLC", which "does not fall under CySEC supervision". Unavailable in: United States, Canada, Australia, Iran, Israel, Japan, Turkey, Syria, Russia, North Korea, Sudan, Palestine, DPR/LPR, Crimea. "IQ Option began as a binary-options-only broker."
- Limitation: internally inconsistent about the offshore entity's name and jurisdiction (St Vincent vs Antigua per S7). The broker's own pages disagree with each other.

**[S9] IQ Option (Wikipedia)**
- Author/org: Wikipedia contributors
- Date: revision current at 2026-11-09 (mentions March 2026 events)
- URL: https://en.wikipedia.org/wiki/IQ_Option
- Quality: C (page carries a banner warning that parts may contain LLM-generated text)
- Finding: founded 2013, Limassol; part of the Quadcode group as of March 2026; moved focus to CFDs in 2017 but says binaries remain a large part of its business in certain markets (paraphrased); CySEC fines (EUR 180,000 in 2016; EUR 450,000 settlement in 2019); removed from CySEC crypto register Sept 2023; MAS Investor Alert List (2017); Indonesian Bappebti block of 92 binary sites including IQ Option (Feb 2022); RBI alert list India (Nov 2025); Brazil CVM stop order (Apr 2020) and a rejected settlement proposal from "IQ Option LLC" (Mar 2026).
- Limitation: secondary and partly flagged as machine-written. Use only as a pointer to the primary regulator records.

**[S10] BCSC Investment Caution List: "Iqoption Europe Ltd., operating as IQ Option"**
- Author/org: British Columbia Securities Commission
- Date: listing (undated in snippet)
- URL: https://www.bcsc.bc.ca/Enforcement/Investment_Caution_List/Iqoption_Europe_Ltd_,_operating_as_IQ_Option/
- Quality: A
- Finding: entity "purports to have an office in Mahé, Seychelles" and "offers an on-line trading platform for binary options"; not registered in BC.
- Limitation: a caution listing, not an adjudicated finding.

**[S11] CVM (Brazil) stop order and decisions on IQ Option**
- Author/org: Comissão de Valores Mobiliários; reported by IstoÉ Dinheiro
- Date: 20/24 Apr 2020 (stop order), reinforced 26 Apr 2021; CVM decision PDF Nov 2022
- URL: https://www.istoedinheiro.com.br/cvm-alerta-sobre-atuacao-irregular-da-iq-option-no-mercado-forex/ and https://conteudo.cvm.gov.br/export/sites/cvm/decisoes/anexos/2022/20221108/2718_22.pdf
- Quality: A (CVM PDF) / C (press)
- Finding: CVM ordered IQ Option to stop soliciting Brazilian residents for Forex, CFDs and binary options, with a daily fine of R$1,000 for non-compliance. The 2022 decision describes Portuguese-language binary-option offers targeting Brazilians from a site hosted abroad.
- Limitation: concerns licensing, not price integrity.

### 1.4 The retail binary-option bans

**[S12] ESMA, "Product Intervention Analysis: Measure on Binary Options" (ESMA50-162-214)**
- Author/org: European Securities and Markets Authority
- Date: 1 Jun 2018
- URL: https://www.esma.europa.eu/sites/default/files/library/esma50-162-214_product_intervention_analysis_binary_options.pdf
- Quality: A
- Finding (verbatim from the PDF text): "Binary options are often provided OTC to retail clients, and the investor generally has the provider as counterparty." "Binary options sold to retail clients usually have very short time horizons, in some cases as short as a few minutes." "Binary options provide investors with a negative expected return, with no appreciable offsetting benefits other than facilitating speculation." Table 1 (firm data supplied via national regulators): Firm A, all products, clients won 54% of trades yet 83% of accounts had negative cumulative return; Firm B up-down binaries, 50.7% of trades won, 83.3% of accounts negative; Firm B volatility binaries, 44.9% won, 73.7% negative; Firm C, 49% won (excluding fees), 85% negative. Firm A stated "the average expected value of an option when issued was 83% of the amount invested." ESMA's worked example: with 20 independent 50/50 trades the probability of ending with a cumulative loss is about 75%.
- Limitation: 2015 to 2016 data from three unnamed EU firms, not IQ Option OTC. It still sets the reference point: a 54% per-trade win rate was a loser at the payouts those firms offered.

**[S13] ESMA agrees to prohibit binary options and restrict CFDs (press release, mirrored by FIN-FSA)**
- Author/org: ESMA, via Finanssivalvonta (Finnish FSA)
- Date: 27 Mar 2018; Decision (EU) 2018/795 applied from 2 Jul 2018
- URL: https://finanssivalvonta.fi/en/publications-and-press-releases/supervision-releases/2018/esma-to-prohibit-binary-options-and-restrict-cfds-to-protect-retail-investors
- Quality: A
- Finding: first use of MiFIR Article 40 powers; prohibition on marketing, distribution or sale of binary options to retail clients in the EU, in three-month renewable terms. ESMA cited "structural expected negative return and embedded conflict of interest between providers and their clients".
- Limitation: temporary measure; superseded by national measures (S14).

**[S14] "ESMA ceases renewal of product intervention measure relating to binary options"**
- Author/org: ESMA
- Date: 1 Jul 2019
- URL: https://www.esma.europa.eu/node/88538
- Quality: A
- Finding: the EU-wide ban lapsed at end of 1 Jul 2019 because "most Member State national competent authorities have now taken permanent national product intervention measures relating to binary options that are at least as stringent as ESMA's."
- Limitation: does not list each member state. The ban is now national law in each state, not an ESMA decision.

**[S15] CySEC Directive 87-08 (permanent prohibition of binary options to retail), law-firm summary**
- Author/org: Andreas Neocleous & Co / AGP Law via Mondaq
- Date: July 2019 (directive applicable from 7 Jul 2019 per one source; policy statement dated 10 Jul 2019 per another)
- URL: https://www.mondaq.com/cyprus/securities/833316/permanent-prohibition-of-binary-options-trading
- Quality: C (summary of an A document; I did not reach the CySEC original)
- Finding: marketing, distribution and sale of binary options to retail clients "is permanently prohibited from or in Cyprus, irrespective of whether these are traded OTC or on a Trading Venue."
- Limitation: dates conflict between sources. Matters because IQ Option's EU entity is Cypriot: it cannot offer binaries to retail clients anywhere, from Cyprus.

**[S16] FCA PS19/11 "Product intervention measures for retail binary options"**
- Author/org: UK Financial Conduct Authority
- Date: Mar 2019, effective 2 Apr 2019
- URL: https://www.fca.org.uk/publications/policy-statements/ps19-11-product-intervention-measures-retail-binary-options
- Quality: A
- Finding: permanent ban on selling, marketing and distributing binary options to retail consumers by firms in or from the UK; wider than ESMA's (includes securitised binary options). FCA estimated savings to consumers of up to GBP 17m per year.
- Limitation: UK only.

**[S17] ASIC 21-064MR "ASIC bans the sale of binary options to retail clients"**
- Author/org: Australian Securities and Investments Commission
- Date: Apr 2021, effective 3 May 2021
- URL: https://asic.gov.au/about-asic/news-centre/find-a-media-release/2021-releases/21-064mr-asic-bans-the-sale-of-binary-options-to-retail-clients
- Quality: A
- Finding: "approximately 80% of retail clients lost money trading binary options" (ASIC reviews 2017 and 2019); net losses about AUD 490m in 2018; "the present value of the expected payoff for a binary option contract is lower than the initial investment"; "average contract duration of binary options traded with one provider was less than six minutes."
- Limitation: Australian licensed issuers, not offshore OTC feeds.

**[S18] ASIC Report 736 (extension of the binary options product intervention order to 2031)**
- Author/org: ASIC
- Date: 5 Sep 2022
- URL: https://download.asic.gov.au/media/pcilau51/rep736-published-5-september-2022.pdf
- Quality: A
- Finding (as reported in coverage of the report): in each quarter of the 13 months before the ban, 74% to 77% of active retail clients lost money; 68% of wholesale clients (outside the ban) lost money in the same period; order extended to 1 Oct 2031.
- Limitation: I did not read the full PDF; figures come from ASIC's release and press coverage.

**[S19] CSA Multilateral Instrument 91-102 "Prohibition of Binary Options"**
- Author/org: Canadian Securities Administrators
- Date: announced 28 Sep 2017, effective 12 Dec 2017
- URL: https://www.osc.ca/en/SecuritiesLaw_csa_20170927_91-102_binary-options.htm
- Quality: A
- Finding: prohibits advertising, offering, selling or trading a binary option with "a term to maturity of less than 30 days" to an individual. British Columbia did not adopt MI 91-102 but issues its own cautions (S10).
- Limitation: Canada only. Note the 30-day line: every IQ Option OTC binary (1 to 15 min) falls inside the ban.

**[S20] CFTC/SEC Investor Alert: "Binary Options and Fraud"**
- Author/org: US CFTC and SEC
- Date: first issued 2013, maintained since
- URL: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/fraudadv_binaryoptions.html
- Quality: A
- Finding: complaints include "manipulation of the binary options trading software to generate losing trades"; example given: "when a customer's trade is 'winning,' the countdown to expiration is extended arbitrarily until the trade becomes a loss." Most of the internet binary market is not compliant with US rules.
- Limitation: describes complaint categories across the industry, not findings against IQ Option. It does tell the lab which manipulation signatures to test for (expiry timing, settlement price vs displayed price).

**[S21] "The wolves of Tel Aviv: Israel's vast, amoral binary options scam exposed"**
- Author/org: Simona Weinglass, The Times of Israel
- Date: 23 Mar 2016
- URL: https://www.timesofisrael.com/binary-options-an-israeli-scam-that-has-to-be-stopped/amp/ (paper's editorial on the series; the original article is listed on the author's Times of Israel page)
- Quality: C
- Finding: investigative series on the Israeli binary-option industry (not IQ Option, which is Russian/Cypriot in origin). Led to Israel's Knesset ban on the industry (23 Oct 2017, per secondary sources).
- Limitation: industry context only. It establishes that broker-as-counterparty binaries have a documented history of abuse, not that IQ Option abuses its OTC feed.

### 1.5 What can and cannot be established

Established, from the broker's own words: OTC quotes are produced in house by an internal model; they are not exchange prices; inputs include historical patterns of the underlying, volatility models, liquidity simulation, statistical noise and (per the 2024 post) "the number of options bought, and the investment amount"; IQ Option is the counterparty; ties refund the stake; advertised binary payout ceiling is 95%; expiries from 1 minute.

Established, from regulators: retail binaries are banned in the EU (national measures since July 2019, including Cyprus), the UK, Australia (to 2031), Canada (under 30 days), Israel, and are restricted or flagged in Brazil, India, Indonesia, Singapore. IQ Option's EU entity therefore cannot offer them to retail; they come from the offshore non-EEA entity (SKY LADDER LLC, Antigua and Barbuda per S7; "IQ Option LLC, St Vincent" per S8), which names no regulator.

Not established: the generator's actual algorithm, whether it is seeded or replayed, how and how strongly client positions feed back into the path, how the settlement tick is chosen at expiry, whether the payout offered is set dynamically from client flow, and whether any independent party audits the feed. The broker does not publish any of this. I found no regulator document that examines IQ Option's OTC feed specifically.

---

## 2. Academic and statistical literature

### 2.1 Arithmetic of a fixed-payout binary

A binary paying a fraction `p` of the stake on a win and losing the stake on a loss has expected value per unit stake `q*p - (1-q)` where `q` is the win probability. Break-even is `q* = 1/(1+p)`. With ties refunded (S5), `q` is measured over non-tie trades.

| Payout p | Break-even win rate | EV per 1 unit at q = 50% |
|---|---|---|
| 70% | 58.82% | -0.150 |
| 75% | 57.14% | -0.125 |
| 80% | 55.56% | -0.100 |
| 82% | 54.95% | -0.090 |
| 85% | 54.05% | -0.075 |
| 87% | 53.48% | -0.065 |
| 90% | 52.63% | -0.050 |
| 92% | 52.08% | -0.040 |
| 95% | 51.28% | -0.025 |

Trades needed to detect an edge of size d above break-even (one-sided alpha 0.05, power 0.80, single pre-registered hypothesis, independent trades):

| Payout | Break-even | True rate | Trades needed |
|---|---|---|---|
| 80% | 55.56% | 56.56% (+1 pt) | 15,241 |
| 80% | 55.56% | 57.56% (+2 pt) | 3,803 |
| 80% | 55.56% | 58.56% (+3 pt) | 1,687 |
| 87% | 53.48% | 55.48% (+2 pt) | 3,837 |
| 92% | 52.08% | 54.08% (+2 pt) | 3,851 |

Each additional strategy variant tried raises these numbers (Section 2.4). ESMA's Firm A clients won 54% of trades and 83% of accounts still lost (S12): 54% only breaks even at an 85.2% payout.

### 2.2 Market efficiency and martingale tests at short horizons

**[S22] Lo, A. W. and MacKinlay, A. C. "Stock Market Prices Do Not Follow Random Walks: Evidence from a Simple Specification Test"**
- Org: Review of Financial Studies 1(1): 41-66
- Date: 1988
- URL: https://web.mit.edu/~alo/www/Papers/lo-mackinlay-88.html
- Quality: A
- Finding: introduces the variance ratio test with statistics valid under heteroskedastic increments; rejects the random walk for weekly US equity index returns 1962 to 1985.
- Limitation: weekly equities. The test is the right tool for an OTC feed (does variance scale linearly with horizon at 1, 2, 5, 15 minutes?), but the empirical result says nothing about synthetic feeds.

**[S23] Wald, A. and Wolfowitz, J. "On a Test Whether Two Samples are from the Same Population"**
- Org: Annals of Mathematical Statistics 11(2): 147-162
- Date: 1940
- URL: https://doi.org/10.1214/aoms/1177731909
- Quality: A
- Finding: the runs test, a distribution-free test of independence for sequences of up/down outcomes.
- Limitation: low power against weak dependence; useful as a quick screen on candle colour sequences, not as proof of an edge.

**[S24] Andersen, T. G., Bollerslev, T. and Das, A. "Variance-ratio Statistics and High-frequency Data: Testing for Changes in Intraday Volatility Patterns"**
- Org: Journal of Finance 56(1): 305-327
- Date: 2001
- URL: https://ideas.repec.org/a/bla/jfinan/v56y2001i1p305-327.html
- Quality: A
- Finding: conventional variance-ratio procedures "can be seriously misleading in a high-frequency context" because of strong intraday volatility seasonality; proposes corrected inference on FX data.
- Limitation: about volatility patterns, not direction. Direct warning for the lab: deseasonalise before running variance ratios on minute OTC data, or false rejections follow.

**[S25] Chaboud, A., Chiquoine, B., Hjalmarsson, E. and Vega, C. "Rise of the Machines: Algorithmic Trading in the Foreign Exchange Market"**
- Org: Journal of Finance 69(5): 2045-2084 (Fed IFDP 980, 2009)
- Date: 2014
- URL: https://www.federalreserve.gov/pubs/ifdp/2009/980/ifdp980.htm
- Quality: A
- Finding: on EBS interdealer data for EUR/USD, USD/JPY, EUR/JPY (2006 to 2007), algorithmic trading is associated with fewer arbitrage opportunities and less return autocorrelation at high frequency, with no causal increase in volatility.
- Limitation: about the real interdealer market. It explains why real-FX minute returns are close to a martingale; an OTC feed that is not traded against by arbitrageurs has no such force acting on it, which is why OTC could in principle differ.

**[S26] Neely, C. J. and Weller, P. A. "Intraday technical trading in the foreign exchange market"**
- Org: Journal of International Money and Finance 22(2): 223-237
- Date: 2003
- URL: https://gpbib.cs.ucl.ac.uk/gp-html/neely_2003_JIMF.html
- Quality: A
- Finding: genetic-programming and linear forecasting rules on half-hourly FX found "no evidence of excess returns" out of sample once realistic transaction costs and trading hours were included, although the rules detected some stable patterns.
- Limitation: older data, half-hour bars. The binary payout gap (Section 2.1) is a far larger cost than a 2003 FX spread.

**[S27] Escanciano, J. C. and Parra, R. "Extending the Scope of Inference About Predictive Ability to Machine Learning Methods"**
- Org: arXiv 2402.12838 (v3)
- Date: 20 Feb 2024, revised 8 May 2025
- URL: https://arxiv.org/abs/2402.12838
- Quality: A-pre
- Finding: ML-based out-of-sample tests of the martingale difference hypothesis on 1-minute Dukascopy data (15 May to 2 Jul 2023): "For the USD/CAD, USD/JPY and EUR/USD, none of the tests reject the null." GBP/CAD rejects on all tests; GBP/USD rejects on one.
- Limitation: one seven-week window. Shows that even where the null is rejected (GBP crosses), the test says nothing about whether the predictability exceeds a binary break-even. Its test design is directly reusable on OTC data.

### 2.3 ML direction prediction in FX and equities, with typical accuracy

**[S28] Gaona, A., Rangel-Madariaga, J. and Uribe, L. "Intraday trading strategy selection under transaction costs with machine learning"**
- Org: Frontiers in Applied Mathematics and Statistics 12
- Date: 1 Oct 2026
- URL: https://www.frontiersin.org/journals/applied-mathematics-and-statistics/articles/10.3389/fams.2026.1888767/full
- Quality: A
- Finding: 1-minute data, 40 assets (10 FX pairs), 2022 to 2023, walk-forward Decision Tree / Random Forest / XGBoost at 1 to 30 minute horizons. Only 5 of 40 assets had positive average return per trade after costs. EUR/USD best configuration: precision 45.17%, recall 7.50%, average return per trade -0.0082%.
- Limitation: real feeds, spread costs rather than binary payouts. Its precision under 50% on EUR/USD, after model selection, is the realistic prior.

**[S29] Theofilatos, K., Likothanassis, S. and Karathanasopoulos, A. "Modeling and Trading the EUR/USD Exchange Rate Using Machine Learning Techniques"**
- Org: Engineering, Technology & Applied Science Research 2(5): 269-272; DOI 10.48084/etasr.200
- Date: Oct 2012
- URL: https://etasr.com/index.php/ETASR/article/view/200
- Quality: A (minor venue)
- Finding: one-day-ahead EUR/USD (ECB fixing) with KNN, naive Bayes, ANN, SVM and random forest on autoregressive inputs; SVM and random forest gave the best annualised return and information ratio. A search-engine summary of the full text put out-of-sample directional hit rates at roughly 50% to 54%; I could not extract the PDF text to confirm that figure myself.
- Limitation: daily, single test period, minor journal, accuracy figure unverified. Even 54% sits below the 80% payout break-even of 55.6%.

**[S30] Guyard, K. C. and Deriaz, M. "Predicting Foreign Exchange EUR/USD direction using machine learning"**
- Org: arXiv 2409.04471
- Date: 4 Sep 2024 (v2 5 Oct 2024)
- URL: https://arxiv.org/abs/2409.04471
- Quality: A-pre
- Finding: daily EUR/USD, reports 58.52% one-day-ahead accuracy and 32.48% return in 2022.
- Limitation: single year, one pair, many model variants compared, cost treatment unclear from the abstract. The kind of headline that Section 2.4 says to deflate.

**[S31] Fischer, T. and Krauss, C. "Deep learning with long short-term memory networks for financial market predictions"**
- Org: European Journal of Operational Research 270(2): 654-669
- Date: 2018
- URL: https://econpapers.repec.org/RePEc:eee:ejores:v:270:y:2018:i:2:p:654-669
- Quality: A
- Finding: LSTM on S&P 500 constituents 1992 to 2015 beat random forest, DNN and logistic regression; daily return 0.46% and Sharpe 5.8 before costs; the edge "fluctuates around zero after transaction costs" from 2010 onward.
- Limitation: cross-sectional equity ranking, not single-series direction. Shows edge decay as markets learn.

**[S32] Lee, "Price predictability in limit order book with deep learning model"**
- Org: arXiv 2409.14157
- Date: 2024
- URL: https://arxiv.org/abs/2409.14157
- Quality: A-pre
- Finding: DeepLOB about 65.9% on a three-class task versus 64.8% for a naive past-price baseline; at a 1-minute-style target accuracy falls to 54.6%; volume imbalance helps, price history alone does not.
- Limitation: equity LOB data. Point for the lab: OTC exposes no order book and no volume, so the feature that carried signal here does not exist.

**[S33] Goodman, A. and Puri, I. "Overvaluing simple bets: Evidence from the options market"**
- Org: Journal of Financial Economics 172
- Date: 2025
- URL: https://ideas.repec.org/a/eee/jfinec/v172y2025ics0304405x25001485.html
- Quality: A
- Finding: retail binary buyers on exchange-listed S&P, gold and silver binaries often buy dominated contracts (15% to 25% of trades) and lose about 34% of price on those; standard preference models do not explain it; retail investors appear to pay for simplicity.
- Limitation: exchange-listed binaries, not broker OTC. Behavioural evidence that binary demand is not driven by edge.

**[S34] AMF study of French retail FX/CFD traders (reported by Finance Magnates)**
- Org: Autorité des marchés financiers, reported by Finance Magnates
- Date: Oct 2014
- URL: https://www.financemagnates.com/forex/analysis/amf-publishes-four-year-fx-study-89-of-investors-experiencing-losses/
- Quality: C (report of an A document)
- Finding: 89% of 14,799 active retail clients lost money 2009 to 2012; average loss about EUR 10,900; experienced traders lost at about the same rate as novices; traders who traded more often lost more often.
- Limitation: FX/CFDs, not binaries. Included because the "frequency increases loss" result matches ESMA's binomial argument (S12).

### 2.4 Backtest overfitting and multiple testing

**[S35] Bailey, D. H., Borwein, J. M., López de Prado, M. and Zhu, Q. J. "The Probability of Backtest Overfitting"**
- Org: Journal of Computational Finance 20(4); DOI 10.21314/JCF.2016.322
- Date: 2017 (SSRN preprint 2013/2015)
- URL: https://papers.ssrn.com/abstract=2326253
- Quality: A
- Finding: defines PBO and estimates it with combinatorially symmetric cross-validation (CSCV): split the performance matrix of all tried configurations into blocks, and measure how often the in-sample best ranks below median out of sample. Hold-out alone is unreliable for investment backtests.
- Limitation: needs the full matrix of every configuration tried, so the lab must log every variant, including discarded ones.

**[S36] Bailey, D. H. and López de Prado, M. "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality"**
- Org: Journal of Portfolio Management 40(5): 94-107
- Date: 2014
- URL: https://papers.ssrn.com/abstract=2460551
- Quality: A
- Finding: adjusts the observed Sharpe ratio for the number of independent trials, sample length, skew and kurtosis; gives the probability the true Sharpe exceeds zero after selection.
- Limitation: needs an estimate of the effective number of independent trials, which is hard to get honestly after the fact. Binary P&L is strongly skewed per trade, so the non-normality correction matters.

**[S37] Bailey, D. H., Borwein, J. M., López de Prado, M. and Zhu, Q. J. "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance"**
- Org: Notices of the American Mathematical Society 61(5): 458-471
- Date: May 2014
- URL: https://www.ams.org/notices/201405/rnoti-p458.pdf
- Quality: A
- Finding: shows how few trials are needed to produce an in-sample Sharpe that is pure noise; derives the minimum backtest length for a given number of trials.
- Limitation: Sharpe framing; translate to win-rate framing for binaries.

**[S38] Harvey, C. R., Liu, Y. and Zhu, H. "...and the Cross-Section of Expected Returns"**
- Org: Review of Financial Studies 29(1): 5-68; DOI 10.1093/rfs/hhv059
- Date: 2016 (NBER w20592, 2014)
- URL: https://www.nber.org/papers/w20592
- Quality: A
- Finding: with hundreds of factors tried, a new factor needs a t-statistic above about 3.0 rather than 2.0; provides Bonferroni, Holm and BHY based hurdles.
- Limitation: cross-sectional equity factors. The multiple-testing machinery transfers directly to "how many OTC patterns did we test".

**[S39] White, H. "A Reality Check for Data Snooping"**
- Org: Econometrica 68(5): 1097-1126
- Date: 2000
- URL: https://doi.org/10.1111/1468-0262.00152
- Quality: A
- Finding: bootstrap test of whether the best of many rules beats a benchmark after accounting for the search.
- Limitation: conservative when many poor rules are included; superseded in power by S40.

**[S40] Hansen, P. R. "A Test for Superior Predictive Ability"**
- Org: Journal of Business & Economic Statistics 23(4): 365-380
- Date: 2005
- URL: https://doi.org/10.1198/073500105000000063
- Quality: A
- Finding: SPA test, more powerful than the Reality Check and less sensitive to irrelevant alternatives.
- Limitation: assumes stationarity of loss differentials, which a broker-controlled feed may violate by design.

**[S41] Sullivan, R., Timmermann, A. and White, H. "Data-Snooping, Technical Trading Rule Performance, and the Bootstrap"**
- Org: Journal of Finance 54(5): 1647-1691
- Date: 1999
- URL: https://doi.org/10.1111/0022-1082.00163
- Quality: A
- Finding: across nearly 8,000 technical rules on the DJIA, the best rule's apparent performance in 1897 to 1986 does not survive out of sample in 1987 to 1996 after the Reality Check.
- Limitation: daily equities. Direct analogue of testing many "OTC candle patterns".

**[S42] López de Prado, M. "Advances in Financial Machine Learning"**
- Org: Wiley, ISBN 978-1-119-48208-6
- Date: Feb 2018
- URL: https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086
- Quality: A (academic monograph)
- Finding: Chapter 7 purged k-fold CV (drop training samples whose label windows overlap the test window) plus an embargo after each test block; Chapter 12 combinatorial purged CV (many backtest paths); triple-barrier labels and meta-labeling; Chapter 14 on deflated Sharpe and PBO.
- Limitation: monograph, not peer reviewed as a whole. Purging width must equal the label horizon: for a 5-minute expiry, at least 5 minutes plus feature lookback.

### 2.5 Probability calibration

**[S43] Platt, J. "Probabilistic Outputs for Support Vector Machines and Comparisons to Regularized Likelihood Methods"**
- Org: in Advances in Large Margin Classifiers, MIT Press
- Date: 1999
- URL: https://citeseerx.ist.psu.edu/viewdoc/summary?doi=10.1.1.41.1639 (pp. 61-74; companion correction: Lin, Lin and Weng, Machine Learning 68, 2007, https://www.csie.ntu.edu.tw/~cjlin/papers/plattprob.pdf)
- Quality: A
- Finding: sigmoid (Platt) scaling of classifier scores into probabilities, fit on held-out data.
- Limitation: assumes a sigmoid-shaped distortion.

**[S44] Niculescu-Mizil, A. and Caruana, R. "Predicting Good Probabilities with Supervised Learning"**
- Org: ICML 2005, pp. 625-632; DOI 10.1145/1102351.1102430
- Date: 2005
- URL: https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting
- Quality: A
- Finding: boosted trees and SVMs are miscalibrated in characteristic ways; Platt and isotonic regression fix it; isotonic overfits when calibration data are scarce.
- Limitation: tabular benchmarks with real signal. When the true probability is near 0.5 everywhere, calibration mostly shrinks predictions to 0.5, and the bet-or-skip threshold (break-even, Section 2.1) is what matters.

**[S45] Brier, G. W. "Verification of Forecasts Expressed in Terms of Probability"**
- Org: Monthly Weather Review 78(1): 1-3
- Date: 1950
- URL: https://doi.org/10.1175/1520-0493(1950)078<0001:VOFEIT>2.0.CO;2
- Quality: A
- Finding: the Brier score (mean squared error of probability forecasts), a proper scoring rule.
- Limitation: at base rate 0.5 the uninformed Brier score is 0.25; skill must be reported as Brier skill score against that baseline.

**[S46] Guo, C., Pleiss, G., Sun, Y. and Weinberger, K. Q. "On Calibration of Modern Neural Networks"**
- Org: ICML 2017; arXiv 1706.04599
- Date: 2017
- URL: https://arxiv.org/abs/1706.04599
- Quality: A
- Finding: modern deep nets are overconfident; temperature scaling is a simple, effective fix; expected calibration error (ECE) as a metric.
- Limitation: image classification; ECE is binning-sensitive.

### 2.6 Time-series foundation models

**[S47] Ansari, A. F. et al. "Chronos: Learning the Language of Time Series"**
- Org: Transactions on Machine Learning Research; arXiv 2403.07815 (Amazon)
- Date: Mar 2024
- URL: https://arxiv.org/abs/2403.07815
- Quality: A
- Finding: tokenised T5-based probabilistic forecaster; good zero-shot results on general benchmarks.
- Limitation: benchmarks are mostly energy, traffic, retail, weather. Not designed or validated for return direction.

**[S48] Das, A., Kong, W., Sen, R. and Zhou, Y. "A decoder-only foundation model for time-series forecasting" (TimesFM)**
- Org: ICML 2024; arXiv 2310.10688 (Google)
- Date: Oct 2023 / Jul 2024
- URL: https://arxiv.org/abs/2310.10688
- Quality: A
- Finding: decoder-only patched transformer, strong zero-shot point forecasts on general benchmarks.
- Limitation: same as S47.

**[S49] Woo, G. et al. "Unified Training of Universal Time Series Forecasting Transformers" (Moirai)**
- Org: ICML 2024; arXiv 2402.02592 (Salesforce)
- Date: Feb 2024
- URL: https://arxiv.org/abs/2402.02592
- Quality: A
- Finding: any-variate masked encoder trained on the LOTSA corpus; competitive zero-shot.
- Limitation: same as S47.

**[S50] Rahimikia, E., Ni, H. and Wang, W. "Re(Visiting) Time Series Foundation Models in Finance"**
- Org: arXiv 2511.18578
- Date: 23 Nov 2025
- URL: https://arxiv.org/abs/2511.18578
- Quality: A-pre
- Finding (abstract): "off-the-shelf pre-trained TSFMs perform poorly in zero-shot and fine-tuning settings" on daily excess returns across many countries; models pretrained from scratch on financial data do better. Per a secondary summary of the full paper, zero-shot Chronos-Large had out-of-sample R² about -1.37% and directional accuracy just above 51%, and tree ensembles (CatBoost) beat both.
- Limitation: daily returns, not minute OTC. The 51% figure came via a summary site, not my own read of the tables.

### 2.7 Reinforcement learning and simulator overfitting

**[S51] Gort, B. J. D., Liu, X.-Y., Sun, X., Gao, J., Chen, S. and Wang, C. D. "Deep Reinforcement Learning for Cryptocurrency Trading: Practical Approach to Address Backtest Overfitting"**
- Org: arXiv 2209.05559
- Date: Sep 2022
- URL: https://arxiv.org/abs/2209.05559
- Quality: A-pre
- Finding: prior DRL trading papers "optimistically reported increased profits in backtesting, which may suffer from the false positive issue due to overfitting"; frames overfitting detection as a hypothesis test with combinatorial CV and rejects overfitted agents.
- Limitation: 10 cryptocurrencies, about two months of test data.

**[S52] Pricope, T.-V. "Deep Reinforcement Learning in Quantitative Algorithmic Trading: A Review"**
- Org: arXiv 2106.00123
- Date: 31 May 2021
- URL: https://arxiv.org/abs/2106.00123
- Quality: A-pre
- Finding: although reviewed DRL works report gains over baselines, "no decent profitability level was obtained in most works"; experiments are mostly in "unrealistic settings" with no live trading.
- Limitation: review of low-frequency stock trading. For OTC the concern is sharper: an RL agent trained on recorded OTC paths learns the recording, while the live feed may respond to the agent's own trades (S1).

**[S53] Liu, X.-Y. et al. "FinRL: A Deep Reinforcement Learning Library for Automated Stock Trading in Quantitative Finance"**
- Org: NeurIPS 2020 Deep RL Workshop; arXiv 2011.09607
- Date: Nov 2020
- URL: https://arxiv.org/abs/2011.09607
- Quality: A-pre / C (library)
- Finding: the reference open-source DRL trading framework; its own later work (S51) concedes backtest overfitting in the field.
- Limitation: simulators replay history and cannot model a counterparty that reacts.

---

## 3. Open-source projects

GitHub figures pulled with `gh api` on 2026-11-09.

**[S54] Lu-Yi-Hsun/iqoptionapi**
- Org: GitHub, Lu-Yi-Hsun
- Date: last push 2026-07-01 (a README note: "close the npt-life web"); last code-bearing commits 2021-06/2021-07
- URL: https://github.com/Lu-Yi-Hsun/iqoptionapi
- Quality: C (popular, effectively unmaintained)
- Stats: 391 stars, 302 forks, 230 open issues, no licence declared.
- Finding: reverse-engineered WebSocket client (candles, digital/binary buy, positions). Docs at https://lu-yi-hsun.github.io/iqoptionapi/.
- Limitation: unofficial; protocol drift since 2021 is likely; no tests of data integrity.

**[S55] iqoptionapi/iqoptionapi**
- Org: GitHub community fork
- Date: last commit 2022-01-31 ("version 7.1.1"); repo pushed 2024-08-12
- URL: https://github.com/iqoptionapi/iqoptionapi
- Quality: C
- Stats: 276 stars, 196 forks, 55 open issues.
- Finding: description reads "supported by community - ONLY FOR STUDY - Don't use it on your real Account!!!".
- Limitation: the maintainers themselves warn against real-account use.

**[S56] n1nj4z33/iqoptionapi**
- Org: GitHub
- Date: last push 2021-07-17
- URL: https://github.com/n1nj4z33/iqoptionapi
- Quality: C (obsolete)
- Stats: 134 stars.
- Finding: original Python 2.7 client; README says "The project is obsolete and is not supported".
- Limitation: historical only.

**[S57] Other IQ Option clients**: MongkonEiadon/IqOption.Net (96 stars, archived, 2021), harwee/IQOption-Api (53 stars, archived, 2019), JorgeBeserra/IqOptionApiDotNet (30 stars, pushed 2026-10-14), Payme-Works/hemes (39 stars, pushed 2026-10-25, multi-broker SDK), LuKks/iqoption (6 stars, 2026-01, real-time data over WebSocket).
- URL: https://github.com/search?q=iqoption+api&type=repositories
- Quality: C/D
- Limitation: none publishes data-quality tests or OTC statistics.

**[S58] PHCStanton/pocket-option-otc-dataset**
- Org: GitHub
- Date: pushed 2026-08-10
- URL: https://github.com/PHCStanton/pocket-option-otc-dataset
- Quality: D
- Stats: 0 stars.
- Finding: tick-level Pocket Option OTC samples (about 500 ms arrival) in Parquet, with a "manipulation" flag computed from the author's own heuristics ("Push & Snap", "Pinning").
- Limitation: different broker; the manipulation label is a heuristic defined by the author, not a validated detector; sample size unknown. The only public OTC tick dataset I found. I found no public IQ Option OTC dataset on GitHub, Kaggle or Hugging Face.

**[S59] otcharts/iq-option-api, otcharts/otcharts-python**
- Org: GitHub, otcharts
- Date: pushed 2026-09/10
- URL: https://github.com/otcharts/iq-option-api
- Quality: D
- Stats: 0 to 3 stars.
- Finding: third-party paid/keyed service reselling OTC candles for IQ Option, Pocket Option, Quotex.
- Limitation: unknown provenance; data could be altered or delayed; not usable as ground truth.

**[S60] cbtradersbd/pocket-option-telegram-signals-engine (and sibling repos)**
- Org: GitHub, cbtradersbd
- Date: pushed 2026-10-27
- URL: https://github.com/cbtradersbd/pocket-option-telegram-signals-engine
- Quality: D
- Finding: advertises "92%+ Winrate Non-Repaint Algorithm" for OTC.
- Limitation: marketing claim with no published trade log. Typical of the "OTC strategy" repos: none of the ones found publishes a backtest with trade counts, payout assumptions, out-of-sample split, or confidence intervals.

**ToS position on unofficial API use.** What I could establish:
- IQ Option offers no public official trading API (only secondary sources say so; I found nothing first-party that offers one).
- I could not obtain the Terms and Conditions text (client-side rendered page; no mirror found), so I cannot quote a clause on bots or third-party software. This is a gap.
- The broker's blog list of account-block reasons (S61) does not mention bots, but the official forum account (S4) states the company may block accounts or decline withdrawals "without giving any reason".
- User reports (S66) describe blocks for VPS use and for alleged "front-running".
- The most active community repo tells users not to use it on a real account (S55).
- Working assumption for the lab: automated use of the unofficial API is at the broker's discretion and may lead to account closure or voided trades. Practice-account data collection carries the least exposure.

**[S61] "Why does IQ Option block accounts?"**
- Author/org: "Nikolas, Chief Market Analyst"; IQ Option blog
- Date: 28 Feb 2020
- URL: https://blog.iqoption.com/iq-option-blocks-accounts
- Quality: B
- Finding: six reasons: third-party payment details, suspicious transactions, multiple accounts, false personal data, refusal of KYC documents, residence in a restricted country. "No account gets blocked without a solid reason."
- Limitation: not the legal terms; silent on automation.

---

## 4. Community evidence on OTC patterns and "manipulation"

None of the items below is a controlled experiment with a pre-registered hypothesis, a disclosed sample, and an out-of-sample test. All are D.

**[S62] "IQ Options (Price Manipulation Proof)"**
- Org: Forex Peace Army forum thread 55857
- Date: not visible to me (site returned 403); thread id suggests roughly 2018
- URL: https://www.forexpeacearmy.com/community/threads/iq-options-price-manipulation-proof.55857/
- Quality: D
- Finding: the poster compared IQ Option charts with another platform's charts for the same assets and posted screenshots of differences.
- Assessment: anecdote. Feed differences between brokers are normal (different liquidity sources, aggregation, time stamps) and, for OTC, expected by design (S2). Screenshots do not show that differences were directional against the client. Site returned 403 to the fetcher; content from search snippets.

**[S63] Forex Peace Army posts alleging OTC manipulation and deleted winning trades**
- Org: Forex Peace Army (e.g. post 478683, "Formal complaint against IQ Option" thread 86819)
- Date: various
- URL: https://www.forexpeacearmy.com/community/threads/formal-complaint-against-iq-option-iqoption-com.86819/latest
- Quality: D
- Finding: claims that "the OTC market appears to be manipulated" and that winning trades were removed from history; one turbo-option complaint reports 6 to 7 s execution latency and about 2 pips slippage from the displayed price.
- Assessment: anecdote with no data. The latency/slippage report is the kind of thing the lab can measure directly (displayed price at click vs recorded open price).

**[S64] "IQ OTC Trading Bot - Your Weekend Playbook"**
- Org: EarnForex forum, user "SignalBotsAI"
- Date: 10 Jul 2026
- URL: https://www.earnforex.com/forum/threads/iq-otc-trading-bot-your-weekend-playbook.54849/
- Quality: D (advert)
- Finding: sells a USD 50 bot whose scores are "calibrated" to IQ Option's "synthetic feed"; no win rate, trade count or method stated.
- Assessment: promotion with no evidence.

**[S65] Artificial Analysis MicroEval prompt: "I am reverse engineering a synthetic OTC binary options price..."**
- Org: artificialanalysis.ai (anonymous user prompt)
- Date: 2026 (no exact date)
- URL: https://artificialanalysis.ai/microevals/i-am-reverse-engineering-a-synthetic-otc-binary-options-pric-1785409957304
- Quality: D
- Finding: an anonymous Quotex user claims the OTC feed tracks Binance with a 5 to 60 s lag and a fixed scale factor, about 54% of ticks are synthetic noise, and a "global balancer" keeps up/down near 50/50. Their own log: "71% base" falling to 50% with more samples; "96.4% on 56 samples" falling to 36% the next day; "every edge we find gets balanced out."
- Assessment: different broker, unverifiable, but useful as a cautionary record: every apparent edge was a small-sample artifact that vanished out of sample. The "tracks a real feed with lag" hypothesis is cheap to test on IQ Option weekday OTC (cross-correlation with a real EURUSD feed at lags).

**[S66] "IQ Option - Blocked Account Due To Using VPS ???" and similar threads**
- Org: Forex Peace Army
- Date: not visible to me; thread id suggests roughly 2019 to 2020
- URL: https://www.forexpeacearmy.com/community/threads/iq-option-blocked-account-due-to-using-vps.63161/latest
- Quality: D
- Finding: a user reports a block email citing VPS use; another reports a block for "front-running".
- Assessment: anecdote, but relevant to running any automated collector against a real account.

**[S67] MQL5 freelance job: capture IQ Option OTC ticks to find repeating patterns**
- Org: mql5.com freelance
- Date: 3 Nov 2023
- URL: https://mql5.com/en/job/206956
- Quality: D
- Finding: client offers USD 1,000 to 10,000+ to record OTC ticks and build an EA if a repeating pattern is confirmed; says "it seems that it does make sense haha" after a year of manual trading.
- Assessment: belief in OTC patterns is common and well funded; evidence is absent.

**[S68] MetalsMine / EnergyExch forum posts (Forex Factory network) on IQ Option OTC being "synthetic"**
- Org: metalsmine.com thread posts 15797855, 15833155
- Date: 2025 to 2026
- URL: https://www.metalsmine.com/thread/post/15797855
- Quality: D
- Finding: states that EUR/USD-OTC is a synthetic instrument and not interbank EUR/USD.
- Assessment: consistent with the broker's own statement (S2); adds nothing beyond it. Site returned 403; content from search snippet.

**[S69] Reclame Aqui complaint "IQ Option: jogos de azar"**
- Org: reclameaqui.com.br (Brazilian consumer complaints)
- Date: undated in snippet
- URL: https://www.reclameaqui.com.br/iq-option/iq-option-jogos-de-azar_5gMVU-tCovubDJDR/
- Quality: D
- Finding: complainant describes the product as gambling.
- Assessment: opinion; matches the regulators' framing (S12, S17) rather than proving anything about the feed.

Overall assessment of community evidence: I found no public, reproducible study of IQ Option OTC feeds with a stated sample, test, and out-of-sample result, either for "patterns" or for "manipulation". The claims of manipulation are unfalsified anecdotes. The claims of exploitable patterns come mostly from sellers of bots and signals. The one detailed self-reported experiment (S65, a different broker) documents edge decay to chance.

---

## What this implies for the lab

1. The broker states OTC prices come from an internal model it controls, with IQ Option as counterparty; there is no exchange price to anchor to and no published algorithm, so every property must be measured, not assumed.
2. The 2024 blog says OTC quotes depend on "the number of options bought, and the investment amount": test for order-flow feedback by comparing paths after our own practice trades vs matched no-trade windows.
3. Break-even is 1/(1+payout): 55.6% at 80%, 53.5% at 87%, 51.3% at 95%. Log the payout actually offered per trade; the advertised 95% is a ceiling.
4. ESMA's own firm data show 54% per-trade wins with 83% of accounts losing; a modest hit rate is not an edge.
5. Detecting a 2-point edge above break-even needs about 3,800 independent trades for one pre-registered hypothesis; anything tested on a few hundred trades is noise.
6. Log every variant tried and report PBO (CSCV), the Deflated Sharpe/win-rate, and Holm or BHY corrected p-values; require t > 3 style hurdles.
7. Use purged, embargoed walk-forward splits with purge width at least expiry plus feature lookback; deseasonalise before variance-ratio and runs tests (Andersen et al. 2001).
8. Real-FX minute ML studies sit near 50% to 54% and lose after costs; off-the-shelf Chronos/TimesFM/Moirai are near chance on returns; RL on replayed OTC paths cannot model a reactive counterparty.
9. Cheap structural tests worth running first: lagged cross-correlation of weekday OTC vs a real EURUSD feed, settlement-tick vs displayed-price audit, expiry-timing audit, and variance ratios across 1 to 15 minutes.
10. Legal and account exposure is real: retail binaries are banned in the EU/UK/AU/CA, the offering entity is offshore with no named regulator, ToS on bots could not be obtained, and the broker can block accounts at discretion; keep collection on practice accounts.
