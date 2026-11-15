# Validation framework

How the models are checked before anyone relies on them. The structure
follows what a bank's model-risk review asks, in the order it asks it.
`python -m tapemark score` runs every check and writes
`data/reports/model_validation.md`.

## The seven questions

| Question | Check | Where |
|---|---|---|
| 1. Is the data sound? | Lifecycle applied; one exclusion reason per trade; counts reconcile; month-by-month table for silent source changes | `report.py`, Data quality screen |
| 2. Is the code right? | Hand calculations; pricing identities; QuantLib; an independent curve provider on 25 real days; automatic differentiation against bump-and-rebuild | `tests/`, `validation.referee_checks` |
| 3. Does it work out of sample? | Every trade predicted before it is used; baselines; significance test | `scoring/swaps.py`, `scoring/options.py` |
| 4. Are the uncertainty bands honest? | Share of trades inside the band against the target, overall and by month | `scoring/swaps.py` |
| 5. Is it fragile? | One setting changed at a time; four consecutive blocks; rolling against expanding windows | `validation.sensitivity` |
| 6. How does it behave when it matters? | Accuracy and band coverage on the most violent days | `validation.stress_days` |
| 8. Does the futures engine match the exchange? | Value to come, amounts paid, the daily interest step and risk against the exchange's settlement file, every contract, 60 days | `futures.check_engine`, Accuracy screen |
| 9. Is the margin rule grounded? | Sixteen historical rules scored against published exchange margins; the best one is used. Both rules backtested: margin set each day from the past alone against the move that followed, 1,025 days, standard 99% | `futures.fit_margin` |
| 11. Is the option side right? | Pricer against every exchange-settled option price; volatility grid against the exchange's at-the-money volatility, level and daily changes | `futures.check_options` |
| 12. Does it install and run clean? | Lint, tests and the pipeline in a new environment from `pyproject.toml` on the newest library versions; every screen rendered in a real browser at three settings and audited for layout and accessibility (axe-core, no violations) | `tools/render_screens.py`, RUNBOOK section 8 |
| 10. Are the flow findings artefacts? | The clustering estimator recovers known triggering on built sequences and reports none when there is only a burst in the baseline; the naive fit is published beside the corrected one; the flow forecast is scored on later days | `tests/test_flow.py`, `flow.py` |
| 7. Do the outputs support decisions? | Hedges built from the risk numbers, tested on next-day real moves | `scoring/risk.py` |

## Evaluation schemes used

| Scheme | What it means here | Why |
|---|---|---|
| Walk-forward, one step ahead | Each trade is predicted from all earlier trades, then added | The only scheme with no look-ahead for a model that updates continuously |
| Frozen settings | Tuned on the first 60 trading days, then never changed | A setting re-tuned on the test period would flatter the result |
| Rolling window | How rates move together is estimated on the last 60, 120 or 250 days | Tests sensitivity to how much history is used |
| Expanding window | The same, on all past days | The alternative to rolling; the result barely differs |
| Block stability | The scored period cut into four consecutive blocks | A good average can hide a bad stretch |
| Held-out product | Forward-starting swaps are never used to fit anything | A test the model could not have learned |
| Independent next-day data | Hedge test revalues on an outside closing curve | The model cannot grade its own homework |
| Train and test split by time | The gap-driver model trains on the first 70% of days | Random splits would leak neighbouring trades |

## Statistical tools

| Tool | Use | Formula |
|---|---|---|
| Median and 95th percentile of absolute error | Headline accuracy | Robust to a few absurd prints, which a mean is not |
| Diebold-Mariano test | Is model A reliably better than B? | $t = \bar d / \sqrt{\widehat{\mathrm{Var}}(\bar d)}$, where $d_t$ is the daily difference in average absolute error and the variance uses Newey-West weights for 5 lags |
| Split conformal calibration | Uncertainty bands with a coverage target | Band half-width $= \hat q_t \cdot s_t$, where $s_t$ is the model's own standard deviation and $\hat q_t$ is the 90th percentile of $|e|/s$ over the previous 5,000 trades |
| Lag-1 autocorrelation of errors | Is the model too slow or too fast? | Zero for a well-specified filter; positive means it lags |
| Permutation importance | Which inputs matter to the gap-driver model | Increase in test error when one input is shuffled |
| Principal components | Main patterns of curve moves | Eigenvectors of the covariance of daily changes |

## Verdicts

Each model gets one of three: **fit for use**, **limited use** (with the
condition stated), or **not fit**. The report opens with them. A model that
loses to its baseline is reported as losing.

## What validation cannot show

- That the model will work in a rate regime unlike 2024 to 2026.
- That a trade far from the curve is wrong. The public record omits terms that can justify it.
- That the referee curve is itself correct.

## Monitoring thresholds

| Signal | Alarm when |
|---|---|
| Clean swaps in the nightly window | below 500 |
| Monthly band coverage | outside 85% to 95% |
| Median miss over a week | above twice its trailing average |
| Share of trades damped | above 30% |
| Monthly share of any exclusion reason | changes by more than a third |
