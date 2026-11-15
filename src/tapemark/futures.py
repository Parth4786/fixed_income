"""Swap futures: the pricing engine checked against the exchange, and a margin model fitted to its margins.

Four checks on real exchange files, then one fit.

1. Value still to come (A). Our cash-flow engine, on the exchange's own
   discount factors and the New York Fed's SOFR fixings, against the A the
   exchange publishes for every listed contract.
2. Amounts already paid (B). Rebuilt from SOFR fixings back to 2020, for
   contracts that have been SOFR contracts all their life. Contracts that
   began on LIBOR and were converted in September 2022 are left out of this
   one check: their early payments were LIBOR amounts, which SOFR fixings
   cannot rebuild.
3. Interest on margin (C). The published one-day step against
   `yesterday's A * overnight rate * days / 360`, with yesterday's A taken
   from the previous day's file.
4. Risk. Our DV01 for each contract against the published one.
6. Options. The exchange also settles options on these futures and publishes
   a price and a normal volatility for each. Two checks: our normal-model
   pricer on the exchange's volatility against the exchange's price, for
   every option; and the volatility grid this project builds from public
   swap-option premiums against the exchange's at-the-money volatility for
   the same option life and swap length.
5. Margin. The exchange publishes the margin it charges on each contract.
   A historical rule, `margin = DV01 * (move not exceeded on q of past
   h-day windows)`, is run over six years of daily curves for several h and
   q, and the pair that best reproduces the published margins is kept. The
   same history at five days then gives the margin a cleared swap would
   need, which is what the margin-cost comparison in the app uses.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd

from tapemark.paths import CLEAN, DATA
from tapemark.pricing import eris_futures as ef
from tapemark.pricing import options as opt
from tapemark.pricing.curve import D
from tapemark.sources import eris, fed

RESULTS = DATA / "results"
HORIZONS = (1, 2, 3, 5)
CONFIDENCES = (0.99, 0.995, 0.997, 0.999)
SWAP_HORIZON = 5       # days a clearing house must allow to close out a cleared swap (US rule 39.13)


def _days(limit: int) -> list[dt.date]:
    last = dt.date.fromisoformat(json.loads((CLEAN / "build_stats.json").read_text())["last_day"])
    out, day = [], last
    while len(out) < limit and (last - day).days < limit * 2:
        if day.weekday() < 5 and eris.raw_path(day, "discount").exists() and eris.fetch(day, "settles") is not None:
            out.append(day)
        day -= dt.timedelta(days=1)
    return out[::-1]


def _engine(day: dt.date, st: pd.DataFrame, fixings: ef.Fixings) -> pd.DataFrame:
    curve = eris.discount_factors(day)
    dates, dfs = curve.index.values.astype(D), curve.values

    def df(when):
        return dfs[np.searchsorted(dates, np.asarray(when, dtype=D))]

    rows = []
    for r in st.itertuples():
        v = ef.value(day, r.EffectiveDate, r.CashFlowAlignmentDate, r.coupon, df, fixings)
        rows.append((r.Symbol, v["a"], v["b"], ef.dv01(day, r.EffectiveDate, r.CashFlowAlignmentDate, r.coupon, df, fixings)))
    return pd.DataFrame(rows, columns=["Symbol", "our_a", "our_b", "our_dv01"]).set_index("Symbol")


def check_engine(limit: int = 60) -> dict:
    sofr = fed.sofr()
    fixings = ef.Fixings(sofr["day"].values, sofr["rate"].values)
    known_to = pd.Timestamp(sofr["day"].max()).date()
    days = [d for d in _days(limit) if (d - known_to).days <= 4]      # every fixing the day needs must be in hand
    a_err, b_err, dv_err, c_err, price_err, converted = [], [], [], [], [], 0
    previous = None
    for day in days:
        st = eris.settles(day).set_index("Symbol")
        st = st[st["MaturityDate"] > pd.Timestamp(day)]
        ours = _engine(day, st.reset_index(), fixings)
        native = (st["EffectiveDate"] >= st["FirstTradeDate"]).values      # never a LIBOR contract
        converted = int((~native).sum())
        a_err.append((ours["our_a"] - st["a"]).abs().values)
        b_err.append((ours["our_b"] - st["b"]).abs().values[native])
        dv_err.append(((ours["our_dv01"] - st["dv01"]) / st["dv01"]).abs().values)
        price_err.append((100 + ours["our_a"] + ours["our_b"] - st["c"] - st["price"]).abs().values[native])
        if previous is not None:
            both = st.index.intersection(previous.index)
            step = ef.pai_step(previous.loc[both, "a"], st.loc[both, "pai_rate"], st.loc[both, "pai_days"])
            c_err.append((st.loc[both, "c"] - previous.loc[both, "c"] - step).abs().values)
        previous = st
    cat = lambda xs: np.concatenate(xs) if xs else np.array([np.nan])  # noqa: E731
    a, b, dv, c, pr = cat(a_err), cat(b_err), cat(dv_err), cat(c_err), cat(price_err)
    # One price point is $1,000 a contract; the smallest price step is far larger than these errors when the engine is right.
    return {"days": len(days), "first_day": str(days[0]) if days else None, "last_day": str(days[-1]) if days else None, "contract_days": int(len(a)), "contracts": int(len(a) / max(len(days), 1)), "converted_from_libor": converted,
            "a": {"median": float(np.median(a)), "p99": float(np.quantile(a, 0.99)), "max": float(a.max())},
            "b": {"median": float(np.median(b)), "p99": float(np.quantile(b, 0.99)), "max": float(b.max()), "contract_days": int(len(b))},
            "c_step": {"median": float(np.median(c)), "p99": float(np.quantile(c, 0.99)), "max": float(c.max()), "contract_days": int(len(c))},
            "price": {"median": float(np.median(pr)), "p99": float(np.quantile(pr, 0.99)), "max": float(pr.max())},
            "dv01_pct": {"median": float(100 * np.median(dv)), "p99": float(100 * np.quantile(dv, 0.99))}}


def fit_margin() -> dict:
    """Which (days, confidence) historical rule reproduces the margins the exchange charges."""
    eris.fetch_par_history()
    hist = eris.par_history()
    nodes = hist.columns.values.astype(float)
    last = dt.date.fromisoformat(json.loads((CLEAN / "build_stats.json").read_text())["last_day"])
    day = next(d for d in _days(10)[::-1] if d <= last)
    st = eris.settles(day)
    st = st[(st["MaturityDate"] > pd.Timestamp(day) + pd.Timedelta(days=200)) & (st["margin"] > 0) & (st["dv01"] > 0)]
    remaining = ((st["CashFlowAlignmentDate"] - pd.Timestamp(day)).dt.days / 365.25).values
    covered = (st["margin"] / st["dv01"]).values                       # the rate move, in bp, the published margin pays for
    table, best = [], None
    for h in HORIZONS:
        for q in CONFIDENCES:
            ratio = np.interp(remaining, nodes, ef.worst_moves(hist.values, h, q)) / covered
            # Typical miss across contracts: a rule can be right on average and still wrong along the curve.
            row = {"days": h, "confidence": q, "median_ratio": round(float(np.median(ratio)), 3), "typical_miss_pct": round(float(100 * np.median(np.abs(ratio - 1))), 1)}
            table.append(row)
            if best is None or row["typical_miss_pct"] < best["typical_miss_pct"]:
                best = row
    q = best["confidence"]
    fut, plain = ef.worst_moves(hist.values, best["days"], q), ef.worst_moves(hist.values, SWAP_HORIZON, q)
    # Cleared swaps: the published structure of the clearing house's model (five days, volatility-scaled history, unscaled floor).
    swp = ef.worst_moves_scaled(hist.values, SWAP_HORIZON, q)
    with_scaling = np.interp(remaining, nodes, ef.worst_moves_scaled(hist.values, best["days"], q)) / covered
    ten = int(np.argmin(np.abs(nodes - 10)))
    structure = {"decay": 0.97, "ten_year_plain_bp": round(float(plain[ten]), 1), "ten_year_scaled_bp": round(float(swp[ten]), 1),
                 "change_pct": round(float(100 * (swp[ten] / plain[ten] - 1)), 1), "futures_miss_with_scaling_pct": round(float(100 * np.median(np.abs(with_scaling - 1))), 1)}
    examples = []
    for t in (2, 5, 10, 30):
        near = st.iloc[np.argsort(np.abs(remaining - t))[:1]]
        examples.append({"length": f"{t}y", "contract": near["Symbol"].iloc[0], "published_margin": float(near["margin"].iloc[0]),
                         "model_margin": round(float(np.interp(remaining[np.argsort(np.abs(remaining - t))[0]], nodes, fut) * near["dv01"].iloc[0]), 0),
                         "covers_bp": round(float(near["margin"].iloc[0] / near["dv01"].iloc[0]), 1)})
    return {"day": str(day), "contracts": int(len(st)), "history_days": int(len(hist)), "history_from": str(hist.index[0].date()), "history_to": str(hist.index[-1].date()),
            "median_cover_bp": round(float(np.median(covered)), 1), "best": best, "table": table, "examples": examples, "swap_days": SWAP_HORIZON,
            "nodes": nodes.tolist(), "future_move_bp": fut.round(2).tolist(), "swap_move_bp": swp.round(2).tolist(),
            "swap_to_future": round(float(np.median(swp / fut)), 2), "published_structure": structure, "backtest": _backtest(hist, best["days"], q)}


def check_options(limit: int = 60) -> dict:
    grids = json.loads((RESULTS / "vol_grids.json").read_text())
    expiries, tenors = np.array(grids["expiry"], float), np.array(grids["tenor"], float)
    price_err, ticks, rows = [], [], []
    days = [d for d in _days(limit) if eris.fetch(d, "options") is not None]
    for day in days:
        o = eris.option_settles(day)
        o = o[(o["expiry_years"] > 0) & (o["vol_pct"] > 0)]
        # A call on the futures price gains when rates fall: it is a receiver option. One price point is PV01 * 10 per unit of rate.
        ours = opt.bachelier(o["strike_minus_price_bp"].values * 1e-4, 0.0, o["expiry_years"].values, o["vol_pct"].values / 100,
                             annuity=o["pv01"].values * 10, payer=(o["kind"] == "P").values)
        price_err.append(np.abs(ours - o["price"].values))
        ticks.append(o["tick"].values)
        grid = grids["days"].get(str(day))
        if grid is None:
            continue
        ours_grid = np.array([[np.nan if v is None else v for v in row] for row in grid["vol"]], float)
        o = o[o["expiry_years"] >= 0.04].assign(dist=lambda f: f["strike_minus_price_bp"].abs())
        near = o.sort_values("dist").groupby(["tenor", "ExpiryDate"]).head(2)          # the call and put nearest the money
        for (tenor, _), g in near.groupby(["tenor", "ExpiryDate"]):
            t, length = float(g["expiry_years"].iloc[0]), float(str(tenor).rstrip("Y"))
            col = int(np.argmin(np.abs(tenors - length)))
            have = np.isfinite(ours_grid[:, col])
            if have.sum() >= 2 and expiries[have].min() <= t:
                rows.append((str(day), length, t, float(np.interp(t, expiries[have], ours_grid[have, col])), float(g["vol_pct"].mean() * 100)))
    err, tick = np.concatenate(price_err), np.concatenate(ticks)
    cmp = pd.DataFrame(rows, columns=["day", "length", "expiry", "ours", "exchange"])
    cmp["diff"] = cmp["ours"] - cmp["exchange"]
    by = []
    for length, g in cmp.groupby("length"):
        daily = g.groupby("day")[["ours", "exchange"]].mean()
        by.append({"length": f"{int(length)}y", "points": int(len(g)), "ours_bp": round(float(g["ours"].median()), 1), "exchange_bp": round(float(g["exchange"].median()), 1),
                   "median_gap_bp": round(float(g["diff"].median()), 1), "typical_miss_bp": round(float(g["diff"].abs().median()), 1),
                   "moves_together": round(float(np.corrcoef(daily["ours"].diff().dropna(), daily["exchange"].diff().dropna())[0, 1]), 2) if len(daily) > 5 else None})
    return {"days": len(days), "options": int(len(err)),
            "pricer": {"median": float(np.median(err)), "p99": float(np.quantile(err, 0.99)), "max": float(err.max()), "within_one_tick_pct": round(float(100 * (err <= tick).mean()), 2)},
            "vol": {"points": int(len(cmp)), "median_gap_bp": round(float(cmp["diff"].median()), 1), "typical_miss_bp": round(float(cmp["diff"].abs().median()), 1),
                    "longest_expiry_months": round(float(cmp["expiry"].max() * 12), 1), "by_length": by}}


def _backtest(hist: pd.DataFrame, future_days: int, q: float, start: int = 500) -> dict:
    """Was each rule's margin enough, day by day, on days it had not seen? The regulatory standard is at least 99%."""
    x = hist.values
    share = lambda ok: round(float(100 * ok.mean()), 2)  # noqa: E731
    fut, swap, swap_scaled = ef.coverage(x, future_days, q, start), ef.coverage(x, SWAP_HORIZON, q, start), ef.coverage(x, SWAP_HORIZON, q, start, scaled=True)
    years = hist.index[start: start + len(swap_scaled)].year
    return {"from": str(hist.index[start].date()), "to": str(hist.index[start + len(swap_scaled) - 1].date()), "days": int(len(swap_scaled)), "target_pct": 100 * q,
            "future_pct": share(fut), "swap_plain_pct": share(swap), "swap_pct": share(swap_scaled),
            "swap_by_year": [{"year": int(y), "pct": share(swap_scaled[years == y]), "days": int((years == y).sum())} for y in sorted(set(years))]}


def run() -> dict:
    out = {"engine": check_engine(), "margin": fit_margin(), "options": check_options()}
    (RESULTS / "futures.json").write_text(json.dumps(out))
    return out
