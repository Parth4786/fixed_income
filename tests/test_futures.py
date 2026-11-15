"""The swap futures engine on small cases worked by hand."""

import numpy as np
import pytest

from tapemark.pricing import eris_futures as ef


def flat(asof, rate):
    asof = np.datetime64(asof, "D")
    return lambda dates: np.exp(-rate * (np.asarray(dates, dtype="datetime64[D]") - asof).astype(int) / 365)


def test_periods_roll_weekend_anniversaries_and_pay_two_business_days_later():
    start, end, pay = ef.periods("2027-12-16", "2030-12-16")
    # 16 Dec 2028 is a Saturday, so that period ends on Monday the 18th and pays on Wednesday the 20th.
    assert str(end[0]) == "2028-12-18" and str(pay[0]) == "2028-12-20"
    assert str(start[1]) == "2028-12-18"
    assert (end - start).astype(int).tolist() == [368, 364, 364]


def test_floating_leg_of_an_unstarted_contract_is_worth_start_minus_end():
    asof, df = "2026-11-13", flat("2026-11-13", 0.04)
    cf = ef.cash_flows(asof, "2026-12-16", "2031-12-16", 0.0, df)
    # Each floating amount is DF(start)/DF(end) - 1; discounted to its own period end the leg telescopes.
    by_hand = 100 * sum(float(df(np.array([s]))[0] / df(np.array([e]))[0] - 1) * float(df(np.array([p]))[0]) for s, e, p in zip(cf["start"], cf["end"], cf["pay"], strict=True))
    assert ef.value(asof, "2026-12-16", "2031-12-16", 0.0, df)["a"] == pytest.approx(-by_hand)


def test_a_fair_coupon_makes_the_value_zero_and_the_price_one_hundred():
    asof, df = "2026-11-13", flat("2026-11-13", 0.04)
    low, high = (ef.value(asof, "2026-12-16", "2036-12-16", c, df)["a"] for c in (0.0, 1.0))
    fair = -low / (high - low)                       # value is a straight line in the coupon
    v = ef.value(asof, "2026-12-16", "2036-12-16", fair, df)
    assert abs(v["a"]) < 1e-9 and v["b"] == 0.0
    assert ef.price(v["a"], v["b"], 0.0) == pytest.approx(100.0)
    assert 3.9 < fair < 4.3                          # 4% continuous is about 4.03% on an Actual/360 yearly basis


def test_fixings_compound_over_weekends():
    fx = ef.Fixings(["2026-11-05", "2026-11-06", "2026-11-09"], [3.60, 3.60, 3.60])
    # Thursday one day, Friday three days, Monday one day.
    assert fx.growth("2026-11-05", "2026-11-10") == pytest.approx((1 + 0.036 / 360) * (1 + 0.036 * 3 / 360) * (1 + 0.036 / 360))
    assert fx.growth("2026-11-10", "2026-11-12") == 1.0


def test_period_under_way_uses_fixings_then_the_curve_and_finished_periods_move_to_b():
    fx = ef.Fixings(np.arange("2025-12-16", "2026-11-13", dtype="datetime64[D]"), np.full(332, 3.6))
    asof, df = "2026-11-13", flat("2026-11-13", 0.04)
    cf = ef.cash_flows(asof, "2024-12-16", "2027-12-16", 2.0, df, fx)
    assert cf["open"].tolist() == [False, True, True]
    done = fx.growth(cf["start"][1], asof)
    assert cf["floating"][1] == pytest.approx(100 * (done / float(df(np.array([cf["end"][1]]))[0]) - 1))
    v = ef.value(asof, "2024-12-16", "2027-12-16", 2.0, df, fx)
    assert v["b"] == pytest.approx(cf["fixed"][0] - cf["floating"][0])


def test_one_day_of_interest_on_margin():
    # The exchange's own row for one contract on 13 Nov 2026: -7.85942 of value, 3.90%, one day.
    assert ef.pai_step(-7.8594195, 3.9, 1) == pytest.approx(-0.0008514371, abs=1e-9)
    assert ef.pai_step(-10.0, 3.6, 3) == pytest.approx(-0.003)


def test_dv01_is_positive_for_the_receiver_and_grows_with_length():
    asof, df = "2026-11-13", flat("2026-11-13", 0.04)
    five = ef.dv01(asof, "2026-12-16", "2031-12-16", 4.0, df)
    ten = ef.dv01(asof, "2026-12-16", "2036-12-16", 4.0, df)
    assert 40 < five < 50 and 75 < ten < 90         # dollars per $100,000 contract


def test_worst_moves_and_margin_years():
    history = np.cumsum(np.full((300, 2), 0.01), axis=0)             # every rate rises 1 bp a day
    assert np.allclose(ef.worst_moves(history, 2, 0.99), [2.0, 2.0])
    assert np.allclose(ef.worst_moves(history, 5, 0.99), [5.0, 5.0])
    # Flat inputs: margin = t * 1e-4 * 20 bp per dollar, falling in a straight line to nothing over ten years.
    today, years = ef.margin_years(10.0, lambda t: t, lambda t: 20.0, lambda t: 1.0)
    assert today == pytest.approx(10 * 1e-4 * 20)
    assert years == pytest.approx(sum((10 - t) * 1e-4 * 20 * 0.25 for t in np.arange(0, 10, 0.25)))


def test_volatility_scaling_follows_recent_volatility_and_never_goes_below_plain_history():
    rng = np.random.default_rng(4)
    steady = np.cumsum(rng.normal(0, 0.05, (900, 2)), axis=0)
    plain = ef.worst_moves(steady, 5, 0.99)
    scaled = ef.worst_moves_scaled(steady, 5, 0.99)
    assert np.all(scaled >= plain - 1e-12) and np.all(scaled < plain * 1.6)       # same volatility throughout: close to plain
    lively = np.cumsum(np.r_[rng.normal(0, 0.05, (800, 2)), rng.normal(0, 0.15, (100, 2))], axis=0)
    assert np.all(ef.worst_moves_scaled(lively, 5, 0.99) > 1.5 * ef.worst_moves(lively[:800], 5, 0.99))   # volatility tripled lately


def test_coverage_backtest_matches_its_target_when_moves_come_from_one_distribution():
    rng = np.random.default_rng(5)
    history = np.cumsum(rng.normal(0, 0.05, (3000, 3)), axis=0)
    ok = ef.coverage(history, 2, 0.99, start=1000)
    assert ok.shape == (3000 - 2 - 1000, 3)
    assert 0.98 < ok.mean() < 0.998                      # close to the 99% it was built for
    # No peeking: changing the future must not change the limit already set. Make every later move enormous.
    shocked = history.copy()
    shocked[2500:] += np.cumsum(np.full((500, 3), 5.0), axis=0)
    assert np.array_equal(ef.coverage(shocked, 2, 0.99, start=1000)[:1400], ok[:1400])


def test_coverage_falls_short_when_the_world_gets_wilder_than_its_history():
    rng = np.random.default_rng(6)
    history = np.cumsum(np.r_[rng.normal(0, 0.03, (1000, 2)), rng.normal(0, 0.12, (300, 2))], axis=0)
    assert ef.coverage(history, 5, 0.99, start=900).mean() < 0.9
