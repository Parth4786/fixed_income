"""Do the risk numbers work on real trades?

A sensitivity is only useful if a hedge built from it actually removes risk.
For a sample of real trades, on the day each was done:

1. compute its risk to each point on the curve;
2. build a hedge from standard 2, 5, 10 and 30-year swaps that cancels it;
3. revalue both on the next day's independent closing curve.

If the risk numbers are right, the hedged position should move far less than
the unhedged one. A simpler hedge (one swap, matching total risk only) is the
baseline the bucketed hedge has to beat.

The same pass checks the value-change explanation: how much of each trade's
one-day change is left unexplained after "time" and "rates".
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from tapemark.models.curve_filter import NODES
from tapemark.paths import DATA
from tapemark.pricing import risk
from tapemark.pricing.curve import Curve, payer_value, shift_years, spot_start
from tapemark.scoring.swaps import eris_par_table

RESULTS = DATA / "results"
HEDGES = np.array([2.0, 5.0, 10.0, 30.0])
PER_DAY = 6


def hedge_test(seed: int = 7) -> pd.DataFrame:
    scores = pd.read_parquet(RESULTS / "swap_scores.parquet")
    scores = scores[scores["scored"] & (scores["tenor_years"] >= 1.0)]
    off = np.abs(scores["tenor_years"].values[:, None] - HEDGES[None, :]).min(axis=1) > 0.4
    pool = scores[off]
    par = eris_par_table()
    days = par.index
    rng = np.random.default_rng(seed)
    rows = []
    for d, group in pool.groupby("trade_date"):
        k = days.searchsorted(d)
        if k >= len(days) - 1 or days[k] != d:
            continue
        d0, d1 = np.datetime64(d, "D"), np.datetime64(days[k + 1], "D")
        par0, par1 = par.values[k], par.values[k + 1]
        c0, c1 = Curve.from_par(d0, NODES, par0), Curve.from_par(d1, NODES, par1)
        start = spot_start(d0)
        # Hedge instruments: par swaps of standard lengths struck on day 0.
        h_end = [shift_years(start, int(t)) for t in HEDGES]
        h_fix = np.interp(HEDGES, NODES, par0)
        h_dv01 = np.array([risk.bucket_dv01_ad(d0, NODES, par0, start, e, f).sum() for e, f in zip(h_end, h_fix, strict=True)])
        h_move = np.array([payer_value(c1, start, e, f)[0] - payer_value(c0, start, e, f)[0] for e, f in zip(h_end, h_fix, strict=True)])
        take = group.sample(min(PER_DAY, len(group)), random_state=int(rng.integers(1 << 31)))
        for t in take.itertuples():
            end = start + np.timedelta64(int(round(t.tenor_years * 365.25)), "D")
            dv = risk.bucket_dv01_ad(d0, NODES, par0, start, end, t.fixed_rate_pct)
            move = payer_value(c1, start, end, t.fixed_rate_pct)[0] - payer_value(c0, start, end, t.fixed_rate_pct)[0]
            w = risk.hedge_weights(dv, NODES, HEDGES)
            bucketed = move - (w / h_dv01) @ h_move
            near = int(np.argmin(np.abs(HEDGES - t.tenor_years)))
            single = move - dv.sum() / h_dv01[near] * h_move[near]
            ex = risk.explain(d0, par0, d1, par1, NODES, start, end, t.fixed_rate_pct)
            rows.append((d, t.tenor_years, move * 1e4, single * 1e4, bucketed * 1e4, ex["time"] * 1e4, ex["rates"] * 1e4, ex["rest"] * 1e4))
    out = pd.DataFrame(rows, columns=["day", "tenor_years", "unhedged_bp", "single_hedge_bp", "bucket_hedge_bp", "time_bp", "rates_bp", "rest_bp"])
    out.to_parquet(RESULTS / "hedge_test.parquet", index=False)
    return out


def summarise() -> dict:
    h = pd.read_parquet(RESULTS / "hedge_test.parquet")

    def spread(col, frame=h):
        return round(float(frame[col].std()), 3)

    bucket = pd.cut(h["tenor_years"], [0, 3.5, 7.5, 12.5, 60], labels=["up to 3y", "4-7y", "8-12y", "over 12y"])
    out = {
        "trades": int(len(h)), "days": int(h["day"].nunique()),
        "one_day_move_sd_bp_of_notional": {"unhedged": spread("unhedged_bp"), "single_swap_hedge": spread("single_hedge_bp"), "bucket_hedge": spread("bucket_hedge_bp")},
        "risk_removed_pct": {"single_swap_hedge": round(100 * (1 - h["single_hedge_bp"].var() / h["unhedged_bp"].var()), 2),
                             "bucket_hedge": round(100 * (1 - h["bucket_hedge_bp"].var() / h["unhedged_bp"].var()), 2)},
        "by_length": {str(b): {"n": int((bucket == b).sum()), "unhedged": spread("unhedged_bp", h[bucket == b]), "single": spread("single_hedge_bp", h[bucket == b]),
                               "bucket": spread("bucket_hedge_bp", h[bucket == b])} for b in bucket.cat.categories},
        "explain": {"median_abs_move_bp": round(float(h["unhedged_bp"].abs().median()), 2),
                    "median_abs_unexplained_bp": round(float(h["rest_bp"].abs().median()), 4),
                    "unexplained_share_median_pct": round(float((h["rest_bp"].abs() / h["unhedged_bp"].abs().clip(lower=1e-9)).median() * 100), 3),
                    "median_time_bp": round(float(h["time_bp"].median()), 4)},
    }
    (RESULTS / "risk_summary.json").write_text(json.dumps(out, indent=1))
    return out
