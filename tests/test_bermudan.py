"""Bermudan engines: each against the exact European, against each other, and against the bounds any price must respect."""

import numpy as np
import pytest

from tapemark.pricing import bermudan as bm
from tapemark.pricing import hullwhite as hw
from tapemark.pricing.calendar import add_business_days
from tapemark.pricing.curve import Curve, annuity_and_float, shift_months, shift_years

A, SIGMA = 0.03, 0.009


@pytest.fixture(scope="module")
def case():
    d = np.datetime64("2026-11-13")
    c = Curve.from_par(d, [1, 2, 3, 5, 7, 10, 15, 20, 30], [3.7, 3.55, 3.5, 3.55, 3.65, 3.8, 4.0, 4.1, 4.05])
    expiry = shift_months(d, 12)
    start = add_business_days(expiry, 2)
    end = shift_years(start, 10)
    a, f = annuity_and_float(c, start, end)
    return c, expiry, start, end, float(f[0] / a[0])


def test_schedule(case):
    _, expiry, start, end, _ = case
    rows = bm.schedule(expiry, start, end)
    assert len(rows) == 10 and rows[0]["exercise"] == expiry and rows[0]["start"] == start
    assert len(rows[-1]["pays"]) == 1 and rows[-1]["pays"][0] == end


def test_bond_formula(case):
    c, expiry, *_ = case
    m = bm._Model(c, A, SIGMA)
    dates = np.array([expiry + 365, expiry + 3650])
    assert np.allclose(m.bond(c.asof, dates, [0.0])[:, 0], c.df(dates))            # today, the model returns today's curve
    t = float(m.years(expiry))
    tau = m.years(dates) - t
    b = bm._b(A, tau)
    textbook = -0.5 * b**2 * bm._v(A, SIGMA, t) - b * SIGMA**2 / (2 * A * A) * (1 - np.exp(-A * t)) ** 2   # Brigo-Mercurio, in x
    mine = np.log(m.bond(expiry, dates, [0.0])[:, 0] / (c.df(dates) / c.df([expiry])[0]))
    assert np.allclose(mine, textbook, atol=1e-12)


def test_european_pde_and_mc_match_exact(case):
    c, expiry, start, end, k = case
    exact = hw.exact_payer_price(c, expiry, start, end, k, A, SIGMA, points=1601)
    pde = bm.pde_price(c, expiry, start, end, k, A, SIGMA, bermudan=False)["price"]
    mc = bm.mc_price(c, expiry, start, end, k, A, SIGMA, bermudan=False, paths=40000)
    assert pde == pytest.approx(exact, rel=5e-4)
    assert abs(mc["price"] - exact) < 3 * mc["stderr"]


def test_pde_converges(case):
    c, expiry, start, end, k = case
    exact = hw.exact_payer_price(c, expiry, start, end, k, A, SIGMA, points=1601)
    coarse = bm.pde_price(c, expiry, start, end, k, A, SIGMA, bermudan=False, nx=51, steps_per_year=12)["price"]
    fine = bm.pde_price(c, expiry, start, end, k, A, SIGMA, bermudan=False, nx=201, steps_per_year=52)["price"]
    assert abs(fine - exact) < abs(coarse - exact) / 5


def test_bermudan_bounds(case):
    c, expiry, start, end, k = case
    pde = bm.pde_price(c, expiry, start, end, k, A, SIGMA)
    coterminal = max(hw.exact_payer_price(c, r["exercise"], r["start"], end, k, A, SIGMA) for r in bm.schedule(expiry, start, end))
    assert pde["price"] >= coterminal                                              # worth at least the best single date
    mc = bm.mc_price(c, expiry, start, end, k, A, SIGMA, paths=40000)
    assert mc["price"] < pde["price"] + 3 * mc["stderr"]                            # out-of-sample rule: a lower bound
    assert mc["price"] > pde["price"] * 0.98
    rates = [b["rate_pct"] for b in pde["boundary"]]
    assert rates[0] > k * 100 and rates[-1] < rates[0]                              # wait unless well in the money; less so near the end


def test_receiver_by_parity(case):
    c, expiry, start, end, k = case
    out = bm.price_all(c, expiry, start, end, k + 0.002, A, SIGMA, payer=False, paths=4000)
    assert out["european"]["pde"] == pytest.approx(out["european"]["exact"], rel=5e-4)
    assert out["bermudan"]["pde"] >= out["european"]["exact"]
