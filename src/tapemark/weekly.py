"""The week in rates: what moved, what the Fed path now prices, and what followed weeks like this one before.

Analogs. Every past week since October 2020 (Eris SOFR par curves, daily) whose
move in the same measure had the same sign and at least three quarters of this
week's size is an analog; weeks closer than five days to a chosen one are
skipped so one episode is not counted five times. For each, the change over
the next week and the next four weeks is recorded. This is history, not a
forecast: it says how often a move like this kept going, and by how much.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def analogs(series: pd.Series, move: float, min_share: float = 0.75, floor: float = 5.0, gap: int = 5) -> dict:
    """Past 5-day moves like `move` (same sign, at least min_share of its size and `floor` bp), and what came next."""
    s = series.dropna()
    v = s.to_numpy()
    d5 = np.full(len(v), np.nan)
    d5[5:] = v[5:] - v[:-5]
    need = max(abs(move) * min_share, floor)
    out, last = [], -10**9
    for t in range(5, len(v) - 20):                       # leave room for four weeks after
        if np.sign(d5[t]) == np.sign(move) and abs(d5[t]) >= need and t - last >= gap:
            out.append({"day": str(s.index[t].date()), "move": round(float(d5[t]), 1),
                        "next_1w": round(float(v[t + 5] - v[t]), 1), "next_4w": round(float(v[t + 20] - v[t]), 1)})
            last = t
    n4 = np.array([o["next_4w"] for o in out])
    cont = float(np.mean(np.sign(n4) == np.sign(move))) if len(out) else None
    return {"move": round(float(move), 1), "threshold": round(float(need), 1), "events": out, "n": len(out),
            "median_next_4w": round(float(np.median(n4)), 1) if len(out) else None, "share_continued": cont,
            "since": str(s.index[0].date())}
