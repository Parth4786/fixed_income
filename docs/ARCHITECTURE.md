# Architecture

High-level design: what the system is, what it talks to, how data moves, and
how it runs. Module-level detail is in [DESIGN.md](DESIGN.md). Reasons for the
choices are in [adr/](adr/README.md).

## 1. Context

Tapemark is a daily batch system. It reads public files, writes local tables
and reports, and has no users writing into it.

```mermaid
flowchart LR
    DTCC[DTCC public trade reports<br/>one zip per day] --> T
    ERIS[Eris end-of-day SOFR curve<br/>two csv files per day] --> T
    T[Tapemark]
    T --> R[Data quality report]
    T --> S[Model scorecards<br/>planned]
    T --> A[App screens<br/>planned]
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
| Reports | `data/reports/` | Data quality report; later, model scorecards | Yes |

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
    SW -.-> PR[Pricing and scoring<br/>stages 1 to 7, planned]
    OP -.-> PR
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
| Pricing, curves, scoring | planned | Stages 1 to 7; pure functions with no file or network access |

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

## 7. Qualities the design protects

| Quality | How |
|---|---|
| Reproducible | Raw files immutable; every later table is a pure function of them |
| Auditable | Each excluded trade carries one reason; counts add up in the report |
| Honest about time | Each row keeps the date it became public (`known_date`) |
| Resilient | Downloads resume; one unreadable file is recorded and skipped, not fatal |
| Tolerant of schema change | Missing columns are filled blank and counted in the report |
| Portable | No database server; runs from a fresh clone |
