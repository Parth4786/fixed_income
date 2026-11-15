# Runbook

How to install, load data, run the models, start the app, and fix it when
something goes wrong. Commands are for a terminal opened in the project folder.

## 1. What runs where

| Part | What it is | How it starts |
|---|---|---|
| Pipeline | Python commands that download, clean and score | `python -m tapemark <command>` |
| Backend | A FastAPI service that reads result files and prices trades | `python -m tapemark serve` |
| Frontend | Plain HTML, CSS and JavaScript in `web/`, served by the backend | Open `http://127.0.0.1:8765` |
| Saved items | One SQLite file, `data/app.db` | Created on first use |

There is no separate frontend build and no database server. One process
serves both the API and the pages.

## 2. First-time setup

Needs Python 3.11 or newer.

```bash
pip install -e ".[dev]"
```

```bash
pytest -q
```

## 3. Load data and run the models

Quick start, about ten days of data (around 30 MB, a few minutes):

```bash
python -m tapemark fetch --start 2026-11-02 --end 2026-11-13
```

Full history, 9 Nov 2024 onward (about 1.3 GB, 30 to 45 minutes; safe to
interrupt and rerun, only missing files are fetched):

```bash
python -m tapemark fetch --start 2024-11-09 --end 2026-11-13 --workers 8
```

Then, in order:

```bash
python -m tapemark build
```

```bash
python -m tapemark report
```

```bash
python -m tapemark score
```

| Command | Reads | Writes | Time on full history |
|---|---|---|---|
| `fetch` | Public sources | `data/raw/` | 30 to 45 min |
| `build` | `data/raw/` | `data/stage/`, `data/clean/` | about 12 min first time, 3 min after |
| `report` | `data/clean/` | `data/reports/data_quality.md` | under 1 min |
| `score` | `data/clean/`, `data/raw/eris`, public Fed data | `data/results/`, `data/reports/model_validation.md` | about 35 min |

The models need at least 60 trading days of history before any trade is
scored, so the ten-day quick start shows data screens but not model scores.

## 4. Start the app

```bash
python -m tapemark serve
```

Open <http://127.0.0.1:8765>. To use another port:

```bash
python -m tapemark serve --port 9000
```

The interactive API reference is at <http://127.0.0.1:8765/docs>.

### Screens

| Screen | What a trader or analyst gets from it |
|---|---|
| Overview | What the product is, its three headline results, and four pricing methods ranked by real trades |
| Guide and glossary | How to read the screens; every term in plain words (also shown on hover) |
| Today | Three written sentences on the day, then where rates closed, what moved, where risk traded, trades furthest from fair |
| Trades | Every clean trade with the fair rate just before it, the gap in basis points and dollars, a flag when unusual; the live feed |
| Volatility | Volatility grid from real premiums, recent option trades, history |
| Other markets | Swap curves in seven other currencies, expected inflation, swap rates against Treasuries, funding rate and pressure gauge |
| Patterns | Rich/cheap screen, implied against realised volatility, cross-market correlations, time-of-day effects, what drives the gap to fair, trade clustering around data releases, signed flow, late-day drift |
| Price a trade | A swap or swap option priced under every model at once, with each model's proven accuracy; verdict, dollar cost, risk, hedge, scenarios; margin and its funding cost as a swap against swap futures |
| Model lab | Change the curve model's settings and rerun it on recent real trades, against the published settings and the baseline |
| Saved trades | Trades you saved, repriced on the latest day |
| Accuracy | Out-of-sample accuracy against baselines, band honesty, sensitivity to settings, worst days, hedge test, the futures engine against the exchange, the margin rule against published margins |
| Data quality | Why each trade was excluded, month-by-month consistency, quiet days with notes |

## 5. Saving, changing and deleting (CRUD)

Two things can be created, read, updated and deleted. Both live in
`data/app.db`; nothing else in the app is writable.

| Item | Create | Read | Update | Delete |
|---|---|---|---|---|
| Saved trade | `POST /api/blotter` | `GET /api/blotter` | `PUT /api/blotter/{id}` | `DELETE /api/blotter/{id}` |
| Note on a day | `POST /api/notes` | `GET /api/notes` | `PUT /api/notes/{id}` | `DELETE /api/notes/{id}` |

In the app: price a trade under **Price a trade** and press **Save to Saved
trades**; change its status or note, or delete it, on the **Saved trades**
screen. Notes are edited on the **Data quality** screen next to each quiet day.

From a terminal:

```bash
curl -X POST http://127.0.0.1:8765/api/blotter -H "Content-Type: application/json" -d "{\"kind\":\"swap\",\"label\":\"client quote\",\"terms\":{\"years\":10,\"rate\":4.76,\"notional\":100000000,\"pay_fixed\":true}}"
```

```bash
curl http://127.0.0.1:8765/api/blotter
```

```bash
curl -X DELETE http://127.0.0.1:8765/api/blotter/1
```

A saved trade stores only its terms. Its value is recalculated from the
latest curve every time it is read, so it is never stale. Unknown ids return
404; malformed terms return 422. To start afresh, stop the app and delete
`data/app.db`.

## 6. Real-time data

**Yes, within limits.** DTCC publishes a public ticker of the latest reported
trades. While the app is running, a background task:

1. asks the ticker for new reports every 45 seconds;
2. keeps new dollar SOFR swap trades and applies the same cleaning rules as the batch pipeline;
3. for each clean one, records the rate the curve model expected, then updates the model with the trade;
4. pushes the result to every open browser (server-sent events), where it appears at the top of the **Trades** screen.

What "real time" means here:

| Question | Answer |
|---|---|
| How fresh is a trade? | Public reporting delay (seconds to minutes; longer for large trades) plus up to 45 seconds of polling |
| How fast is pricing once it arrives? | About 80 microseconds per trade through the model; a full curve build is under 2 ms |
| What limits it? | The public source, not the code. It is a polled feed, not a stream, and it returns only the latest 100 reports |
| Weekends and holidays | The feed shows the last trading day's reports; nothing new arrives |
| Is live data kept? | No. It is held in memory. The nightly `fetch` brings the complete official file |

Pause or resume from the **Trades** screen, or:

```bash
curl -X POST http://127.0.0.1:8765/api/live/off
```

To keep stored history current, run these once a day after 06:00 UTC, then
restart the app:

```bash
python -m tapemark fetch --start 2026-11-10 --end 2026-11-20
```

```bash
python -m tapemark build
```

```bash
python -m tapemark score
```

## 7. Speed

Measured by `score` and written to the validation report.

| Operation | Speed |
|---|---|
| Curve model, trades processed | about 12,600 a second |
| Swap pricing, vectorised | about 105,000 swaps a second |
| Build a curve from rates | about 1.6 ms |
| Risk to every curve point, automatic differentiation | about 6 ms |
| Same by rebuilding the curve per point | about 64 ms |
| App start (loading results) | about 4 seconds |

What makes it fast: the model updates in constant time per trade; swaps are
priced as whole arrays, not one by one; curve building has a closed form, so
no root search; outside curves are parsed once and cached in binary; staged
tables keep only needed columns.

## 8. Checks

```bash
ruff check .
```

```bash
pytest -q
```

The same two run on every push. A second workflow runs the pipeline on the
last ten days of real files every weekday and fails if too few clean trades
come through.

**Screens.** With the app running, this opens all twelve screens in a real
browser at desktop width, at phone width and in the dark theme (39 renders).
It checks each for sideways scrolling, text outside its card, overlapping
chart labels, blank charts and console errors, runs the axe-core accessibility
checker on the desktop and dark renders, and saves an image of each:

```bash
pip install -e ".[ui]"
```

```bash
python tools/render_screens.py
```

**Clean install.** The pipeline and tests were also run in a new virtual
environment built from `pyproject.toml` alone, on the newest library versions
(numpy 2.5, pandas 3.1, scipy 1.18, scikit-learn 1.9). That run is how a
missing dependency and a crash on short histories were found and fixed.

## 9. When something goes wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| `no raw files yet` | `fetch` has not run | Run `fetch` |
| `fetch` reports failed days | Network or the source was briefly down | Run the same `fetch` again |
| App fails to start: file not found in `data/results` | `score` has not run | Run `build`, then `score` |
| Accuracy screen empty or scores missing | Fewer than 60 trading days loaded | Fetch more history |
| A page says "Could not load" | Backend error | Read the terminal running `serve`; the error is printed there |
| Live dot is red | The ticker could not be reached | Usually temporary; the app keeps working on stored data |
| Share of clean trades jumps in the monthly table | The source changed a field | Compare raw files before and after, as in ADR 11 |
| Port already in use | Another copy is running | Stop it, or use `--port` |
| Every screen takes about a quarter of a second longer than it should (Windows) | The address `localhost` is tried over IPv6 first and falls back | Open `http://127.0.0.1:8765` instead |
| Price a trade shows no margin card; Accuracy shows no futures card | The futures step could not download the exchange's settlement files | Run `score` again with network access. The step is optional and everything else works without it |
| Numbers look wrong after a code change | Old staged or cached tables | Delete `data/stage` and `data/clean`, then `build` and `score` |

## 10. Folders

| Folder | Keep? | Size on full history |
|---|---|---|
| `data/raw/` | Yes. The archive; some sources will close | 1.3 GB |
| `data/stage/` | Rebuildable | 0.3 GB |
| `data/clean/` | Rebuildable | 50 MB |
| `data/results/` | Rebuildable | 50 MB |
| `data/reports/` | Rebuildable | small |
| `data/app.db` | Your saved trades and notes | small |

`data/` is not in git. Back up `data/raw/` and `data/app.db`.
