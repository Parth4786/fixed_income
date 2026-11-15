"""Swap option pricing in the normal (Bachelier) model, and the SABR smile.

The forward swap rate F is assumed to move in absolute steps with volatility
sigma (in rate units per year) until expiry T. With annuity A:

    payer    = A * [(F - K) * N(d) + sigma * sqrt(T) * n(d)]
    receiver = A * [(K - F) * N(-d) + sigma * sqrt(T) * n(d)]
    d        = (F - K) / (sigma * sqrt(T))
    vega     = A * sqrt(T) * n(d)

Rates and strikes are in decimals here (0.045, not 4.5).
"""

from __future__ import annotations

import numpy as np
from scipy.special import ndtr

SQRT_2PI = np.sqrt(2.0 * np.pi)


def _pdf(x):
    return np.exp(-0.5 * x * x) / SQRT_2PI


def bachelier(forward, strike, expiry_years, vol, annuity=1.0, payer=True):
    forward, strike, vol = np.asarray(forward, float), np.asarray(strike, float), np.asarray(vol, float)
    sd = np.maximum(vol * np.sqrt(np.asarray(expiry_years, float)), 1e-12)
    d = (forward - strike) / sd
    sign = np.where(payer, 1.0, -1.0)
    return annuity * (sign * (forward - strike) * ndtr(sign * d) + sd * _pdf(d))


def vega(forward, strike, expiry_years, vol, annuity=1.0):
    """Change in price per unit of volatility. Same for payer and receiver."""
    t = np.asarray(expiry_years, float)
    sd = np.maximum(np.asarray(vol, float) * np.sqrt(t), 1e-12)
    return annuity * np.sqrt(t) * _pdf((np.asarray(forward, float) - strike) / sd)


def implied_vol(price, forward, strike, expiry_years, annuity=1.0, payer=True, lo=1e-5, hi=0.10, steps=60):
    """Volatility that reproduces ``price``. NaN where no volatility can (price below intrinsic value)."""
    price = np.asarray(price, float)
    shape = np.broadcast(price, forward, strike, expiry_years, annuity, payer).shape
    a = np.full(shape, lo)
    b = np.full(shape, hi)
    for _ in range(steps):  # bisection: price rises with volatility
        mid = 0.5 * (a + b)
        too_low = bachelier(forward, strike, expiry_years, mid, annuity, payer) < price
        a = np.where(too_low, mid, a)
        b = np.where(too_low, b, mid)
    out = 0.5 * (a + b)
    floor = bachelier(forward, strike, expiry_years, lo, annuity, payer)
    cap = bachelier(forward, strike, expiry_years, hi, annuity, payer)
    return np.where((price > floor * (1 + 1e-9)) & (price < cap), out, np.nan)


def sabr_normal_vol(forward, strike, expiry_years, alpha, rho, nu):
    """Normal volatility at each strike under SABR with beta = 0 (Hagan et al. 2002).

    alpha is the at-the-money level, rho tilts the smile, nu curves it.
    """
    f, k = np.asarray(forward, float), np.asarray(strike, float)
    t = np.asarray(expiry_years, float)
    zeta = nu * (f - k) / np.maximum(alpha, 1e-12)
    x = np.log((np.sqrt(1.0 - 2.0 * rho * zeta + zeta * zeta) + zeta - rho) / (1.0 - rho))
    ratio = np.where(np.abs(zeta) < 1e-7, 1.0, zeta / np.where(np.abs(x) < 1e-12, 1.0, x))
    return alpha * ratio * (1.0 + (2.0 - 3.0 * rho * rho) / 24.0 * nu * nu * t)
