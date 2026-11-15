"""Monitoring alarms on hand-made data, and file fingerprints."""

import hashlib

import numpy as np
import pandas as pd

from tapemark import governance as gv


def _scores(days=80, per_day=900, gap=0.3, damped=0.1, in_band=0.9, seed=3):
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2026-06-01", periods=days).repeat(per_day)
    n = len(d)
    return pd.DataFrame({"trade_date": d, "scored": True, "gap_bp": rng.normal(0, gap, n), "damped": rng.random(n) < damped, "in_band": rng.random(n) < in_band})


MONTHLY = [{"month": "2026-07", "swaps": 1000, "clean": 300, "package_pct": 60.0, "corrected_pct": 5.0},
           {"month": "2026-08", "swaps": 1000, "clean": 310, "package_pct": 61.0, "corrected_pct": 5.2},
           {"month": "2026-09", "swaps": 900, "clean": 280, "package_pct": 60.0, "corrected_pct": 5.0}]


def test_healthy_data_is_green():
    assert {m["status"] for m in gv.monitoring(_scores(), MONTHLY)} == {"green"}


def test_each_alarm_fires():
    s = _scores()
    s.loc[s["trade_date"] >= s["trade_date"].unique()[-5], "gap_bp"] *= 3          # the miss triples in the last week
    s["damped"] = np.random.default_rng(1).random(len(s)) < 0.4                    # 40% damped
    s = s[~((s["trade_date"] == s["trade_date"].max()) & (s.index % 3 != 0))]       # a thin last day
    bad = [dict(m) for m in MONTHLY]
    bad[1]["corrected_pct"] = 9.0                                                  # a reason share jumps by 80%
    st = {m["signal"].split(",")[0]: m["status"] for m in gv.monitoring(s, bad)}
    assert st["Clean swaps on the latest day"] == "red"
    assert st["Typical miss"] == "red" and st["Share of trades damped"] == "red" and st["Exclusion reasons"] == "red"


def test_band_coverage_off_target_is_red():
    st = {m["signal"].split(",")[0]: m["status"] for m in gv.monitoring(_scores(in_band=0.8), MONTHLY)}
    assert st["Band coverage"] == "red"


def test_fingerprint_matches_hashlib(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"tapemark" * 100000)
    assert gv._sha256(f) == hashlib.sha256(f.read_bytes()).hexdigest()
