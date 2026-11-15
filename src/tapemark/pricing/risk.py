"""Risk of a swap to each point on the curve, two independent ways.

``bucket_dv01_bump``  moves one input rate by a basis point, rebuilds the
whole curve, and reprices. Simple and obviously right, but it rebuilds the
curve once per input.

``bucket_dv01_ad``    carries exact derivatives through the same arithmetic
in a single pass (forward-mode automatic differentiation with dual numbers).
Banks use this family of methods because it gives every sensitivity for
roughly the cost of one valuation.

The two must agree; a test holds them to it. Values are for paying fixed.
DV01 here is the change in value for a ONE BASIS POINT RISE in that input rate.
"""

from __future__ import annotations

import math

import numpy as np

from tapemark.pricing.calendar import add_business_days
from tapemark.pricing.curve import MAX_YEARS, SHORT_MONTHS, Curve, payer_value, shift_months, shift_years

BP = 0.01  # one basis point, in percent


def bucket_dv01_bump(asof, tenors, par_pct, effective, maturity, fixed_pct, notional=1.0) -> np.ndarray:
    par = np.asarray(par_pct, dtype=float)
    out = np.empty(len(par))
    for j in range(len(par)):
        up, dn = par.copy(), par.copy()
        up[j] += BP / 2
        dn[j] -= BP / 2
        v_up = payer_value(Curve.from_par(asof, tenors, up), effective, maturity, fixed_pct, notional)[0]
        v_dn = payer_value(Curve.from_par(asof, tenors, dn), effective, maturity, fixed_pct, notional)[0]
        out[j] = v_up - v_dn
    return out


class Dual:
    """A number together with its derivatives with respect to every input rate."""

    __slots__ = ("v", "d")

    def __init__(self, v: float, d: np.ndarray):
        self.v, self.d = v, d

    @staticmethod
    def lift(x, n: int) -> Dual:
        return x if isinstance(x, Dual) else Dual(float(x), np.zeros(n))

    def __add__(self, o):
        o = Dual.lift(o, len(self.d))
        return Dual(self.v + o.v, self.d + o.d)

    __radd__ = __add__

    def __sub__(self, o):
        o = Dual.lift(o, len(self.d))
        return Dual(self.v - o.v, self.d - o.d)

    def __rsub__(self, o):
        return Dual.lift(o, len(self.d)) - self

    def __mul__(self, o):
        o = Dual.lift(o, len(self.d))
        return Dual(self.v * o.v, self.d * o.v + o.d * self.v)

    __rmul__ = __mul__

    def __truediv__(self, o):
        o = Dual.lift(o, len(self.d))
        return Dual(self.v / o.v, (self.d * o.v - o.d * self.v) / (o.v * o.v))

    def __rtruediv__(self, o):
        return Dual.lift(o, len(self.d)) / self

    def log(self):
        return Dual(math.log(self.v), self.d / self.v)

    def exp(self):
        e = math.exp(self.v)
        return Dual(e, self.d * e)


def _interp_weights(x: float, xs: np.ndarray) -> np.ndarray:
    """Weights w with interp(x, xs, ys) == w @ ys (flat beyond the ends)."""
    w = np.zeros(len(xs))
    if x <= xs[0]:
        w[0] = 1.0
    elif x >= xs[-1]:
        w[-1] = 1.0
    else:
        j = int(np.searchsorted(xs, x, side="right"))
        w[j] = (x - xs[j - 1]) / (xs[j] - xs[j - 1])
        w[j - 1] = 1.0 - w[j]
    return w


def _dual_curve(asof, tenors, par_pct):
    """The bootstrap of ``Curve.from_par``, with every discount factor carrying its derivatives."""
    tenors = np.asarray(tenors, dtype=float)
    n = len(tenors)
    rates = [Dual(float(r) / 100.0, np.eye(n)[i] / 100.0) for i, r in enumerate(par_pct)]  # derivative per percent

    def rate_at(t: float) -> Dual:
        w = _interp_weights(t, tenors)
        out = Dual(0.0, np.zeros(n))
        for i in np.nonzero(w)[0]:
            out = out + rates[i] * float(w[i])
        return out

    asof = np.datetime64(asof, "D")
    start = add_business_days(asof, 2)
    df_start = 1.0 / (1.0 + rate_at(tenors.min()) * (float((start - asof).astype(int)) / 360.0))
    days, logs = [0.0, float((start - asof).astype(int))], [Dual(0.0, np.zeros(n)), df_start.log()]
    for tenor, months in SHORT_MONTHS.items():
        if tenors.min() <= tenor:
            end = shift_months(start, months)
            df = df_start / (1.0 + rate_at(tenor) * (float((end - start).astype(int)) / 360.0))
            days.append(float((end - asof).astype(int)))
            logs.append(df.log())
    annuity, prev = Dual(0.0, np.zeros(n)), start
    for k in range(1, MAX_YEARS):
        end = shift_years(start, k)
        alpha = float((end - prev).astype(int)) / 360.0
        s = rate_at(float(k))
        df = (df_start - s * annuity) / (1.0 + s * alpha)
        annuity = annuity + df * alpha
        days.append(float((end - asof).astype(int)))
        logs.append(df.log())
        prev = end
    order = np.argsort(days)
    return asof, np.array(days)[order], [logs[i] for i in order]


def _dual_df(asof, days, logs, date) -> Dual:
    x = float((np.datetime64(date, "D") - asof).astype(int))
    if x >= days[-1]:
        slope = (logs[-1] - logs[-2]) / (days[-1] - days[-2])
        return (logs[-1] + slope * (x - days[-1])).exp()
    j = max(int(np.searchsorted(days, x, side="right")), 1)
    w = (x - days[j - 1]) / (days[j] - days[j - 1])
    return (logs[j - 1] * (1.0 - w) + logs[j] * w).exp()


def bucket_dv01_ad(asof, tenors, par_pct, effective, maturity, fixed_pct, notional=1.0) -> np.ndarray:
    asof, days, logs = _dual_curve(asof, tenors, par_pct)
    eff, mat = np.datetime64(effective, "D"), np.datetime64(maturity, "D")
    n = len(par_pct)
    annuity, later = Dual(0.0, np.zeros(n)), mat
    for k in range(1, MAX_YEARS + 1):
        if later <= eff:
            break
        earlier = max(shift_years(mat, -k), eff)
        annuity = annuity + _dual_df(asof, days, logs, later) * (float((later - earlier).astype(int)) / 360.0)
        later = earlier
    value = (_dual_df(asof, days, logs, eff) - _dual_df(asof, days, logs, mat) - annuity * (float(fixed_pct) / 100.0)) * float(notional)
    return value.d * BP  # derivative per percent -> per basis point


def explain(asof0, par0, asof1, par1, tenors, effective, maturity, fixed_pct, notional=1.0) -> dict:
    """Why a swap's value changed between two dates (paying fixed).

    time   value on the new date if rates had not changed
    rates  each input's move times the swap's sensitivity to that input
    rest   what a straight-line approximation misses
    """
    tenors = np.asarray(tenors, dtype=float)
    v0 = payer_value(Curve.from_par(asof0, tenors, par0), effective, maturity, fixed_pct, notional)[0]
    v_time = payer_value(Curve.from_par(asof1, tenors, par0), effective, maturity, fixed_pct, notional)[0]
    v1 = payer_value(Curve.from_par(asof1, tenors, par1), effective, maturity, fixed_pct, notional)[0]
    dv01 = bucket_dv01_ad(asof1, tenors, par0, effective, maturity, fixed_pct, notional)
    move_bp = (np.asarray(par1, float) - np.asarray(par0, float)) * 100.0
    by_bucket = dv01 * move_bp
    return {"start": float(v0), "end": float(v1), "total": float(v1 - v0), "time": float(v_time - v0), "rates": float(by_bucket.sum()),
            "rest": float(v1 - v_time - by_bucket.sum()), "by_bucket": by_bucket.tolist(), "dv01": dv01.tolist()}


def hedge_weights(dv01: np.ndarray, tenors: np.ndarray, hedge_tenors=(2, 5, 10, 30)) -> np.ndarray:
    """Spread each input's risk onto the two nearest hedge lengths, in proportion to closeness."""
    hedge_tenors = np.asarray(hedge_tenors, dtype=float)
    out = np.zeros(len(hedge_tenors))
    for t, r in zip(tenors, dv01, strict=True):
        out += _interp_weights(float(t), hedge_tenors) * r
    return out


SCENARIOS = {
    "All rates up 25 bp": lambda t: np.full(len(t), 25.0),
    "All rates down 25 bp": lambda t: np.full(len(t), -25.0),
    "All rates up 100 bp": lambda t: np.full(len(t), 100.0),
    "Curve steepens: short down 25, long up 25": lambda t: np.interp(t, [2, 30], [-25.0, 25.0]),
    "Curve flattens: short up 25, long down 25": lambda t: np.interp(t, [2, 30], [25.0, -25.0]),
    "Short rates up 50 bp, long unchanged": lambda t: np.interp(t, [2, 10], [50.0, 0.0]),
}


def stress(asof, tenors, par_pct, effective, maturity, fixed_pct, notional=1.0, extra: dict | None = None) -> list[dict]:
    """Value change under each scenario, by full repricing (not by sensitivities)."""
    tenors = np.asarray(tenors, dtype=float)
    par = np.asarray(par_pct, dtype=float)
    base = payer_value(Curve.from_par(asof, tenors, par), effective, maturity, fixed_pct, notional)[0]
    shocks = {name: fn(tenors) for name, fn in SCENARIOS.items()}
    shocks.update(extra or {})
    out = []
    for name, shock_bp in shocks.items():
        v = payer_value(Curve.from_par(asof, tenors, par + np.asarray(shock_bp) / 100.0), effective, maturity, fixed_pct, notional)[0]
        out.append({"scenario": name, "change": float(v - base)})
    return out
