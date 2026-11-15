"""Eris SOFR swap futures: price, interest on margin, and the cost of posting margin.

What the contract is
    A future whose cash flows copy a fixed-for-SOFR swap. One contract is
    $100,000 of size; the long side receives the fixed coupon. The exchange
    publishes the settlement price as

        price = 100 + A + B - C

    A   value today of the cash flows still to come (fixed minus floating),
        per 100 of size
    B   fixed minus floating amounts already paid since the contract began
    C   "Eris PAI": interest on the daily margin payments, added up since the
        first trading day

Why C exists
    A cleared swap pays interest on the cash that changes hands as its value
    moves (price alignment interest). A plain future does not, so a future
    and a swap with the same cash flows would be worth different amounts.
    Eris puts that interest into the price itself, one day at a time:

        C(today) = C(yesterday) + A(yesterday) * overnight rate * days / 360

    so holding the future costs or earns the same as holding the swap.

Conventions, read off the exchange's own cash-flow file and then tested
against it: yearly periods on anniversaries of the effective date, moved to
a business day; Actual/360 on both legs; payment two business days after the
period ends; the floating amount is SOFR compounded daily over the period.

Margin and its funding cost
    Margin is sized to a bad move over the time it takes to close a position
    out: `margin = DV01 * (the move not exceeded on `confidence` of past
    `horizon`-day windows)`. US rules set that time at one day or more for
    futures and five days or more for cleared swaps, which is the main
    reason a future needs less margin than the same swap. Margin is cash
    that must be funded for as long as the trade lives:

        funding cost = spread * sum over time of [ margin(t) * discount(t) * dt ]

    margin(t) is the margin of the trade as it will be at t, shorter by
    then. This is the margin valuation adjustment (MVA) in its simplest
    form: one trade on its own, the curve held still, no netting.
"""

from __future__ import annotations

import numpy as np

from tapemark.pricing.calendar import _calendar, add_business_days
from tapemark.pricing.curve import D, shift_years

CONTRACT = 100_000  # dollars of size in one contract; one price point is $1,000


def periods(effective, alignment):
    """Accrual start, accrual end and payment date of each yearly period."""
    effective, alignment = np.datetime64(effective, "D"), np.datetime64(alignment, "D")
    years = int(round((alignment - effective).astype(int) / 365.25))
    raw = np.array([shift_years(np.array([effective]), k)[0] for k in range(years + 1)], dtype=D)
    adj = np.busday_offset(raw, 0, roll="modifiedfollowing", busdaycal=_calendar())
    return adj[:-1], adj[1:], add_business_days(adj[1:], 2)


class Fixings:
    """SOFR fixings, for the part of a floating period that has already happened."""

    def __init__(self, days, rates_pct):
        self.days = np.asarray(days, dtype=D)
        self.rates = np.asarray(rates_pct, dtype=float) / 100

    def growth(self, start, end) -> float:
        """Value of 1 invested at SOFR from `start` and rolled daily to `end`."""
        start, end = np.datetime64(start, "D"), np.datetime64(end, "D")
        use = (self.days >= start) & (self.days < end)
        d, r = self.days[use], self.rates[use]
        if not len(d):
            return 1.0
        span = np.diff(np.r_[d, end]).astype(int)          # each fixing applies until the next one, or to the end
        return float(np.prod(1 + r * span / 360))


def cash_flows(asof, effective, alignment, coupon_pct, df, fixings: Fixings | None = None):
    """Fixed and floating amount of each period per 100 of size, and which are still to be paid.

    `df(dates)` is the discount factor from `asof`. Floating amounts not yet
    known come from the curve; the part already fixed comes from `fixings`.
    """
    asof = np.datetime64(asof, "D")
    start, end, pay = periods(effective, alignment)
    days = (end - start).astype(int)
    fixed = coupon_pct * days / 360
    ahead = start >= asof
    floating = np.zeros(len(start))
    floating[ahead] = 100 * (df(start[ahead]) / df(end[ahead]) - 1)          # all in the future: read off the curve
    for i in np.flatnonzero(~ahead):
        s, e = start[i], end[i]
        if e > asof:                                        # under way: fixed so far, the curve for the rest
            done = fixings.growth(s, asof) if fixings else 1.0
            floating[i] = 100 * (done / float(df(np.array([e]))[0]) - 1)
        else:                                               # finished
            floating[i] = 100 * ((fixings.growth(s, e) if fixings else 1.0) - 1)
    return {"start": start, "end": end, "pay": pay, "fixed": fixed, "floating": floating, "open": pay > asof}


def value(asof, effective, alignment, coupon_pct, df, fixings: Fixings | None = None) -> dict:
    """A (what is still to come, discounted) and B (what has been paid), per 100 of size."""
    cf = cash_flows(asof, effective, alignment, coupon_pct, df, fixings)
    live = cf["open"]
    disc = df(cf["pay"][live]) if live.any() else np.array([])
    a = float(np.sum((cf["fixed"][live] - cf["floating"][live]) * disc))
    b = float(np.sum(cf["fixed"][~live] - cf["floating"][~live]))
    return {"a": a, "b": b}


def pai_step(previous_a: float, rate_pct: float, days: int) -> float:
    """One day's addition to C: interest at the overnight rate on yesterday's value."""
    return previous_a * rate_pct / 100 * days / 360


def price(a: float, b: float, c: float) -> float:
    return 100 + a + b - c


def dv01(asof, effective, alignment, coupon_pct, df, fixings: Fixings | None = None) -> float:
    """Dollars lost on one long contract when every rate rises one basis point.

    The rise is in the yearly-compounded Actual/360 rate to each date, the
    way a swap rate is quoted. That is the definition under which the
    exchange's published DV01 is reproduced; a rise in continuously
    compounded rates gives a number about 3% larger.
    """
    asof = np.datetime64(asof, "D")

    def up(dates):
        t = np.maximum((np.asarray(dates, dtype=D) - asof).astype(int) / 365, 1e-9)
        return (df(dates) ** (-1 / t) + 1e-4 * 365 / 360) ** (-t)

    base = value(asof, effective, alignment, coupon_pct, df, fixings)["a"]
    return (base - value(asof, effective, alignment, coupon_pct, up, fixings)["a"]) * CONTRACT / 100


# ------------------------------------------------------------------ margin and its funding cost
def worst_moves(history: np.ndarray, horizon: int, confidence: float) -> np.ndarray:
    """For each curve point: the rate move, in basis points, not exceeded on `confidence` of past `horizon`-day windows.

    `history` is one row a day of par rates in percent. Windows overlap, as
    in the historical method clearing houses use.
    """
    change = np.abs(history[horizon:] - history[:-horizon]) * 100
    return np.quantile(change, confidence, axis=0)


def worst_moves_scaled(history: np.ndarray, horizon: int, confidence: float, decay: float = 0.97) -> np.ndarray:
    """The same, with each past move rescaled to today's volatility, and never below the unscaled figure.

    This is the structure CME describes for its cleared swap margin: a
    historical method in which past moves are rescaled by a short-term
    volatility forecast (an exponentially weighted average of squared daily
    moves), paired with unscaled moves so that margin does not collapse when
    markets are calm. `decay` is the weight on yesterday's estimate; the
    clearing house does not publish its value, and 0.97 is a common choice.
    """
    vol = _volatility(history, decay)
    change = (history[horizon:] - history[:-horizon]) * 100
    scale = vol[-1] / np.maximum(vol[: len(change)], 1e-6)
    scaled = np.quantile(np.abs(change * scale), confidence, axis=0)
    return np.maximum(scaled, worst_moves(history, horizon, confidence))


def _volatility(history: np.ndarray, decay: float) -> np.ndarray:
    """Daily volatility in basis points as known at the close of each day (row i uses moves up to day i only)."""
    daily = np.diff(history, axis=0) * 100
    var = daily[:60].var(axis=0)
    vol = np.empty_like(history)
    vol[0] = np.sqrt(var)
    for i in range(len(daily)):
        if i >= 60:                                         # the first 60 days are the starting estimate
            var = decay * var + (1 - decay) * daily[i] ** 2
        vol[i + 1] = np.sqrt(var)
    return vol


def coverage(history: np.ndarray, horizon: int, confidence: float, start: int = 500, scaled: bool = False, decay: float = 0.97) -> np.ndarray:
    """The standard test of a margin model: was the margin set on each day enough for what happened next?

    For every day from `start` on, the margin move is computed from windows
    that had fully ended by that day, and compared with the move over the
    following `horizon` days. Returns one row a day, one column a curve
    point: True where the margin was enough. The rule passes if the share of
    True is at least `confidence`.
    """
    change = np.abs(history[horizon:] - history[:-horizon]) * 100   # change[s] is the move over the window starting on day s
    vol = _volatility(history, decay) if scaled else None
    rows = []
    for t in range(start, len(history) - horizon):
        past = change[: t - horizon + 1]                             # windows that ended on or before day t
        limit = np.quantile(past, confidence, axis=0)
        if scaled:
            limit = np.maximum(limit, np.quantile(past * vol[t] / np.maximum(vol[: t - horizon + 1], 1e-6), confidence, axis=0))
        rows.append(change[t] <= limit)
    return np.array(rows)


def margin_years(tenor_years: float, annuity_at, move_at, discount_at, step: float = 0.25) -> tuple[float, float]:
    """Margin today and discounted margin-years over the life, per dollar of size.

    annuity_at(t) is the value of receiving 1 a year for t years (so a
    swap's DV01 per dollar is annuity * 0.0001), move_at(t) the margin move
    in basis points for a swap of length t, discount_at(t) the discount
    factor t years out. Funding cost = spread * margin-years.
    """
    def margin(remaining):
        return annuity_at(remaining) * 1e-4 * move_at(remaining)

    times = np.arange(0.0, tenor_years, step)
    total = sum(margin(tenor_years - t) * discount_at(t + step / 2) * min(step, tenor_years - t) for t in times)
    return float(margin(tenor_years)), float(total)
