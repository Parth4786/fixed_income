"""The C++ revaluation kernel against the NumPy reference, and the real-book cash flows on a hand case."""

import numpy as np
import pandas as pd
import pytest

from tapemark import fast, treasury


def _case(seed=1):
    rng = np.random.default_rng(seed)
    t = rng.uniform(0.02, 35, 400)
    return t, rng.uniform(1e5, 1e8, 400), np.arange(1.0, 31.0), 4 + 0.03 * np.arange(30), rng.normal(0, 0.1, (60, 30))


def test_numpy_reference_by_hand():
    v = fast.revalue_numpy([2.0, 40.0], [100.0, 50.0], np.arange(1.0, 31.0), np.full(30, 5.0), np.zeros((1, 30)))
    assert v[0] == pytest.approx(100 * np.exp(-0.10) + 50 * np.exp(-0.05 * 40))


@pytest.mark.skipif(not fast.available(), reason="C++ kernel not built (python tools/build_cpp.py)")
def test_cpp_matches_numpy():
    a = _case()
    assert np.allclose(fast.revalue_cpp(*a), fast.revalue_numpy(*a), rtol=0, atol=1e-6)


def test_bond_cash_flows_by_hand():
    h = pd.DataFrame({"securityType": ["NotesBonds", "Bills", "TIPS"], "maturityDate": pd.to_datetime(["2027-11-15", "2027-01-15", "2030-01-15"]),
                      "parValue": [1000.0, 500.0, 300.0], "coupon": [4.0, np.nan, 1.0], "asOfDate": pd.to_datetime(["2026-11-10"] * 3)})
    t, amt, info = treasury.soma_cash_flows(h, "2026-11-10")
    assert sorted(amt.tolist()) == [20.0, 20.0, 500.0, 1020.0]    # coupons 15 Nov 2026 and 15 May 2027, the bill, then coupon and principal
    assert info["securities"] == 2 and info["left_out"] == {"TIPS": 300.0}
