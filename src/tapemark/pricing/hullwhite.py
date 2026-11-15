"""Hull-White one-factor model: one volatility surface from two numbers.

The short rate follows  dr = (theta(t) - a r) dt + sigma dW.  Two numbers
describe every swap option in the market: ``a`` (how fast rates are pulled
back toward their path) and ``sigma`` (how much the short rate moves a year).

Under the model the price at expiry T of a bond paying at T_i is the forward
price times exp(-B_i x - B_i^2 v / 2), where x is the model's single random
factor, v = sigma^2 (1 - e^{-2aT}) / (2a) is its variance at expiry, and
B_i = (1 - e^{-a (T_i - T)}) / a.

The forward swap rate S = (P_0 - P_n) / A is a function of x. Freezing its
slope at x = 0 gives the swap rate's normal volatility in closed form:

    sigma_N = sigma * |dS/dx| * sqrt((1 - e^{-2aT}) / (2aT))
    dS/dx   = (-B_0 P_0 + B_n P_n) / A + S * (sum_i alpha_i B_i P_i) / A

A test integrates the exact model price numerically and holds this
approximation to it.

Assumptions: one source of randomness moves the whole curve; ``a`` and
``sigma`` are constant; volatility does not depend on strike.
"""

from __future__ import annotations

import numpy as np

from tapemark.pricing.curve import MAX_YEARS, Curve, shift_years

D = "datetime64[D]"


def _terms(curve: Curve, expiry, start, end, a: float):
    """Forward bond prices seen from expiry and their B weights, summed over the fixed dates."""
    expiry, start, end = (np.atleast_1d(np.asarray(x, dtype=D)) for x in (expiry, start, end))
    df_exp = curve.df(expiry)
    years = lambda d: (d - expiry).astype(float) / 365.0  # noqa: E731
    b = lambda d: (1.0 - np.exp(-a * years(d))) / a  # noqa: E731
    ann = np.zeros(len(start))
    ann_b = np.zeros(len(start))
    later = end.copy()
    for k in range(1, MAX_YEARS + 1):
        earlier = np.maximum(shift_years(end, -k), start)
        live = later > start
        if not live.any():
            break
        alpha = (later - earlier).astype(float) / 360.0
        p = curve.df(later) / df_exp
        ann += np.where(live, alpha * p, 0.0)
        ann_b += np.where(live, alpha * p * b(later), 0.0)
        later = earlier
    p0, pn = curve.df(start) / df_exp, curve.df(end) / df_exp
    return p0, b(start), pn, b(end), ann, ann_b


def normal_vol_factor(curve: Curve, expiry, start, end, a: float) -> np.ndarray:
    """Swap-rate normal volatility per unit of sigma. Multiply by sigma to get the volatility."""
    p0, b0, pn, bn, ann, ann_b = _terms(curve, expiry, start, end, a)
    swap = (p0 - pn) / ann
    slope = (-b0 * p0 + bn * pn) / ann + swap * ann_b / ann
    t = (np.atleast_1d(np.asarray(expiry, dtype=D)) - curve.asof).astype(float) / 365.0
    return np.abs(slope) * np.sqrt((1.0 - np.exp(-2.0 * a * t)) / (2.0 * a * t))


def exact_payer_price(curve: Curve, expiry, start, end, strike: float, a: float, sigma: float, points: int = 400) -> float:
    """Model price of the right to pay ``strike``, by integrating over the random factor. For checks, not speed."""
    expiry, start, end = (np.datetime64(x, "D") for x in (expiry, start, end))
    t = float((expiry - curve.asof).astype(int)) / 365.0
    var = sigma**2 * (1.0 - np.exp(-2.0 * a * t)) / (2.0 * a)
    x = np.linspace(-8, 8, points) * np.sqrt(var)
    weight = np.exp(-0.5 * x**2 / var) / np.sqrt(2 * np.pi * var)
    one = lambda date: float(np.atleast_1d(curve.df(date))[0])  # noqa: E731
    df_exp = one(expiry)

    def bond(date):
        yrs = float((date - expiry).astype(int)) / 365.0
        bb = (1.0 - np.exp(-a * yrs)) / a
        return one(date) / df_exp * np.exp(-bb * x - 0.5 * bb**2 * var)

    ann, later = np.zeros(points), end
    for k in range(1, MAX_YEARS + 1):
        if later <= start:
            break
        earlier = max(shift_years(end, -k), start)
        ann += float((later - earlier).astype(int)) / 360.0 * bond(later)
        later = earlier
    payoff = np.maximum(bond(start) - bond(end) - strike * ann, 0.0)
    return df_exp * float(np.sum(payoff * weight) * (x[1] - x[0]))


def calibrate(factors: np.ndarray, vols: np.ndarray) -> tuple[int, float, float]:
    """Best column of ``factors`` (one per candidate ``a``) and its sigma, by least squares on volatilities.

    For a fixed ``a`` the model volatility is sigma times the factor, so sigma has a closed form.
    Returns (column index, sigma, root-mean-square error).
    """
    sigma = (factors * vols[:, None]).sum(axis=0) / (factors**2).sum(axis=0)
    err = np.sqrt(((factors * sigma - vols[:, None]) ** 2).mean(axis=0))
    k = int(np.argmin(err))
    return k, float(sigma[k]), float(err[k])
