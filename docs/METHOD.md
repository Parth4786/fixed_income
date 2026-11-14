# How Tapemark is judged

This file is the contract for every result the project reports. If a number
in a report was not produced under these rules, it does not count.

## The research question

How accurately can free public data reconstruct the prices of real swap and
swap option trades, and what explains the part it gets wrong?

The project is a valuation and model-checking platform. It is not a new
pricing library; good ones exist and are used here as referees.

## First principles

1. **A model is judged only on trades it has not seen.** Fitting a model to
   prices and then reporting how well it matches those same prices proves nothing.
2. **Use only what was known at the time.** A trade at 10:14 is priced with
   information available before 10:14.
3. **Every model must beat a simple baseline.** If a clever model is no better
   than "use the last trade", the clever model has not earned its place.
4. **Report what was left out.** Every accuracy figure is shown with the share
   of trades it covers.
5. **Publish the failures.** Buckets, days and trade types where the model is
   poor are part of the result.

## How the test is run (walk-forward)

Time only moves forward. For each trading day D:

| Test | Fit on | Judge on | Question answered |
|---|---|---|---|
| Same-day, later trades | Trades on D before time t | Trades on D after t | Given this morning, can it price this afternoon? |
| Next day, fresh inputs | Rates on D+1, volatility from D | Option trades on D+1 | Is yesterday's volatility still right once rates are updated? |
| Next day, nothing new | Everything from D | Trades on D+1 | How fast does the model go stale? |

No trade is ever in both the fitting set and the judging set. Settings are
chosen on the first part of the history and then frozen for the rest.

## What is measured

- **Swaps:** model rate minus traded rate, in basis points. By swap length,
  time of day, trade size and venue.
- **Swap options:** model premium minus traded premium, and the same gap
  divided by vega, so it reads as a volatility error. Trades with almost no
  vega are reported separately because that division is unstable.
- **Risk numbers:** does a hedge sized by the model's sensitivity reduce the
  next-day value change of real trades? By how much?
- **Stability:** how much fitted parameters and sensitivities move day to day.
- **Coverage:** share of all trades each figure includes.

## Baselines every model must beat

| Product | Baseline |
|---|---|
| Swap | Last traded rate at that length; previous day's closing curve |
| Swap option | One flat volatility for the day; yesterday's volatility for that bucket; straight-line interpolation between traded strikes |

## Known biases and the control for each

| Bias | How it would mislead | Control |
|---|---|---|
| Look-ahead | Judging a morning trade with the closing curve | Curves are built from trades before the timestamp only |
| Leakage | Fitting and judging on the same trades | Strict time split; judging set never touches fitting |
| Selection | Only clean trades are scored (about 16% of dollar swaps) | Coverage shown beside every figure; excluded trades compared with included |
| Package pricing | A leg's reported price reflects the whole bundle | Standalone trades scored separately; packages studied as their own question |
| Reporting | Cancelled, corrected and late reports | Lifecycle applied; each row keeps when it became known |
| Capped sizes | Large trades are published with size capped | Flagged; never used where size matters |
| Benchmark | The outside curve is itself a model, and its free access ends 1 Jan 2027 | Archived now; a second referee library; our own curve from trades |
| Unit and convention errors | A wrong premium unit can still give plausible volatility | Unit tests, bounds, cross-check with published volatility data |
| Thin data | Few option trades per bucket | Minimum counts, uncertainty ranges, pooling across days stated openly |
| Too many attempts | Trying many models and reporting the best | Metrics and baselines fixed in advance; all variants reported |
| Short history | Public record starts November 2024 | Stated with every result; no claim beyond that period |

## Checks before any model is trusted

1. Formulas match hand-worked cases.
2. Prices and sensitivities match an independent library on the same inputs.
3. Internal identities hold (for example, a swap priced at its own par rate is worth zero).
4. Then, and only then, the walk-forward test against real trades.

## Watching it run

Each daily run records: files received, row counts against the recent average,
share of trades that survive cleaning, curve fit error, and the day's scores.
A run that falls outside its normal range is flagged, not silently published.
Every reported price can be traced to the curve and inputs that produced it.

## Data

| Source | Use | Coverage |
|---|---|---|
| DTCC public trade reports | The trades | From 9 Nov 2024 |
| Eris end-of-day SOFR files | Outside curve to check against | Archived from Nov 2024; anonymous access ends 1 Jan 2027 |
| NY Fed SOFR | Daily overnight rate | From Apr 2018 |
