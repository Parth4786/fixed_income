"""The trade-clustering estimator, checked on inputs with a known answer.

The product's numbers come only from real trades. The sequences below are
generated on purpose, with a known amount of triggering, to prove that the
estimator recovers it: a test of the method, not a source of results.
"""

import numpy as np

from tapemark import flow


def test_kernel_state_matches_the_sum_it_stands_for():
    rng = np.random.default_rng(0)
    active = (rng.random(200) < 0.2).astype(float)
    decay = 0.3
    f = np.exp(-decay)
    brute = np.array([sum((1 - f) * f ** (lag - 1) * active[t - lag] for lag in range(1, t + 1)) for t in range(len(active))])
    assert np.allclose(flow.kernel_state(active, decay), brute)


def test_kernel_weights_sum_to_one():
    # One active second long ago should, in total, add exactly one unit of weight.
    active = np.zeros(4000)
    active[0] = 1.0
    assert abs(flow.kernel_state(active, 0.05).sum() - 1.0) < 1e-6


def _generate(k, decay, base, windows, seed):
    rng = np.random.default_rng(seed)
    n = flow.WARM + flow.LENGTH
    f = np.exp(-decay)
    out = np.zeros((windows, 2, n))
    for w in range(windows):
        state = np.zeros(2)
        for t in range(n):
            lam = base + k @ state
            y = (rng.random(2) < 1 - np.exp(-lam)).astype(float)
            out[w, :, t] = y
            state = f * state + (1 - f) * y
    return out


def test_fit_recovers_known_triggering():
    k = np.array([[0.30, 0.10], [0.05, 0.40]])
    active = _generate(k, decay=0.05, base=np.array([0.03, 0.02]), windows=30, seed=1)
    shape = flow.hour_shape(active)
    s = flow._summary(flow.fit(active, shape), active, shape)
    assert abs(s["branching"] - np.max(np.abs(np.linalg.eigvals(k)))) < 0.08
    assert np.allclose(np.array(s["matrix"]), k, atol=0.09)
    assert 0.6 < s["half_life_s"] / (np.log(2) / 0.05) < 1.6


def test_no_triggering_is_reported_as_none():
    active = _generate(np.zeros((2, 2)), decay=0.05, base=np.array([0.05, 0.04]), windows=20, seed=2)
    shape = flow.hour_shape(active)
    assert flow._summary(flow.fit(active, shape), active, shape)["branching"] < 0.05


def test_a_burst_in_the_baseline_is_not_mistaken_for_triggering():
    # No triggering at all, but arrivals triple for ten minutes in every window: the trap the hour-shape removes.
    rng = np.random.default_rng(3)
    n = flow.WARM + flow.LENGTH
    rate = np.full(n, 0.03)
    rate[flow.WARM:flow.WARM + 600] = 0.09
    active = (rng.random((40, 2, n)) < 1 - np.exp(-rate)).astype(float)
    naive = flow._summary(flow.fit(active, flow._flat(active)), active, flow._flat(active))["branching"]
    fixed = flow._summary(flow.fit(active, flow.hour_shape(active)), active, flow.hour_shape(active))["branching"]
    assert naive > 0.15 and fixed < 0.06


def test_release_calendar_is_weekdays_without_duplicates():
    days = flow.CPI_DAYS + flow.JOBS_DAYS
    assert len(set(days)) == len(days)
    assert all(np.datetime64(d).astype("datetime64[D]").astype(int) % 7 not in (2, 3) for d in days)   # 1970-01-01 was a Thursday
