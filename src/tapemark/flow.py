"""Order flow: when trades arrive, what their direction says, and what happens late in the day.

Three studies, each on real trades only.

1. Do trades trigger more trades?  (a self-exciting, or Hawkes, model)

   The public record stamps every trade to the whole second, so the model is
   written in one-second steps (the discrete form of a Hawkes process;
   Kirchner 2016 shows the two agree as the step shrinks). Two streams are
   kept: swaps up to 5.5 years long and swaps longer than that. In each
   second a stream is either active (at least one trade) or not, which keeps
   a package reported as several legs in the same second from counting as
   several arrivals.

       rate_i(t) = base_i * shape_i(t) + sum_j K[i, j] * sum_{l >= 1} (1 - f) f^(l-1) * active_j(t - l)

   - base_i is the rate of trades that arrive on their own. It is set for
     each morning separately from that morning's average, so a busy day is
     not mistaken for trades triggering trades.
   - shape_i(t) is the average course of the hour across the days in the
     set, minute by minute. On release days it jumps at 8:30 and stays
     high, so the burst caused by the number is treated as news, not as
     trades triggering trades. A constant baseline would credit that burst
     to triggering; this is the main known trap in this literature
     (Filimonov and Sornette 2015). What K measures is clustering beyond
     the usual course of the hour.
   - K[i, j] is the number of extra active seconds in stream i caused by one
     active second in stream j. The weights (1 - f) f^(l-1) sum to one, so K
     is exactly that count; f = exp(-decay).
   - The largest eigenvalue of K is the branching ratio: the share of
     activity that is a reaction to earlier activity. At 1 the process
     feeds on itself without limit.

   The model is fitted by maximum likelihood on three sets of hours: 8:30 to
   9:30 New York time on days with a consumer price or jobs report, the same
   hour on other days, and 10:30 to 11:30 on other days. The release-day fit
   is repeated with a constant baseline to show how large the trap is. Standard errors
   come from refitting with one sixth of the days left out, six times. The
   out-of-sample check fits on the first half of the days and scores the
   second half against a model with no triggering.

2. Does net paying flow move the rate?

   The record does not say who bought. Each clean trade is given a side from
   where it printed against the model's fair rate just before it: above fair
   means the initiator paid fixed. Size is counted in ten-year equivalents
   (size times length over ten), the desk's rough unit of rate risk. Flow is
   summed over ten-minute intervals and set against the move in the model's
   ten-year rate in the same interval and in the next one.

3. Late-day drift after a large move.

   Mortgage hedgers are said to push rates further in the direction of a
   large move late in the New York day (Hanson 2014 documents the mechanism
   at lower frequency). The test: on days when the ten-year rate has moved
   at least 8 bp by 2 pm, does it keep going between 2 pm and 4 pm?

Release days are the Bureau of Labor Statistics' own calendar, including the
dates moved by the lapses in funding of late 2025 and early 2026.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.signal import lfilter

from tapemark.paths import CLEAN, DATA

RESULTS = DATA / "results"
NY = "America/New_York"

# Release days at 8:30 New York time. Source: bls.gov/schedule (year pages) and
# bls.gov/bls/2025-lapse-revised-release-dates.htm. October 2025 had no consumer
# price release and no separate jobs report. Every date from November 2025 on was
# also matched to the dated links in the bureau's archive of releases
# (bls.gov/bls/news-release/cpi.htm and empsit.htm) on 15 Nov 2026.
CPI_DAYS = """2024-11-13 2024-12-11 2025-01-15 2025-02-12 2025-03-12 2025-04-10 2025-05-13 2025-06-11 2025-07-15 2025-08-12
2025-09-11 2025-10-24 2025-12-18 2026-01-13 2026-02-13 2026-03-11 2026-04-10 2026-05-12 2026-06-10 2026-07-14 2026-08-12
2026-09-11 2026-10-14 2026-11-10""".split()
JOBS_DAYS = """2024-12-06 2025-01-10 2025-02-07 2025-03-07 2025-04-04 2025-05-02 2025-06-06 2025-07-03 2025-08-01 2025-09-05
2025-11-20 2025-12-16 2026-01-09 2026-02-11 2026-03-06 2026-04-03 2026-05-08 2026-06-05 2026-07-02 2026-08-07 2026-09-04
2026-10-02 2026-11-06""".split()

WARM = 600          # seconds of trading read before each window so the first seconds have a history
LENGTH = 3600       # seconds in each window
SPLIT_YEARS = 5.5   # short stream at or below, long stream above
MAX_WINDOWS = 160   # evenly spaced days per set; enough seconds for tight estimates, and it keeps the fit quick
BOUNDS = [(0.0, 0.95)] * 4 + [(np.log(1 / 600), np.log(2.0))]   # four entries of K, then log of the decay per second
START = np.array([0.3, 0.05, 0.05, 0.3, np.log(0.05)])


# ------------------------------------------------------------------ 1. trades triggering trades
def kernel_state(active: np.ndarray, decay: float) -> np.ndarray:
    """Weighted count of earlier activity: sum over lags l >= 1 of (1 - f) f^(l-1) * active(t - l), f = exp(-decay)."""
    f = np.exp(-decay)
    return lfilter([0.0, 1.0 - f], [1.0, -f], active, axis=-1)


def hour_shape(active: np.ndarray) -> np.ndarray:
    """Average course of the window for each stream, by minute, scaled to average one. Shape (2, seconds)."""
    y = active[:, :, WARM:]
    by_minute = y.reshape(len(y), 2, -1, 60).mean(axis=(0, 3))
    by_minute = by_minute / np.maximum(by_minute.mean(axis=1, keepdims=True), 1e-12)
    return np.repeat(by_minute, 60, axis=1)


def _rates(theta: np.ndarray, active: np.ndarray, shape: np.ndarray):
    k = theta[:4].reshape(2, 2)
    state = kernel_state(active, np.exp(theta[4]))[:, :, WARM:]
    y = active[:, :, WARM:]
    mean = y.mean(axis=-1)                                           # (windows, 2): that morning's own level
    base = np.maximum(mean - mean @ k.T, 1e-7)                       # what is left once triggered activity is taken out
    lam = base[:, :, None] * shape[None] + np.einsum("ij,wjt->wit", k, state)
    return y, lam, base


def log_likelihood(theta: np.ndarray, active: np.ndarray, shape: np.ndarray) -> float:
    """A second is active with probability 1 - exp(-rate): the chance a Poisson count is not zero."""
    y, lam, _ = _rates(theta, active, shape)
    lam = np.maximum(lam, 1e-9)
    return float(np.sum(np.where(y > 0, np.log(-np.expm1(-lam)), -lam)))


def fit(active: np.ndarray, shape: np.ndarray, start: np.ndarray | None = None, triggering: bool = True) -> np.ndarray:
    x0 = START.copy() if start is None else start.copy()
    bounds = list(BOUNDS)
    if not triggering:
        x0[:4] = 0.0
        bounds[:4] = [(0.0, 0.0)] * 4
    scale = max(float(active[:, :, WARM:].sum()), 1.0)
    return minimize(lambda t: -log_likelihood(t, active, shape) / scale, x0, method="L-BFGS-B", bounds=bounds).x


def _summary(theta: np.ndarray, active: np.ndarray, shape: np.ndarray) -> dict:
    y, _, base = _rates(theta, active, shape)
    k = theta[:4].reshape(2, 2)
    return {"branching": float(np.max(np.abs(np.linalg.eigvals(k)))), "matrix": k.round(3).tolist(),
            "triggered_share": float(1 - base.sum() / max(y.mean(axis=-1).sum(), 1e-12)), "half_life_s": float(np.log(2) / np.exp(theta[4]))}


def _flat(active: np.ndarray) -> np.ndarray:
    return np.ones((2, LENGTH))


def _fit_set(active: np.ndarray, flat: bool = False, blocks: int = 6) -> dict:
    """flat=True fits with a constant baseline instead of the hour's average course, to show what that choice does."""
    shape_of = _flat if flat else hour_shape
    theta = fit(active, shape_of(active))
    out = _summary(theta, active, shape_of(active))
    # Uncertainty: leave out one block of consecutive days at a time and refit.
    left = []
    for part in np.array_split(np.arange(len(active)), blocks):
        rest = np.delete(active, part, axis=0)
        left.append(_summary(fit(rest, shape_of(rest), start=theta), rest, shape_of(rest)))
    for key in ("branching", "triggered_share", "half_life_s"):
        v = np.array([x[key] for x in left])
        out[f"{key}_se"] = float(np.sqrt((blocks - 1) / blocks * np.sum((v - v.mean()) ** 2)))
    # Out of sample: fit on the first half of the days (their own average course), score the second half against no triggering.
    half = len(active) // 2
    shape = shape_of(active[:half])
    with_k, without = fit(active[:half], shape, start=theta), fit(active[:half], shape, triggering=False)
    events = max(float(active[half:, :, WARM:].sum()), 1.0)
    gain = (log_likelihood(with_k, active[half:], shape) - log_likelihood(without, active[half:], shape)) / events
    out.update(windows=int(len(active)), active_seconds=int(active[:, :, WARM:].sum()), out_of_sample_gain=float(np.exp(gain)))
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def _windows(sw: pd.DataFrame, days: list, hour: int, minute: int) -> np.ndarray:
    """active[day, stream, second] for the window starting WARM seconds before hour:minute New York time."""
    index = {d: i for i, d in enumerate(days)}
    local = sw["local"]
    sec = ((local.dt.hour * 3600 + local.dt.minute * 60 + local.dt.second) - (hour * 3600 + minute * 60 - WARM)).values
    day = local.dt.date.map(index).values
    keep = (sec >= 0) & (sec < WARM + LENGTH) & ~np.isnan(day.astype(float))
    out = np.zeros((len(days), 2, WARM + LENGTH))
    out[day[keep].astype(int), (sw["tenor_years"].values[keep] > SPLIT_YEARS).astype(int), sec[keep]] = 1.0
    return out


def _spread(days: list) -> list:
    if len(days) <= MAX_WINDOWS:
        return days
    return [days[i] for i in np.linspace(0, len(days) - 1, MAX_WINDOWS).round().astype(int)]


def clustering() -> dict:
    stats = json.loads((CLEAN / "build_stats.json").read_text())
    sw = pd.read_parquet(CLEAN / "usd_sofr_swaps.parquet", columns=["exec_ts", "trade_date", "tenor_years"])
    sw = sw[sw["trade_date"] >= stats["first_day"]].copy()
    sw["local"] = sw["exec_ts"].dt.tz_convert(NY)
    sw = sw[sw["local"].dt.date == sw["trade_date"].dt.date]                  # executed on the day it is filed under
    per_day = sw.groupby(sw["local"].dt.date).size()
    trading = [d for d, n in per_day.items() if n >= 500 and pd.Timestamp(d).dayofweek < 5]
    release = {pd.Timestamp(d).date() for d in CPI_DAYS + JOBS_DAYS}
    rel, other = [d for d in trading if d in release], [d for d in trading if d not in release]
    sets = {"release": _windows(sw, rel, 8, 30), "other": _windows(sw, _spread(other), 8, 30), "midmorning": _windows(sw, _spread(other), 10, 30)}
    out = {name: _fit_set(active) for name, active in sets.items()}
    out["release_flat_baseline"] = _fit_set(sets["release"], flat=True, blocks=3)   # the naive fit, kept to show the size of the trap
    a, b = out["release"], out["other"]
    out["difference"] = {"branching": round(a["branching"] - b["branching"], 4), "z": round((a["branching"] - b["branching"]) / max(np.hypot(a["branching_se"], b["branching_se"]), 1e-9), 2)}
    # The picture: active seconds in each minute from 8:20 to 9:30, release days against the rest.
    both = lambda active: active.max(axis=1).reshape(len(active), -1, 60).sum(axis=-1).mean(axis=0).round(2).tolist()  # noqa: E731
    all_other = _windows(sw, other, 8, 30)
    out["profile"] = {"minutes": [f"{8 + (20 + m) // 60}:{(20 + m) % 60:02d}" for m in range((WARM + LENGTH) // 60)], "release": both(sets["release"]), "other": both(all_other)}
    # A check on the calendar itself: a real release shows as a jump in the first five minutes.
    first5 = lambda active: active.max(axis=1)[:, WARM:WARM + 300].sum(axis=-1)  # noqa: E731
    usual = float(np.median(first5(all_other)))
    jumps = first5(sets["release"]) / max(usual, 1.0)
    out["calendar"] = {"release_days": len(rel), "cpi_days": len([d for d in rel if str(d) in CPI_DAYS]), "jobs_days": len([d for d in rel if str(d) in JOBS_DAYS]), "other_days": len(other),
                       "median_jump": round(float(np.median(jumps)), 2), "days_without_jump": [str(d) for d, j in zip(rel, jumps, strict=True) if j < 1.25]}
    return out


# ------------------------------------------------------------------ 2. signed flow
def _ols(x: np.ndarray, y: np.ndarray, cluster: np.ndarray):
    """Least squares with standard errors clustered by day."""
    inv = np.linalg.inv(x.T @ x)
    beta = inv @ x.T @ y
    resid = y - x @ beta
    by = np.zeros((cluster.max() + 1, x.shape[1]))
    np.add.at(by, cluster, x * resid[:, None])
    g = by.shape[0]
    se = np.sqrt(np.diag(inv @ (by.T @ by) @ inv * g / (g - 1)))
    return beta, se, 1 - resid.var() / y.var()


def signed_flow(min_gap_bp: float = 0.05) -> dict:
    s = pd.read_parquet(RESULTS / "swap_scores.parquet", columns=["exec_ts", "tenor_years", "fixed_rate_pct", "notional", "filter", "scored", "damped"])
    s = s[s["scored"] & ~s["damped"]].copy()
    gap = (s["fixed_rate_pct"] - s["filter"]) * 100
    s["side"] = np.sign(gap).where(gap.abs() >= min_gap_bp, 0.0)
    s["flow"] = s["side"] * s["notional"] * s["tenor_years"] / 10 / 1e9          # billions of dollars, ten-year equivalents
    snaps = pd.read_parquet(RESULTS / "curve_snapshots.parquet", columns=["ts", "10.0"]).sort_values("ts").reset_index(drop=True)
    ts = snaps["ts"].values.astype("datetime64[s]")
    when = s["exec_ts"].dt.tz_localize(None).values.astype("datetime64[s]")
    slot = np.searchsorted(ts, when, side="left")                                # the snapshot that closes the interval the trade fell in
    ok = (slot > 0) & (slot < len(ts))
    flow = np.bincount(slot[ok], weights=s["flow"].values[ok], minlength=len(ts))
    count = np.bincount(slot[ok], weights=(s["side"].values[ok] != 0).astype(float), minlength=len(ts))
    move = np.r_[np.nan, np.diff(snaps["10.0"].values) * 100]                    # bp over the interval ending at each snapshot
    local = snaps["ts"].dt.tz_localize("UTC").dt.tz_convert(NY)
    step = np.r_[np.inf, np.diff(ts).astype(float)]
    f = pd.DataFrame({"day": local.dt.date.values, "hour": local.dt.hour.values, "flow": flow, "n": count, "move": move, "step": step})
    f["next_move"] = f["move"].shift(-1).where((f["step"].shift(-1) == 600) & (f["day"].shift(-1) == f["day"]))
    f = f[(f["step"] == 600) & f["hour"].between(7, 16) & f["move"].notna() & (f["move"].abs() < 15)]
    day = pd.factorize(f["day"])[0]
    one = np.ones(len(f))
    b0, se0, r0 = _ols(np.column_stack([one, f["flow"]]), f["move"].values, day)
    p = f[f["next_move"].notna() & (f["next_move"].abs() < 15)]
    pday = pd.factorize(p["day"])[0]
    xp = np.column_stack([np.ones(len(p)), p["flow"], p["move"]])
    b1, se1, r1 = _ols(xp, p["next_move"].values, pday)
    # Out of sample: coefficients from the first 70% of days, scored on the rest against "no change".
    cut = int(0.7 * (pday.max() + 1))
    tr, te = pday < cut, pday >= cut
    bt = np.linalg.lstsq(xp[tr], p["next_move"].values[tr], rcond=None)[0]
    err = p["next_move"].values[te] - xp[te] @ bt
    oos = 1 - float(np.sum(err ** 2) / np.sum(p["next_move"].values[te] ** 2))
    return {"trades": int(len(s)), "signed_share_pct": round(float(100 * (s["side"] != 0).mean()), 1), "intervals": int(len(f)), "days": int(day.max() + 1),
            "typical_flow_bn": round(float(f["flow"].abs().median()), 3),
            "same_interval": {"bp_per_bn": round(float(b0[1]), 4), "t": round(float(b0[1] / se0[1]), 1), "r_squared": round(float(r0), 4)},
            "next_interval": {"bp_per_bn": round(float(b1[1]), 4), "t": round(float(b1[1] / se1[1]), 1), "carry_over": round(float(b1[2]), 4), "carry_over_t": round(float(b1[2] / se1[2]), 1),
                              "r_squared": round(float(r1), 4), "out_of_sample_r_squared": round(oos, 4)}}


# ------------------------------------------------------------------ 3. late-day drift
def late_day_drift(threshold_bp: float = 8.0) -> dict:
    snaps = pd.read_parquet(RESULTS / "curve_snapshots.parquet", columns=["ts", "10.0"]).sort_values("ts")
    local = snaps["ts"].dt.tz_localize("UTC").dt.tz_convert(NY)
    rate = pd.Series(snaps["10.0"].values * 100, index=local)                    # basis points
    rate = rate[rate.index.dayofweek < 5]
    at = lambda h: rate[rate.index.hour < h].groupby(rate[rate.index.hour < h].index.date).last()  # noqa: E731  last reading before h o'clock
    two, four = at(14), at(16)
    d = pd.DataFrame({"two": two, "four": four}).dropna()
    d["morning"] = d["two"] - d["four"].shift(1)                                 # previous 4 pm to today's 2 pm
    d["late"] = d["four"] - d["two"]
    d = d.dropna()
    d = d[d["late"].abs() < 30]
    big = d[d["morning"].abs() >= threshold_bp]
    cont = np.sign(big["morning"]) * big["late"]
    slope, se, r2 = _ols(np.column_stack([np.ones(len(d)), d["morning"]]), d["late"].values, np.arange(len(d)))
    return {"days": int(len(d)), "threshold_bp": threshold_bp, "big_days": int(len(big)),
            "same_direction_pct": round(float(100 * (cont > 0).mean()), 1) if len(big) else None,
            "mean_continuation_bp": round(float(cont.mean()), 2) if len(big) else None,
            "t": round(float(cont.mean() / (cont.std(ddof=1) / np.sqrt(len(big)))), 2) if len(big) > 2 else None,
            "all_days_slope": round(float(slope[1]), 4), "all_days_t": round(float(slope[1] / se[1]), 2), "typical_late_move_bp": round(float(d["late"].abs().median()), 2)}


def run() -> dict:
    out = {"clustering": clustering(), "signed_flow": signed_flow(), "late_day": late_day_drift()}
    (RESULTS / "flow.json").write_text(json.dumps(out))
    return out
