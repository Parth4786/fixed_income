"""A short end that moves in steps on Federal Reserve meeting dates.

The curve model's short end is smooth: between its 3-month, 6-month, 1-year
and 2-year points it interpolates. The overnight rate does not move smoothly.
It is set by the Federal Open Market Committee and changes, if at all, the day
after a scheduled meeting. A swap that starts in four months and runs for
three is a bet on two or three particular meetings, and a smooth curve spreads
those bets across the year. That is the model's measured weak spot: forward-
starting swaps shorter than a year miss by about 1.1 bp against 0.5 bp for
the rest.

This module keeps the curve model's own short-end points exactly and changes
only what happens between them. The overnight rate is held constant between
meetings, r_k on segment k, so that

    -ln DF(T) = sum_k r_k * (days of segment k before T) / 360

and the steps are chosen as the smoothest path (smallest sum of squared
changes between meetings) that reproduces the curve's discount factor at each
short-end point exactly. That is a small least-squares problem with equality
constraints, solved in closed form. Between meeting dates the discount factor
is then log-linear, which is exactly what a constant overnight rate implies, so
the result plugs into the ordinary curve class.

Meeting dates: federalreserve.gov/monetarypolicy/fomccalendars.htm, read on
15 Nov 2026. 2027 dates are tentative on that page. The unscheduled notation
vote of 22 Aug 2025 is left out: it changed no rate.
"""

from __future__ import annotations

import numpy as np

from tapemark.pricing.curve import Curve, D

MEETINGS = np.array([
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-11-17",
], dtype=D)
EFFECTIVE = MEETINGS + 1            # a decision applies from the next day
SHORT_END_YEARS = 2.0               # steps are fitted out to here; the curve model is used unchanged beyond


def stepped(curve: Curve, horizon_years: float = SHORT_END_YEARS) -> Curve:
    """The same curve with its first `horizon_years` rebuilt as steps on meeting dates."""
    asof = curve.asof
    end = asof + np.timedelta64(int(round(horizon_years * 365.25)), "D")
    # Points of the original curve inside the horizon that the steps must reproduce exactly.
    knots_days = curve.days[(curve.days > 0) & (curve.days <= (end - asof).astype(float) + 0.5)]
    if len(knots_days) == 0:
        return curve
    last = asof + np.timedelta64(int(knots_days[-1]), "D")
    edges = np.concatenate([[asof], EFFECTIVE[(EFFECTIVE > asof) & (EFFECTIVE < last)], [last]]).astype(D)
    seg = np.diff(edges).astype(float)                                  # days in each segment
    n = len(seg)
    starts = (edges[:-1] - asof).astype(float)
    # A[j, k]: days of segment k before knot j, in years of 360 days.
    a = np.clip(knots_days[:, None] - starts[None, :], 0.0, seg[None, :]) / 360.0
    b = -np.interp(knots_days, curve.days, curve.logdf)
    if n == 1:
        r = np.linalg.lstsq(a, b, rcond=None)[0]
    else:
        diff = np.diff(np.eye(n), axis=0)                               # changes between neighbouring segments
        q = diff.T @ diff + 1e-10 * np.eye(n)
        kkt = np.block([[2 * q, a.T], [a, np.zeros((len(b), len(b)))]])
        sol = np.linalg.lstsq(kkt, np.concatenate([np.zeros(n), b]), rcond=None)[0]
        r = sol[:n]
    logdf_edges = -np.concatenate([[0.0], np.cumsum(r * seg / 360.0)])
    later = curve.days > (last - asof).astype(float) + 0.5
    days = np.concatenate([(edges[1:] - asof).astype(float), curve.days[later]])
    logdf = np.concatenate([logdf_edges[1:], curve.logdf[later]])
    return Curve(asof, asof + days.astype("timedelta64[D]"), np.exp(logdf))


def overnight_path(curve: Curve, horizon_years: float = SHORT_END_YEARS) -> list[dict]:
    """The overnight rate the stepped curve implies after each meeting, in percent (simple, Actual/360)."""
    s = stepped(curve, horizon_years)
    # One row for today and one for the day after each listed meeting inside the horizon; nothing past the last
    # meeting the Fed has published, since a step there would have no date to hang on.
    starts = [s.asof] + [d for d in EFFECTIVE if s.asof < d <= s.asof + np.timedelta64(int(horizon_years * 365.25), "D")]
    out = []
    for d in starts:
        a = float((d - s.asof).astype(int))
        r = (np.log(s.df(np.array([d], dtype=D)))[0] - np.log(s.df(np.array([d + 1], dtype=D)))[0]) * 360.0   # one day's rate, continuous
        out.append({"from": str(d), "rate_pct": round(float(np.expm1(r / 360.0) * 360.0 * 100), 3), "days_out": int(a)})
    return out
