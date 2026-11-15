"""The web service.

Three kinds of route:

- **Read models** (GET /api/...): views over result tables, computed by ``Store``.
- **Pricing** (POST /api/price/...): pure calculations on the curve of a chosen day.
- **Saved items** (create, read, update, delete): a trade blotter and notes on
  days, stored in a small SQLite file. This is the only state the app writes.

Plus a live feed: a background task polls DTCC's public ticker, runs each new
clean dollar swap through the curve filter, and pushes it to open browsers.

Run with:  python -m tapemark serve
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sqlite3
import threading
from contextlib import asynccontextmanager, closing
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tapemark.clean.swaps import usd_sofr_swaps
from tapemark.models.curve_filter import NODES, CurveFilter, trailing_covariance
from tapemark.paths import DATA, ROOT
from tapemark.server.store import Store

WEB = ROOT / "web"
DB = DATA / "app.db"
TICKER = "https://pddata.dtcc.com/ppd/api/ticker/CFTC/RATES"
POLL_SECONDS = 45

# Live feed field -> column name used by the cleaning code, so the same rules apply to both.
FIELD = {"disseminationIdentifier": "trade_id", "executionTimestamp": "Execution Timestamp", "effectiveDate": "Effective Date", "expirationDate": "Expiration Date",
         "fixedRateLeg1": "Fixed rate-Leg 1", "fixedRateLeg2": "Fixed rate-Leg 2", "notionalAmountLeg1": "Notional amount-Leg 1", "platformIdentifier": "Platform identifier",
         "cleared": "Cleared", "blocktradeElectionIndicator": "Block trade election indicator", "packageIndicator": "Package indicator", "otherPaymentAmount": "Other payment amount",
         "fixedRateDaycountConventionleg1": "Fixed rate day count convention-leg 1", "fixedRatePaymentFrequencyPeriodLeg1": "Fixed rate payment frequency period-Leg 1",
         "embeddedOptionType": "Embedded Option type", "nonstandardizedTermIndicator": "Non-standardized term indicator", "spreadLeg1": "Spread-Leg 1", "spreadLeg2": "Spread-Leg 2",
         "uniqueProductIdentifierShortName": "UPI FISN", "uniqueProductIdentifierUnderlierName": "UPI Underlier Name"}


# ---------------------------------------------------------------- saved items
def db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("create table if not exists blotter (id integer primary key, created text, updated text, kind text, label text, terms text, note text, status text)")
    con.execute("create table if not exists notes (id integer primary key, created text, updated text, day text, text text)")
    return con


class BlotterItem(BaseModel):
    kind: str  # "swap" or "option"
    label: str = ""
    terms: dict
    note: str = ""
    status: str = "watching"


class Note(BaseModel):
    day: str
    text: str


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- live feed
class Live:
    def __init__(self, store: Store):
        self.store = store
        self.seen: set[str] = set()
        self.rows: list[dict] = []
        self.listeners: set[asyncio.Queue] = set()
        self.status = {"enabled": True, "last_poll": None, "last_error": None, "polls": 0, "received": 0}
        q = trailing_covariance(store.par.values[-120:])
        self.filter = CurveFilter(store.eod.values[-1].copy(), q * 0.5, q, store.summary["swap_summary"]["filter_settings"]["noise_sd_pct"])
        self.last_ts: np.datetime64 | None = None

    def ingest(self, trades: list[dict]) -> list[dict]:
        fresh = [t for t in trades if t.get("disseminationIdentifier") not in self.seen and t.get("actionType") == "NEWT" and t.get("eventType") == "TRAD"]
        for t in trades:
            self.seen.add(t.get("disseminationIdentifier"))
        if not fresh:
            return []
        frame = pd.DataFrame([{col: (t.get(key) or "") for key, col in FIELD.items()} for t in fresh])
        frame["n_corrections"] = 0
        clean = usd_sofr_swaps(frame)
        out = []
        for r in clean.sort_values("exec_ts").itertuples():
            row = {"id": r.trade_id, "time": r.exec_ts.strftime("%Y-%m-%d %H:%M:%S"), "length": round(float(r.tenor_years), 2), "rate": round(float(r.fixed_rate_pct), 4),
                   "notional": float(r.notional), "venue": r.venue, "start": r.start, "reason": r.exclusion or None, "fair": None, "gap_bp": None, "band_bp": None}
            ts = np.datetime64(r.exec_ts.tz_localize(None), "s")
            if r.standard and r.tenor_years >= 0.2 and ts > np.datetime64(self.store.snap_ts[-1]):
                if self.last_ts is not None:
                    self.filter.advance(min(max((ts - self.last_ts) / np.timedelta64(86400, "s"), 0.0), 1.0))
                step = self.filter.update(float(r.tenor_years), float(r.fixed_rate_pct))
                self.last_ts = ts
                band = self.store.band_bp(self.store.days[-1], float(r.tenor_years))
                row |= {"fair": round(step.prediction, 4), "gap_bp": round(step.gap * 100, 2), "band_bp": round(band, 2), "outside": bool(abs(step.gap) * 100 > band)}
            elif r.standard:
                fair = float(np.interp(r.tenor_years, NODES, self.filter.x))  # trade is older than the stored history: compare, do not update
                row |= {"fair": round(fair, 4), "gap_bp": round((r.fixed_rate_pct - fair) * 100, 2), "band_bp": None, "stale": True}
            out.append(row)
        self.rows = (out[::-1] + self.rows)[:300]
        self.status["received"] += len(out)
        return out

    async def poll_forever(self):
        import requests

        headers = {"User-Agent": "tapemark/0.1", "Accept": "application/json", "Referer": "https://pddata.dtcc.com/ppd/cftcdashboard"}
        while True:
            if self.status["enabled"]:
                try:
                    resp = await asyncio.to_thread(requests.get, TICKER, headers=headers, timeout=30)
                    resp.raise_for_status()
                    new = self.ingest(resp.json().get("tradeList", []))
                    self.status |= {"last_poll": _now(), "last_error": None, "polls": self.status["polls"] + 1}
                    for q in list(self.listeners):
                        for row in new:
                            q.put_nowait(row)
                except Exception as exc:  # the feed is best effort; the app must stay up
                    self.status |= {"last_poll": _now(), "last_error": repr(exc)[:200]}
            await asyncio.sleep(POLL_SECONDS)


# ---------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = Store()
    app.state.live = Live(app.state.store)
    # Build the two slow results once in the background, so the first visit to those screens does not wait for them.
    threading.Thread(target=lambda: (app.state.store.quality(), app.state.store.lab({}), app.state.store.fed_book(), app.state.store.engine_checks()), daemon=True).start()
    task = asyncio.create_task(app.state.live.poll_forever())
    yield
    task.cancel()


def _clean(x):
    """Make a result safe to send: numbers that are not finite become null."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


class SafeJSON(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(_clean(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


app = FastAPI(title="Tapemark", lifespan=lifespan, default_response_class=SafeJSON)


def S() -> Store:
    return app.state.store


@app.get("/api/health")
def health():
    s = S()
    return {"ok": True, "first_day": str(s.days[0]), "last_day": str(s.days[-1]), "trading_days": len(s.days), "scored_trades": int(s.scores["scored"].sum())}


@app.get("/api/days")
def days():
    return [str(d) for d in S().days[-260:]]


@app.get("/api/overview")
def overview(day: str | None = None):
    return S().overview(day)


@app.get("/api/curve")
def curve(day: str | None = None):
    return S().curve(day)


@app.get("/api/history")
def history():
    return S().history()


@app.get("/api/tape")
def tape(day: str | None = None, limit: int = 400):
    return S().tape(day, limit)


@app.get("/api/flow")
def flow(day: str | None = None):
    return S().flow(day)


@app.get("/api/vol")
def vol(day: str | None = None):
    return S().vol(day)


@app.get("/api/scorecard")
def scorecard():
    return S().scorecard()


@app.get("/api/quality")
def quality():
    out = S().quality()
    with closing(db()) as con:
        notes = {r["day"]: dict(r) for r in con.execute("select * from notes")}
    for f in out["flagged"]:
        f["note"] = notes.get(f["day"])
    return out


@app.get("/api/markets")
def markets():
    return S().markets()


@app.get("/api/insights")
def insights():
    path = DATA / "results" / "insights.json"
    if not path.exists():
        raise HTTPException(404, "run `python -m tapemark score` to build the research results")
    out = json.loads(path.read_text())
    for extra in ("flow", "futures"):                      # later studies, each in its own file
        p = DATA / "results" / f"{extra}.json"
        out[extra] = json.loads(p.read_text()) if p.exists() else None
    return out


@app.post("/api/lab")
def lab(q: dict):
    try:
        return S().lab(q)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"could not run with these settings: {exc}") from exc


@app.post("/api/price/swap")
def price_swap(q: dict):
    try:
        return S().price_swap(q)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"could not price this swap: {exc}") from exc


@app.post("/api/price/option")
def price_option(q: dict):
    try:
        return S().price_option(q)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"could not price this option: {exc}") from exc


# ---- blotter: create, read, update, delete
def _valued(row: sqlite3.Row) -> dict:
    item = dict(row) | {"terms": json.loads(row["terms"])}
    try:
        priced = S().price_swap(item["terms"] | {"day": None}) if item["kind"] == "swap" else S().price_option(item["terms"] | {"day": None})
        keys = ("fair_rate", "gap_bp", "value", "dv01", "verdict", "day") if item["kind"] == "swap" else ("model_premium", "vol_gap_bp", "verdict", "day", "forward_rate")
        item["now"] = {k: priced.get(k) for k in keys}
    except Exception as exc:
        item["now"] = {"error": str(exc)[:120]}
    return item


@app.get("/api/blotter")
def blotter_list():
    with closing(db()) as con:
        return [_valued(r) for r in con.execute("select * from blotter order by id desc")]


@app.get("/api/monitor")
def monitor(day: str | None = None):
    """The curve monitor: every point and the main spreads, with changes, range, roll-down and forward."""
    return S().monitor(day)


@app.get("/api/engine-checks")
def engine_checks():
    """Bermudan option engines (PDE, Monte Carlo) against the closed-form European on real calibrated days."""
    return S().engine_checks()


@app.get("/api/fed-book")
def fed_book():
    """A real book: the Fed's Treasury portfolio, priced on the Fed's Treasury curve, under the regulatory shocks and VaR."""
    return S().fed_book()


@app.get("/api/book-risk")
def book_risk(tier1: float | None = None):
    """Interest rate risk of the saved swaps: Basel/EBA shocks, historical VaR and its backtest."""
    with closing(db()) as con:
        items = [dict(r) | {"terms": json.loads(r["terms"])} for r in con.execute("select * from blotter order by id")]
    return S().book_risk(items, tier1)


@app.post("/api/blotter", status_code=201)
def blotter_create(item: BlotterItem):
    if item.kind not in ("swap", "option"):
        raise HTTPException(422, "kind must be 'swap' or 'option'")
    with closing(db()) as con, con:
        cur = con.execute("insert into blotter (created, updated, kind, label, terms, note, status) values (?,?,?,?,?,?,?)",
                          (_now(), _now(), item.kind, item.label, json.dumps(item.terms), item.note, item.status))
        return _valued(con.execute("select * from blotter where id=?", (cur.lastrowid,)).fetchone())


@app.put("/api/blotter/{item_id}")
def blotter_update(item_id: int, item: BlotterItem):
    with closing(db()) as con, con:
        n = con.execute("update blotter set updated=?, kind=?, label=?, terms=?, note=?, status=? where id=?",
                        (_now(), item.kind, item.label, json.dumps(item.terms), item.note, item.status, item_id)).rowcount
        if not n:
            raise HTTPException(404, "no such saved trade")
        return _valued(con.execute("select * from blotter where id=?", (item_id,)).fetchone())


@app.delete("/api/blotter/{item_id}", status_code=204)
def blotter_delete(item_id: int):
    with closing(db()) as con, con:
        if not con.execute("delete from blotter where id=?", (item_id,)).rowcount:
            raise HTTPException(404, "no such saved trade")


# ---- notes on days: create, read, update, delete
@app.get("/api/notes")
def notes_list():
    with closing(db()) as con:
        return [dict(r) for r in con.execute("select * from notes order by day desc")]


@app.post("/api/notes", status_code=201)
def notes_create(note: Note):
    with closing(db()) as con, con:
        cur = con.execute("insert into notes (created, updated, day, text) values (?,?,?,?)", (_now(), _now(), note.day, note.text))
        return dict(con.execute("select * from notes where id=?", (cur.lastrowid,)).fetchone())


@app.put("/api/notes/{note_id}")
def notes_update(note_id: int, note: Note):
    with closing(db()) as con, con:
        if not con.execute("update notes set updated=?, day=?, text=? where id=?", (_now(), note.day, note.text, note_id)).rowcount:
            raise HTTPException(404, "no such note")
        return dict(con.execute("select * from notes where id=?", (note_id,)).fetchone())


@app.delete("/api/notes/{note_id}", status_code=204)
def notes_delete(note_id: int):
    with closing(db()) as con, con:
        if not con.execute("delete from notes where id=?", (note_id,)).rowcount:
            raise HTTPException(404, "no such note")


# ---- live feed
@app.get("/api/live")
def live():
    lv = app.state.live
    return {"status": lv.status, "rows": lv.rows[:120]}


@app.post("/api/live/{state}")
def live_switch(state: str):
    app.state.live.status["enabled"] = state == "on"
    return app.state.live.status


@app.get("/api/live/stream")
async def live_stream():
    lv = app.state.live
    q: asyncio.Queue = asyncio.Queue()
    lv.listeners.add(q)

    async def events():
        try:
            yield "retry: 5000\n\n"
            while True:
                try:
                    row = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"data: {json.dumps(row)}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            lv.listeners.discard(q)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(Path(WEB) / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
