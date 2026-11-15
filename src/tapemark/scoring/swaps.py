"""Walk-forward scoring of swap pricing against real trades.

Every clean trade is predicted before it is used. Four predictions are kept
side by side so the model has to earn its place:

- ``filter``     the curve filter's expectation just before the trade
- ``last``       the last clean trade of the same length (simple baseline)
- ``prev_close`` yesterday's outside closing curve (stale baseline)
- ``same_close`` today's outside closing curve. This uses information from
                 after the trade, so it is a reference, not a fair competitor.

Forward-starting swaps are never used to fit anything, so they are a second,
fully held-out test of the curve itself.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd

from tapemark.models.curve_filter import NODES, CurveFilter, trailing_covariance
from tapemark.models.meeting_curve import stepped
from tapemark.paths import CLEAN, DATA
from tapemark.pricing.curve import Curve, par_rate
from tapemark.sources import dtcc, eris

RESULTS = DATA / "results"
SYMBOLS = {0.25: "SOFR3M", 0.5: "SOFR6M", 1: "SOFR12M", 2: "SOFR2Y", 3: "SOFR3Y", 4: "SOFR4Y", 5: "SOFR5Y", 7: "SOFR7Y",
           10: "SOFR10Y", 12: "SOFR12Y", 15: "SOFR15Y", 20: "SOFR20Y", 25: "SOFR25Y", 30: "SOFR30Y"}
BURN_IN_DAYS = 60  # trading days used to settle the filter and choose its noise level; never scored
COV_WINDOW = 120
COVERAGE = 0.90
CONFORMAL_WINDOW = 5000


def eris_par_table() -> pd.DataFrame:
    """Outside closing par rates at the filter's nodes, one row per day. Cached."""
    path = CLEAN / "eris_par.parquet"
    if path.exists():
        return pd.read_parquet(path)
    rows = {}
    day, end = dtcc.available_days()[0], dtcc.available_days()[-1]
    while day <= end:
        if eris.raw_path(day, "par").exists():
            par = eris.par_rates(day)
            if all(s in par.index for s in SYMBOLS.values()):
                rows[pd.Timestamp(day)] = [par[s] for s in SYMBOLS.values()]
        day += dt.timedelta(days=1)
    table = pd.DataFrame.from_dict(rows, orient="index", columns=[str(t) for t in SYMBOLS])
    table.to_parquet(path)
    return table


def _run_filter(prints: pd.DataFrame, par: pd.DataFrame, noise_sd: float, snapshot_minutes: int = 10, huber: float = 3.0, cov_window: int = COV_WINDOW):
    """One pass over the trades in time order. Returns per-trade predictions and state snapshots."""
    par_days = par.index.values
    par_vals = par.values
    ts = prints["exec_ts"].values.astype("datetime64[s]")
    day_of = prints["trade_date"].values.astype("datetime64[D]")
    tenor = prints["tenor_years"].values
    rate = prints["fixed_rate_pct"].values

    first_idx = int(np.searchsorted(par_days, day_of[0], side="left"))
    x0 = par_vals[max(first_idx - 1, 0)]
    q = trailing_covariance(par_vals[: max(first_idx, 30)][-cov_window:]) if first_idx >= 30 else trailing_covariance(par_vals[:30])
    f = CurveFilter(x0, q * 4.0, q, noise_sd, huber)

    n = len(prints)
    pred, sd, damped = np.empty(n), np.empty(n), np.zeros(n, dtype=bool)
    snaps_t, snaps_x = [], []
    snap_step = np.timedelta64(snapshot_minutes * 60, "s")
    next_snap = ts[0]
    last_ts, last_month = ts[0], None
    for i in range(n):
        month = day_of[i].astype("datetime64[M]")
        if month != last_month:  # refresh how rates move together, from the past only
            k = int(np.searchsorted(par_days, day_of[i], side="left"))
            if k >= 30:
                f.q = trailing_covariance(par_vals[:k][-cov_window:])
            last_month = month
        while ts[i] >= next_snap:  # state as known strictly before this trade
            snaps_t.append(next_snap)
            snaps_x.append(f.x.copy())
            next_snap = next_snap + snap_step if ts[i] - next_snap < np.timedelta64(86400, "s") else ts[i].astype("datetime64[D]").astype("datetime64[s]") + ((ts[i] - ts[i].astype("datetime64[D]").astype("datetime64[s]")) // snap_step + 1) * snap_step
        gap_days = min((ts[i] - last_ts) / np.timedelta64(86400, "s"), 1.0)
        f.advance(float(gap_days))
        step = f.update(float(tenor[i]), float(rate[i]))
        pred[i], sd[i], damped[i] = step.prediction, step.sd, step.damped
        last_ts = ts[i]
    snaps_t.append(ts[-1] + np.timedelta64(1, "s"))  # closing state, after the final trade
    snaps_x.append(f.x.copy())
    snaps = pd.DataFrame(np.array(snaps_x), columns=[str(t) for t in NODES])
    snaps.insert(0, "ts", np.array(snaps_t))
    return pred, sd, damped, snaps


def _interp_close(par: pd.DataFrame, days: np.ndarray, tenor: np.ndarray, lag: int) -> np.ndarray:
    """Outside closing rate at each trade's length, from the same day (lag 0) or the previous one (lag 1)."""
    idx = np.searchsorted(par.index.values, days, side="left")
    exact = (idx < len(par)) & (par.index.values[np.minimum(idx, len(par) - 1)] == days)
    row = np.where(exact, idx, idx - 1) - lag if lag == 0 else idx - 1
    out = np.full(len(days), np.nan)
    ok = (row >= 0) & (exact if lag == 0 else True)
    vals = par.values
    for r in np.unique(row[ok]):
        m = ok & (row == r)
        out[m] = np.interp(tenor[m], NODES, vals[r])
    return out


def score_spot() -> pd.DataFrame:
    """Predict every clean spot-starting trade before using it."""
    swaps = pd.read_parquet(CLEAN / "usd_sofr_swaps.parquet")
    par = eris_par_table()
    prints = swaps[swaps["standard"] & (swaps["tenor_years"] >= 0.2) & (swaps["trade_date"] >= par.index[0])]
    prints = prints.sort_values("exec_ts").reset_index(drop=True)
    # One execution is sometimes published as several identical rows (allocations).
    # Counting each would make the filter overconfident and flatter every model.
    same = pd.DataFrame({"t": prints["exec_ts"].dt.floor("s"), "b": (prints["tenor_years"] * 4).round(), "r": prints["fixed_rate_pct"]})
    prints = prints[~same.duplicated(keep="first")].reset_index(drop=True)
    days = np.sort(prints["trade_date"].unique())
    burn_end = days[min(BURN_IN_DAYS, len(days) - 1)]
    burn = prints[prints["trade_date"] < burn_end]

    # Trade noise is chosen on the burn-in period only, then frozen.
    tried = {}
    for noise in (0.0015, 0.0025, 0.004, 0.006, 0.009, 0.014):
        p, _, _, _ = _run_filter(burn, par, noise)
        tried[noise] = float(np.median(np.abs(burn["fixed_rate_pct"].values - p)[len(burn) // 4:]))
    noise = min(tried, key=tried.get)

    pred, sd, damped, snaps = _run_filter(prints, par, noise)
    out = prints[["trade_id", "exec_ts", "trade_date", "tenor_years", "fixed_rate_pct", "notional", "venue", "cleared"]].copy()
    out["filter"], out["filter_sd"], out["damped"] = pred, sd, damped
    bucket = (out["tenor_years"] * 4).round() / 4
    out["last"] = out.groupby(bucket)["fixed_rate_pct"].shift(1)
    d = out["trade_date"].values.astype("datetime64[ns]")
    out["prev_close"] = _interp_close(par, d, out["tenor_years"].values, 1)
    out["same_close"] = _interp_close(par, d, out["tenor_years"].values, 0)
    out["scored"] = out["trade_date"] >= burn_end

    # Uncertainty bands with a coverage target, calibrated on the past only
    # (split conformal prediction on the standardised gap).
    z = (out["fixed_rate_pct"] - out["filter"]).abs() / out["filter_sd"]
    out["band_mult"] = z.rolling(CONFORMAL_WINDOW, min_periods=1000).quantile(COVERAGE).shift(1)
    out["in_band"] = z <= out["band_mult"]
    out["in_raw_band"] = z <= 1.645

    RESULTS.mkdir(parents=True, exist_ok=True)
    out.to_parquet(RESULTS / "swap_scores.parquet", index=False)
    snaps.to_parquet(RESULTS / "curve_snapshots.parquet", index=False)
    (RESULTS / "swap_filter.json").write_text(json.dumps({"noise_sd_pct": noise, "tried": tried, "burn_in_ends": str(pd.Timestamp(burn_end).date())}))
    return out


def score_forwards() -> pd.DataFrame:
    """Price forward-starting swaps, which no model here was fitted to."""
    swaps = pd.read_parquet(CLEAN / "usd_sofr_swaps.parquet")
    snaps = pd.read_parquet(RESULTS / "curve_snapshots.parquet")
    burn_end = pd.Timestamp(json.loads((RESULTS / "swap_filter.json").read_text())["burn_in_ends"])
    fw = swaps[(swaps["start"] == "forward") & swaps["plain"] & (swaps["tenor_years"] >= 0.08) & (swaps["trade_date"] >= burn_end)]
    fw = fw.sort_values("exec_ts").reset_index(drop=True)
    eff = fw["effective"].values.astype("datetime64[D]")
    mat = fw["maturity"].values.astype("datetime64[D]")
    ts = fw["exec_ts"].values.astype("datetime64[s]")
    day = fw["trade_date"].values.astype("datetime64[D]")

    # Filter curve: the latest snapshot taken before the trade.
    snap_ts = snaps["ts"].values.astype("datetime64[s]")
    snap_x = snaps[[str(t) for t in NODES]].values
    which = np.searchsorted(snap_ts, ts, side="right") - 1
    model, steps = np.full(len(fw), np.nan), np.full(len(fw), np.nan)
    near = (mat - day).astype(int) <= 730          # the step curve only changes the first two years
    for s in np.unique(which[which >= 0]):
        m = which == s
        asof = day[m][0]
        curve = Curve.from_par(asof, NODES, snap_x[s])
        model[m] = par_rate(curve, eff[m], mat[m])
        mn = m & near
        if mn.any():
            steps[mn] = par_rate(stepped(curve), eff[mn], mat[mn])
    steps = np.where(near, steps, model)

    # Outside curve, same day and previous day, from its full discount-factor file.
    same, prev = np.full(len(fw), np.nan), np.full(len(fw), np.nan)
    have = [d for d in pd.to_datetime(np.unique(day)) if eris.raw_path(d.date(), "discount").exists()]
    prev_curve = None
    for d in have:
        dfs = eris.discount_factors(d.date())
        curve = Curve.from_discount_factors(d.date(), dfs.index.values.astype("datetime64[D]"), dfs.values)
        m = day == np.datetime64(d, "D")
        same[m] = par_rate(curve, eff[m], mat[m])
        if prev_curve is not None:
            prev[m] = par_rate(prev_curve, eff[m], mat[m])
        prev_curve = curve
    out = fw[["trade_id", "exec_ts", "trade_date", "effective", "maturity", "tenor_years", "start_lag_bdays", "fixed_rate_pct", "notional"]].copy()
    out["filter"], out["same_close"], out["prev_close"], out["meeting_steps"] = model, same, prev, steps
    out.to_parquet(RESULTS / "swap_forward_scores.parquet", index=False)
    return out


def price_as_of(frame: pd.DataFrame) -> np.ndarray:
    """Fair rate for each swap in ``frame`` from the curve known just before it traded."""
    snaps = pd.read_parquet(RESULTS / "curve_snapshots.parquet")
    snap_ts = snaps["ts"].values.astype("datetime64[s]")
    snap_x = snaps[[str(t) for t in NODES]].values
    ts = frame["exec_ts"].values.astype("datetime64[s]")
    day = frame["trade_date"].values.astype("datetime64[D]")
    eff = frame["effective"].values.astype("datetime64[D]")
    mat = frame["maturity"].values.astype("datetime64[D]")
    which = np.searchsorted(snap_ts, ts, side="right") - 1
    out = np.full(len(frame), np.nan)
    order = np.argsort(which, kind="stable")
    bounds = np.flatnonzero(np.diff(which[order])) + 1
    for idx in np.split(order, bounds):
        s = which[idx[0]]
        if s >= 0:
            out[idx] = par_rate(Curve.from_par(day[idx[0]], NODES, snap_x[s]), eff[idx], mat[idx])
    return out


def _stats(err_pct: pd.Series) -> dict:
    e = err_pct.dropna().abs() * 100  # basis points
    return {"n": int(len(e)), "median_bp": round(float(e.median()), 3), "p95_bp": round(float(e.quantile(0.95)), 2)} if len(e) else {"n": 0}


def diebold_mariano(loss_a: pd.Series, loss_b: pd.Series, by_day: pd.Series, lags: int = 5) -> dict:
    """Is model A's daily average loss reliably lower than B's? Newey-West standard error."""
    d = (loss_a - loss_b).groupby(by_day).mean().dropna().values
    n = len(d)
    mean = d.mean()
    c = d - mean
    var = (c @ c) / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * (c[k:] @ c[:-k]) / n
    t = mean / np.sqrt(var / n)
    return {"days": int(n), "mean_diff_bp": round(float(mean * 100), 4), "t_stat": round(float(t), 2)}


def _meeting_test(f: pd.DataFrame) -> dict:
    """Smooth short end against steps on Fed meeting dates, on forward swaps maturing within two years.

    Same trades, same moment, same curve points; only the shape between the points differs. The comparison is
    paired by trading day: the mean daily difference in absolute miss and its t-statistic.
    """
    out = {}
    for name, g in (("under 1y long", f[f["tenor_years"] < 0.95]), ("1y to 2y long", f[f["tenor_years"] >= 0.95])):
        e0 = (g["filter"] - g["fixed_rate_pct"]).abs() * 100
        e1 = (g["meeting_steps"] - g["fixed_rate_pct"]).abs() * 100
        d = (e1 - e0).groupby(g["trade_date"]).mean()
        out[name] = {"trades": int(len(g)), "days": int(len(d)), "smooth_bp": round(float(e0.median()), 3), "steps_bp": round(float(e1.median()), 3),
                     "daily_diff_bp": round(float(d.mean()), 4), "t": round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2), "days_better_pct": round(float(100 * (d < 0).mean()), 1)}
    return out


def summarise() -> dict:
    s = pd.read_parquet(RESULTS / "swap_scores.parquet")
    s = s[s["scored"]]
    models = ["filter", "last", "prev_close", "same_close"]
    err = {m: s[m] - s["fixed_rate_pct"] for m in models}
    both = s["last"].notna()
    bucket = pd.cut(s["tenor_years"], [0, 1.5, 3.5, 7.5, 12.5, 60], labels=["up to 1y", "2-3y", "4-7y", "8-12y", "over 12y"])
    whole = (s["tenor_years"] - s["tenor_years"].round()).abs() < 0.05
    month = s["trade_date"].dt.to_period("M").astype(str)
    hour = s["exec_ts"].dt.hour
    size = pd.cut(s["notional"], [0, 25e6, 100e6, 1e12], labels=["under 25m", "25m to 100m", "over 100m"])
    abs_f = err["filter"].abs() * 100
    out = {
        "period": [str(s["trade_date"].min().date()), str(s["trade_date"].max().date())],
        "overall": {m: _stats(err[m]) for m in models},
        "by_length": {str(b): {m: _stats(err[m][bucket == b]) for m in models} for b in bucket.cat.categories},
        "odd_lengths": {m: _stats(err[m][~whole]) for m in models},
        "by_month": {mo: {"filter": _stats(err["filter"][month == mo]), "last": _stats(err["last"][month == mo]),
                          "coverage": round(float(s["in_band"][month == mo].mean()), 3)} for mo in sorted(month.unique())},
        "by_hour_utc": {int(h): _stats(err["filter"][hour == h]) for h in sorted(hour.unique()) if (hour == h).sum() >= 500},
        "by_size": {str(b): _stats(err["filter"][size == b]) for b in size.cat.categories},
        "by_venue": {v: _stats(err["filter"][s["venue"] == v]) for v in s["venue"].value_counts().head(6).index},
        "filter_vs_last": diebold_mariano(err["filter"][both].abs(), err["last"][both].abs(), s["trade_date"][both]),
        "filter_vs_prev_close": diebold_mariano(err["filter"].abs(), err["prev_close"].abs(), s["trade_date"]),
        "coverage": {"target": COVERAGE, "calibrated": round(float(s["in_band"][s["band_mult"].notna()].mean()), 4),
                     "uncalibrated": round(float(s["in_raw_band"].mean()), 4),
                     "band_half_width_bp_median": round(float((s["band_mult"] * s["filter_sd"]).median() * 100), 2)},
        "damped_share": round(float(s["damped"].mean()), 4),
        "worst": s.assign(gap_bp=abs_f).nlargest(8, "gap_bp")[["exec_ts", "tenor_years", "fixed_rate_pct", "filter", "gap_bp", "venue"]]
        .assign(exec_ts=lambda d: d["exec_ts"].astype(str)).round(3).to_dict("records"),
        "filter_settings": json.loads((RESULTS / "swap_filter.json").read_text()),
    }
    fpath = RESULTS / "swap_forward_scores.parquet"
    if fpath.exists():
        f = pd.read_parquet(fpath)
        lag = pd.cut(f["start_lag_bdays"], [0, 66, 260, 520, 1e5], labels=["starts within 3m", "3m to 1y", "1y to 2y", "over 2y"])
        length = pd.cut(f["tenor_years"], [0, 0.95, 5.5, 60], labels=["under 1y long", "1-5y long", "over 5y long"])
        fm = ["filter", "prev_close", "same_close"]
        ferr = {m: f[m] - f["fixed_rate_pct"] for m in fm}
        out["forwards"] = {
            "overall": {m: _stats(ferr[m]) for m in fm},
            "by_start": {str(b): {m: _stats(ferr[m][lag == b]) for m in fm} for b in lag.cat.categories},
            "by_length": {str(b): {m: _stats(ferr[m][length == b]) for m in fm} for b in length.cat.categories},
        }
        if "meeting_steps" in f:
            near = (f["maturity"] - f["trade_date"]).dt.days <= 730
            out["forwards"]["meeting_steps"] = _meeting_test(f[near])
    (RESULTS / "swap_summary.json").write_text(json.dumps(out, indent=1))
    return out
