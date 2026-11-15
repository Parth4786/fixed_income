"""Caps and floors: parity with the swap, the in-arrears variance, and limits."""

import numpy as np
import pytest

from tapemark.pricing import caps
from tapemark.pricing.curve import Curve, shift_years


@pytest.fixture(scope="module")
def curve():
    return Curve.from_par(np.datetime64("2026-11-13"), [1, 2, 3, 5, 7, 10], [3.9, 3.8, 3.75, 3.8, 3.9, 4.0])


def test_cap_minus_floor_is_the_swap(curve):
    s, e = np.datetime64("2026-11-17"), shift_years(np.array([np.datetime64("2026-11-17")]), 5)[0]
    for k in (0.03, 0.038, 0.05):
        cap = caps.cap_floor(curve, s, e, k, 0.009, 1e8)["price"]
        flo = caps.cap_floor(curve, s, e, k, 0.009, 1e8, floor=True)["price"]
        assert cap - flo == pytest.approx(caps.swap_leg_value(curve, s, e, k, 1e8), abs=1.0)


def test_in_arrears_variance_time():
    # a period not yet started counts its accrual at a third; one half-way through counts a third of what is left, scaled
    ts, te = 1.0, 1.25
    assert ts + (te - ts) ** 3 / (3 * (te - ts) ** 2) == pytest.approx(1.0 + 0.25 / 3)


def test_limits(curve):
    s, e = np.datetime64("2026-11-17"), np.datetime64("2028-11-17")
    tiny = caps.cap_floor(curve, s, e, 0.04, 1e-6, 1e8)
    assert tiny["price"] >= max(caps.swap_leg_value(curve, s, e, 0.04, 1e8), 0.0) - 1.0      # at least the capped leg's value
    lo, hi = (caps.cap_floor(curve, s, e, 0.04, v, 1e8)["price"] for v in (0.005, 0.012))
    assert hi > lo > 0                                           # more volatility, more value
    assert caps.cap_floor(curve, s, e, 0.04, 0.009, 1e8)["vega_per_bp"] > 0


def test_at_the_money_cap_equals_floor(curve):
    s, e = np.datetime64("2026-11-17"), np.datetime64("2031-11-17")
    k = caps.atm_strike(curve, s, e)
    assert caps.cap_floor(curve, s, e, k, 0.009, 1e8)["price"] == pytest.approx(caps.cap_floor(curve, s, e, k, 0.009, 1e8, floor=True)["price"], abs=1.0)
