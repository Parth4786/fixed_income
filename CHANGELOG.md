# Changelog

All notable changes to this project are recorded here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Relative value screen (`rv.py`, `/api/rv`): PCA fair value of every curve point and PCA-weighted 1s2s5s, 2s5s10s and 5s10s30s butterflies, fitted day by day on the previous 250 days of six years of Eris SOFR curves; z-scores, half-lives, and a backtest of past 2σ readings. Points reverted 44-79% of the time within 20 days; flies 29-40%, which the screen states.
- Caps and floors on compounded SOFR (`pricing/caps.py`, `/api/price/cap`, a third product on Price a trade): quarterly caplets in the normal model with Lyashenko-Mercurio in-arrears variance; at the money where cap equals floor; parity with the swap tested. The default volatility is borrowed from the swap option surface and labelled; the user can type their own. Caps can be saved and repriced like other trades.
- Greeks on Price a trade: swap gamma by full curve rebuild (held to the AD DV01), three-month carry and roll-down on an unchanged curve with the breakeven move, and normal-model gamma and theta per day for options.
- This week screen (`weekly.py`, `/api/week`): the week's move at every swap length, the Fed meeting path now against a week ago (hawkish or dovish, in bp), and every similar week since October 2020 with what followed over the next four weeks, drawn as dots.
- Model governance screen (`governance.py`, `/api/governance`): the validation report's five monitoring alarms computed daily (green, amber, red); forecast evaluation in a validator's terms (RMSE, MAE, Theil's U 0.71, bias, Mincer-Zarnowitz with day-clustered errors, hit rate 84%); the VaR backtest with Kupiec and Christoffersen tests; a model inventory whose evidence is read from result files; data lineage with SHA-256 fingerprints of the newest source files and every result file.
- Bermudan swap options under Hull-White (`pricing/bermudan.py`, ADR 25), priced two independent ways. The PDE is Crank-Nicolson with Rannacher smoothing. The Monte Carlo is Longstaff-Schwartz on exact joint simulation of the factor and its integral, with the exercise rule fitted out of sample. Both are anchored to the exact European price: the PDE is within 0.022% at worst on 250 real calibrated days. Price an option now shows the every-reset price, the value of waiting and the exercise boundary by date. Accuracy shows convergence, the history and how much the Bermudan moves with mean reversion when the European is held fixed (11%).
- Book risk screen (`treasury.py`): the six supervisory interest rate shocks of the Basel IRRBB standard as specified in the EBA's supervisory outlier test (sizes, maturity decay, steepener/flattener weights, post-shock floor), with full repricing; the 15%-of-Tier-1 outlier test; historical VaR and expected shortfall from six years of published curves; a 250-day VaR backtest with Basel's traffic-light zones.
- A real book: the Federal Reserve's Treasury holdings, security by security (New York Fed, weekly), priced on the Fed's fitted zero-coupon Treasury curve: $3.78tn, duration 5.4 years, worst shock parallel up (−$361bn), 1-day VaR $27.7bn, backtest green.
- C++ revaluation kernel (`cpp/revalue.cpp`, loaded through ctypes by `tapemark.fast`, built by `tools/build_cpp.py` and in CI): identical to the NumPy reference, about 2.6-3x faster on full-repricing VaR.
- Daily brief screen: one page of the latest numbers, saved as PDF from the browser.
- The "Add three example trades" button is removed: every position in the app is one the user entered, and every other number comes from published data.
- Steps on Fed meeting dates (`models/meeting_curve.py`, ADR 23): the first two years of the curve rebuilt as an overnight rate that changes only after scheduled meetings, keeping every curve point. Scored beside the smooth curve on forward swaps maturing within two years: under a year 1.10 → 1.07 bp (t 3.1); one to two years, no reliable difference. Shown as a model row on Price a trade and as "What the market prices for each Fed meeting" on Today.
- Inflation two ways (Other markets): inflation swap rates from public trades against TIPS breakevens from the Federal Reserve's fitted curve (`fed.breakevens`), same day and maturity, put on the same compounding. The gap averaged +9.2 bp at 10 years over 435 days.

### Changed
- Fourth design pass, after an independent review graded the app 7/10: a type scale of eight sizes instead of 22; status pills are quiet dots unless amber or red; every chart axis carries its unit; signed risk is no longer drawn in rise/fall colours; currency curves share one vertical span; the inflation card plots the swap-TIPS gap against its typical level; Trades drops the repeated "unusual" badge and pages on phones; Patterns and Accuracy open with four numbers instead of four sentences.
- Patterns and Accuracy keep each card's number, chart and one bold takeaway in view; method notes fold into a closed "Method and caveats" section. On a phone, any table wider than the screen becomes one card per row: no table scrolls sideways on any screen. RUNBOOK section 6 lists every free source, how often it updates and how the app picks it up, and what true streaming would need.
- Price a trade is now a ticket and a quote. The ticket has Pay/Receive buttons, one-tap tenor chips and size in $m, and reprices as you type; a slower answer to an older request is dropped. The quote leads with the fair rate (or model premium) in large type, the range 9 in 10 recent trades landed in, your rate against it, and four figures: value, gain per bp, normal range and dates. The separate Verdict, "trade in numbers" and four-number strip are merged into it.
- Third design pass, aimed at a reader who knows some fixed income. The app opens on Today, not on the pitch page (now "What this is" under About). Today leads with a curve monitor: every swap length and the 2s10s, 5s30s and 2s5s10s spreads, each with level, 1-day, 1-week and 1-month change, place in the past year's range, a 60-day trend, 3-month roll-down and the 3-month forward (`/api/monitor`). Card explanations moved behind an ⓘ button, which prints in full on the Daily brief. Numbers are set in IBM Plex Mono with tabular figures, cards are denser, and the data status reads "Closing data" instead of a red "unreachable". The 1-year forward chart is gone: the monitor's forward column and the Fed meeting path cover it.
- Second independent design review (graded 7/10 before these changes): every remaining card now leads with a number, orange means only "what the model is compared with", swap lengths and gaps use one format, time axes tick on evenly spaced months, short cards no longer stretch, thin currencies are listed on one line instead of empty boxes.

### Fixed
- On a forward-starting swap, Price a trade now shows every model's record on forward swaps; it showed the main model's record on ordinary swaps, which flattered it.
- "Days the model beat the last trade: 464" was wrong: 464 is the number of trading days compared. Reworded everywhere, with the Diebold-Mariano statistic shown as 24.5.
- Today and Trades counted trades outside the normal range differently (86 against 73); both now say 86, split into 73 unusual and 13 off-market.
- The price screen showed "at fair" when no rate had been typed.

## [0.3.0] - 2026-11-15

### Added
- Swap futures engine (`pricing/eris_futures.py`, `futures.py`): cash flows, value to come (A), amounts paid (B) and the daily interest-on-margin step (C) of Eris SOFR swap futures, checked against the exchange's settlement file for every listed contract on 60 days.
- Margin rule fitted to published exchange margins on six years of daily curves; margin today and discounted margin-years for a swap and for the equivalent futures. "Swap or future?" card on Price a trade with a funding spread the user sets.
- Order flow studies (`flow.py`): a two-stream self-exciting model of trade arrivals in one-second steps around consumer price and jobs releases; trade direction inferred from the fair rate, with flow regressed on the move in the same and the next ten minutes; a test of late-day drift after large moves.
- Eris sources: settlement files and the historical par curve since October 2020.
- Charts draw at the real width of their card and redraw when it changes; ranked rows replace a bar chart whose names could not fit.
- 16 tests: estimator recovery on sequences with known triggering, the baseline trap, futures conventions worked by hand, margin and API checks.

- Option checks against the exchange (`futures.check_options`): the normal-model pricer against every settled option price on Eris swap futures, and the project's volatility grid against the exchange's at-the-money volatility.
- Margin backtest (`eris_futures.coverage`): for every day after the first 500, the margin set from the past alone is compared with the move that followed. The exchange's marketing claim that futures margin is "up to 65% lower" is quoted as context and is not used in any calculation.
- `tools/render_screens.py`: renders all twelve screens at desktop, phone and dark settings in a real browser, audits the layout and saves images.
- Tables drop their lower-priority columns on a phone, and the correlation grid switches to numbered rows and columns with values in hundredths; no table scrolls sideways at phone width.
- Accessibility: the screen check runs axe-core on every screen in both themes. Six kinds of problem were found and fixed: text contrast below 4.5:1 (caption grey, warning chips, the active menu item, numbers on coloured cells, button text in the dark theme), charts with no text name, table columns with no header, links marked only by colour, scroll areas unreachable by keyboard, and a skipped heading level. Values resting on few trades are now marked with a dotted underline instead of being faded.
- Swap margin low end follows the published structure of the clearing house's model: five days, past moves rescaled to current volatility, with an unscaled floor (`eris_futures.worst_moves_scaled`).
- Model lab leaves a thin day out of its chart and names it; its runs are kept, and the default one is prepared at startup (7.4 s down to under 0.5 s on first open).
- Frontend reworked after an independent design review of the rendered screens (15 findings, ADR 22): every card leads with one number and a verdict, with tables behind a closed details element; Price a trade opens with four numbers; Trades lists clean trades first, separates "off-market terms" from "unusual", and shows only comparable rows in the live feed; one name, colour and number format per idea across screens; month-based time axes; forwards drawn as points; four null results gathered in one table.
- The screen check records time to content per screen: median 0.26 s, slowest 0.7 s.

### Fixed
- Swap rate minus Treasury yield compared a current swap rate with a Treasury curve up to a week old, which produced a false jump at the end of the chart and a wrong headline figure (-15.2 bp instead of -41.3 bp). Both rates now come from the same day, and nothing is carried forward.
- `scikit-learn` was used but not declared as a dependency, so `score` failed on a clean install.
- `score` crashed on histories shorter than about 240 trading days (the curve-forecast study); it now reports that it needs more history.
- A date calculation used a form numpy has deprecated and will reject in a later version.
- The live feed showed a full date and time; the fix had been applied to a different table.
- Charts drawn a moment after the page is built were erasing the notes placed under them in the same card (a regression from drawing charts at their card's real width). Each chart now has a container of its own.

### Changed
- `docs/LITERATURE.md`: every reference checked against a publisher, DOI or RePEc record. Corrected: Bailey et al. is 2017 (*Journal of Computational Finance*); Angelopoulos and Bates is a preprint; Giles and Glasserman describes the adjoint form, not the forward form used here; SR 11-7 was replaced by SR 26-2 in April 2026. One entry is marked as not confirmed.
- The Data quality screen's audit is built once and kept (2.5 s down to under 0.1 s on later visits).
- Number fields accept any value; the option form no longer rejects its own default.
- Bar and axis labels are placed by available width and never overlap; long series names no longer clip.

### Findings recorded
- Futures engine against the exchange: value to come within $0.27 a contract at worst, amounts paid within $0.01, risk within 0.1% (median).
- Best margin rule: a two-day move at 99%, within 12.5% of the published margin for the typical contract. Five days at the same confidence gives 1.47 times as much.
- Share of trading triggered by earlier trades: 0.23 (release mornings), 0.30 (other mornings), 0.24 (mid-morning). With a flat baseline release mornings read 0.56.
- Net paying flow of $1bn of ten-year equivalents goes with a 1.07 bp rise in the same ten minutes and does not predict the next ten.
- No late-day drift: on 39 days with a move of 8 bp or more by 2 pm, 46% continued.
- Option pricer against the exchange: 100% of 89,014 settled option prices reproduced within one price step.
- Margin backtest on 1,025 later days (Oct 2022 to Nov 2026): the futures rule covered 99.13% of moves and the swap rule 99.44%, against the regulatory standard of 99%. Weakest year 2022, at 98.89%.
- Rescaling history to current volatility fits the published futures margins no better (13.6% typical miss against 12.5%) and leaves the 10-year swap figure unchanged today, because current volatility is close to its six-year norm.
- All 47 release days in the calendar match the dated links in the Bureau of Labor Statistics archive.
- Volatility grid against the exchange at option lives up to four months: typically 6.9 bp away and 5.4 bp higher; correlation of daily changes is about zero. The grid is a guide to the level, not a daily mark.

## [0.2.0] - 2026-11-15

### Added
- Hull-White one-factor rate model (`pricing/hullwhite.py`): closed-form swap-rate volatility, checked against the model's exact price by numerical integration; calibrated daily to earlier trades and scored walk-forward beside the other option predictors.
- Bias audit in the validation pack: a causality test for look-ahead, separate scoring of amended and late-published trades, the model's miss on each group of excluded trades, and the share of repeated rows collapsed.
- Model lab screen and `POST /api/lab`: rerun the curve model on recent real trades with other settings.
- Phone-width layout and dark theme verified on every screen.
- Two published models replicated on the data: an execution-cost regression with errors clustered by day plus the Roll effective spread, and the Diebold-Li yield curve forecast against a random walk.
- `docs/LITERATURE.md`: the published source behind each method and what this data showed.
- Pricing library from first principles: bond-market calendar, discount curve with closed-form bootstrap, swap pricing, normal-model option pricing, SABR normal volatility.
- Curve model: a Kalman filter that updates the whole curve with each trade, with damping of absurd trades.
- Walk-forward scoring of swaps against three baselines, a Diebold-Mariano significance test, and conformally calibrated uncertainty bands.
- Fully held-out test on forward-starting swaps.
- Option scoring: implied volatility from real premiums, five predictors compared out of sample.
- Risk by curve point by bump-and-rebuild and by forward-mode automatic differentiation; value-change explanation; scenario repricing.
- Hedge test on real trades with next-day revaluation on an independent curve.
- Validation pack: referee checks, residual diagnostics, sensitivity to settings, block stability, worst-day analysis, speed benchmarks.
- Other markets: overnight-index swap curves in seven currencies and US inflation swaps from the same files; Treasury curve and SOFR from the Federal Reserve.
- Research patterns: rich/cheap screen, cross-market correlations, implied against realised volatility, time-of-day effects, a gradient-boosted model of the gap to fair.
- Web service (FastAPI) with read models, pricing endpoints, create/read/update/delete for saved trades and day notes, and a live feed from the public ticker pushed by server-sent events.
- Frontend: eleven screens with plain-language summaries, hover definitions, light and dark themes.
- `tapemark score` and `tapemark serve` commands; RUNBOOK.md; docs/VALIDATION.md.
- 44 more tests, including QuantLib comparison and end-to-end tests of the web service.

### Findings recorded
- "Call" in the public data means the right to pay fixed.
- For swap options the last similar trade predicts better than a fitted volatility surface; the app uses it.
- Premiums reported on package legs are not standalone prices (about 80 bp of volatility away from any model).
- One execution is sometimes published as several identical rows (1.1% of prints); they are collapsed before scoring.
- A one-factor Hull-White model cannot fit the traded volatility surface: it misses by about 16 bp of volatility against 4 for the last similar trade, and its pull-back speed sits at the edge of its range on 61% of days.

## [0.1.1] - 2026-11-14

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
