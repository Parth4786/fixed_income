"""The regulatory shocks, VaR and backtest on cases worked by hand."""

import numpy as np
import pytest

from tapemark import treasury as tr
from tapemark.pricing.curve import Curve, par_rate, shift_years


def test_shock_shapes_match_the_standard():
    t = np.array([0.0, 4.0, 1e6])
    assert np.allclose(tr.shift_bp("Parallel up", t), 200)
    assert np.allclose(tr.shift_bp("Short rates up", t), [300, 300 * np.exp(-1), 0])
    assert tr.shift_bp("Steepener", [0.0])[0] == pytest.approx(-0.65 * 300)          # short end down
    assert tr.shift_bp("Steepener", [1e6])[0] == pytest.approx(0.9 * 150)            # long end up
    assert tr.shift_bp("Flattener", [0.0])[0] == pytest.approx(0.8 * 300)
    assert tr.shift_bp("Flattener", [1e6])[0] == pytest.approx(-0.6 * 150)
    assert tr.floor_bp([0, 10, 50, 80]).tolist() == [-150, -120, 0, 0]


def _curve(rate=0.04):
    asof = np.datetime64("2026-11-13")
    dates = asof + np.array([365 * k for k in range(1, 41)]).astype("timedelta64[D]")
    return Curve(asof, dates, np.exp(-rate * np.arange(1, 41) * 365 / 365.0))


def test_parallel_shock_moves_zero_rates_and_respects_the_floor():
    c = _curve(0.04)
    up = tr.shocked(c, "Parallel up")
    assert -np.log(up.df(np.array([c.asof + 3650]))[0]) / 10 == pytest.approx(0.06, abs=1e-9)
    low = _curve(0.005)
    down = tr.shocked(low, "Parallel down")
    z1 = -np.log(down.df(np.array([low.asof + 365]))[0]) * 1e4      # 50 - 200 = -150, floor at 1y is -147: floored
    assert z1 == pytest.approx(-147, abs=1e-6)


def test_a_payer_swap_gains_when_rates_rise_and_loses_when_they_fall():
    c = _curve(0.04)
    eff, mat = c.asof + 2, shift_years(c.asof + 2, 10)
    fair = float(par_rate(c, eff, mat)[0])
    book = [{"effective": eff, "maturity": mat, "rate": fair, "notional": 1e8, "pay_fixed": True}]
    res = {r["scenario"]: r["delta_eve"] for r in tr.supervisory_shocks(c, book)["rows"]}
    assert res["Parallel up"] > 0 > res["Parallel down"]
    assert tr.supervisory_shocks(c, book, tier1=1e7)["worst_share_of_tier1_pct"] > 0


def test_var_es_and_backtest():
    rng = np.random.default_rng(7)
    hist = np.cumsum(rng.normal(0, 0.05, (1500, 3)), axis=0)
    pnl = tr.pnl_history(np.array([1000.0, -500.0, 200.0]), hist)
    assert len(pnl) == 1499
    m = tr.var_es(pnl)
    assert m["es975"] > 0 and m["var99"] > 0
    bt = tr.backtest(pnl)
    assert bt["days"] == 250 and bt["zone"] in ("green", "yellow")    # a stable world should rarely be red


def test_kupiec_and_christoffersen_by_hand():
    from tapemark import treasury as tr

    ok = np.zeros(250, dtype=bool)
    ok[[30, 90, 150]] = True                                    # 3 spread-out breaches in 250 days, about the 2.5 expected
    assert tr.kupiec(ok)["p_value"] > 0.3 and tr.christoffersen(ok)["p_value"] > 0.3
    many = np.zeros(250, dtype=bool)
    many[:15] = True                                            # 15 breaches, all in a row
    assert tr.kupiec(many)["p_value"] < 0.001 and tr.christoffersen(many)["p_value"] < 0.001
