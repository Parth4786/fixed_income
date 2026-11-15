"""Risk numbers: two methods must agree, and the pieces must add up."""

import numpy as np
import pytest

from tapemark.models.curve_filter import NODES, CurveFilter, weights
from tapemark.pricing import risk
from tapemark.pricing.curve import Curve, payer_value, shift_years, spot_start

ASOF = np.datetime64("2026-11-12")
PAR = np.array([3.95, 4.20, 4.63, 4.72, 4.71, 4.69, 4.69, 4.69, 4.75, 4.80, 4.88, 4.91, 4.89, 4.84])
START = spot_start(ASOF)


@pytest.mark.parametrize("years,fixed", [(1, 4.6), (4, 4.2), (7, 4.69), (13, 5.1), (30, 4.84)])
def test_automatic_differentiation_matches_bump_and_rebuild(years, fixed):
    end = shift_years(START, years)
    bump = risk.bucket_dv01_bump(ASOF, NODES, PAR, START, end, fixed, 1e8)
    ad = risk.bucket_dv01_ad(ASOF, NODES, PAR, START, end, fixed, 1e8)
    assert np.allclose(ad, bump, rtol=1e-4, atol=0.5)  # dollars per basis point on 100m


def test_forward_swap_risk_also_matches():
    eff, end = shift_years(START, 5), shift_years(START, 10)
    bump = risk.bucket_dv01_bump(ASOF, NODES, PAR, eff, end, 4.9, 1e8)
    ad = risk.bucket_dv01_ad(ASOF, NODES, PAR, eff, end, 4.9, 1e8)
    assert np.allclose(ad, bump, rtol=1e-4, atol=0.5)
    assert ad[NODES == 5][0] < 0 < ad[NODES == 10][0]  # short the 5-year point, long the 10-year point


def test_ten_year_risk_sits_on_the_ten_year_point():
    dv01 = risk.bucket_dv01_ad(ASOF, NODES, PAR, START, shift_years(START, 10), 4.75, 1e8)
    assert np.argmax(np.abs(dv01)) == list(NODES).index(10)
    assert 70_000 < dv01.sum() < 90_000  # about 8 years of annuity on 100m


def test_value_change_pieces_add_up():
    end = shift_years(START, 7)
    par1 = PAR + np.linspace(0.03, 0.08, len(PAR))
    e = risk.explain(ASOF, PAR, np.datetime64("2026-11-13"), par1, NODES, START, end, 4.69, 1e8)
    assert e["time"] + e["rates"] + e["rest"] == pytest.approx(e["total"], abs=1e-6)
    assert abs(e["rest"]) < 0.02 * abs(e["rates"])  # the straight-line part explains nearly all of it


def test_stress_is_full_repricing():
    end = shift_years(START, 10)
    out = {s["scenario"]: s["change"] for s in risk.stress(ASOF, NODES, PAR, START, end, 4.75, 1e8)}
    direct = payer_value(Curve.from_par(ASOF, NODES, PAR + 0.25), START, end, 4.75, 1e8)[0] - payer_value(Curve.from_par(ASOF, NODES, PAR), START, end, 4.75, 1e8)[0]
    assert out["All rates up 25 bp"] == pytest.approx(direct)
    assert out["All rates up 25 bp"] > 0 > out["All rates down 25 bp"]  # paying fixed gains when rates rise


def test_hedge_weights_conserve_total_risk():
    dv01 = risk.bucket_dv01_ad(ASOF, NODES, PAR, START, shift_years(START, 7), 4.69, 1e8)
    assert risk.hedge_weights(dv01, NODES).sum() == pytest.approx(dv01.sum())


def test_filter_moves_toward_trades_and_gets_more_certain():
    q = np.eye(len(NODES)) * 0.05**2
    f = CurveFilter(PAR.copy(), q * 4, q, noise_sd_pct=0.005)
    before, var_before = f.expect(10.0)
    step = f.update(10.0, before + 0.02)
    after, var_after = f.expect(10.0)
    assert step.gap == pytest.approx(0.02)
    assert before < after < before + 0.02
    assert var_after < var_before


def test_filter_damps_an_absurd_trade():
    q = np.eye(len(NODES)) * 0.02**2
    f = CurveFilter(PAR.copy(), q, q, noise_sd_pct=0.005)
    before, _ = f.expect(20.0)
    step = f.update(20.0, 9.046)  # a real bad print from the data
    after, _ = f.expect(20.0)
    assert step.damped
    assert after - before < 0.25  # moved, but nowhere near the 4+ points the print implied


def test_interpolation_weights():
    assert weights(10.0) == (list(NODES).index(10), list(NODES).index(12), 0.0)
    i, j, w = weights(8.5)
    assert (NODES[i], NODES[j]) == (7, 10) and w == pytest.approx(0.5)
