"""Other rates products found in the same free public files.

The dollar swap pipeline is the deep part of the project. This module is the
wide part: the same daily files also hold overnight-index swaps in other
currencies and inflation swaps. Here they are reduced to one number per day,
currency and swap length (the median traded rate), which is enough for a
market overview and shows that a new product is a configuration, not a new
pipeline.

Simplification, stated plainly: corrections are applied within each day only,
because loading two years of every product at once would not fit in memory.
A correction that arrives on a later day is missed. For a daily median over
many trades the effect is negligible; it would not be acceptable for the
trade-level scoring done on dollar swaps, which uses the full lifecycle.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from tapemark.clean.lifecycle import apply_lifecycle
from tapemark.clean.swaps import _flag, to_date, to_number
from tapemark.paths import CLEAN
from tapemark.sources import dtcc

OIS = {"EUR": "euro (€STR)", "GBP": "sterling (SONIA)", "JPY": "yen (TONA)", "INR": "rupee (MIBOR)", "CAD": "Canadian dollar (CORRA)",
       "AUD": "Australian dollar (AONIA)", "CHF": "Swiss franc (SARON)"}
COLUMNS = ["Dissemination Identifier", "Original Dissemination Identifier", "Action type", "Event type", "Event timestamp",
           "Execution Timestamp", "Effective Date", "Expiration Date", "UPI FISN", "UPI Underlier Name", "Fixed rate-Leg 1",
           "Fixed rate-Leg 2", "Notional amount-Leg 1", "Package indicator", "Other payment amount"]


def _day(day: dt.date) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = dtcc.read(day, COLUMNS)
    fisn = raw["UPI FISN"]
    wanted = fisn.isin([f"NA/Swap OIS {c}" for c in OIS]) | (fisn == "NA/Swap Infl Idx USD") | raw["Action type"].isin(["CORR", "EROR"])
    t = apply_lifecycle(raw[wanted])
    t = t[t["UPI FISN"].str.startswith("NA/Swap")]
    fixed = t["Fixed rate-Leg 1"].where(t["Fixed rate-Leg 1"] != "", t["Fixed rate-Leg 2"])
    d = pd.DataFrame({
        "product": t["UPI FISN"].str.replace("NA/Swap ", "", regex=False),
        "exec": pd.to_datetime(t["Execution Timestamp"], utc=True, errors="coerce").dt.tz_localize(None).dt.normalize(),
        "eff": to_date(t["Effective Date"]), "mat": to_date(t["Expiration Date"]),
        "rate": pd.to_numeric(fixed, errors="coerce") * 100, "notional": to_number(t["Notional amount-Leg 1"]),
        "package": _flag(t, "Package indicator"), "upfront": t["Other payment amount"] != "",
    }).dropna(subset=["exec", "eff", "mat", "rate"])
    d = d[d["exec"] == pd.Timestamp(day)]
    lag = np.busday_count(d["exec"].values.astype("datetime64[D]"), d["eff"].values.astype("datetime64[D]"))
    d["tenor"] = ((d["mat"] - d["eff"]).dt.days / 365.25)
    whole = (d["tenor"] - d["tenor"].round()).abs() < 0.05
    plain = (lag >= 0) & (lag <= 3) & ~d["package"] & ~d["upfront"] & d["rate"].between(-2, 25) & whole & (d["tenor"] >= 0.9)
    d = d[plain].assign(tenor=lambda x: x["tenor"].round().astype(int), day=pd.Timestamp(day))
    out = d.groupby(["day", "product", "tenor"]).agg(rate=("rate", "median"), trades=("rate", "size"), notional=("notional", "sum")).reset_index()
    ois = out[out["product"].str.startswith("OIS")].assign(ccy=lambda x: x["product"].str[-3:]).drop(columns="product")
    infl = out[out["product"] == "Infl Idx USD"].drop(columns="product")
    return ois, infl


def build(progress_every: int = 50) -> None:
    """One pass over every raw daily file. Resumable: finished days are kept."""
    ois_path, infl_path = CLEAN / "global_ois_daily.parquet", CLEAN / "usd_inflation_daily.parquet"
    ois = [pd.read_parquet(ois_path)] if ois_path.exists() else []
    infl = [pd.read_parquet(infl_path)] if infl_path.exists() else []
    done = set(ois[0]["day"].dt.date) if ois else set()
    todo = [d for d in dtcc.available_days() if d not in done and d.weekday() < 5]
    for i, day in enumerate(todo, 1):
        try:
            a, b = _day(day)
            ois.append(a)
            infl.append(b)
        except Exception as exc:  # one bad file must not stop the pass
            print(f"{day} skipped: {exc!r}"[:160], flush=True)
        if i % progress_every == 0 or i == len(todo):
            pd.concat(ois, ignore_index=True).to_parquet(ois_path, index=False)
            pd.concat(infl, ignore_index=True).to_parquet(infl_path, index=False)
            print(f"{i}/{len(todo)} days", flush=True)


if __name__ == "__main__":
    build()
