"""A swap curve estimated from individual trades as they arrive.

The problem
-----------
Trades arrive one at a time, at irregular moments, each for a different swap
length. A 10-year trade at 14:02 says something about the 7-year rate too,
because rates of different lengths move together. Taking the median of recent
trades per length throws that information away and gives no measure of how
sure the estimate is.

The model (a Kalman filter)
---------------------------
State x: the par swap rate at a fixed set of lengths (the nodes), in percent.

    between trades:   x_t = x_{t-1} + w,   w ~ N(0, Q * dt)
    a trade arrives:  y   = h' x_t + v,    v ~ N(0, R)

- Q is how rates of different lengths move together per day. It is estimated
  from the past only (daily changes of an outside curve over a trailing window).
- h holds the straight-line weights that interpolate the trade's length
  between its two neighbouring nodes.
- R is the noise in a single trade.

Before each trade the filter already has a prediction h'x and its variance
S = h'Ph + R. The gap between the trade and that prediction is, by
construction, an out-of-sample error: the trade was not used to make it.
Then the state is updated:  K = P h / S,  x += K * gap,  P -= K h' P.

A very surprising trade moves the state only partly (its noise is inflated so
that the surprise counts as ``huber`` standard deviations). A real market move
is followed by more trades that agree, and the state catches up within a few.

Assumptions
-----------
Rate changes are roughly normal with a covariance that changes slowly; a
trade's rate is the market rate plus independent noise; lengths between nodes
follow a straight line in par-rate space.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

NODES = np.array([0.25, 0.5, 1, 2, 3, 4, 5, 7, 10, 12, 15, 20, 25, 30], dtype=float)


def weights(tenor_years: float) -> tuple[int, int, float]:
    """Neighbouring node indices and the weight on the upper one."""
    t = min(max(tenor_years, NODES[0]), NODES[-1])
    j = int(np.searchsorted(NODES, t, side="right"))
    j = min(max(j, 1), len(NODES) - 1)
    lo, hi = NODES[j - 1], NODES[j]
    return j - 1, j, (t - lo) / (hi - lo)


@dataclass
class Step:
    prediction: float  # rate the filter expected, percent
    sd: float  # standard deviation of that expectation plus trade noise, percent
    gap: float  # traded minus expected, percent
    damped: bool  # the trade was too surprising to take at face value


class CurveFilter:
    def __init__(self, x0, p0, q_per_day, noise_sd_pct: float = 0.0075, huber: float = 3.0):
        self.x = np.array(x0, dtype=float)
        self.p = np.array(p0, dtype=float)
        self.q = np.array(q_per_day, dtype=float)
        self.r = noise_sd_pct**2
        self.huber = huber

    def advance(self, days: float) -> None:
        """Let uncertainty grow for ``days`` with no trades."""
        if days > 0:
            self.p += self.q * days

    def expect(self, tenor_years: float) -> tuple[float, float]:
        """Predicted rate and its variance (without trade noise) for a swap length."""
        i, j, w = weights(tenor_years)
        pred = (1 - w) * self.x[i] + w * self.x[j]
        var = (1 - w) ** 2 * self.p[i, i] + w**2 * self.p[j, j] + 2 * w * (1 - w) * self.p[i, j]
        return pred, var

    def update(self, tenor_years: float, rate_pct: float) -> Step:
        i, j, w = weights(tenor_years)
        pred, var = self.expect(tenor_years)
        gap = rate_pct - pred
        s = var + self.r
        r_eff, damped = self.r, False
        limit = self.huber * np.sqrt(s)
        if abs(gap) > limit:  # treat as if it were exactly ``huber`` deviations away
            r_eff = (gap / self.huber) ** 2 - var
            damped = True
        ph = (1 - w) * self.p[:, i] + w * self.p[:, j]  # P h
        k = ph / (var + r_eff)
        self.x += k * gap
        self.p -= np.outer(k, ph)
        return Step(pred, float(np.sqrt(s)), gap, damped)


def trailing_covariance(daily_rates: np.ndarray, floor_bp: float = 1.0) -> np.ndarray:
    """Covariance of daily changes (rows are days, columns are nodes), in percent squared.

    A small floor on the diagonal keeps the filter from becoming overconfident
    about a node the window happened to see little movement in.
    """
    changes = np.diff(daily_rates, axis=0)
    cov = np.cov(changes, rowvar=False)
    return cov + np.eye(cov.shape[0]) * (floor_bp / 100.0) ** 2 * 0.01
