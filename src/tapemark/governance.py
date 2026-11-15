"""Model governance: what each model is for, whether it is behaving today, and where every number came from.

Three parts, the ones a model-risk or audit reviewer asks for first:

1. Monitoring. The alarms written down in docs/VALIDATION.md, computed on the
   latest data instead of described: volume of clean trades, band coverage,
   drift in the typical miss, share of trades damped, and shifts in why trades
   are excluded. Each is green, amber (close to its limit) or red.
2. Model inventory. Each model's purpose, inputs, key assumption, known limit
   and the evidence behind it, with the evidence read from the result files.
3. Data lineage. For each source: how many files, which days they cover, the
   newest file and its SHA-256, so any figure can be traced to the bytes it
   was computed from. Result files are hashed too: the published numbers.

Nothing here changes a result; it only reads them.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from tapemark.paths import DATA

RAW = DATA / "raw"
RESULTS = DATA / "results"


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _when(path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


_DAY = re.compile(r"(20\d\d)[-_]?(\d\d)[-_]?(\d\d)")


def _day_of(name: str) -> str | None:
    m = _DAY.search(name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


SOURCES = [
    ("DTCC public swap reports", "dtcc", "Every reported US dollar swap and swap option, daily files", "pddata.dtcc.com"),
    ("Eris swap futures (CME)", "eris", "Daily settlements: prices, risk, margin, options, curves", "files.erisfutures.com"),
    ("Federal Reserve and New York Fed", "fed", "Treasury and TIPS curves, SOFR, Fed Treasury holdings", "federalreserve.gov, markets.newyorkfed.org"),
]


def lineage() -> dict:
    """Per source: files, days covered, bytes, newest file with its hash. Result files are all hashed."""
    rows = []
    for name, folder, what, origin in SOURCES:
        root = RAW / folder
        files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
        if not files:
            rows.append({"source": name, "what": what, "origin": origin, "files": 0})
            continue
        days = sorted(d for d in (_day_of(p.name) for p in files) if d)
        newest = max(files, key=lambda p: (_day_of(p.name) or "", p.stat().st_mtime))
        rows.append({"source": name, "what": what, "origin": origin, "files": len(files), "bytes": int(sum(p.stat().st_size for p in files)),
                     "first_day": days[0] if days else None, "last_day": days[-1] if days else None,
                     "newest_file": newest.relative_to(RAW).as_posix(), "newest_sha256": _sha256(newest), "fetched": _when(newest)})
    results = [{"file": p.name, "bytes": p.stat().st_size, "written": _when(p), "sha256": _sha256(p)}
               for p in sorted(RESULTS.glob("*")) if p.is_file() and p.suffix in (".json", ".parquet")]
    return {"sources": rows, "results": results}


def _status(value, amber, red, higher_is_bad=True) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    bad = value >= red if higher_is_bad else value <= red
    warn = value >= amber if higher_is_bad else value <= amber
    return "red" if bad else "amber" if warn else "green"


def monitoring(scores: pd.DataFrame, monthly: list[dict]) -> list[dict]:
    """The alarms of docs/VALIDATION.md on the latest data."""
    s = scores[scores["scored"]] if "scored" in scores else scores
    days = np.sort(s["trade_date"].unique())
    last = days[-1]
    out = []

    n = int((s["trade_date"] == last).sum())
    out.append({"signal": "Clean swaps on the latest day", "value": f"{n:,}", "limit": "alarm below 500", "status": _status(n, 750, 500, higher_is_bad=False),
                "day": str(pd.Timestamp(last).date())})

    month = s["trade_date"].dt.to_period("M")
    full = sorted(month.unique())
    m = full[-2] if len(full) > 1 and (s[month == full[-1]]["trade_date"].nunique() < 10) else full[-1]
    cov = float(s.loc[month == m, "in_band"].mean())
    dist = abs(cov - 0.90)
    out.append({"signal": f"Band coverage, {m}", "value": f"{cov * 100:.1f}%", "limit": "alarm outside 85% to 95%", "status": _status(dist, 0.03, 0.05)})

    recent = s[s["trade_date"].isin(days[-5:])]["gap_bp"].abs().median()
    trail = s[s["trade_date"].isin(days[-65:-5])]["gap_bp"].abs().median()
    ratio = float(recent / trail) if trail else np.nan
    out.append({"signal": "Typical miss, last 5 days against the 60 before", "value": f"{recent:.2f} bp vs {trail:.2f} bp ({ratio:.2f}×)", "limit": "alarm above 2×",
                "status": _status(ratio, 1.5, 2.0)})

    damped = float(s[s["trade_date"].isin(days[-20:])]["damped"].mean())
    out.append({"signal": "Share of trades damped, last 20 days", "value": f"{damped * 100:.1f}%", "limit": "alarm above 30%", "status": _status(damped, 0.2, 0.3)})

    if len(monthly) >= 3:
        a, b = monthly[-2], monthly[-3]                                     # the last complete month against the one before
        shifts = []
        for key, label in (("package_pct", "inside packages"), ("corrected_pct", "corrected later")):
            if b.get(key):
                shifts.append((abs(a[key] / b[key] - 1), label, a[key], b[key]))
        clean_a, clean_b = a["clean"] / a["swaps"], b["clean"] / b["swaps"]
        shifts.append((abs(clean_a / clean_b - 1), "clean share", clean_a * 100, clean_b * 100))
        worst = max(shifts)
        out.append({"signal": f"Exclusion reasons, {a['month']} against {b['month']}", "value": f"{worst[1]}: {worst[3]:.1f}% → {worst[2]:.1f}%",
                    "limit": "alarm if any share moves by more than a third", "status": _status(worst[0], 0.2, 1 / 3)})
    return out


def inventory(evidence: dict) -> list[dict]:
    """The models in use, each with what it is for and the evidence behind it."""
    e = evidence
    return [
        {"model": "Curve model (Kalman filter)", "use": "Fair swap rate, normal range, curve on every screen", "inputs": "Clean DTCC swap trades",
         "assumption": "The curve moves as a whole; each trade is a noisy look at it", "limit": "Short forward-starting swaps are a weak spot",
         "evidence": e.get("curve"), "monitored": True},
        {"model": "Normal range (conformal band)", "use": "Whether a trade is unusual", "inputs": "Past errors of the curve model",
         "assumption": "Recent errors describe the next ones", "limit": "Trades in time order are not exchangeable; checked month by month", "evidence": e.get("band"), "monitored": True},
        {"model": "Swap option volatility", "use": "Option premiums and verdicts", "inputs": "DTCC swap option trades",
         "assumption": "The last similar trade is the best guide when recent", "limit": "Sparse trading at long expiries", "evidence": e.get("options"), "monitored": False},
        {"model": "Hull-White and Bermudan engines", "use": "Options with many exercise dates", "inputs": "Curve, Hull-White fit to option trades",
         "assumption": "One factor, constant parameters", "limit": "Mean reversion is not pinned by European prices", "evidence": e.get("bermudan"), "monitored": False},
        {"model": "Swap futures engine", "use": "Eris futures prices and risk", "inputs": "Eris settlements, SOFR fixings",
         "assumption": "Exchange's own price formula", "limit": "LIBOR-era contracts left out of one check", "evidence": e.get("futures"), "monitored": False},
        {"model": "Margin rule", "use": "Margin and its funding cost", "inputs": "Six years of Eris curves",
         "assumption": "Historical moves over the close-out period", "limit": "Clearing house confidence level not public", "evidence": e.get("margin"), "monitored": False},
        {"model": "Supervisory shocks and VaR", "use": "Book risk, regulatory views", "inputs": "Saved trades, Fed Treasury holdings and curves",
         "assumption": "EBA shock sizes (2016 calibration); historical simulation", "limit": "2024 Basel recalibration not applied", "evidence": e.get("var"), "monitored": False},
        {"model": "Hedge (risk by curve point)", "use": "Hedges on Price a trade", "inputs": "Curve model",
         "assumption": "First-order risk is enough for one day", "limit": "Large moves need full repricing (shown under Scenarios)", "evidence": e.get("hedge"), "monitored": False},
    ]


# ---------------------------------------------------------------------------------------------------------------
# Forecast evaluation in the terms a bank's validation team uses.

def forecast_metrics(scores: pd.DataFrame) -> dict:
    """The curve model's predictions against each next trade, beside the last trade as the naive forecast.

    error         traded rate minus prediction, bp
    RMSE, MAE     size of errors; bias is their mean
    Theil's U     RMSE of the model over RMSE of the last trade (a random walk); below 1 beats it
    Mincer-Zarnowitz   regress the move from the last trade, (traded - last), on the predicted move,
                  (prediction - last). An unbiased, efficient forecast has intercept 0 and slope 1.
                  Standard errors are clustered by day, since trades on one day share news.
    Off-market prints (over 25 bp from the model or from the last trade) are left out and counted.
    Hit rate      share of trades where the predicted move and the actual move have the same sign
                  (both at least 0.1 bp), against 50% for a coin.
    """
    s0 = scores[scores["scored"] & scores["last"].notna()]
    keep = (s0["gap_bp"].abs() <= 25) & ((s0["fixed_rate_pct"] - s0["last"]).abs() * 100 <= 25)   # off-market prints (terms not in the record) are left out, and counted
    s = s0[keep]
    err = s["gap_bp"].to_numpy()
    naive = ((s["fixed_rate_pct"] - s["last"]) * 100).to_numpy()
    pred = ((s["filter"] - s["last"]) * 100).to_numpy()
    rmse, rmse_naive = float(np.sqrt(np.mean(err**2))), float(np.sqrt(np.mean(naive**2)))
    X = np.column_stack([np.ones_like(pred), pred])
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ naive
    resid = naive - X @ beta
    day = s["trade_date"].to_numpy()
    meat = np.zeros((2, 2))
    for g in np.unique(day):
        m = day == g
        v = X[m].T @ resid[m]
        meat += np.outer(v, v)
    se = np.sqrt(np.diag(xtx_inv @ meat @ xtx_inv))
    both = (np.abs(pred) >= 0.1) & (np.abs(naive) >= 0.1)
    hit = float(np.mean(np.sign(pred[both]) == np.sign(naive[both])))
    return {"trades": int(len(s)), "left_out": int((~keep).sum()), "days": int(len(np.unique(day))), "rmse_bp": rmse, "mae_bp": float(np.mean(np.abs(err))), "bias_bp": float(np.mean(err)),
            "rmse_last_bp": rmse_naive, "theil_u": rmse / rmse_naive,
            "mz": {"intercept": float(beta[0]), "intercept_se": float(se[0]), "slope": float(beta[1]), "slope_se": float(se[1]),
                   "r2": float(1 - resid.var() / naive.var())},
            "hit_rate": hit, "hit_trades": int(both.sum())}
