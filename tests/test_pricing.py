"""Pricing checked three ways: by hand, by identity, and against QuantLib."""

import datetime as dt

import numpy as np
import pytest

from tapemark.pricing import options
from tapemark.pricing.calendar import add_business_days, holidays
from tapemark.pricing.curve import Curve, par_rate, payer_value, shift_years, spot_start

ASOF = np.datetime64("2026-11-12")
TENORS = [1, 2, 3, 5, 7, 10, 15, 20, 30]
RATES = [4.63, 4.72, 4.71, 4.69, 4.69, 4.75, 4.88, 4.91, 4.84]


def test_holidays_match_days_the_real_data_went_quiet():
    # These weekdays had almost no swap trades in the public record.
    quiet = ["2024-11-28", "2024-12-25", "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
             "2025-06-19", "2025-07-04", "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27", "2025-12-25",
             "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
             "2026-09-07", "2026-10-12", "2026-11-11"]
    ours = {d.isoformat() for y in (2024, 2025, 2026) for d in holidays(y)}
    assert set(quiet) <= ours
    in_range = {d for d in ours if "2024-11-13" <= d <= "2026-11-13"}  # the public record starts on 13 Nov 2024 for weekdays
    assert in_range == set(quiet)


def test_spot_start_skips_weekend_and_holiday():
    assert spot_start("2026-11-12") == np.datetime64("2026-11-16")  # Thursday -> Monday
    assert add_business_days(np.datetime64("2026-11-10"), 2) == np.datetime64("2026-11-13")  # Veterans Day between


def test_one_year_swap_by_hand():
    curve = Curve.from_par(ASOF, [1, 2], [5.0, 5.0])
    start = spot_start(ASOF)
    end = shift_years(start, 1)
    days = float((end - start).astype(int))
    by_hand = (curve.df(start) / curve.df(end) - 1.0) * 360.0 / days * 100.0
    assert by_hand == pytest.approx(5.0, abs=1e-10)


def test_bootstrap_reprices_its_inputs():
    curve = Curve.from_par(ASOF, TENORS, RATES)
    start = spot_start(ASOF)
    for tenor, rate in zip(TENORS, RATES, strict=True):
        assert par_rate(curve, start, shift_years(start, tenor))[0] == pytest.approx(rate, abs=1e-9)


def test_swap_at_its_par_rate_is_worth_zero():
    curve = Curve.from_par(ASOF, TENORS, RATES)
    start, end = spot_start(ASOF), shift_years(spot_start(ASOF), 7)
    fair = par_rate(curve, start, end)
    assert payer_value(curve, start, end, fair)[0] == pytest.approx(0.0, abs=1e-14)


def test_forward_swap_is_consistent_with_spot_swaps():
    # Paying fixed 0->10y equals paying 0->5y plus paying 5y->10y, at one common rate.
    curve = Curve.from_par(ASOF, TENORS, RATES)
    s = spot_start(ASOF)
    m5, m10 = shift_years(s, 5), shift_years(s, 10)
    k = 4.7
    whole = payer_value(curve, s, m10, k)[0]
    parts = payer_value(curve, s, m5, k)[0] + payer_value(curve, m5, m10, k)[0]
    assert whole == pytest.approx(parts, abs=1e-12)


def test_matches_quantlib_ois_curve():
    ql = pytest.importorskip("QuantLib")
    today = ql.Date(12, 11, 2026)
    ql.Settings.instance().evaluationDate = today
    index = ql.Sofr()
    helpers = [
        ql.OISRateHelper(2, ql.Period(t, ql.Years), ql.QuoteHandle(ql.SimpleQuote(r / 100)), index,
                         ql.YieldTermStructureHandle(), False, 0, ql.Following, ql.Annual, ql.UnitedStates(ql.UnitedStates.GovernmentBond))
        for t, r in zip(TENORS, RATES, strict=True)
    ]
    ref = ql.PiecewiseLogLinearDiscount(today, helpers, ql.Actual360())
    ref.enableExtrapolation()
    curve = Curve.from_par(ASOF, TENORS, RATES)
    start = spot_start(ASOF)
    # Off-node swaps: neither library was given these rates.
    for years in (4, 6, 8, 12, 25):
        end = shift_years(start, years)
        ours = par_rate(curve, start, end)[0]
        d0 = ql.Date(start.astype(dt.date).day, start.astype(dt.date).month, start.astype(dt.date).year)
        swap = ql.MakeOIS(ql.Period(years, ql.Years), ql.Sofr(ql.YieldTermStructureHandle(ref)), 0.04, effectiveDate=d0,
                          discountingTermStructure=ql.YieldTermStructureHandle(ref), paymentLag=0)
        theirs = swap.fairRate() * 100
        # Different interpolation between input tenors: par-rate straight line here, log discount there.
        assert ours == pytest.approx(theirs, abs=0.02), years


def test_bachelier_put_call_parity_and_limits():
    f, k, t, vol, a = 0.046, 0.037, 1.0, 0.011, 4.2
    payer = options.bachelier(f, k, t, vol, a, True)
    receiver = options.bachelier(f, k, t, vol, a, False)
    assert payer - receiver == pytest.approx(a * (f - k), abs=1e-14)
    assert options.bachelier(f, f, t, vol, a, True) == pytest.approx(a * vol * np.sqrt(t) / np.sqrt(2 * np.pi), rel=1e-12)


def test_implied_vol_round_trip():
    f, t, a = 0.046, 2.0, 8.0
    strikes = np.array([0.026, 0.041, 0.046, 0.051, 0.066])
    vols = np.array([0.0125, 0.0112, 0.0108, 0.0109, 0.0121])
    for payer in (True, False):
        price = options.bachelier(f, strikes, t, vols, a, payer)
        back = options.implied_vol(price, f, strikes, t, a, payer)
        assert np.allclose(back, vols, atol=1e-8)


def test_implied_vol_is_nan_below_intrinsic_value():
    assert np.isnan(options.implied_vol(0.5 * 4.0 * 0.01, 0.05, 0.04, 1.0, 4.0, True))


def test_vega_matches_finite_difference():
    f, k, t, vol, a = 0.046, 0.05, 3.0, 0.01, 6.0
    bump = 1e-6
    fd = (options.bachelier(f, k, t, vol + bump, a) - options.bachelier(f, k, t, vol - bump, a)) / (2 * bump)
    assert options.vega(f, k, t, vol, a) == pytest.approx(fd, rel=1e-6)


def test_sabr_is_flat_without_vol_of_vol_and_tilts_with_rho():
    f, t = 0.046, 1.0
    k = np.array([0.036, 0.046, 0.056])
    assert np.allclose(options.sabr_normal_vol(f, k, t, 0.011, 0.0, 1e-9), 0.011, atol=1e-9)
    tilted = options.sabr_normal_vol(f, k, t, 0.011, -0.5, 0.6)
    assert tilted[0] > tilted[1]  # negative rho: low strikes carry higher volatility


def test_hull_white_closed_form_matches_exact_model_price():
    # The closed-form volatility is an approximation. Check it against the model's
    # exact price, found by integrating over the model's random factor.
    from tapemark.pricing import hullwhite
    from tapemark.pricing.calendar import add_business_days
    from tapemark.pricing.curve import annuity_and_float, shift_months

    curve = Curve.from_par(ASOF, TENORS, RATES)
    for months, years, a, sigma in [(12, 5, 0.03, 0.010), (3, 10, 0.01, 0.012), (60, 10, 0.05, 0.009), (24, 2, 0.02, 0.011)]:
        expiry = shift_months(ASOF, months)
        start = add_business_days(expiry, 2)
        end = shift_years(start, years)
        ann, fl = annuity_and_float(curve, start, end)
        forward = float(fl[0] / ann[0])
        vol = sigma * float(hullwhite.normal_vol_factor(curve, expiry, start, end, a)[0])
        t = float((expiry - ASOF).astype(int)) / 365.0
        approx = float(options.bachelier(forward, forward, t, vol, ann[0], True))
        exact = hullwhite.exact_payer_price(curve, expiry, start, end, forward, a, sigma)
        assert approx == pytest.approx(exact, rel=0.02), (months, years)


def test_hull_white_calibration_recovers_known_parameters():
    from tapemark.pricing import hullwhite

    rng = np.random.default_rng(0)
    factors = np.abs(rng.normal(1.0, 0.3, size=(200, 3)))
    vols = 0.011 * factors[:, 1]
    k, sigma, err = hullwhite.calibrate(factors, vols)
    assert k == 1 and sigma == pytest.approx(0.011) and err < 1e-12



def test_meeting_steps_keep_the_curve_points_and_only_move_after_meetings():
    from tapemark.models import meeting_curve as mc
    asof = "2026-11-13"
    c = Curve.from_par(asof, [0.25, 0.5, 1, 2, 5, 10, 30], [3.95, 3.90, 3.80, 3.70, 3.75, 4.0, 4.3])
    s = mc.stepped(c)
    knots = c.days[(c.days > 0) & (c.days <= 731)]
    when = np.datetime64(asof, "D") + knots.astype("timedelta64[D]")
    assert np.allclose(np.log(s.df(when)), np.log(c.df(when)), atol=1e-12)          # every short-end point is reproduced exactly
    far = np.datetime64("2036-11-13")
    assert abs(float(s.df(np.array([far]))[0]) - float(c.df(np.array([far]))[0])) < 1e-12   # beyond two years nothing changes
    path = mc.overnight_path(c, 1.5)
    steps = [np.datetime64(x["from"]) for x in path[1:]]
    assert all(d - 1 in set(mc.MEETINGS.tolist()) or d - 1 in mc.MEETINGS for d in steps)  # the rate changes only the day after a meeting
    assert 2.5 < path[0]["rate_pct"] < 5.0
