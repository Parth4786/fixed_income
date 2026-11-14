"""US dollar swaptions: options to enter a SOFR swap at a fixed rate.

The buyer pays a premium today for the right, on the expiry date, to enter a
swap at the strike rate. Strike, expiry, premium and size are all published.
"""

from __future__ import annotations

import pandas as pd

from tapemark.clean.swaps import _first_failed, _flag, to_date, to_number

PATTERN = r"^NA/O (Call|P) Epn OIS USD$"  # European call or put on a USD overnight-index swap


def usd_swaptions(trades: pd.DataFrame) -> pd.DataFrame:
    t = trades[trades["UPI FISN"].str.match(PATTERN)]
    out = pd.DataFrame(
        {
            "trade_id": t["trade_id"],
            "exec_ts": pd.to_datetime(t["Execution Timestamp"], utc=True, errors="coerce"),
            "expiry": to_date(t["Expiration Date"]),
            "swap_maturity": to_date(t["Maturity date of the underlier"]),
            "strike_pct": pd.to_numeric(t["Strike Price"], errors="coerce") * 100,
            "premium": to_number(t["Option Premium Amount"]),
            "premium_ccy": t["Option Premium Currency"],
            "notional": to_number(t["Notional amount-Leg 1"]),
            "notional_capped": t["Notional amount-Leg 1"].str.endswith("+"),
            # Reported label only. Whether "Call" means the right to pay or to
            # receive fixed is settled later by checking prices, not assumed here.
            "reported_type": t["UPI FISN"].str.extract(PATTERN)[0].map({"Call": "call", "P": "put"}),
            "venue": t["Platform identifier"],
            "package": _flag(t, "Package indicator"),
            "n_corrections": t["n_corrections"],
        }
    )
    out = out.dropna(subset=["exec_ts", "expiry", "swap_maturity", "strike_pct", "premium", "notional"])
    trade_date = out["exec_ts"].dt.tz_localize(None).dt.normalize()
    out["trade_date"] = trade_date
    out["option_years"] = (out["expiry"] - trade_date).dt.days / 365.25
    out["swap_years"] = (out["swap_maturity"] - out["expiry"]).dt.days / 365.25
    out["premium_bp_of_notional"] = out["premium"] / out["notional"] * 1e4
    if "file_date" in t.columns:
        out["known_date"] = pd.to_datetime(t["file_date"].reindex(out.index), errors="coerce")
    out["exclusion"] = _first_failed(out, OPTION_RULES)
    out["usable"] = out["exclusion"] == ""
    return out.sort_values("exec_ts").reset_index(drop=True)


OPTION_RULES = [
    ("no premium reported", lambda d: ~(d["premium"] > 0)),
    ("no strike reported", lambda d: ~(d["strike_pct"] > 0)),
    ("premium not in dollars", lambda d: d["premium_ccy"] != "USD"),
    ("size capped in the public record", lambda d: d["notional_capped"]),
    ("expires within a week", lambda d: ~(d["option_years"] > 0.02)),
    ("underlying swap shorter than a year", lambda d: ~(d["swap_years"] > 0.9)),
]
