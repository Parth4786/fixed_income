"""Patterns in the data: standard desk analytics, each with its method stated.

1. Rich/cheap screen. Curve spreads and butterflies against their own recent
   history, as z-scores: (today - 60-day mean) / 60-day standard deviation.
2. Cross-market correlation. Pearson correlation of daily changes across
   currencies, inflation, volatility and swap spreads over the last 250 days,
   plus a rolling 60-day correlation to show how stable it is.
3. Implied against realised volatility. What options charge for movement
   (implied) against how much the rate actually moved (20-day standard
   deviation of daily changes, annualised by sqrt(252)).
4. Time of day. Activity and model accuracy by hour.
5. What drives the gap to fair. A gradient-boosted model predicts the size of
   each trade's gap from its size, length, hour and venue. It is trained on
   the earlier 70% of days and tested on the later 30%, against the baseline
   of always predicting the typical gap. Permutation importance on the test
   period says which inputs matter.

Everything is descriptive of the past two years; none of it is a forecast.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from tapemark.models.curve_filter import NODES
from tapemark.paths import CLEAN, DATA

RESULTS = DATA / "results"


def _eod() -> pd.DataFrame:
    scores = pd.read_parquet(RESULTS / "swap_scores.parquet", columns=["trade_date"])
    snaps = pd.read_parquet(RESULTS / "curve_snapshots.parquet")
    days = np.sort(scores["trade_date"].unique()).astype("datetime64[D]")
    ts = snaps["ts"].values.astype("datetime64[s]")
    nxt = np.minimum(np.searchsorted(ts, (days + 1).astype("datetime64[s]"), side="left"), len(snaps) - 1)
    x = snaps[[str(t) for t in NODES]].values[nxt]
    return pd.DataFrame({t: [np.interp(t, NODES, row) for row in x] for t in (2, 5, 10, 30)}, index=pd.DatetimeIndex(days))


def rich_cheap(e: pd.DataFrame) -> list[dict]:
    series = {
        "2y to 10y steepness": (e[10] - e[2]) * 100, "5y to 30y steepness": (e[30] - e[5]) * 100, "2y to 5y steepness": (e[5] - e[2]) * 100,
        "10y to 30y steepness": (e[30] - e[10]) * 100, "5y against 2y and 10y": (2 * e[5] - e[2] - e[10]) * 100,
        "10y against 5y and 30y": (2 * e[10] - e[5] - e[30]) * 100, "10y against 2y and 30y": (2 * e[10] - e[2] - e[30]) * 100,
    }
    out = []
    for name, s in series.items():
        w = s.iloc[-61:-1]
        z = (s.iloc[-1] - w.mean()) / w.std()
        out.append({"name": name, "now_bp": round(float(s.iloc[-1]), 1), "mean_60d_bp": round(float(w.mean()), 1), "sd_60d_bp": round(float(w.std()), 1),
                    "z": round(float(z), 2), "percentile_1y": round(float((s.iloc[-250:] <= s.iloc[-1]).mean() * 100), 0),
                    "history": s.iloc[-250:].round(1).tolist()})
    return sorted(out, key=lambda r: -abs(r["z"]))


def cross_market(e: pd.DataFrame) -> dict:
    cols = {"US 2y": e[2], "US 10y": e[10], "US 30y": e[30]}
    path = CLEAN / "global_ois_daily.parquet"
    if path.exists():
        g = pd.read_parquet(path)
        ten = g[(g["tenor"] == 10) & (g["trades"] >= 2)].pivot_table(index="day", columns="ccy", values="rate")
        names = {"EUR": "Euro 10y", "GBP": "Sterling 10y", "JPY": "Yen 10y", "CAD": "Canada 10y", "AUD": "Australia 10y", "CHF": "Swiss 10y", "INR": "India 5y"}
        five = g[(g["tenor"] == 5) & (g["ccy"] == "INR")].set_index("day")["rate"]
        for c, n in names.items():
            s = five if c == "INR" else ten.get(c)
            if s is not None and s.notna().sum() > 120:
                cols[n] = s
    infl = CLEAN / "usd_inflation_daily.parquet"
    if infl.exists():
        f = pd.read_parquet(infl)
        cols["US inflation 10y"] = f[f["tenor"] == 10].set_index("day")["rate"]
    grids = json.loads((RESULTS / "vol_grids.json").read_text())
    ie, it = grids["expiry"].index(1), grids["tenor"].index(10)
    vol = pd.Series({pd.Timestamp(k): v["vol"][ie][it] for k, v in grids["days"].items()}, dtype=float)
    cols["Option volatility"] = vol / 100
    frame = pd.DataFrame(cols).reindex(e.index).ffill(limit=3)
    ch = (frame.diff() * 100).iloc[-250:]
    ch = ch.where(ch.abs() < 60)  # a bad median on a thin day must not drive a correlation
    corr = ch.corr(min_periods=60)
    roll = {n: ch["US 10y"].rolling(60, min_periods=40).corr(ch[n]).round(2) for n in ("Euro 10y", "Sterling 10y", "Yen 10y") if n in ch}
    return {"labels": list(corr.columns), "matrix": [[None if not np.isfinite(v) else round(float(v), 2) for v in row] for row in corr.values],
            "rolling": {"days": [str(d.date()) for d in ch.index], **{n: [None if not np.isfinite(v) else float(v) for v in s] for n, s in roll.items()}}}


def implied_realised(e: pd.DataFrame) -> dict:
    realised = (e[10].diff() * 100).rolling(20).std() * np.sqrt(252)
    grids = json.loads((RESULTS / "vol_grids.json").read_text())
    ie, it = grids["expiry"].index(1), grids["tenor"].index(10)
    implied = pd.Series({pd.Timestamp(k): v["vol"][ie][it] for k, v in grids["days"].items()}, dtype=float).reindex(e.index)
    both = pd.DataFrame({"implied": implied, "realised": realised}).dropna().iloc[40:]
    return {"days": [str(d.date()) for d in both.index], "implied": both["implied"].round(1).tolist(), "realised": both["realised"].round(1).tolist(),
            "now": {"implied": round(float(both["implied"].iloc[-1]), 1), "realised": round(float(both["realised"].iloc[-1]), 1)},
            "share_of_days_implied_above": round(float((both["implied"] > both["realised"]).mean() * 100), 0),
            "median_gap": round(float((both["implied"] - both["realised"]).median()), 1)}


def time_of_day() -> list[dict]:
    s = pd.read_parquet(RESULTS / "swap_scores.parquet", columns=["exec_ts", "fixed_rate_pct", "filter", "scored", "notional"])
    s = s[s["scored"]]
    gap = (s["fixed_rate_pct"] - s["filter"]).abs() * 100
    g = pd.DataFrame({"hour": s["exec_ts"].dt.hour, "gap": gap}).groupby("hour")["gap"].agg(["median", "size"])
    days = s["exec_ts"].dt.date.nunique()
    return [{"hour_utc": int(h), "median_gap_bp": round(float(r["median"]), 3), "trades_per_day": round(float(r["size"] / days), 1)} for h, r in g.iterrows() if r["size"] >= 300]


def gap_drivers() -> dict:
    """Can the size of a trade's gap be predicted from what is known about the trade?"""
    import os

    os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))   # stops a noisy core-count probe on Windows
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.inspection import permutation_importance

    s = pd.read_parquet(RESULTS / "swap_scores.parquet")
    s = s[s["scored"] & ~s["damped"]].copy()
    s["gap"] = ((s["fixed_rate_pct"] - s["filter"]).abs() * 100).clip(upper=10)
    top = s["venue"].value_counts().head(6).index
    feats = pd.DataFrame({
        "Trade size": np.log10(s["notional"].clip(lower=1e5)), "Swap length": s["tenor_years"], "Hour of day": s["exec_ts"].dt.hour + s["exec_ts"].dt.minute / 60,
        "Odd length (not whole years)": ((s["tenor_years"] - s["tenor_years"].round()).abs() > 0.05).astype(int),
        "Venue": s["venue"].where(s["venue"].isin(top), "other").astype("category").cat.codes, "Cleared": s["cleared"].astype(int),
        "Model's own uncertainty": s["filter_sd"] * 100,
    })
    days = np.sort(s["trade_date"].unique())
    split = days[int(len(days) * 0.7)]
    tr, te = (s["trade_date"] < split).values, (s["trade_date"] >= split).values
    model = HistGradientBoostingRegressor(loss="absolute_error", max_iter=200, learning_rate=0.08, max_leaf_nodes=31, random_state=0)
    model.fit(feats[tr], s["gap"][tr])
    pred = model.predict(feats[te])
    base = np.full(te.sum(), s["gap"][tr].median())
    mae_model, mae_base = float(np.abs(pred - s["gap"][te]).mean()), float(np.abs(base - s["gap"][te]).mean())
    sub = np.random.default_rng(0).choice(np.where(te)[0], size=min(20000, int(te.sum())), replace=False)
    imp = permutation_importance(model, feats.iloc[sub], s["gap"].iloc[sub], n_repeats=3, random_state=0, scoring="neg_mean_absolute_error")
    size_b = pd.cut(s["notional"], [0, 10e6, 25e6, 50e6, 100e6, 250e6, 1e13], labels=["under 10m", "10-25m", "25-50m", "50-100m", "100-250m", "over 250m"])
    return {"train_until": str(pd.Timestamp(split).date()), "test_trades": int(te.sum()), "mae_model_bp": round(mae_model, 3), "mae_baseline_bp": round(mae_base, 3),
            "improvement_pct": round(100 * (1 - mae_model / mae_base), 1),
            "importance": sorted(({"feature": f, "worsening_bp": round(float(v), 4)} for f, v in zip(feats.columns, imp.importances_mean, strict=True)), key=lambda r: -r["worsening_bp"]),
            "by_size": [{"size": str(k), "median_gap_bp": round(float(v), 3)} for k, v in s.groupby(size_b, observed=False)["gap"].median().items()]}


def execution_cost() -> dict:
    """What moves a trade away from fair: a regression with standard errors clustered by day.

    Dependent variable: the absolute gap between the traded rate and the model's
    rate just before the trade, in basis points (capped at 10 so a few absurd
    prints do not drive it). This is the standard reduced form used in studies
    of swap execution costs on regulatory trade data. Coefficients are in basis
    points per unit of each regressor.

    Also the Roll (1984) effective spread: 2 * sqrt(-Cov(dp_t, dp_{t-1})) from
    successive trade prices of the same swap length, which needs no quotes.
    """
    s = pd.read_parquet(RESULTS / "swap_scores.parquet")
    s = s[s["scored"] & ~s["damped"]].copy()
    e = _eod()
    move = (e[10].diff().abs() * 100).rename("move")
    s = s.join(move, on="trade_date")
    y = ((s["fixed_rate_pct"] - s["filter"]).abs() * 100).clip(upper=10).values
    hour = s["exec_ts"].dt.hour
    cols = {
        "Baseline (small standard 10-year trade, quiet day)": np.ones(len(s)),
        "Trade ten times larger": np.log10(s["notional"].clip(lower=1e6) / 1e7).values,
        "Each extra 10 years of length": (s["tenor_years"].values - 10) / 10,
        "Length is not a whole number of years": ((s["tenor_years"] - s["tenor_years"].round()).abs() > 0.05).astype(float).values,
        "Traded off an electronic venue": s["venue"].isin(["XOFF", "BILT"]).astype(float).values,
        "Not cleared": (~s["cleared"]).astype(float).values,
        "During New York hours (13 to 20 UTC)": hour.between(13, 20).astype(float).values,
        "Each 10 bp the 10-year rate moved that day": s["move"].fillna(0).values / 10,
    }
    x = np.column_stack(list(cols.values()))
    xtx_inv = np.linalg.inv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    resid = y - x @ beta
    day = pd.factorize(s["trade_date"])[0]
    xe = x * resid[:, None]
    by_day = np.zeros((day.max() + 1, x.shape[1]))
    np.add.at(by_day, day, xe)
    g = by_day.shape[0]
    cov = xtx_inv @ (by_day.T @ by_day) @ xtx_inv * g / (g - 1)
    se = np.sqrt(np.diag(cov))
    roll = []
    whole = s[(s["tenor_years"] - s["tenor_years"].round()).abs() < 0.05]
    for t in (2, 5, 10, 30):
        w = whole[whole["tenor_years"].round() == t].sort_values("exec_ts")
        dp = w.groupby("trade_date")["fixed_rate_pct"].diff().dropna() * 100
        dp = dp[dp.abs() < 5]
        c = float(np.cov(dp.values[1:], dp.values[:-1])[0, 1])
        roll.append({"length": f"{t}y", "trades": int(len(w)), "spread_bp": round(2 * np.sqrt(-c), 3) if c < 0 else None})
    return {"trades": int(len(s)), "days": int(g), "r_squared": round(float(1 - resid.var() / y.var()), 4),
            "terms": [{"term": k, "bp": round(float(b), 4), "t": round(float(b / e_), 1)} for k, b, e_ in zip(cols, beta, se, strict=True)],
            "roll_spread": roll}


def diebold_li() -> dict:
    """Can tomorrow's curve be forecast? Diebold and Li (2006) against a random walk.

    Each day's curve is summarised by three Nelson-Siegel factors (level, slope,
    curvature) by least squares with the decay fixed. Each factor follows its own
    AR(1), re-estimated every day on the past only, and the forecast curve is
    rebuilt from the forecast factors. The benchmark is "no change".
    Applied here to par swap rates at the model's 14 lengths.
    """
    scores = pd.read_parquet(RESULTS / "swap_scores.parquet", columns=["trade_date"])
    snaps = pd.read_parquet(RESULTS / "curve_snapshots.parquet")
    days = np.sort(scores["trade_date"].unique()).astype("datetime64[D]")
    ts = snaps["ts"].values.astype("datetime64[s]")
    nxt = np.minimum(np.searchsorted(ts, (days + 1).astype("datetime64[s]"), side="left"), len(snaps) - 1)
    y = snaps[[str(t) for t in NODES]].values[nxt]
    lam = 0.0609 * 12  # Diebold and Li's monthly decay, per year
    load = np.column_stack([np.ones(len(NODES)), (1 - np.exp(-lam * NODES)) / (lam * NODES), (1 - np.exp(-lam * NODES)) / (lam * NODES) - np.exp(-lam * NODES)])
    beta = np.linalg.lstsq(load, y.T, rcond=None)[0].T
    fit_rmse = float(np.sqrt(((beta @ load.T - y) ** 2).mean()) * 100)
    keep = [list(NODES).index(t) for t in (2, 5, 10, 30)]
    out = {"days": int(len(y)), "fit_rmse_bp": round(fit_rmse, 2), "horizons": [], "lengths": ["2y", "5y", "10y", "30y"]}
    start = 200
    if len(y) < start + 40:      # the factor dynamics need a long history before the first forecast; say so instead of failing
        return out | {"needs_days": start + 40}
    for h in (1, 5, 20):
        e_dl, e_rw = [], []
        for t in range(start, len(y) - h):
            f = np.empty(3)
            for k in range(3):
                b = beta[: t + 1, k]
                phi, c = np.polyfit(b[:-1], b[1:], 1)
                mu = c / (1 - phi) if abs(phi) < 0.999 else b[-1]
                f[k] = mu + phi**h * (b[-1] - mu)
            e_dl.append((load @ f - y[t + h])[keep])
            e_rw.append((y[t] - y[t + h])[keep])
        e_dl, e_rw = np.array(e_dl) * 100, np.array(e_rw) * 100
        d = (e_dl**2).mean(axis=1) - (e_rw**2).mean(axis=1)
        c = d - d.mean()
        lags = max(h, 5)
        var = (c @ c) / len(c) + sum(2 * (1 - k / (lags + 1)) * (c[k:] @ c[:-k]) / len(c) for k in range(1, lags + 1))
        out["horizons"].append({"days_ahead": h, "forecasts": int(len(d)), "model_rmse_bp": [round(float(v), 2) for v in np.sqrt((e_dl**2).mean(axis=0))],
                                "random_walk_rmse_bp": [round(float(v), 2) for v in np.sqrt((e_rw**2).mean(axis=0))],
                                "t_stat": round(float(d.mean() / np.sqrt(var / len(d))), 2)})
    return out


def run() -> dict:
    e = _eod()
    out = {"day": str(e.index[-1].date()), "rich_cheap": rich_cheap(e), "cross_market": cross_market(e), "implied_realised": implied_realised(e),
           "time_of_day": time_of_day(), "gap_drivers": gap_drivers(), "execution_cost": execution_cost(), "diebold_li": diebold_li()}
    (RESULTS / "insights.json").write_text(json.dumps(out))
    return out
