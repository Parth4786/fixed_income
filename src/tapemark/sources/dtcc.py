"""DTCC public swap trade reports (CFTC jurisdiction, interest rates).

US rules require every reported swap trade to be published. DTCC posts one
"cumulative" zip per day holding every report disseminated that day: new
trades, corrections, cancellations and post-trade events, for all currencies.
"""

from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

import pandas as pd
import requests

from tapemark.paths import RAW

URL = "https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/eod/CFTC_CUMULATIVE_RATES_{d:%Y_%m_%d}.zip"
HEADERS = {"User-Agent": "tapemark/0.1"}


def raw_path(day: dt.date) -> Path:
    return RAW / "dtcc" / "rates" / f"{day:%Y}" / f"CFTC_CUMULATIVE_RATES_{day:%Y_%m_%d}.zip"


def fetch(day: dt.date, force: bool = False) -> Path | None:
    """Download one day's file. Returns None when DTCC has no file for that day."""
    path = raw_path(day)
    if path.exists() and not force:
        return path
    resp = requests.get(URL.format(d=day), headers=HEADERS, timeout=120)
    if resp.status_code in (403, 404):  # weekend, holiday, or outside the public window
        return None
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(resp.content)
    with zipfile.ZipFile(tmp) as z:  # refuse to keep a truncated download
        if z.testzip() is not None:
            tmp.unlink()
            raise OSError(f"corrupt zip for {day}")
    tmp.replace(path)
    return path


# Columns the project uses. The public schema has changed over time, so any
# column missing from an older file is added as blank rather than failing.
COLUMNS = [
    "Dissemination Identifier", "Original Dissemination Identifier", "Action type", "Event type",
    "Event timestamp", "Execution Timestamp", "Effective Date", "Expiration Date",
    "Maturity date of the underlier", "First exercise date", "UPI FISN", "UPI Underlier Name",
    "Unique Product Identifier", "Fixed rate-Leg 1", "Fixed rate-Leg 2", "Spread-Leg 1", "Spread-Leg 2",
    "Notional amount-Leg 1", "Notional currency-Leg 1", "Platform identifier", "Cleared",
    "Block trade election indicator", "Prime brokerage transaction indicator",
    "Non-standardized term indicator", "Package indicator", "Package transaction price",
    "Package transaction spread", "Other payment amount", "Other payment type",
    "Fixed rate day count convention-leg 1", "Fixed rate payment frequency period-Leg 1",
    "Strike Price", "Strike price notation", "Option Premium Amount", "Option Premium Currency",
    "Embedded Option type",
]


def read(day: dt.date, columns: list[str] | None = None) -> pd.DataFrame:
    """One day's reports as text, exactly as published.

    With ``columns``, only those are loaded and any that the file lacks are
    returned blank; ``missing_columns`` in ``attrs`` records which ones.
    """
    want = set(columns) if columns else None
    with zipfile.ZipFile(raw_path(day)) as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(
                f, dtype=str, keep_default_na=False, encoding="utf-8", encoding_errors="replace",
                usecols=(lambda c: c in want) if want else None,
            )
    missing = [c for c in (columns or []) if c not in df.columns]
    for c in missing:
        df[c] = ""
    if columns:
        df = df[columns]
    df.attrs["missing_columns"] = missing
    df["file_date"] = day.isoformat()
    return df


def read_usd(day: dt.date) -> pd.DataFrame:
    """Only US dollar overnight-index swaps and US dollar options, needed columns only."""
    df = read(day, COLUMNS)
    fisn = df["UPI FISN"]
    usd = fisn.str.contains("USD", regex=False) & (fisn.str.startswith("NA/Swap OIS") | fisn.str.startswith("NA/O "))
    # Keep every correction and cancellation, whatever product it now names:
    # a correction can reclassify a trade, and dropping it would leave the
    # superseded original looking like a live dollar swap.
    fixes = df["Action type"].isin(["CORR", "EROR"])
    out = df[usd | fixes].reset_index(drop=True)
    out.attrs["missing_columns"] = df.attrs["missing_columns"]
    return out


def available_days() -> list[dt.date]:
    days = []
    for p in sorted((RAW / "dtcc" / "rates").glob("*/CFTC_CUMULATIVE_RATES_*.zip")):
        y, m, d = p.stem.split("_")[-3:]
        days.append(dt.date(int(y), int(m), int(d)))
    return days
