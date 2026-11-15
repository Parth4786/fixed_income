# Architecture

High-level design: what the system is, what it talks to, how data moves, and
how it runs. Module-level detail is in [DESIGN.md](DESIGN.md). Reasons for the
choices are in [adr/](adr/README.md).

## 1. Context

Tapemark is a daily batch pipeline plus a small web service. The pipeline
reads public files and writes local tables, model results and reports. The
service reads those results, prices trades on request, stores saved trades and
notes, and follows a public live ticker.

```mermaid
flowchart LR
    DTCC[DTCC public trade reports<br/>one zip per day] --> T
    ERIS[Eris end-of-day SOFR curve<br/>two csv files per day] --> T
    T[Tapemark]
    FED[Federal Reserve<br/>Treasury curve, SOFR] --> T
    TICK[DTCC public ticker<br/>polled every 45 s] --> T
    T --> R[Data quality and model validation reports]
    T --> A[Web app: eleven screens]
    U[Trader or analyst] <--> A
    REF[Reference libraries<br/>QuantLib, rateslib] -. used only in tests .-> T
```

## 2. Layers

Data moves one way through four layers. Each layer can be deleted and rebuilt
from the one before it; only `raw` cannot be recreated once a source closes.

| Layer | Location | Contents | Rebuildable |
|---|---|---|---|
| Raw | `data/raw/` | Files exactly as downloaded | No: this is the archive |
| Stage | `data/stage/` | One table per day: dollar swaps and options, needed columns only, plus all corrections | Yes |
| Clean | `data/clean/` | One row per real trade, typed and labelled, with an exclusion reason | Yes |
| Results | `data/results/` | Per-trade predictions, curve snapshots, option volatilities, summaries | Yes |
| Reports | `data/reports/` | Data quality report and model validation report | Yes |
| Saved items | `data/app.db` | Saved trades and notes on days, written by the app | No: user data |

## 3. Data flow

```mermaid
flowchart TD
    subgraph Sources
        D[(DTCC zip per day)]
        E[(Eris curve csv per day)]
    end
    D -->|fetch: resumable, parallel, zip integrity check| RAW[(data/raw)]
    E -->|fetch: live folder then archive| RAW
    RAW -->|read_usd: keep dollar swaps, dollar options, all corrections| STG[(data/stage, one parquet per day)]
    STG -->|apply_lifecycle: corrections replace, cancellations remove, events dropped| TR[Real trades]
    TR -->|usd_sofr_swaps: type, label start, one exclusion reason| SW[(clean/usd_sofr_swaps)]
    TR -->|usd_swaptions: type, measure, one exclusion reason| OP[(clean/usd_swaptions)]
    SW --> RPT[report: waterfall, monthly table, curve agreement, flagged days]
    OP --> RPT
    RAW -->|Eris par rates| RPT
    RPT --> OUT[(data/reports/data_quality.md)]
    SW -->|curve filter, one trade at a time| SC[(results/swap_scores, curve_snapshots)]
    SC -->|forward-starting swaps priced, never fitted| FW[(results/swap_forward_scores)]
    OP -->|forward rate and annuity from the curve as of each trade| OV[(results/option_vols, option_scores)]
    SC -->|hedge and revalue next day on the outside curve| HT[(results/hedge_test)]
    SC --> VAL[validation: referee, residuals, sensitivity, worst days, speed]
    OV --> VAL
    HT --> VAL
    VAL --> VR[(data/reports/model_validation.md)]
    SC --> API[web service]
    OV --> API
```

## 4. Data model

```mermaid
erDiagram
    RAW_REPORT ||--o| RAW_REPORT : "corrects or cancels (Original Dissemination Identifier)"
    RAW_REPORT }o--|| TRADE : "lifecycle collapses reports into"
    TRADE ||--o| SWAP : "if dollar SOFR swap"
    TRADE ||--o| SWAPTION : "if dollar European swap option"
    CURVE_DAY ||--o{ SWAP : "same trade_date, used to check rates"

    RAW_REPORT {
        string dissemination_id PK
        string original_dissemination_id FK
        string action_type "NEWT, CORR, EROR, MODI, TERM"
        string event_type "TRAD, COMP, NOVA, EXER"
        string execution_timestamp
        string upi_fisn "product name"
        string file_date "day it was published"
    }
    TRADE {
        string trade_id PK "id of the first report"
        int n_corrections
    }
    SWAP {
        string trade_id PK
        datetime exec_ts
        date effective
        date maturity
        float fixed_rate_pct
        float notional
        bool notional_capped
        string start "spot, forward, backdated"
        float tenor_years
        string exclusion "blank if clean"
        date known_date
    }
    SWAPTION {
        string trade_id PK
        datetime exec_ts
        date expiry
        date swap_maturity
        float strike_pct
        float premium
        float notional
        string reported_type "call or put"
        bool package
        string exclusion "blank if usable"
    }
    CURVE_DAY {
        date day PK
        float discount_factor "per calendar date"
        float par_rate_pct "per standard swap length"
    }
```

## 5. Components

| Component | Module | Responsibility |
|---|---|---|
| Source adapters | `tapemark.sources.dtcc`, `tapemark.sources.eris` | Know one provider's URLs and file format. Nothing else does. |
| Lifecycle | `tapemark.clean.lifecycle` | Turn a log of reports into one row per real trade |
| Product cleaners | `tapemark.clean.swaps`, `tapemark.clean.swaptions` | Type fields, derive measures, assign one exclusion reason |
| Report | `tapemark.report` | Summarise coverage, exclusions, outside agreement, unusual days |
| Command line | `tapemark.cli` | `fetch`, `build`, `summary`, `audit`, `report` |
| Pricing | `tapemark.pricing.{calendar,curve,options,risk}` | Pure functions: business days, curve build, swap and option prices, risk by curve point. No files, no network |
| Curve model | `tapemark.models.curve_filter` | Kalman filter over par rates; predicts each trade, then learns from it |
| Scoring | `tapemark.scoring.{swaps,options,risk}` | Walk-forward predictions, baselines, significance, calibration, hedge test |
| Validation | `tapemark.validation` | Gathers every check into one report with verdicts |
| Other markets | `tapemark.markets`, `tapemark.sources.fed` | Other currencies, inflation swaps, Treasury curve, SOFR |
| Research | `tapemark.insights` | Correlations, implied against realised volatility, rich/cheap screen, gap drivers |
| Web service | `tapemark.server.{store,app}` | Read models, pricing endpoints, saved items, live feed |
| Frontend | `web/` | Plain HTML, CSS and ES modules; hand-written SVG charts |

## 6. How it runs

```mermaid
flowchart LR
    P[Push or pull request] --> CI[tests.yml<br/>lint, then tests]
    N[Schedule: weekdays 06:00 UTC] --> NB[nightly.yml<br/>fetch last 10 days, build, report]
    NB --> ART[Report uploaded as a workflow artifact]
    L[Local: make-style commands] --> FULL[Full history build and report]
```

- **On every push:** lint and the test suite. Tests use hand-built rows, so they need no network.
- **Nightly:** a short window of real files is fetched and the whole pipeline runs end to end. This catches a changed file format or a moved URL within a day. The report is kept as a workflow artifact; data is not committed.
- **Full history:** built locally, about 1.3 GB of raw files.

## 7. The web service at run time

```mermaid
flowchart LR
    B[Browser] -->|GET read models| API[FastAPI]
    B -->|POST price a swap or option| API
    B <-->|create, read, update, delete| API
    API -->|server-sent events: new trades| B
    API --> ST[Store: result tables in memory, loaded once at start]
    API --> PR[Pricing functions]
    API --> DB[(SQLite: saved trades, notes)]
    POLL[Background task] -->|every 45 s| TICK[DTCC ticker]
    POLL -->|clean, predict, update filter| API
```

- **Read models** are computed from tables loaded once at start (about 4 seconds). No request reads from disk except saved items.
- **Pricing** is stateless: terms in, numbers out, on the curve of the chosen day.
- **Saved items** are the only writes. A saved trade stores terms only and is repriced on every read, so it cannot go stale.
- **Live rows** are held in memory and never written to the data folders.

## 8. Qualities the design protects

| Quality | How |
|---|---|
| Reproducible | Raw files immutable; every later table is a pure function of them |
| Auditable | Each excluded trade carries one reason; counts add up in the report |
| Honest about time | Each row keeps the date it became public (`known_date`) |
| Resilient | Downloads resume; one unreadable file is recorded and skipped, not fatal |
| Tolerant of schema change | Missing columns are filled blank and counted in the report |
| Portable | No database server; runs from a fresh clone |
