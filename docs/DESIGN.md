# Detailed design

Module-level design: contracts, table definitions, cleaning rules and how
failures are handled. The big picture is in [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Module contracts

### `tapemark.sources.dtcc`

| Function | Input | Output | Notes |
|---|---|---|---|
| `fetch(day, force=False)` | calendar date | path, or `None` if no file | Skips existing files. Writes to `.part`, verifies the zip, then renames, so a broken download never looks complete. 403 and 404 mean "no file that day". |
| `read(day, columns=None)` | date | all rows, every column text | Nothing is parsed here. With `columns`, absent ones are added blank and listed in `attrs["missing_columns"]`. |
| `read_usd(day)` | date | dollar swaps, dollar options, and every correction and cancellation | See ADR 4 for why corrections are never filtered by product. |
| `available_days()` | none | sorted dates with a raw file | |

### `tapemark.sources.eris`

| Function | Output | Notes |
|---|---|---|
| `fetch(day, kind)` | path or `None` | Tries the live folder, then `archives/YYYY/MM-Month/`. Rejects responses that are not the expected csv. |
| `discount_factors(day)` | series indexed by date | |
| `par_rates(day)` | percent by symbol, e.g. `SOFR10Y` | |

### `tapemark.clean.lifecycle`

`apply_lifecycle(raw) -> trades`

- Keeps reports with action `NEWT` and event `TRAD`: new, price-forming trades.
- A `CORR` report replaces the report it points to. Chains are followed to the last correction.
- An `EROR` report removes the trade, whether it points at the original or at a later correction.
- `MODI`, `TERM`, and `NEWT` with events `COMP`, `NOVA`, `EXER` are events on existing positions. They carry no new market price and are dropped.
- Adds `trade_id` (id of the first report) and `n_corrections`. Records counts in `attrs["lifecycle"]`.
- Works on one day or many. A correction arriving days later is applied when both rows are present.

### `tapemark.clean.swaps` and `tapemark.clean.swaptions`

Pure functions: lifecycle-cleaned trades in, typed table out. Rows whose
essential fields cannot be parsed are dropped. Every remaining row gets
exactly one `exclusion` value: the first rule it fails, or blank.

## 2. Tables

### `clean/usd_sofr_swaps.parquet`

| Column | Type | Meaning |
|---|---|---|
| `trade_id` | text | Id of the trade's first public report |
| `exec_ts` | timestamp, UTC | When the trade was agreed |
| `trade_date` | date | Date part of `exec_ts` |
| `effective`, `maturity` | date | When interest starts and stops |
| `fixed_rate_pct` | number | Agreed fixed rate, in percent |
| `notional` | number | Size in dollars |
| `notional_capped` | true/false | Published size was capped (source shows a trailing `+`) |
| `venue` | text | Trading platform code |
| `cleared`, `block`, `package`, `upfront_payment` | true/false | Flags from the report |
| `fixed_day_count`, `fixed_frequency` | text | Fixed leg conventions as reported |
| `n_corrections` | integer | Times the report was amended |
| `start_lag_bdays` | integer | Business days from trade to start |
| `start` | text | `spot`, `forward` or `backdated` |
| `tenor_years` | number | Length of the swap |
| `known_date` | date | Day this version of the row became public |
| `report_lag_days` | integer | `known_date` minus `trade_date` |
| `exclusion` | text | Why it is not a clean price; blank if it is |
| `standard` | true/false | `exclusion` is blank |

### `clean/usd_swaptions.parquet`

| Column | Type | Meaning |
|---|---|---|
| `trade_id`, `exec_ts`, `trade_date`, `known_date` | | As above |
| `expiry` | date | Day the holder decides |
| `swap_maturity` | date | End of the swap the option is on |
| `strike_pct` | number | Fixed rate of that swap, in percent |
| `premium`, `premium_ccy` | number, text | Price paid for the option |
| `notional`, `notional_capped` | | As above |
| `reported_type` | text | `call` or `put` as reported. Which one means "pay fixed" is settled by price checks in stage 4, not assumed. |
| `package` | true/false | Traded as part of a bundle |
| `option_years`, `swap_years` | number | Time to expiry; length of the swap |
| `premium_bp_of_notional` | number | Premium as hundredths of a percent of size |
| `exclusion`, `usable` | | As above |

## 3. Cleaning rules and the edge cases behind them

| Situation in the data | What is done | Why |
|---|---|---|
| A trade is corrected, sometimes several times | Last correction wins; first id kept | The corrected terms are the true ones |
| A trade is cancelled after being corrected | Removed | The cancellation can point at either report |
| A correction changes the product type | Kept through lifecycle, then filtered | Otherwise the superseded original survives (ADR 4) |
| Correction arrives days after the trade | Applied across files | Builds read all days together |
| Compression, novation, exercise reported as "new" | Dropped | Not a new market price |
| Size shown as `250,000,000+` | Parsed, flagged `notional_capped` | Rules cap published size for large trades |
| Thursday trade starting Monday | `spot` | Two business days, not four calendar days (ADR 5) |
| Start date before trade date | `backdated`, excluded | Rate reflects an old agreement |
| Start date far ahead | `forward`, excluded from clean set | A forward rate, not today's rate. Used later in its own right. |
| Trade is one leg of a package | Excluded from clean set, kept in table | Its price reflects the whole bundle |
| Side payment attached | Excluded from clean set | The fixed rate is off-market by design |
| Swap of a year or less with one payment at maturity | Treated as standard | That is the normal schedule at that length (ADR 9) |
| Swap with an early-termination right | Excluded: `has an embedded option` | The rate includes the value of the right |
| Reporter flags non-standard terms | Excluded | Special terms unknown |
| Spread on the floating side | Excluded | Fixed rate is offset by it |
| Fixed rate like 0.000019 | Excluded by range check | Unit or entry error |
| Option premium 0 or blank | Excluded | Price is elsewhere in a package |
| Timestamp or date cannot be parsed | Row dropped | Cannot be placed in time |
| True/false written as `true` in older files and `TRUE` in newer ones | Compared without regard to case | The source changed spelling on 3 Nov 2025 (ADR 11) |
| A column is absent in older files | Filled blank, counted in the report | Schema has changed over time |
| A daily file is unreadable | Recorded as `.error.txt`, build continues | One bad day must not stop two years |
| Weekend files | Downloaded | DTCC publishes late reports on weekends |
| Public holiday | Very low volume, flagged in report | Should be explained, not silently used |

## 4. Failure handling

| Failure | Behaviour |
|---|---|
| Network error on one day | Logged as failed; rerun fetches only what is missing |
| Truncated download | Zip check fails, partial file deleted |
| Source returns an error page with status 200 | Content check rejects it (Eris) |
| Unreadable daily file | Skipped and recorded; count shown in build stats |
| Empty clean set | Commands exit with a message saying what to run first |

## 5. Testing

| Kind | Where | What it protects |
|---|---|---|
| Rule tests | `tests/test_lifecycle.py` | Each lifecycle rule, including chains and cancel-after-correct |
| Labelling tests | `tests/test_swaps.py` | Number parsing, business-day start, capped size |
| Exclusion tests | `tests/test_exclusions.py` | Every rule reachable; one reason per row; waterfall adds up; unusual-day flag |
| End to end | nightly workflow | Real files still download and parse |
| Reference tests | planned, stage 1 on | Prices match an independent library |

Tests use hand-built rows with the real column names, so they are fast and
need no network. They are fixtures for code correctness, not model inputs:
every result the project reports comes from real data.
