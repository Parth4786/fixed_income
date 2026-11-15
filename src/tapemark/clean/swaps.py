"""US dollar SOFR swaps: typed, labelled, one row per trade.

A SOFR swap exchanges a fixed interest rate for the compounded overnight
dollar rate (SOFR). The fixed rate agreed is the "price" of the swap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def to_number(s: pd.Series) -> pd.Series:
    """'220,000,000' and '250,000,000+' -> floats. Blank or junk -> NaN."""
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.rstrip("+"), errors="coerce")


def to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.str.slice(0, 10), format="%Y-%m-%d", errors="coerce")


def usd_sofr_swaps(trades: pd.DataFrame) -> pd.DataFrame:
    """Select and type USD SOFR swaps from lifecycle-cleaned trades."""
    t = trades[(trades["UPI FISN"] == "NA/Swap OIS USD") & trades["UPI Underlier Name"].str.contains("SOFR")]
    fixed = t["Fixed rate-Leg 1"].where(t["Fixed rate-Leg 1"] != "", t["Fixed rate-Leg 2"])
    out = pd.DataFrame(
        {
            "trade_id": t["trade_id"],
            "exec_ts": pd.to_datetime(t["Execution Timestamp"], utc=True, errors="coerce"),
            "effective": to_date(t["Effective Date"]),
            "maturity": to_date(t["Expiration Date"]),
            "fixed_rate_pct": pd.to_numeric(fixed, errors="coerce") * 100,
            "notional": to_number(t["Notional amount-Leg 1"]),
            # Large trades are published with the size capped, marked by a trailing '+'.
            "notional_capped": t["Notional amount-Leg 1"].str.endswith("+"),
            "venue": t["Platform identifier"],
            "cleared": t["Cleared"].isin(["Y", "I"]),
            "block": _flag(t, "Block trade election indicator"),
            "package": _flag(t, "Package indicator"),
            "upfront_payment": t["Other payment amount"] != "",
            "fixed_day_count": t["Fixed rate day count convention-leg 1"],
            "fixed_frequency": t["Fixed rate payment frequency period-Leg 1"],
            # Early-termination rights change what the fixed rate means.
            "embedded_option": _text(t, "Embedded Option type"),
            "non_standard_terms": _flag(t, "Non-standardized term indicator"),
            "floating_spread": (pd.to_numeric(_text(t, "Spread-Leg 1"), errors="coerce").fillna(0) != 0)
            | (pd.to_numeric(_text(t, "Spread-Leg 2"), errors="coerce").fillna(0) != 0),
            "n_corrections": t["n_corrections"],
        }
    )
    out = out.dropna(subset=["exec_ts", "effective", "maturity", "fixed_rate_pct", "notional"])
    trade_date = out["exec_ts"].dt.tz_localize(None).dt.normalize()
    out["trade_date"] = trade_date
    # A standard swap starts two business days after the trade. Count business
    # days, not calendar days: a Thursday trade starts the following Monday.
    # Allow three to absorb a public holiday, since no holiday calendar is used yet.
    out["start_lag_bdays"] = np.busday_count(
        trade_date.values.astype("datetime64[D]"), out["effective"].values.astype("datetime64[D]")
    )
    out["tenor_years"] = (out["maturity"] - out["effective"]).dt.days / 365.25
    out["start"] = "spot"
    out.loc[out["start_lag_bdays"] > 3, "start"] = "forward"
    out.loc[out["start_lag_bdays"] < 0, "start"] = "backdated"
    # When the row became public. After a correction this is the correction's
    # date, so "what was known on day D" can be reconstructed honestly.
    if "file_date" in t.columns:
        out["known_date"] = pd.to_datetime(t["file_date"].reindex(out.index), errors="coerce")
        out["report_lag_days"] = (out["known_date"] - trade_date).dt.days

    # "Standard": a plain swap whose fixed rate can be read as the market rate
    # for its tenor at that moment. Every other trade gets exactly one reason,
    # the first rule it fails, so exclusions add up and can be audited.
    out["exclusion"] = _first_failed(out, SWAP_RULES)
    out["standard"] = out["exclusion"] == ""
    # "Plain": passes every rule except the two about the start date. A plain
    # forward-starting swap is a usable price for a forward rate.
    out["plain"] = _first_failed(out, SWAP_RULES[2:]) == ""
    return out.sort_values("exec_ts").reset_index(drop=True)


# Order matters: it is the order of the exclusion waterfall in the data report.
SWAP_RULES = [
    ("starts before the trade date", lambda d: d["start"] == "backdated"),
    ("starts in the future", lambda d: d["start"] == "forward"),
    ("part of a package", lambda d: d["package"]),
    ("carries an upfront payment", lambda d: d["upfront_payment"]),
    ("has an embedded option", lambda d: d["embedded_option"] != ""),
    ("flagged as non-standard terms", lambda d: d["non_standard_terms"]),
    ("spread on the floating leg", lambda d: d["floating_spread"]),
    ("non-standard payment schedule", lambda d: ~_standard_schedule(d)),
    ("rate outside 0.01% to 20%", lambda d: ~d["fixed_rate_pct"].between(0.01, 20)),
]


def _text(t: pd.DataFrame, column: str) -> pd.Series:
    """A text column, or blanks when the source file did not have it."""
    return t[column] if column in t.columns else pd.Series("", index=t.index, dtype=object)


def _flag(t: pd.DataFrame, column: str) -> pd.Series:
    """A true/false field, read without regard to letter case.

    The public files wrote these as 'true'/'false' until 2 Nov 2025 and as
    'TRUE'/'FALSE' from 3 Nov 2025. Matching one spelling silently lost a
    year of package flags; see ADR 11.
    """
    return _text(t, column).str.strip().str.upper() == "TRUE"


def _standard_schedule(d: pd.DataFrame) -> pd.Series:
    """Fixed leg pays yearly on Actual/360, or once at the end for swaps up to a year.

    Dollar SOFR swaps of a year or less make a single payment at maturity, so
    "one payment at the end" is the standard schedule for them, not an oddity.
    """
    yearly = d["fixed_frequency"] == "YEAR"
    single = (d["fixed_frequency"] == "EXPI") & (d["tenor_years"] <= 1.05)
    return (yearly | single) & (d["fixed_day_count"] == "A004")


def _first_failed(df: pd.DataFrame, rules) -> pd.Series:
    """Name of the first rule each row fails; blank when it passes all of them."""
    reason = pd.Series("", index=df.index, dtype=object)
    for name, failed in rules:
        reason = reason.mask((reason == "") & failed(df), name)
    return reason
