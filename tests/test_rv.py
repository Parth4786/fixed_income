"""Relative value on hand-made curves: a bump is found, fly weights are level- and slope-neutral."""

import numpy as np
import pandas as pd

from tapemark import rv


def _curves(days=400, seed=2):
    rng = np.random.default_rng(seed)
    t = np.array([1, 2, 3, 5, 7, 10, 15, 20, 30], dtype=float)
    level, slope = rng.normal(0, 0.05, days).cumsum(), rng.normal(0, 0.02, days).cumsum()
    x = 3 + level[:, None] + slope[:, None] * (t / 30)[None, :] + rng.normal(0, 0.003, (days, len(t)))
    return pd.DataFrame(x, index=pd.bdate_range("2023-01-02", periods=days), columns=t)


def test_fly_weights_cancel_level_and_slope():
    lv = _curves()
    w = rv.fly_weights(lv.to_numpy(), (1, 4, 5))
    v = rv._pcs(lv.to_numpy())
    assert abs(w @ v[[1, 4, 5], 0]) < 1e-9 and abs(w @ v[[1, 4, 5], 1]) < 1e-9


def test_a_bump_shows_as_a_residual():
    lv = _curves()
    lv.iloc[-1, 4] += 0.10                                        # the 7-year point 10 bp above the rest of the curve
    res = rv.residuals(lv)
    last = res.iloc[-1]
    assert last.idxmax() == 7.0 and last.max() > 5
