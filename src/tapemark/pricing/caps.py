"""Caps and floors on compounded SOFR, normal model, with the in-arrears variance of Lyashenko and Mercurio.

A cap pays, at the end of each period, max(R - K, 0) times the accrual, where R
is the overnight rate compounded over the period. A floor pays max(K - R, 0).

Because R is only known at the end of its period, its uncertainty keeps growing
through the period. Lyashenko and Mercurio (2019) show that, for a normal model
with volatility sigma, the caplet is priced as an option on the period's simple
forward with an effective variance time

    tau = t_s+ + (t_e - t_s+)^3 / (3 (t_e - t_s)^2),     t_s+ = max(t_s, 0)

so a period that has not started counts its first part fully and its accrual
period at a third; a period already running counts only what is left.

    caplet = alpha * DF(t_e) * Bachelier(F, K, tau, sigma)
    F      = (DF(t_s) / DF(t_e) - 1) / alpha,  alpha = days / 360

Check: cap - floor = the value of paying K against the floating leg, exactly
(sum of alpha * DF(t_e) * (F - K)), for any sigma.

Assumes: one flat normal volatility for every caplet (free data has no cap
volatilities; the app borrows a swap option volatility and says so); single
curve; quarterly periods.
"""

from __future__ import annotations

import numpy as np
from scipy.special import ndtr

from tapemark.pricing import options as opt
from tapemark.pricing.curve import Curve, shift_months

D = "datetime64[D]"


def periods(start, end, months: int = 3) -> list[tuple]:
    start, end = np.datetime64(start, "D"), np.datetime64(end, "D")
    out, a, k = [], start, 1
    while a < end:
        b = min(np.datetime64(shift_months(np.array([start]), months * k)[0], "D"), end)
        out.append((a, b))
        a, k = b, k + 1
    return out


def cap_floor(curve: Curve, start, end, strike: float, vol: float, notional: float = 1.0, floor: bool = False, months: int = 3) -> dict:
    """Price, risk and the caplets of a cap (or floor). Rates and vol as decimals; vol is normal (bp/1e4 a year)."""
    rows, total, vega, delta = [], 0.0, 0.0, 0.0
    for a, b in periods(start, end, months):
        ts, te = (float((x - curve.asof).astype(int)) / 365.0 for x in (a, b))
        alpha = float((b - a).astype(int)) / 360.0
        dfa, dfb = (float(np.atleast_1d(curve.df(np.array([x], dtype=D)))[0]) for x in (a, b))
        fwd = (dfa / dfb - 1.0) / alpha
        t0 = max(ts, 0.0)
        tau = t0 + (te - t0) ** 3 / (3.0 * (te - ts) ** 2)
        ann = alpha * dfb
        v = float(opt.bachelier(fwd, strike, tau, vol, ann, not floor))
        sd = vol * np.sqrt(tau)
        d = (fwd - strike) / sd
        nd = float(np.exp(-0.5 * d * d) / np.sqrt(2 * np.pi))
        vega += ann * np.sqrt(tau) * nd
        cdf = float(ndtr(d))
        delta += ann * (cdf if not floor else cdf - 1.0)
        total += v
        rows.append({"start": str(a), "end": str(b), "forward_pct": round(fwd * 100, 4), "tau_years": round(tau, 4), "value": v * notional})
    return {"price": total * notional, "vega_per_bp": vega * notional * 1e-4, "delta_per_bp": delta * notional * 1e-4, "caplets": rows}


def swap_leg_value(curve: Curve, start, end, strike: float, notional: float = 1.0, months: int = 3) -> float:
    """Value of receiving the compounded rate and paying `strike`, on the same periods: the parity reference."""
    total = 0.0
    for a, b in periods(start, end, months):
        alpha = float((b - a).astype(int)) / 360.0
        dfa, dfb = (float(np.atleast_1d(curve.df(np.array([x], dtype=D)))[0]) for x in (a, b))
        total += alpha * dfb * ((dfa / dfb - 1.0) / alpha - strike)
    return total * notional


def atm_strike(curve: Curve, start, end, months: int = 3) -> float:
    """The strike at which cap and floor are worth the same: the rate of a swap on the cap's own periods."""
    num = den = 0.0
    for a, b in periods(start, end, months):
        alpha = float((b - a).astype(int)) / 360.0
        dfa, dfb = (float(np.atleast_1d(curve.df(np.array([x], dtype=D)))[0]) for x in (a, b))
        num += dfa - dfb
        den += alpha * dfb
    return num / den
