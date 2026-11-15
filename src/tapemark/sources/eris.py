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

import numpy as np
import pandas as pd
import requests

from tapemark.paths import DATA, RAW

BASE = "https://files.erisfutures.com/ftp"
FILES = {
    "discount": "Eris_{d:%Y%m%d}_EOD_DiscountFactors_SOFR.csv",
    "par": "Eris_{d:%Y%m%d}_EOD_ParCouponCurve_SOFR.csv",
    "settles": "Eris_Instruments_{d:%Y%m%d}_Settles.csv",   # every listed swap future: price, its parts A, B and C, risk, exchange margin
    "options": "Eris_Options_{d:%Y%m%d}_Settles.csv",       # every listed option on those futures: price, strike, the exchange's volatility
}
HISTORY = "Eris_Historical_ParCouponCurve_SOFR.csv"         # one row a day of par rates since October 2020
HEADERS = {"User-Agent": "tapemark/0.1"}
STAGE = DATA / "stage" / "eris_df"


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
    """Discount factor for every calendar date out the curve, indexed by date.

    The csv is parsed once and kept as a compact binary copy; parsing 500 of
    them is otherwise the slowest step of a full scoring run.
    """
    cache = STAGE / f"{day.isoformat()}.npz"
    if cache.exists():
        z = np.load(cache)
        return pd.Series(z["df"], index=pd.DatetimeIndex(z["dates"]), name="DiscountFactor")
    df = pd.read_csv(raw_path(day, "discount"), usecols=["Date", "DiscountFactor"])
    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    out = df.set_index("Date")["DiscountFactor"]
    STAGE.mkdir(parents=True, exist_ok=True)
    np.savez(cache, dates=out.index.values, df=out.values)
    return out


def par_rates(day: dt.date) -> pd.Series:
    """Par swap rate in percent by symbol, e.g. 'SOFR10Y'."""
    df = pd.read_csv(raw_path(day, "par"), usecols=["Symbol", "FairCoupon (%)"])
    return df.set_index("Symbol")["FairCoupon (%)"]


def settles(day: dt.date) -> pd.DataFrame:
    """The exchange's settlement record for every listed SOFR swap future on one day."""
    df = pd.read_csv(raw_path(day, "settles"))
    for col in ("EffectiveDate", "CashFlowAlignmentDate", "MaturityDate", "FirstTradeDate"):
        df[col] = pd.to_datetime(df[col], format="%m/%d/%Y")
    return df.rename(columns={"NPV (A)": "a", "PastFxdFltPmts (B)": "b", "ErisPAI (C)": "c", "SettlementPrice (100+A+B-C)": "price", "Coupon (%)": "coupon",
                              "PAIRate (%)": "pai_rate", "AccrualDays": "pai_days", "DailyIncrementalErisPAI": "pai_step", "PrevNPVForPAI": "prev_a",
                              "PreviousErisPAI": "prev_c", "DV01": "dv01", "InitialHedgerMargin": "margin"})


def fetch_par_history(force: bool = False) -> Path | None:
    path = RAW / "eris" / HISTORY
    if path.exists() and not force:
        return path
    resp = requests.get(f"{BASE}/{HISTORY}", headers=HEADERS, timeout=120)
    if resp.status_code != 200 or not resp.text.startswith("Evaluation Date,"):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return path


def par_history() -> pd.DataFrame:
    """Daily par swap rates in percent since 2020, oldest first, columns in years (0.25 ... 30)."""
    df = pd.read_csv(RAW / "eris" / HISTORY, parse_dates=["Evaluation Date"]).set_index("Evaluation Date").sort_index()
    years = {f"SOFR{m}M": m / 12 for m in (3, 6, 9, 12, 18)} | {f"SOFR{y}Y": float(y) for y in (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30)}
    out = df[[c for c in df.columns if c in years]].rename(columns=years)
    return out.dropna()


def option_settles(day: dt.date) -> pd.DataFrame:
    """The exchange's settlement record for every listed option on SOFR swap futures on one day."""
    df = pd.read_csv(raw_path(day, "options"))
    return df.rename(columns={"Price": "price", "UnderlyingTenor": "tenor", "OptionType": "kind", "TimeToExpiry": "expiry_years", "UnderlyingPV01": "pv01",
                              "Rate Vol Nor": "vol_pct", "BP OTM": "strike_minus_price_bp", "Settlement MPI": "tick"})
