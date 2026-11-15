"""Bermudan swap options under Hull-White, priced two independent ways: a finite-difference PDE and Monte Carlo.

A Bermudan payer option gives the right, on each yearly reset date, to enter
the remaining swap paying a fixed rate. A European option can be used only on
the first date. The Bermudan is worth at least as much; the difference is the
value of waiting.

Model. Under the risk-neutral measure the short rate is r(t) = x(t) + phi(t),
with dx = -a x dt + sigma dW, x(0) = 0, and phi(t) chosen so every discount
factor of today's curve is reproduced exactly. Two quantities give everything:

    V(t)  = sigma^2 (1 - e^{-2at}) / (2a)                         variance of x(t)
    W(tau) = sigma^2 / a^2 [tau - 2 B(tau) + (1 - e^{-2a tau}) / (2a)]   variance of the integral of x over tau
    B(tau) = (1 - e^{-a tau}) / a

    exp(-integral of phi from 0 to t) = DF(t) exp(-W(t) / 2)
    P(t, T | x) = DF(T) / DF(t) * exp(-B(T-t) x + (W(T-t) - W(T) + W(t)) / 2)

Both follow from x being Gaussian: no approximation enters the bond prices.

1. PDE. The value u(t, x) solves  u_t - a x u_x + sigma^2/2 u_xx - (x + phi) u = 0.
   The phi part depends on time only and is applied exactly between steps; the
   rest is stepped backwards by Crank-Nicolson on a uniform grid in x, with two
   fully implicit half-steps after every exercise date (Rannacher smoothing:
   the payoff's kink otherwise rings in Crank-Nicolson). At each exercise date
   u = max(u, exercise value).

2. Monte Carlo (Longstaff-Schwartz). x and the integral of x are simulated
   exactly, jointly Gaussian, from one exercise date to the next, so there is
   no time-stepping error. The value of continuing is estimated by regressing
   later discounted cash flows on (1, x, x^2, exercise value) over in-the-money
   paths. The regression is fitted on one set of paths and the exercise rule
   applied to a second, independent set, so the estimate is a lower bound
   (an exercise rule that is not optimal can only lose value), with antithetic
   pairs for the standard error.

Check: with only the first date allowed, both must reproduce the European
price from direct integration (hullwhite.exact_payer_price).

Assumptions: one factor, constant a and sigma (the model's calibration of the
day); single curve; exercise on the reset date into the remaining annual fixed
leg, with the same lag between exercise and start as the first date.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import solve_banded

from tapemark.pricing.curve import MAX_YEARS, Curve, shift_years

D = "datetime64[D]"


def _b(a, tau):
    return (1.0 - np.exp(-a * tau)) / a


def _v(a, s, t):
    return s * s * (1.0 - np.exp(-2.0 * a * t)) / (2.0 * a)


def _w(a, s, tau):
    return s * s / (a * a) * (tau - 2.0 * _b(a, tau) + (1.0 - np.exp(-2.0 * a * tau)) / (2.0 * a))


def schedule(expiry, start, end) -> list[dict]:
    """One row per exercise date: the date, the swap's start, and its fixed payment dates with accruals."""
    expiry, start, end = (np.datetime64(x, "D") for x in (expiry, start, end))
    bounds = [end]
    for k in range(1, MAX_YEARS + 1):
        earlier = np.datetime64(max(shift_years(np.array([end]), -k)[0], start), "D")
        bounds.append(earlier)
        if earlier <= start:
            break
    bounds = bounds[::-1]                                   # start, ..., end
    lag = start - expiry
    rows = []
    for k in range(len(bounds) - 1):
        pays = np.array(bounds[k + 1:], dtype=D)
        acc = np.array([(bounds[j + 1] - bounds[j]).astype(int) / 360.0 for j in range(k, len(bounds) - 1)])
        rows.append({"exercise": bounds[k] - lag, "start": bounds[k], "pays": pays, "accrual": acc})
    return rows


class _Model:
    def __init__(self, curve: Curve, a: float, sigma: float):
        self.c, self.a, self.s = curve, a, sigma

    def years(self, d):
        return (np.asarray(d, dtype=D) - self.c.asof).astype(float) / 365.0

    def df(self, d):
        return np.asarray(self.c.df(np.atleast_1d(np.asarray(d, dtype=D))), dtype=float)

    def bond(self, t_date, dates, x):
        """P(t, T | x) for each T in `dates` (rows) and each x (columns)."""
        t = float(self.years(t_date))
        big_t = self.years(dates)
        tau = big_t - t
        a, s = self.a, self.s
        g = 0.5 * (_w(a, s, tau) - _w(a, s, big_t) + _w(a, s, t))
        ratio = self.df(dates) / self.df(t_date)[0]
        return (ratio * np.exp(g))[:, None] * np.exp(-_b(a, tau)[:, None] * np.asarray(x, dtype=float)[None, :])

    def exercise(self, row, x, strike, payer):
        p = self.bond(row["exercise"], np.concatenate([[row["start"]], row["pays"]]), x)
        swap = p[0] - p[-1] - strike * (row["accrual"][:, None] * p[1:]).sum(axis=0)
        return swap if payer else -swap

    def swap_rate(self, row, x):
        p = self.bond(row["exercise"], np.concatenate([[row["start"]], row["pays"]]), x)
        return (p[0] - p[-1]) / (row["accrual"][:, None] * p[1:]).sum(axis=0)

    def deflator(self, t):
        """exp(-integral of phi from 0 to t): the deterministic part of discounting."""
        return self.df(self.c.asof + np.round(np.asarray(t) * 365.0).astype("timedelta64[D]")) * np.exp(-0.5 * _w(self.a, self.s, np.asarray(t)))


def pde_price(curve: Curve, expiry, start, end, strike: float, a: float, sigma: float, payer: bool = True,
              bermudan: bool = True, nx: int = 201, steps_per_year: int = 52, width_sd: float = 7.0) -> dict:
    """Price per unit notional by Crank-Nicolson, and the rate on each date above (payer) which using the right is best."""
    m = _Model(curve, a, sigma)
    rows = schedule(expiry, start, end)
    rows = rows if bermudan else rows[:1]
    ex_days = [int((r["exercise"] - curve.asof).astype(int)) for r in rows]
    last = ex_days[-1]
    half = width_sd * np.sqrt(_v(a, sigma, last / 365.0))
    nx += 1 - nx % 2                                       # odd, so x = 0 is a node
    x = np.linspace(-half, half, nx)
    h = x[1] - x[0]
    n = max(int(np.ceil(last / 365.0 * steps_per_year)), 1)
    days = np.unique(np.concatenate([np.round(np.linspace(0, last, n + 1)), ex_days])).astype(int)
    t = days / 365.0
    defl = m.deflator(t)

    # the operator L u = -a x u_x + sigma^2/2 u_xx - x u, as three diagonals
    lo, di, up = np.zeros(nx), np.zeros(nx), np.zeros(nx)
    conv, diff = -a * x / (2 * h), 0.5 * sigma**2 / h**2
    lo[1:-1], di[1:-1], up[1:-1] = diff - conv[1:-1], -2 * diff - x[1:-1], diff + conv[1:-1]
    di[0], up[0] = a * x[0] / h - x[0], -a * x[0] / h                  # edges: no curvature, one-sided drift
    lo[-1], di[-1] = a * x[-1] / h, -a * x[-1] / h - x[-1]

    def step(u, dt, theta):
        ab = np.zeros((3, nx))
        ab[0, 1:], ab[1], ab[2, :-1] = -theta * dt * up[:-1], 1 - theta * dt * di, -theta * dt * lo[1:]
        lu = di * u
        lu[1:] += lo[1:] * u[:-1]
        lu[:-1] += up[:-1] * u[1:]
        return solve_banded((1, 1), ab, u + (1 - theta) * dt * lu)

    u = np.zeros(nx)
    ex_at = dict(zip(ex_days, rows, strict=True))
    boundary = []
    kink = False
    for i in range(len(days) - 1, -1, -1):
        if days[i] in ex_at:
            row = ex_at[days[i]]
            pay = m.exercise(row, x, strike, payer)
            gain = pay - u                                  # exercise minus continuation
            go = (gain > 0) & (pay > 0)
            if go.any() and not go.all():
                j = int(np.argmax(go)) if payer else int(len(go) - 1 - np.argmax(go[::-1]))
                k = j - 1 if payer else j + 1               # the last node where waiting was better
                xs = x[k] + (x[j] - x[k]) * (-gain[k]) / (gain[j] - gain[k]) if 0 <= k < nx and gain[j] != gain[k] else x[j]
                boundary.append({"date": str(row["exercise"]), "rate_pct": round(float(m.swap_rate(row, np.array([xs]))[0]) * 100, 4)})
            u = np.maximum(u, pay)
            kink = True
        if i == 0:
            break
        dt = t[i] - t[i - 1]
        if kink:
            for _ in range(4):
                u = step(u, dt / 4, 1.0)
            kink = False
        else:
            u = step(u, dt, 0.5)
        u *= defl[i] / defl[i - 1]
    return {"price": float(u[nx // 2]), "dates": len(rows), "grid": nx, "time_steps": int(len(days) - 1), "boundary": boundary[::-1]}


def mc_price(curve: Curve, expiry, start, end, strike: float, a: float, sigma: float, payer: bool = True,
             bermudan: bool = True, paths: int = 20000, seed: int = 7) -> dict:
    """Price per unit notional by Longstaff-Schwartz on exact simulation; fitted on one set of paths, priced on another."""
    m = _Model(curve, a, sigma)
    rows = schedule(expiry, start, end)
    rows = rows if bermudan else rows[:1]
    t = np.array([float(m.years(r["exercise"])) for r in rows])
    dts = np.diff(np.concatenate([[0.0], t]))
    defl = m.deflator(t)
    rng = np.random.default_rng(seed)
    half = paths // 2

    def simulate():
        z = rng.standard_normal((len(t), 2, half))
        z = np.concatenate([z, -z], axis=2)                 # antithetic pairs: path j and j + half
        xs, ints = np.zeros((len(t), paths)), np.zeros((len(t), paths))
        xv, iv = np.zeros(paths), np.zeros(paths)
        for k, dt in enumerate(dts):
            v1, v2 = _v(a, sigma, dt), _w(a, sigma, dt)
            cov = sigma**2 / (2 * a * a) * (1 - np.exp(-a * dt)) ** 2
            l21 = cov / np.sqrt(v1)
            e1 = np.sqrt(v1) * z[k, 0]
            e2 = l21 * z[k, 0] + np.sqrt(max(v2 - l21 * l21, 0.0)) * z[k, 1]
            iv = iv + xv * _b(a, dt) + e2
            xv = xv * np.exp(-a * dt) + e1
            xs[k], ints[k] = xv, iv
        disc = defl[:, None] * np.exp(-ints)                 # time-0 value of one unit paid at each date, per path
        pays = np.array([np.maximum(m.exercise(r, xs[k], strike, payer), 0.0) for k, r in enumerate(rows)]) * disc
        return xs, pays

    def basis(xk, pk):
        return np.column_stack([np.ones_like(xk), xk, xk * xk, pk])

    xa, pa = simulate()                                     # set A: learn when to exercise
    coefs = [None] * len(rows)
    cash = pa[-1].copy()
    for k in range(len(rows) - 2, -1, -1):
        itm = pa[k] > 0
        if itm.sum() > 10:
            beta = np.linalg.lstsq(basis(xa[k, itm], pa[k, itm]), cash[itm], rcond=None)[0]
            coefs[k] = beta
            go = itm.copy()
            go[itm] = pa[k, itm] > basis(xa[k, itm], pa[k, itm]) @ beta
            cash[go] = pa[k, go]
    xb, pb = simulate()                                     # set B: apply that rule to fresh paths
    cash = pb[-1].copy()
    for k in range(len(rows) - 2, -1, -1):
        if coefs[k] is None:
            continue
        itm = pb[k] > 0
        go = itm.copy()
        go[itm] = pb[k, itm] > basis(xb[k, itm], pb[k, itm]) @ coefs[k]
        cash[go] = pb[k, go]
    pair = 0.5 * (cash[:half] + cash[half:])
    return {"price": float(cash.mean()), "stderr": float(pair.std(ddof=1) / np.sqrt(half)), "paths": int(paths), "dates": len(rows)}


def price_all(curve: Curve, expiry, start, end, strike: float, a: float, sigma: float, payer: bool = True, paths: int = 20000) -> dict:
    """European by direct integration, PDE and Monte Carlo; Bermudan by PDE and Monte Carlo."""
    from tapemark.pricing.hullwhite import exact_payer_price

    exact = exact_payer_price(curve, expiry, start, end, strike, a, sigma, points=801)
    if not payer:                                          # receiver = payer - (forward swap value), by parity
        p0 = float(np.atleast_1d(curve.df(np.datetime64(start, "D")))[0])
        rows = schedule(expiry, start, end)
        ann = float((rows[0]["accrual"] * curve.df(rows[0]["pays"])).sum())
        exact = exact - (p0 - float(np.atleast_1d(curve.df(np.datetime64(end, "D")))[0]) - strike * ann)
    eu_pde = pde_price(curve, expiry, start, end, strike, a, sigma, payer, bermudan=False)
    eu_mc = mc_price(curve, expiry, start, end, strike, a, sigma, payer, bermudan=False, paths=paths)
    be_pde = pde_price(curve, expiry, start, end, strike, a, sigma, payer, bermudan=True)
    be_mc = mc_price(curve, expiry, start, end, strike, a, sigma, payer, bermudan=True, paths=paths)
    return {"european": {"exact": exact, "pde": eu_pde["price"], "mc": eu_mc["price"], "mc_stderr": eu_mc["stderr"]},
            "bermudan": {"pde": be_pde["price"], "mc": be_mc["price"], "mc_stderr": be_mc["stderr"], "dates": be_pde["dates"]},
            "boundary": be_pde["boundary"], "grid": be_pde["grid"], "time_steps": be_pde["time_steps"], "paths": paths}


def convergence(curve: Curve, expiry, start, end, strike: float, a: float, sigma: float) -> dict:
    """How the PDE's European error shrinks with the grid, and Monte Carlo's with the number of paths."""
    from tapemark.pricing.hullwhite import exact_payer_price

    exact = exact_payer_price(curve, expiry, start, end, strike, a, sigma, points=1601)
    pde = [{"grid": nx, "steps_per_year": spy, "error": pde_price(curve, expiry, start, end, strike, a, sigma, bermudan=False, nx=nx, steps_per_year=spy)["price"] - exact}
           for nx, spy in ((51, 12), (101, 26), (201, 52), (401, 104))]
    mc = [{"paths": p, **{k: v for k, v in mc_price(curve, expiry, start, end, strike, a, sigma, bermudan=False, paths=p).items() if k in ("price", "stderr")}} for p in (2000, 8000, 32000, 128000)]
    for r in mc:
        r["error"] = r.pop("price") - exact
    return {"exact": exact, "pde": pde, "mc": mc}
