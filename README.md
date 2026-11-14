# Tapemark

A valuation and model-checking platform for interest rate swaps and swap
options, built only on free public data.

US rules require every reported swap and swap option trade to be published.
Tapemark downloads those reports, cleans them, prices the trades with standard
models written from first principles, and then scores each model on trades it
has never seen. Nothing is simulated.

**The question it answers:** how accurately can public data reconstruct the
prices real traders paid, and what explains the part it gets wrong?

## Status

| Stage | What | State |
|---|---|---|
| 0 | Download, lifecycle, clean tables, data audit | Working, tested |
| 1 | Bond and swap pricing from first principles | Next |
| 2 | SOFR curve from the day's trades | Planned |
| 3 | Walk-forward score on swaps | Planned |
| 4 | Volatility from traded option premiums | Planned |
| 5 | Walk-forward score on options | Planned |
| 6 | Risk by market input, by bumping and by automatic differentiation; value change of real trades explained | Planned |
| 7 | Desk decisions on real trades: hedge and measure what it removed, stress scenarios, quote with uncertainty | Planned |
| 8 | Stretch: one term-structure model on the same scorecard; optional compiled core | If the data supports it |

Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Run it

```bash
pip install -e ".[dev]"
```

```bash
python -m tapemark fetch --start 2026-11-02 --end 2026-11-13
```

```bash
python -m tapemark build
```

```bash
python -m tapemark report
```

```bash
pytest
```

`fetch` is resumable: rerun it and only missing files are downloaded. The full
history (`--start 2024-11-09`) is about 1.3 GB. Data lands in `data/`, which is
git-ignored. Raw files are kept exactly as downloaded; everything else can be
deleted and rebuilt.

## How results are judged

Read [docs/METHOD.md](docs/METHOD.md) before trusting any number. In short:
models are scored only on unseen trades, time only moves forward, every model
must beat a simple baseline, and every score is shown with the share of trades
it covers.

## Documentation

| Document | Answers |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | What the system is, how data flows, the data model, how it runs |
| [docs/DESIGN.md](docs/DESIGN.md) | Module contracts, table definitions, every cleaning rule and the edge case behind it |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | Product quirks that change the price, and whether each is handled, planned or open |
| [docs/MODELS.md](docs/MODELS.md) | Every equation, what it assumes, where the assumption fails |
| [docs/METHOD.md](docs/METHOD.md) | How results are tested: walk-forward, baselines, known biases |
| [docs/adr/](docs/adr/README.md) | Decisions and their reasons, one file each |
| [CHANGELOG.md](CHANGELOG.md) | What changed, by version |

## Automation

- **Every push:** lint (`ruff`) and tests.
- **Every weekday, 06:00 UTC:** the full pipeline runs on the last ten days of real files and fails loudly if a source has changed. The data quality report is kept as a workflow artifact.

## Layout

```
src/tapemark/
  sources/   one module per public data source (DTCC trades, Eris curve)
  clean/     trade lifecycle, swaps, swaptions; one exclusion reason per trade
  report.py  one-page data quality report
  cli.py     fetch, build, summary, audit, report
tests/       lifecycle, labelling and exclusion rules, case by case
docs/        architecture, design, models, method, decision records
.github/     lint and tests on push; nightly end-to-end data check
```

## Data sources

| Source | What | Access |
|---|---|---|
| DTCC public price dissemination | Every reported rates swap and swaption trade | Free daily files, from 9 Nov 2024 |
| Eris SOFR end-of-day files | Daily SOFR discount curve and par rates, used as an outside check | Free; anonymous access ends 1 Jan 2027 |
| NY Fed | Daily SOFR fixing | Free API, from Apr 2018 |

Downloaded data is not redistributed in this repository. Check each
provider's terms before sharing files.

## Prior work

Public projects already fetch this data and price these products, notably
[Curvy-CUSIPs](https://github.com/yieldcurvemonkey/Curvy-CUSIPs). Tapemark's
contribution is the evaluation: held-out real trades, baselines, and a
breakdown of pricing error. Established libraries (QuantLib, rateslib) are
used in tests as referees.
