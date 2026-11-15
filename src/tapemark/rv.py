"""Relative value: where the curve is rich or cheap against itself, and whether that has paid before.

1. PCA fair value. On each day, the first three principal components (level,
   slope, curvature) of daily curve changes are estimated from the previous
   250 days only. Today's curve is projected on them around its recent mean;
   what the three factors cannot explain at a point is its residual. A point
   whose rate sits above its fair value is cheap to receive (rich to pay);
   below, rich.
2. PCA-weighted butterflies. Weights on the three legs are chosen so the fly
   does not move with the first two components (level and slope); what is left
   is curvature and noise, the part relative-value desks trade.
3. Each signal gets a z-score against its own past 250 days, a half-life of
   mean reversion from an AR(1) fit, and a backtest: on past days when the
   z-score was beyond 2, how often had the signal moved back toward its mean
   20 days later, and by how much. All of it is computed with data available on
   the day; nothing is fitted on the future.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW = 250


def _pcs(levels: np.ndarray) -> np.ndarray:
    ch = np.diff(levels, axis=0)
    ch = ch[np.abs(ch).max(axis=1) < 0.6]                          # drop broken days (moves over 60 bp at any point)
    val, vec = np.linalg.eigh(np.cov(ch, rowvar=False))
    v = vec[:, np.argsort(val)[::-1][:3]]
    return v * np.sign(v.sum(axis=0))


def residuals(levels: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    """Out-of-sample PCA residual (bp) of each point, each day after the first `window`."""
    x = levels.to_numpy()
    out = np.full(x.shape, np.nan)
    for t in range(window, len(x)):
        past = x[t - window:t]
        v = _pcs(past)
        mu = past.mean(axis=0)
        dev = x[t] - mu
        out[t] = (dev - v @ (v.T @ dev)) * 100
    return pd.DataFrame(out, index=levels.index, columns=levels.columns)


def fly_weights(levels: np.ndarray, legs: tuple[int, int, int]) -> np.ndarray:
    """Weights (wing, belly = -1... normalised to belly 1) neutral to the first two components."""
    v = _pcs(levels)[:, :2]
    a, b, c = legs
    # belly weight 1; solve wings so the fly has no exposure to PC1 and PC2
    m = np.array([[v[a, 0], v[c, 0]], [v[a, 1], v[c, 1]]])
    rhs = -np.array([v[b, 0], v[b, 1]])
    wa, wc = np.linalg.solve(m, rhs)
    return np.array([wa, 1.0, wc])


def half_life(series: pd.Series) -> float | None:
    """Days for a gap to halve, from an AR(1) fit on daily levels; None if it does not mean-revert."""
    s = series.dropna().to_numpy()
    if len(s) < 60:
        return None
    phi = np.polyfit(s[:-1], s[1:], 1)[0]
    return float(np.log(0.5) / np.log(phi)) if 0 < phi < 1 else None


def signal_stats(series: pd.Series, horizon: int = 20, window: int = WINDOW, z_in: float = 2.0) -> dict:
    """Z-score today and a backtest of past extremes: did they revert within `horizon` days?"""
    s = series.dropna()
    mean, sd = s.rolling(window, min_periods=120).mean(), s.rolling(window, min_periods=120).std()
    z = (s - mean) / sd
    ext = z[(z.abs() >= z_in)].index
    hits, moves, last = [], [], None
    pos = {d: i for i, d in enumerate(s.index)}
    for d in ext:
        i = pos[d]
        if i + horizon >= len(s) or (last is not None and i - last < horizon):
            continue                                                 # one event per episode, and only with a known outcome
        toward = -np.sign(z.iloc[i]) * (s.iloc[i + horizon] - s.iloc[i])
        hits.append(toward > 0)
        moves.append(float(toward))
        last = i
    return {"now": float(s.iloc[-1]), "z": float(z.iloc[-1]) if np.isfinite(z.iloc[-1]) else None, "half_life_days": half_life(s.iloc[-window:]),
            "events": len(hits), "reverted_pct": float(np.mean(hits) * 100) if hits else None, "median_reversion_bp": float(np.median(moves)) if moves else None,
            "history": [round(float(v), 2) for v in s.iloc[-120:]]}


def relative_value(levels: pd.DataFrame, labels: list[str]) -> dict:
    """Levels: daily par rates in percent, one column per curve point."""
    res = residuals(levels)
    points = []
    for j, lab in enumerate(labels):
        st = signal_stats(res.iloc[:, j])
        points.append({"length": lab, "residual_bp": round(st["now"], 2), **{k: st[k] for k in ("z", "half_life_days", "events", "reverted_pct", "median_reversion_bp")}})
    x = levels.to_numpy()
    idx = {lab: i for i, lab in enumerate(labels)}
    flies = []
    for name, legs in (("2s5s10s", ("2y", "5y", "10y")), ("5s10s30s", ("5y", "10y", "30y")), ("1s2s5s", ("1y", "2y", "5y"))):
        if not all(leg in idx for leg in legs):
            continue
        li = (idx[legs[0]], idx[legs[1]], idx[legs[2]])
        vals = np.full(len(x), np.nan)
        for t in range(WINDOW, len(x)):                                  # weights from the previous 250 days only
            vals[t] = x[t, list(li)] @ fly_weights(x[t - WINDOW:t], li) * 100
        w = fly_weights(x[-WINDOW:], li)
        series = pd.Series(vals, index=levels.index)                      # bp; belly weight 1
        st = signal_stats(series)
        flies.append({"name": name, "legs": list(legs), "weights": [round(float(v), 3) for v in w], **st})
    return {"points": points, "flies": flies, "window_days": WINDOW, "from": str(pd.Timestamp(levels.index[0]).date()), "to": str(pd.Timestamp(levels.index[-1]).date())}
