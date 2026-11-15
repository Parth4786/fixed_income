"""Two free Federal Reserve datasets.

- The Board's fitted Treasury yield curve (Gurkaynak, Sack and Wright), daily
  since 1961. Used for swap spreads: the swap rate minus the government bond
  yield of the same length.
- The New York Fed's daily SOFR, with the spread of rates paid that day and
  the volume. Used as a gauge of funding conditions.
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from tapemark.paths import RAW

GSW_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
SOFR_URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate={start}&endDate={end}"
HEADERS = {"User-Agent": "tapemark/0.1"}
DIR = RAW / "fed"


def fetch_treasury_curve() -> pd.DataFrame:
    """Treasury par yields in percent for 1 to 30 years, indexed by date."""
    DIR.mkdir(parents=True, exist_ok=True)
    resp = requests.get(GSW_URL, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    (DIR / "feds200628.csv").write_bytes(resp.content)
    return treasury_curve()


def treasury_curve() -> pd.DataFrame:
    text = (DIR / "feds200628.csv").read_text(encoding="utf-8", errors="replace")
    start = text.index("Date,")  # the file opens with several lines of notes
    df = pd.read_csv(io.StringIO(text[start:]), parse_dates=["Date"]).set_index("Date")
    par = df[[c for c in df.columns if c.startswith("SVENPY")]].dropna(how="all")
    par.columns = [int(c[-2:]) for c in par.columns]
    return par


def fetch_sofr(start: str = "2018-04-02", end: str = "2030-01-01") -> pd.DataFrame:
    DIR.mkdir(parents=True, exist_ok=True)
    resp = requests.get(SOFR_URL.format(start=start, end=end), headers=HEADERS, timeout=120)
    resp.raise_for_status()
    rows = resp.json()["refRates"]
    df = pd.DataFrame(rows)[["effectiveDate", "percentRate", "percentPercentile1", "percentPercentile25", "percentPercentile75",
                             "percentPercentile99", "volumeInBillions"]]
    df.columns = ["day", "rate", "p1", "p25", "p75", "p99", "volume_bn"]
    df["day"] = pd.to_datetime(df["day"])
    for col in df.columns[1:]:  # early rows carry the text "NA" where a figure was not published
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("day").reset_index(drop=True)
    df.to_parquet(DIR / "sofr.parquet", index=False)
    return df


def sofr() -> pd.DataFrame:
    return pd.read_parquet(DIR / "sofr.parquet")
