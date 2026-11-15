# Literature

Where each part of the project comes from, and what the project found when
the published method met this data. No claim here goes beyond what the
project measured.

**How these were checked.** On 15 November 2026 every entry was looked up
against a publisher, DOI or RePEc record. That confirms authors, year, title
and venue, and that the one-line description matches the abstract. The full
texts, most of them behind paywalls, were not read for this check. One entry
could not be confirmed and is marked.

## Methods used

| Part of the project | Source | What it says | What this project did with it |
|---|---|---|---|
| Curve estimated from trades as they arrive | Kalman (1960), "A New Approach to Linear Filtering and Prediction Problems", *Journal of Basic Engineering* 82(1), 35-45 | Optimal recursive estimate of a hidden state from noisy observations | State is the par curve; each trade is one observation; the innovation is the out-of-sample error |
| How rates of different lengths move together | Litterman and Scheinkman (1991), "Common Factors Affecting Bond Returns", *Journal of Fixed Income* 1(1), 54-61 (**volume and pages not confirmed**; the paper is known from secondary citations only) | Three factors (level, slope, curvature) explain most curve moves | Found 88%, 10% and 2% on swap rates; the covariance drives the filter |
| Curve construction and interpolation | Hagan and West (2006), "Interpolation Methods for Curve Construction", *Applied Mathematical Finance* 13(2), 89-129 | The interpolation rule is part of the curve build and many rules have flaws | Log-linear discount factors; the cost is measured against an outside curve |
| Comparing two forecasts | Diebold and Mariano (1995), "Comparing Predictive Accuracy", *Journal of Business & Economic Statistics* 13(3), 253-263 | A test of equal forecast accuracy that allows correlated errors | Model against last trade: t = -24.5 over 464 days |
| Standard errors under autocorrelation | Newey and West (1987), "A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix", *Econometrica* 55(3), 703-708 | A variance estimate that stays valid when errors are correlated in time | Used inside the Diebold-Mariano test |
| Uncertainty bands with a coverage target | Vovk, Gammerman and Shafer (2005), *Algorithmic Learning in a Random World*, Springer; Angelopoulos and Bates (2021), "A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification", arXiv:2107.07511 (a preprint) | Bands calibrated on past errors reach a stated coverage when the data are exchangeable, with no distribution assumed | 89.8% coverage at a 90% target, where the normal assumption gave 70%. Trades in time order are not exchangeable, which is why coverage is checked month by month |
| Option pricing in basis-point terms | Bachelier (1900), "Théorie de la spéculation", *Annales scientifiques de l'École Normale Supérieure* 17, 21-86 | Option price when the underlying moves in absolute steps | Normal-model price, implied volatility and vega |
| Volatility by strike | Hagan, Kumar, Lesniewski and Woodward (2002), "Managing Smile Risk", *Wilmott Magazine*, September, 84-108 | The SABR model and its closed-form volatility | Implemented; did not improve out-of-sample error on this data |
| A model of how rates move | Hull and White (1990), "Pricing Interest-Rate-Derivative Securities", *Review of Financial Studies* 3(4), 573-592 | One-factor short-rate models extended to fit today's curve | Closed form checked against the exact price; out of sample it loses to the last trade |
| Forecasting the curve | Diebold and Li (2006), "Forecasting the Term Structure of Government Bond Yields", *Journal of Econometrics* 130(2), 337-364 | Three Nelson-Siegel factors with simple dynamics; the paper reports its best results at long horizons | Replicated on swap rates. The test against "no change" at 1, 5 and 20 days is this project's choice; the model loses |
| Curve shape in a few numbers | Nelson and Siegel (1987), "Parsimonious Modeling of Yield Curves", *Journal of Business* 60(4), 473-489 | A smooth curve from a handful of parameters. Reading them as level, slope and curvature is Diebold and Li's interpretation | The factor loadings in the Diebold-Li replication |
| Spread without quotes | Roll (1984), "A Simple Implicit Measure of the Effective Bid-Ask Spread in an Efficient Market", *Journal of Finance* 39(4), 1127-1139 | Negative correlation between successive price changes implies a spread | Effective spread by swap length from trade prices alone: 0.24 to 0.30 bp |
| Fast sensitivities | Giles and Glasserman (2006), "Smoking Adjoints: Fast Monte Carlo Greeks", *Risk* 19(1), 92-96 | Brought algorithmic differentiation into derivatives risk, in its adjoint (reverse) form, where cost does not grow with the number of inputs | This project uses the simpler forward form, whose cost grows with the number of inputs (14 curve points here). It agrees with bump-and-rebuild and is about ten times faster |
| Model risk management | Federal Reserve and OCC (2011), *SR 11-7: Guidance on Model Risk Management* | Conceptual soundness, outcomes analysis, ongoing monitoring | The structure of the validation report. SR 11-7 was replaced on 17 April 2026 by SR 26-2 (OCC Bulletin 2026-13); the report has not been re-mapped to the new letter |
| Overfitting in backtests | Bailey, Borwein, Lopez de Prado and Zhu (2017), "The Probability of Backtest Overfitting", *Journal of Computational Finance* 20(4) (circulated as a working paper from 2013) | Choosing among many trials inflates results | Settings frozen after 60 days; all variants reported |
| Options with many exercise dates, by simulation | Longstaff and Schwartz (2001), "Valuing American Options by Simulation: A Simple Least-Squares Approach", *Review of Financial Studies* 14(1), 113-147 | Estimate the value of continuing by regressing later cash flows on functions of today's state | The Monte Carlo Bermudan engine, with the rule fitted on one set of paths and applied to another |
| Solving the pricing equation | Crank and Nicolson (1947), "A Practical Method for Numerical Evaluation of Solutions of Partial Differential Equations of the Heat-Conduction Type", *Mathematical Proceedings of the Cambridge Philosophical Society* 43(1), 50-67; Rannacher (1984), "Finite Element Solution of Diffusion Problems with Irregular Data", *Numerische Mathematik* 43, 309-327 | A second-order time step; a few implicit steps after a kink stop it ringing | The PDE Bermudan engine |
| Caps on backward-looking rates | Lyashenko and Mercurio (2019), "Looking Forward to Backward-Looking Rates: A Modeling Framework for Term Rates Replacing LIBOR", SSRN working paper 3330240 | A compounded overnight rate keeps gathering uncertainty through its own period; the caplet's variance time reflects that | The cap and floor pricer |
| Trades that trigger trades | Hawkes (1971), "Spectra of Some Self-Exciting and Mutually Exciting Point Processes", *Biometrika* 58(1), 83-90 | A point process whose rate rises after each event | The model behind the clustering study |
| The same model in whole seconds | Kirchner (2016), "Hawkes and INAR(∞) Processes", *Stochastic Processes and their Applications* 126(8), 2494-2525 | A count model in discrete time converges to the Hawkes process | Justifies fitting in one-second steps, which is what the public timestamps allow |
| Reflexivity in markets | Filimonov and Sornette (2012), "Quantifying Reflexivity in Financial Markets: Toward a Prediction of Flash Crashes", *Physical Review E* 85, 056108; Hardiman, Bercot and Bouchaud (2013), "Critical Reflexivity in Financial Markets: a Hawkes Process Analysis", *European Physical Journal B* 86 | The share of activity triggered by earlier activity is high and has risen | Measured here on swaps: about a quarter to a third |
| The trap in that measurement | Filimonov and Sornette (2015), "Apparent Criticality and Calibration Issues in the Hawkes Self-Excited Point Process Model", *Quantitative Finance* 15(8), 1293-1314 | A baseline that changes over time, fitted as constant, shows up as false triggering | Reproduced: release days score 0.56 with a constant baseline and 0.23 once the hour's usual course is removed |
| Order flow and prices | Kyle (1985), "Continuous Auctions and Insider Trading", *Econometrica* 53(6), 1315-1335 | Prices move in proportion to net order flow | The signed-flow regression: 1.07 bp per $1bn of ten-year equivalents in the same ten minutes |
| Flow toxicity, and its critique | Easley, Lopez de Prado and O'Hara (2012), "Flow Toxicity and Liquidity in a High-Frequency World", *Review of Financial Studies* 25(5), 1457-1493; Andersen and Bondarenko (2014), "VPIN and the Flash Crash", *Journal of Financial Markets* 17, 1-46 | A volume-imbalance measure meant to warn of volatility; the critique finds its predictive content is mechanical | Not built. The public record has no trade side and caps large sizes; the signed-flow study is the version the data supports, and it finds no out-of-sample prediction |
| Mortgage hedging and rates | Hanson (2014), "Mortgage Convexity", *Journal of Financial Economics* 113(2), 270-299; Malkhozov, Mueller, Vedolin and Venter (2016), "Mortgage Risk and the Yield Curve", *Review of Financial Studies* 29(5), 1220-1253 | Changes in mortgage duration move bond risk premia and rate volatility, over weeks and months | The intraday version of the claim (rates keep going late on big days) is tested and not found: 39 days, 46% continued |

## Rules and exchange documents

| Source | What it sets | Use here |
|---|---|---|
| US Commodity Futures Trading Commission, Regulation 39.13(g)(2) (17 CFR 39.13) | Clearing-house margin must cover at least 99% of moves over a close-out period of at least one day for futures and five days for interest rate swaps | The horizons in the margin comparison |
| CME Group, published material on Eris SOFR swap futures | CME applies a two-day period to Eris contracts and five days to cleared swaps; defines the daily interest adjustment ("Eris PAI") | The two-day rule was not assumed: it is the rule that best fits the exchange's published margins |
| CME Group, "Cleared OTC IRS Margin Methodology", and the Reserve Bank of Australia's 2014 assessment of CME | CME's cleared swap margin is a historical method over a five-day close-out, with past moves rescaled by a volatility forecast and paired with unscaled moves, aiming to cover at least 99% of losses. The confidence level actually used and the length of history are not public | The structure of the low end of the swap margin in the margin comparison |
| US Bureau of Labor Statistics, release schedule and archive of news releases | The date of every consumer price and jobs report, including those moved by the lapses in funding of late 2025 and early 2026 | The release calendar in the trade-clustering study; all 47 dates match the archive |
| Basel Committee, BCBS 368, *Interest rate risk in the banking book* (2016); BCBS d578, recalibration of the shocks (2024, effective 2026); EBA, *Final draft RTS on supervisory outlier tests* (EBA/RTS/2022/10) | The six standardised shocks, their sizes by currency, the maturity decay, rotation weights, the post-shock floor and the 15%-of-Tier-1 outlier test | Book risk. Sizes and formulas read from the EBA text; the 2024 recalibrated sizes could not be read and are not applied |
| Basel Committee, supervisory framework for backtesting (1996), traffic-light zones | 0-4 exceptions green, 5-9 yellow, 10+ red, over 250 days at 99% | The VaR backtest on Book risk |
| Eris daily settlement files | Price, its three parts, risk and margin for every listed contract | The referee for the futures engine |

## Studies on the same kind of data

| Study | Finding | Relation to this project |
|---|---|---|
| Benos, Payne and Vasios (2020), "Centralized Trading, Transparency and Interest Rate Swap Market Liquidity: Evidence from the Implementation of the Dodd-Frank Act", *Journal of Financial and Quantitative Analysis* 55(1), 159-192 | Liquidity improved for swaps required to trade on electronic venues. Uses clearing-house data together with the public trade reports | The execution-cost regression here is in the same spirit (distance from a benchmark on trade characteristics), on public data only |
| Riggs, Onur, Reiffen and Zhu (2020), "Swap Trading after Dodd-Frank: Evidence from Index CDS", *Journal of Financial Economics* 137(3), 857-886 | How customers and dealers trade on swap execution facilities | Same reporting regime; a different product |
| Gürkaynak, Sack and Wright (2007), "The U.S. Treasury Yield Curve: 1961 to the Present", *Journal of Monetary Economics* 54(8), 2291-2304 | A daily fitted Treasury curve | Used for swap rates against Treasury yields |

## What is and is not new here

Not new: every method above is standard.

What the project contributes is the combination and the evidence: a filter
that prices each public swap trade before using it; calibrated bands with
verified coverage; a bias audit that tests look-ahead, selection and hindsight
on the data; a futures engine that matches the exchange to the cent; and
negative results reported as such (the volatility surface, SABR and
Hull-White lose to the last trade; signed flow does not predict; no late-day
drift; and the rise in "reflexivity" around data releases disappears once the
news itself is accounted for).
