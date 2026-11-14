# Changelog

All notable changes to this project are recorded here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Month-by-month data audit (`tapemark audit`): coverage, share of clean trades, and agreement with an outside curve.
- Parallel, resumable history download (`tapemark fetch --workers`), including weekend trade files and the Eris archive folders.
- Per-day staging tables so two years of history builds without loading every column.
- `docs/METHOD.md`: the rules every reported result must follow (walk-forward testing, baselines, known biases).
- One recorded exclusion reason per trade (the first rule it fails), so exclusions add up and can be audited.
- One-page data quality report (`tapemark report`): exclusion waterfall, month-by-month coverage, agreement with an outside curve, unusually quiet days, schema changes.
- `known_date` and `report_lag_days` on every swap: the day each row became public.
- An unreadable daily file is recorded and skipped instead of stopping the build.
- `docs/ARCHITECTURE.md` (context, data flow, data model), `docs/DESIGN.md` (contracts, tables, cleaning rules), `docs/MODELS.md` (equations and assumptions).
- `docs/adr/`: design decisions, one file each.
- Continuous integration: lint and tests on every push; a nightly end-to-end run on real files.

### Changed
- Roadmap extended after benchmarking against desk job requirements: risk by automatic differentiation (stage 6), hedging, stress and quoting decisions on real trades (stage 7), and a stretch term-structure model (stage 8).
- README repositions the project as a valuation and model-checking platform and credits prior public work.

### Fixed
- True/false fields were matched in uppercase only. The source wrote them in lowercase until 2 Nov 2025, so a year of package trades was counted as clean. Found by the month-by-month table in the data report; fields are now read without regard to case.
- Swaps of a year or less were excluded as "non-standard schedule" although a single payment at maturity is their normal schedule (about 176 trades a day).
- Swaps with embedded early-termination rights, a reporter's non-standard flag, or a spread on the floating leg were treated as clean prices. They now have their own exclusion reasons. The largest 10-year outlier in the sample was one of these.
- Swaps traded on a Thursday or Friday were wrongly labelled as non-standard because the start date was measured in calendar days. It is now measured in business days. Found by the first real ten-day run.
- Corrections that reclassify a trade were dropped by filtering to dollar products before applying corrections, leaving the superseded original in the data. Corrections and cancellations are now always kept.

## [0.1.0] - 2026-11-14

### Added
- Download of DTCC public swap trade files and Eris end-of-day SOFR curve files.
- Trade lifecycle: corrections replace, cancellations remove, post-trade events are excluded.
- Clean tables of US dollar SOFR swaps and US dollar swaptions.
- Command line: `fetch`, `build`, `summary`.
- Tests for lifecycle rules and swap labelling.
