"""Analog weeks on a hand-made series."""

import numpy as np
import pandas as pd

from tapemark import weekly


def test_analogs_find_moves_and_what_followed():
    v = np.zeros(200)
    v[50:55] = np.linspace(2, 10, 5)            # a 10 bp rise by day 54
    v[55:] = 10
    v[70:] = 14                                 # 4 bp more within the next four weeks
    s = pd.Series(v, index=pd.bdate_range("2024-01-01", periods=200))
    a = weekly.analogs(s, move=12.0, floor=5.0)
    assert a["n"] == 1 and a["events"][0]["move"] >= 9
    assert a["events"][0]["next_4w"] == 4.0 and a["share_continued"] == 1.0


def test_no_analog_when_nothing_that_large():
    s = pd.Series(np.random.default_rng(0).normal(0, 0.5, 300).cumsum(), index=pd.bdate_range("2024-01-01", periods=300))
    assert weekly.analogs(s, move=80.0)["n"] == 0
