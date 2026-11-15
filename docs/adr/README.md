# Architecture decision records

One file per decision. A decision is never edited after it is accepted; it is superseded by a new record.

| No. | Decision | Status |
|---|---|---|
| 1 | [Public trade reports are the ground truth](0001-public-trade-reports-are-the-ground-truth.md) | Accepted |
| 2 | [Raw files are never edited](0002-raw-files-are-never-edited.md) | Accepted |
| 3 | [Files and Parquet, no database server](0003-files-and-parquet-no-database-server.md) | Accepted |
| 4 | [Corrections are applied before any product filter](0004-corrections-are-applied-before-any-product-filter.md) | Accepted |
| 5 | [Start dates are measured in business days](0005-start-dates-are-measured-in-business-days.md) | Accepted |
| 6 | [Reference libraries are referees, not engines](0006-reference-libraries-are-referees-not-engines.md) | Accepted |
| 7 | [The Eris curve is a reference, archived while it is free](0007-the-eris-curve-is-a-reference-archived-while-it-is-free.md) | Accepted |
| 8 | [Results are only valid under docs/METHOD.md](0008-results-are-only-valid-under-docs-method-md.md) | Accepted |
| 9 | [Every excluded trade carries exactly one reason](0009-every-excluded-trade-carries-exactly-one-reason.md) | Accepted |
| 10 | [Outcomes are summarised by median and tail, not mean](0010-outcomes-are-summarised-by-median-and-tail-not-mean.md) | Accepted |
| 11 | [Coded fields are read without regard to letter case](0011-coded-fields-are-read-without-regard-to-letter-case.md) | Accepted |
| 12 | [The curve is a filter updated by every trade](0012-the-curve-is-a-filter-updated-by-every-trade.md) | Accepted |
| 13 | [Uncertainty bands are calibrated on past errors](0013-uncertainty-bands-are-calibrated-on-past-errors.md) | Accepted |
| 14 | [Surprising trades are damped, not dropped](0014-surprising-trades-are-damped-not-dropped.md) | Accepted |
| 15 | [The simplest option predictor is used because it won](0015-the-simplest-option-predictor-is-used-because-it-won.md) | Accepted |
| 16 | [Risk is computed two ways and must agree](0016-risk-is-computed-two-ways-and-must-agree.md) | Accepted |
| 17 | [The frontend has no build step](0017-the-frontend-has-no-build-step.md) | Accepted |
| 18 | [Live data is polled and never stored](0018-live-data-is-polled-and-never-stored.md) | Accepted |
| 19 | [A one-factor rate model is kept as a measured negative result](0019-a-one-factor-rate-model-is-kept-as-a-measured-negative-result.md) | Accepted |
| 20 | [Trade clustering is measured against the hour's usual course](0020-trade-clustering-is-measured-against-the-hours-usual-course.md) | Accepted |
| 21 | [The futures engine and the margin rule are checked against what the exchange publishes](0021-the-futures-engine-and-margin-rule-are-fitted-to-what-the-exchange-publishes.md) | Accepted |
| 22 | [Every card leads with one number, and the screens are checked by machine](0022-every-card-leads-with-one-number-and-the-screens-are-checked-by-machine.md) | Accepted |
| 23 | [The short end steps on Fed meeting dates, and is kept beside the smooth curve](0023-the-short-end-steps-on-fed-meeting-dates-and-is-kept-beside-the-smooth-curve.md) | Accepted |
| 24 | [Risk frameworks run on real books, and a C++ kernel does the repricing](0024-risk-frameworks-run-on-real-books-and-a-cpp-kernel-does-the-repricing.md) | Accepted |
| 25 | [Bermudan options are priced two ways and anchored to the exact European](0025-bermudan-options-are-priced-two-ways-and-anchored-to-the-exact-european.md) | Accepted |
