"""Volatility from real option premiums, and a walk-forward test of predicting it.

Step 1. For each traded option, work out the forward swap rate F and annuity A
from the curve known at the moment of the trade (the curve filter's latest
snapshot), then find the volatility that makes the normal-model price equal
the premium paid. "Call" is read as the right to pay fixed: under that reading
far more trades have a valid volatility, and out-of-the-money calls sit above
the forward rate as they should.

Step 2. Predict each trade's volatility from earlier trades only, four ways:

- ``flat``     one number: the median volatility of the last few days
- ``last``     the last trade in the same expiry and swap-length bucket
- ``surface``  a smooth at-the-money surface: a weighted average of earlier
               near-the-money trades, weighted by closeness in expiry and swap
               length and by recency
- ``smile``    the surface, adjusted for how far the strike is from the
               forward, with the adjustment fitted on earlier trades
- ``anchored`` the last similar trade, moved by the surface's difference
               between that trade and this one
- ``hull_white`` a one-factor rate model: two numbers, fitted each day to
               earlier days' trades, give a volatility for every option

Step 3. Score: predicted minus traded volatility, and the same thing as a
premium, on standalone trades. Package legs are scored separately because a
leg's reported premium may belong to the whole bundle.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from tapemark.models.curve_filter import NODES
from tapemark.paths import CLEAN, DATA
from tapemark.pricing import hullwhite
from tapemark.pricing import options as opt
from tapemark.pricing.calendar import add_business_days
from tapemark.pricing.curve import Curve, annuity_and_float

RESULTS = DATA / "results"
WINDOW_DAYS = 20  # trading days of history a prediction may use
BANDWIDTH = 0.45  # kernel width in log-expiry / log-length units
HALF_LIFE_DAYS = 5.0
NEAR_MONEY = 0.5  # |strike - forward| below this many standard deviations counts as near the money
VOL_RANGE = (0.0020, 0.0300)  # implied volatilities outside 20 to 300 bp/yr are treated as bad rows
GRID_EXPIRY = [1 / 12, 0.25, 0.5, 1, 2, 3, 5, 10]
GRID_TENOR = [1, 2, 5, 10, 30]
HW_A = [0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12]  # candidate pull-back speeds for the Hull-White model


def implied_vols() -> pd.DataFrame:
    """Forward rate, annuity and implied volatility for every usable option trade."""
    o = pd.read_parquet(CLEAN / "usd_swaptions.parquet")
    o = o[o["usable"]].sort_values("exec_ts").reset_index(drop=True)
    snaps = pd.read_parquet(RESULTS / "curve_snapshots.parquet")
    snap_ts = snaps["ts"].values.astype("datetime64[s]")
    snap_x = snaps[[str(t) for t in NODES]].values
    ts = o["exec_ts"].values.astype("datetime64[s]")
    day = o["trade_date"].values.astype("datetime64[D]")
    start = add_business_days(o["expiry"].values.astype("datetime64[D]"), 2)
    end = o["swap_maturity"].values.astype("datetime64[D]")
    which = np.searchsorted(snap_ts, ts, side="right") - 1
    fwd, ann = np.full(len(o), np.nan), np.full(len(o), np.nan)
    expiry = o["expiry"].values.astype("datetime64[D]")
    hw = np.full((len(o), len(HW_A)), np.nan)
    for s in np.unique(which[which >= 0]):
        m = which == s
        curve = Curve.from_par(day[m][0], NODES, snap_x[s])
        a, fl = annuity_and_float(curve, start[m], end[m])
        ann[m], fwd[m] = a, fl / a
        for k, speed in enumerate(HW_A):
            hw[m, k] = hullwhite.normal_vol_factor(curve, expiry[m], start[m], end[m], speed)
    o["forward_pct"], o["annuity"] = fwd * 100, ann
    for k in range(len(HW_A)):
        o[f"hw_{k}"] = hw[:, k]
    payer = (o["reported_type"] == "call").values
    price = (o["premium"] / o["notional"]).values
    k, t = o["strike_pct"].values / 100, o["option_years"].values
    vol = opt.implied_vol(price, fwd, k, t, ann, payer)
    o["payer"] = payer
    o["vol_bp"] = vol * 1e4
    o["vega"] = opt.vega(fwd, k, t, np.where(np.isfinite(vol), vol, 0.01), ann)
    o["moneyness_bp"] = (k - fwd) * 1e4
    o["z"] = (k - fwd) / (np.where(np.isfinite(vol), vol, 0.01) * np.sqrt(t))
    o["valid"] = np.isfinite(vol) & (vol >= VOL_RANGE[0]) & (vol <= VOL_RANGE[1]) & np.isfinite(fwd)
    o.to_parquet(RESULTS / "option_vols.parquet", index=False)
    return o


def _kernel(lt_a, ln_a, lt_b, ln_b):
    """Closeness of each target (a) to each earlier trade (b) in log expiry and log swap length."""
    d2 = (lt_a[:, None] - lt_b[None, :]) ** 2 + (ln_a[:, None] - ln_b[None, :]) ** 2
    return np.exp(-0.5 * d2 / BANDWIDTH**2)


def _fit_smile(z, ratio):
    """Least-squares fit of vol / at-the-money vol = 1 + a*z + b*z^2, clipped against outliers."""
    ok = np.isfinite(z) & np.isfinite(ratio) & (np.abs(z) < 3) & (ratio > 0.5) & (ratio < 2.0)
    if ok.sum() < 30:
        return 0.0, 0.0
    x = np.column_stack([z[ok], z[ok] ** 2])
    coef, *_ = np.linalg.lstsq(x, ratio[ok] - 1.0, rcond=None)
    return float(coef[0]), float(coef[1])


def score() -> pd.DataFrame:
    """Predict every option trade's volatility from earlier trades only."""
    o = pd.read_parquet(RESULTS / "option_vols.parquet")
    o = o[o["valid"]].sort_values("exec_ts").reset_index(drop=True)
    days = np.sort(o["trade_date"].unique())
    day_idx = np.searchsorted(days, o["trade_date"].values)
    ts = o["exec_ts"].values.astype("datetime64[s]").astype(np.int64)
    lt, ln = np.log(o["option_years"].values), np.log(np.maximum(o["swap_years"].values, 0.5))
    vol, z = o["vol_bp"].values, o["z"].values
    alone = (~o["package"]).values
    near = np.abs(z) < NEAR_MONEY
    exp_b = np.digitize(o["option_years"].values, [0.2, 0.75, 1.5, 3.5, 7.5])
    ten_b = np.digitize(o["swap_years"].values, [1.5, 3.5, 7.5, 12.5, 25])
    bucket = exp_b * 10 + ten_b

    n = len(o)
    flat, last, surf, smile, support = (np.full(n, np.nan) for _ in range(5))
    hw_pred = np.full(n, np.nan)
    hw_fac = o[[f"hw_{k}" for k in range(len(HW_A))]].values
    hw_params = {}
    grids = {}
    smile_coef = (0.0, 0.0)
    for d in range(len(days)):
        target = np.where(day_idx == d)[0]
        hist = np.where((day_idx >= d - WINDOW_DAYS) & (day_idx <= d) & alone)[0]
        if len(target) == 0 or len(hist) < 50:
            continue
        before = hist[day_idx[hist] < d]
        if len(before) >= 30:
            flat[target] = np.median(vol[before[day_idx[before] >= d - 5]]) if (day_idx[before] >= d - 5).any() else np.median(vol[before])
        # Smile shape: refitted at the start of each month from earlier days only.
        if d % 21 == 0 and len(before) >= 200:
            atm_guess = np.median(vol[before][near[before]])
            smile_coef = _fit_smile(z[before], vol[before] / atm_guess)
        # Hull-White: two numbers fitted to earlier days' near-the-money trades, then used to predict today.
        fit = before[near[before]] if len(before) else before
        fit = fit[np.isfinite(hw_fac[fit]).all(axis=1)] if len(fit) else fit
        if len(fit) >= 60:
            k, sig, rmse = hullwhite.calibrate(hw_fac[fit], vol[fit] / 1e4)
            hw_pred[target] = sig * hw_fac[target, k] * 1e4
            hw_params[str(pd.Timestamp(days[d]).date())] = [HW_A[k], round(sig, 6), round(rmse * 1e4, 1)]
        core = hist[near[hist]]
        if len(core) < 20:
            continue
        w = _kernel(lt[target], ln[target], lt[core], ln[core])
        age_days = (ts[target][:, None] - ts[core][None, :]) / 86400.0
        w = w * np.exp(-np.log(2) * np.maximum(age_days, 0) / HALF_LIFE_DAYS) * (age_days > 0)  # strictly earlier trades
        total = w.sum(axis=1)
        ok = total > 0.5
        surf[target[ok]] = (w[ok] @ vol[core]) / total[ok]
        support[target] = total
        a, b = smile_coef
        smile[target] = surf[target] * (1.0 + a * z[target] + b * z[target] ** 2)
        # End-of-day at-the-money grid for display.
        ge, gt = np.meshgrid(np.log(GRID_EXPIRY), np.log(GRID_TENOR), indexing="ij")
        wg = _kernel(ge.ravel(), gt.ravel(), lt[core], ln[core]) * np.exp(-np.log(2) * (ts[core].max() - ts[core])[None, :] / 86400.0 / HALF_LIFE_DAYS)
        tg = wg.sum(axis=1)
        grids[str(pd.Timestamp(days[d]).date())] = {"vol": np.round(np.where(tg > 0.5, (wg @ vol[core]) / np.maximum(tg, 1e-9), np.nan), 1).reshape(ge.shape).tolist(),
                                                   "support": np.round(tg, 1).reshape(ge.shape).tolist()}
    # Last standalone trade in the same bucket, strictly earlier.
    s = pd.Series(np.where(alone, vol, np.nan))
    last[:] = s.groupby(bucket).transform(lambda v: v.ffill().shift(1)).values

    # Anchored: start from the last similar trade and use the surface only for the
    # difference between that trade and this one (expiry, swap length, strike).
    # This is how a desk marks an illiquid point: relative to the nearest liquid one.
    idx = pd.Series(np.where(alone, np.arange(n), np.nan))
    j = idx.groupby(bucket).transform(lambda v: v.ffill().shift(1)).values
    has = np.isfinite(j)
    jj = np.where(has, j, 0).astype(int)
    fresh = has & ((ts - ts[jj]) < 3 * 86400)
    anchored = np.where(fresh & np.isfinite(smile) & np.isfinite(smile[jj]), vol[jj] + smile - smile[jj], smile)

    o["flat"], o["last"], o["surface"], o["smile"], o["support"] = flat, last, surf, smile, support
    o["anchored"] = anchored
    o["hull_white"] = hw_pred
    o["bucket"] = bucket
    o.to_parquet(RESULTS / "option_scores.parquet", index=False)
    (RESULTS / "vol_grids.json").write_text(json.dumps({"expiry": GRID_EXPIRY, "tenor": GRID_TENOR, "smile": smile_coef, "days": grids, "hull_white": hw_params, "hw_speeds": HW_A}))
    return o


def _stats(err: pd.Series) -> dict:
    e = err.dropna().abs()
    return {"n": int(len(e)), "median": round(float(e.median()), 2), "p95": round(float(e.quantile(0.95)), 1)} if len(e) else {"n": 0}


def summarise() -> dict:
    o = pd.read_parquet(RESULTS / "option_scores.parquet")
    all_usable = len(pd.read_parquet(RESULTS / "option_vols.parquet"))
    start = np.sort(o["trade_date"].unique())[WINDOW_DAYS + 40]
    s = o[(o["trade_date"] >= start) & o["surface"].notna()]
    models = ["flat", "last", "surface", "smile", "anchored", "hull_white"]
    alone, pack = s[~s["package"]], s[s["package"]]

    def table(frame):
        vol_err = {m: _stats(frame[m] - frame["vol_bp"]) for m in models}
        # Premium error in basis points of notional: volatility error times vega.
        prem = {m: _stats((frame[m] - frame["vol_bp"]) / 1e4 * frame["vega"] * 1e4) for m in models}
        return {"vol_bp": vol_err, "premium_bp_of_notional": prem}

    exp_lab = pd.cut(alone["option_years"], [0, 0.2, 0.75, 1.5, 3.5, 60], labels=["under 3m", "3m-9m", "about 1y", "2-3y", "over 3y"])
    money = pd.cut(alone["z"].abs(), [-1, 0.25, 1.0, 10], labels=["at the money", "up to 1 sd away", "further out"])
    month = alone["trade_date"].dt.to_period("M").astype(str)
    d = (alone["surface"] - alone["vol_bp"]).abs() - (alone["flat"] - alone["vol_bp"]).abs()
    daily = d.groupby(alone["trade_date"]).mean().dropna().values
    c = daily - daily.mean()
    var = (c @ c) / len(c) + sum(2 * (1 - k / 6) * (c[k:] @ c[:-k]) / len(c) for k in range(1, 6))
    out = {
        "period": [str(s["trade_date"].min().date()), str(s["trade_date"].max().date())],
        "coverage": {"usable_options": int(all_usable), "valid_volatility": int(len(o)), "scored": int(len(s)), "standalone_scored": int(len(alone))},
        "standalone": table(alone),
        "packages": table(pack),
        "by_expiry": {str(b): {m: _stats((alone[m] - alone["vol_bp"])[exp_lab == b]) for m in models} for b in exp_lab.cat.categories},
        "by_moneyness": {str(b): {m: _stats((alone[m] - alone["vol_bp"])[money == b]) for m in models} for b in money.cat.categories},
        "by_month": {mo: {m: _stats((alone[m] - alone["vol_bp"])[month == mo]) for m in ("flat", "surface")} for mo in sorted(month.unique())},
        "surface_vs_flat": {"days": int(len(daily)), "mean_diff_vol_bp": round(float(daily.mean()), 2), "t_stat": round(float(daily.mean() / np.sqrt(var / len(daily))), 2)},
        "bias_vol_bp": {m: round(float((alone[m] - alone["vol_bp"]).median()), 2) for m in models},
        "level": {"median_vol_bp": round(float(alone["vol_bp"].median()), 1)},
    }
    hw = json.loads((RESULTS / "vol_grids.json").read_text()).get("hull_white", {})
    if hw:
        p = pd.DataFrame(hw, index=["a", "sigma", "fit_rmse_bp"]).T
        out["hull_white"] = {"days": int(len(p)), "a_median": round(float(p["a"].median()), 3), "a_share_at_grid_edge_pct": round(float(p["a"].isin([HW_A[0], HW_A[-1]]).mean() * 100), 0),
                             "sigma_bp_median": round(float(p["sigma"].median() * 1e4), 1), "sigma_bp_range": [round(float(p["sigma"].quantile(0.05) * 1e4), 1), round(float(p["sigma"].quantile(0.95) * 1e4), 1)],
                             "fit_rmse_bp_median": round(float(p["fit_rmse_bp"].median()), 1)}
    (RESULTS / "option_summary.json").write_text(json.dumps(out, indent=1))
    return out
