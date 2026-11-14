"""Eris SOFR end-of-day curve files.

Eris publishes a daily SOFR discount curve and par swap rates. Tapemark uses
it as an outside reference to check its own numbers against. It is not a
fully independent benchmark: the curve is itself modelled from market inputs.

The anonymous file server is being retired on 1 January 2027 (registration
will be required afterwards), so history is archived locally while it is open.
Recent files sit in the top folder; older ones under archives/YYYY/MM-Month/.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import requests

from tapemark.paths import RAW

BASE = "https://files.erisfutures.com/ftp"
FILES = {
    "discount": "Eris_{d:%Y%m%d}_EOD_DiscountFactors_SOFR.csv",
    "par": "Eris_{d:%Y%m%d}_EOD_ParCouponCurve_SOFR.csv",
}
HEADERS = {"User-Agent": "tapemark/0.1"}


def raw_path(day: dt.date, kind: str) -> Path:
    return RAW / "eris" / f"{day:%Y}" / FILES[kind].format(d=day)


def _urls(day: dt.date, kind: str) -> list[str]:
    name = FILES[kind].format(d=day)
    return [f"{BASE}/{name}", f"{BASE}/archives/{day:%Y}/{day:%m-%B}/{name}"]


def fetch(day: dt.date, kind: str = "discount", force: bool = False) -> Path | None:
    """Download one day's file, trying the live folder and then the archive."""
    path = raw_path(day, kind)
    if path.exists() and not force:
        return path
    for url in _urls(day, kind):
        resp = requests.get(url, headers=HEADERS, timeout=120)
        if resp.status_code == 200 and resp.text.lstrip().startswith(("Date,", "Symbol,")):
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(resp.content)
            tmp.replace(path)
            return path
    return None


def discount_factors(day: dt.date) -> pd.Series:
    """Discount factor for every calendar date out the curve, indexed by date."""
    df = pd.read_csv(raw_path(day, "discount"), usecols=["Date", "DiscountFactor"])
    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    return df.set_index("Date")["DiscountFactor"]


def par_rates(day: dt.date) -> pd.Series:
    """Par swap rate in percent by symbol, e.g. 'SOFR10Y'."""
    df = pd.read_csv(raw_path(day, "par"), usecols=["Symbol", "FairCoupon (%)"])
    return df.set_index("Symbol")["FairCoupon (%)"]
