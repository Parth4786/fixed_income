# Tapemark

Fair prices for interest rate swaps, built from public trade records and
checked against the trades that came next.

US rules put every reported swap and swap option trade into the public
record. Tapemark downloads those records, cleans them, prices trades with
models written from first principles, and scores each model only on trades it
had not seen. Everything comes from free public data. Nothing is simulated.

## Results

Out of sample, 7 Feb 2025 to 13 Nov 2026, on real US dollar SOFR swap trades.

| Question | Answer |
|---|---|
| How close is the model's rate to the next real trade? | Median miss **0.26 bp** on 275,578 trades |
| Is that better than the obvious shortcut? | Yes: using the last trade of the same length misses by 0.41 bp. Over 464 trading days the difference is far beyond chance (Diebold-Mariano statistic 24.5) |
| Does it price swaps it was never fitted to? | 0.56 bp on 115,768 forward-starting swaps, against 2.55 bp for the previous day's closing curve |
| Are its uncertainty bands honest? | A 90% band held 89.8% of trades (70% before calibration) |
| Do its risk numbers work? | Hedges built from them removed 99.6% of next-day variance on 2,647 real trades |
| Does it hold on violent days? | 0.36 bp on the 26 worst days, against 0.25 bp otherwise |
| Is the code right? | Median 0.001 bp from an independent curve provider's swap rates; also checked against QuantLib |
| How close to the limit is that? | The effective spread implied by trade prices (Roll's estimator) is 0.24 to 0.30 bp, so a 0.26 bp miss is near the floor set by the market's own bid-offer bounce |
| Is the result flattered by a bias? | Tested: predictions are identical with and without later trades; amended, late and excluded trades are scored separately and published |
| Can it price exchange-traded swap futures? | Yes, to the cent: on 16,312 contract-days the value of future cash flows is within $0.27 a contract of the exchange's own figure at worst, and risk within 0.1% |
| What does margin cost? | A historical margin rule was fitted to the margins the exchange publishes; two days at 99% fits best. The swap rule follows the method the clearing house describes and, tested on 1,025 later days, covered 99.4% of moves against a 99% standard. On a $100m 10-year position a cleared swap ties up 1.4 times the margin of the equivalent futures |
| Is the option pricer right, and the volatility grid? | The pricer reproduces all 89,014 exchange-settled option prices within one price step. The volatility grid built from public premiums is within about 7 bp of the exchange's level at short option lives, but its day-to-day changes do not track the exchange's |
| Do trades trigger more trades? | About a quarter to a third of trading is a reaction to earlier trades. The apparent jump on data-release mornings (0.56) is an artefact: once the release itself is treated as news it is 0.23, no higher than other days |
| Does modelling Fed meetings help? | A short end that steps on meeting dates cuts the miss on forward swaps under a year from 1.10 to 1.07 bp (reliable, t 3.1) and makes no difference beyond a year: most of the remaining error is in the curve points, not their shape |
| What do inflation markets say? | Inflation swaps price about 9 bp more inflation than TIPS breakevens at 10 years (435 days, same-day comparison): the usual liquidity gap, shown on Other markets |
| Can it measure bank interest rate risk the way regulators ask? | Yes, on a real published book: the Fed's $3.78tn Treasury portfolio under the six Basel/EBA shocks (worst −$361bn) with full-repricing VaR ($27.7bn, 1 day, 99%) backtested green, run by a C++ kernel that matches NumPy exactly |
| Where does it lose? | Swap options: the last similar trade (4.0 bp of volatility) beats the fitted surface (11.1) and a Hull-White rate model (16.0). Short forward-starting swaps are a weak spot (1.1 bp) |

The full report is written to `data/reports/model_validation.md` by `tapemark score`.

## What is in it

| Part | What it does |
|---|---|
| Data pipeline | 733 daily files, 4.1 million reports, corrections and cancellations applied, one recorded reason for every excluded trade |
| Pricing library | Calendar, discount curve, swap pricing, normal-model option pricing, risk by curve point (bump and automatic differentiation) |
| Curve model | A Kalman filter that updates the whole curve with each trade and predicts the next one |
| Scoring | Walk-forward tests, baselines, significance tests, calibrated uncertainty bands, sensitivity and stress-day analysis |
| Research | Cross-market correlations, implied against realised volatility, rich/cheap screen, drivers of the gap to fair |
| Order flow | A self-exciting (Hawkes) model of trade arrivals around data releases; trade direction inferred from the fair rate and tested as a predictor; a test of late-day drift |
| Swap futures | An Eris SOFR swap futures engine (price = 100 + value to come + amounts paid - interest on margin) checked against exchange settlements; a margin rule fitted to published margins; margin funding cost of a swap against the future |
| Web app | Twelve screens for traders and analysts, including multi-model pricing and a model lab; saved trades; a live feed from the public ticker |

## Run it

Everything, with troubleshooting, is in [RUNBOOK.md](RUNBOOK.md). In short:

```bash
pip install -e ".[dev]"
```

```bash
python -m tapemark fetch --start 2024-11-09 --end 2026-11-13 --workers 8
```

```bash
python -m tapemark build
```

```bash
python -m tapemark score
```

```bash
python -m tapemark serve
```

Then open <http://127.0.0.1:8765>.

## Documentation

| Document | Answers |
|---|---|
| [RUNBOOK.md](RUNBOOK.md) | How to run every part, how saving works, real-time data, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | What the system is, how data flows, the data model, how it runs |
| [docs/DESIGN.md](docs/DESIGN.md) | Module contracts, tables, every cleaning rule and the edge case behind it |
| [docs/MODELS.md](docs/MODELS.md) | Every equation, what it assumes, where the assumption fails |
| [docs/METHOD.md](docs/METHOD.md) | How results are tested: walk-forward, baselines, known biases |
| [docs/VALIDATION.md](docs/VALIDATION.md) | The validation framework and how to read the report |
| [docs/LITERATURE.md](docs/LITERATURE.md) | The published method behind each part, and what this data showed |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | Product quirks that change the price, and the status of each |
| [docs/adr/](docs/adr/README.md) | Decisions and their reasons, one file each |
| [CHANGELOG.md](CHANGELOG.md) | What changed, by version |

## Layout

```
src/tapemark/
  sources/    one module per public data source (DTCC, Eris, Federal Reserve)
  clean/      trade lifecycle, swaps, swap options; one exclusion reason per trade
  pricing/    calendar, curve, swaps, options, Hull-White, risk. Pure functions
  models/     the curve filter
  scoring/    walk-forward scoring of swaps, options and risk
  markets.py  other currencies and inflation swaps from the same files
  insights.py patterns in the data
  validation.py  the validation pack
  server/     web service: read models, pricing, saved items, live feed
web/          the frontend: plain HTML, CSS and JavaScript, no build step
cpp/          the C++ revaluation kernel (python tools/build_cpp.py)
tests/        96 tests: rules, pricing identities, QuantLib, risk, swap futures, the clustering estimator, the web service
tools/        render_screens.py: every screen in a real browser at three settings, layout and accessibility checked
docs/         architecture, design, models, method, validation, decisions
```

## Automation

- **Every push:** lint (`ruff`) and tests.
- **Every weekday, 06:00 UTC:** the pipeline runs on the last ten days of real files and fails loudly if a source has changed.

## Data sources

| Source | What | Access |
|---|---|---|
| DTCC public price dissemination | Every reported rates swap and swap option trade; a live ticker | Free; daily files from 9 Nov 2024 |
| Eris SOFR end-of-day files | An independent daily SOFR curve, used as a referee | Free; anonymous access ends 1 Jan 2027 |
| Federal Reserve Board | Fitted Treasury yield curve, daily since 1961 | Free |
| New York Fed | Daily SOFR with the spread of rates paid and volume | Free |

Downloaded data is not redistributed in this repository. Check each
provider's terms before sharing files.

## Prior work

Public projects already fetch this data and price these products, notably
[Curvy-CUSIPs](https://github.com/yieldcurvemonkey/Curvy-CUSIPs). Tapemark's
contribution is the evaluation: every model is scored on held-out real
trades against simple baselines, and the report says where it loses.
