"""Interest rate risk of a book of swaps: the regulatory shocks, historical VaR, and a backtest of that VaR.

The book is whatever the user has saved (the Saved trades screen). Nothing is
invented: the curves are the model's own, and the history is six years of
published daily swap curves.

1. Supervisory shocks (IRRBB). Basel's standard for interest rate risk in the
   banking book (BCBS 368, 2016) and the EBA's technical standard on the
   supervisory outlier tests (final draft RTS, 2022) prescribe six shocks to
   the risk-free curve, sized per currency:

       parallel        dR(t) = +/- P
       short rate      dR(t) = +/- S * exp(-t / 4)
       steepener       dR(t) = -0.65 |S exp(-t/4)| + 0.9 |L (1 - exp(-t/4))|
       flattener       dR(t) = +0.8 |S exp(-t/4)| - 0.6 |L (1 - exp(-t/4))|

   with t in years. For USD, P = 200, S = 300, L = 150 basis points. After the
   shock, rates may not fall below a floor of -150 bp at zero maturity rising
   3 bp a year to 0% at 50 years; a rate already below the floor stays where
   it is. The change in economic value (EVE) is found by repricing every
   trade on each shocked curve. The EBA's outlier test compares the worst loss
   with 15% of Tier 1 capital; capital is an input.

   Source of the sizes, formulas and floor: EBA, Final draft RTS on
   supervisory outlier tests (EBA/RTS/2022/10), Article 3 and Annex I. Basel
   recalibrated the shock sizes in July 2024 (BCBS d578, effective January
   2026); the 2024 values could not be read from the BIS site when this was
   written, so the 2016 sizes are used and labelled as such.

2. Historical VaR. The book's gain per basis point at each curve point,
   times every past daily (or ten-day) change in the published curve, gives a
   distribution of profit and loss. VaR is the loss not exceeded on 99% of
   days; expected shortfall is the average loss beyond the 97.5% point, the
   measure the Basel trading-book rules (FRTB) use. This is a first-order
   (delta) approximation; the shocks above are full revaluations.

3. Backtest. Each day, VaR is set from the previous 250 days only and
   compared with that day's P&L. Over the last 250 test days, Basel's traffic
   light counts the days the loss exceeded VaR: 0-4 green, 5-9 yellow, 10 or
   more red.
"""

from __future__ import annotations

import numpy as np

from tapemark.pricing.curve import Curve, payer_value

# Specified shock sizes in basis points: parallel, short, long (EBA RTS Annex I, from BCBS 368).
SHOCKS = {"USD": (200, 300, 150), "EUR": (200, 250, 100), "GBP": (250, 300, 150), "JPY": (100, 100, 100), "INR": (400, 500, 300)}
SCENARIOS = ("Parallel up", "Parallel down", "Steepener", "Flattener", "Short rates up", "Short rates down")
OUTLIER_SHARE_OF_TIER1 = 0.15


def shift_bp(scenario: str, t_years, ccy: str = "USD") -> np.ndarray:
    p, s, lg = SHOCKS[ccy]
    t = np.asarray(t_years, dtype=float)
    short, long_ = s * np.exp(-t / 4.0), lg * (1.0 - np.exp(-t / 4.0))
    return {
        "Parallel up": np.full_like(t, p), "Parallel down": np.full_like(t, -p),
        "Steepener": -0.65 * np.abs(short) + 0.9 * np.abs(long_), "Flattener": 0.8 * np.abs(short) - 0.6 * np.abs(long_),
        "Short rates up": short, "Short rates down": -short,
    }[scenario]


def floor_bp(t_years) -> np.ndarray:
    return np.minimum(-150.0 + 3.0 * np.asarray(t_years, dtype=float), 0.0)


def shocked(curve: Curve, scenario: str, ccy: str = "USD") -> Curve:
    """The curve with every zero rate shifted by the scenario, subject to the floor."""
    days = curve.days[1:]
    t = days / 365.0
    zero = -curve.logdf[1:] / t * 1e4                                       # basis points, continuously compounded
    new = zero + shift_bp(scenario, t, ccy)
    new = np.maximum(new, np.minimum(zero, floor_bp(t)))                    # not below the floor, unless already below it
    return Curve(curve.asof, curve.asof + days.astype("timedelta64[D]"), np.exp(-new / 1e4 * t))


def book_value(curve: Curve, book: list[dict]) -> float:
    """Sum of trade values; each trade: effective, maturity, rate (%), notional, pay_fixed."""
    return float(sum((1 if b["pay_fixed"] else -1) * payer_value(curve, b["effective"], b["maturity"], b["rate"], b["notional"])[0] for b in book))


def supervisory_shocks(curve: Curve, book: list[dict], ccy: str = "USD", tier1: float | None = None) -> dict:
    base = book_value(curve, book)
    rows = []
    for sc in SCENARIOS:
        delta = book_value(shocked(curve, sc, ccy), book) - base
        rows.append({"scenario": sc, "delta_eve": delta, "shift_bp": {f"{t}y": round(float(shift_bp(sc, [t], ccy)[0]), 1) for t in (1, 2, 5, 10, 30)}})
    worst = min(rows, key=lambda r: r["delta_eve"])
    out = {"currency": ccy, "sizes_bp": dict(zip(("parallel", "short", "long"), SHOCKS[ccy], strict=True)), "base_value": base, "rows": rows,
           "worst": {"scenario": worst["scenario"], "delta_eve": worst["delta_eve"]}}
    if tier1:
        out["tier1"] = tier1
        out["worst_share_of_tier1_pct"] = round(100 * -min(worst["delta_eve"], 0.0) / tier1, 2)
        out["outlier"] = -worst["delta_eve"] > OUTLIER_SHARE_OF_TIER1 * tier1
    return out


def pnl_history(dv01: np.ndarray, history_pct: np.ndarray, horizon: int = 1) -> np.ndarray:
    """P&L of the book for each past window: gain per bp at each point times the change in bp there."""
    change_bp = (history_pct[horizon:] - history_pct[:-horizon]) * 100.0
    return change_bp @ dv01


def var_es(pnl: np.ndarray) -> dict:
    q99, q975 = np.quantile(pnl, 0.01), np.quantile(pnl, 0.025)
    return {"var99": float(-q99), "es975": float(-pnl[pnl <= q975].mean())}


def kupiec(breaches: np.ndarray, p: float = 0.01) -> dict:
    """Kupiec (1995) proportion-of-failures test: is the breach rate p? Likelihood ratio, chi-squared with 1 degree."""
    from scipy.special import xlogy
    from scipy.stats import chi2

    t, x = len(breaches), int(np.sum(breaches))
    q = x / t if t else 0.0
    lr = -2 * (xlogy(t - x, 1 - p) + xlogy(x, p) - xlogy(t - x, 1 - q) - xlogy(x, q))
    return {"lr": float(lr), "p_value": float(chi2.sf(lr, 1))}


def christoffersen(breaches: np.ndarray) -> dict:
    """Christoffersen (1998) independence test: does a breach today make one tomorrow more likely?"""
    from scipy.special import xlogy
    from scipy.stats import chi2

    b = np.asarray(breaches, dtype=int)
    prev, nxt = b[:-1], b[1:]
    n00, n01 = int(np.sum((prev == 0) & (nxt == 0))), int(np.sum((prev == 0) & (nxt == 1)))
    n10, n11 = int(np.sum((prev == 1) & (nxt == 0))), int(np.sum((prev == 1) & (nxt == 1)))
    p01 = n01 / (n00 + n01) if n00 + n01 else 0.0
    p11 = n11 / (n10 + n11) if n10 + n11 else 0.0
    p = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)
    lr = -2 * (xlogy(n00 + n10, 1 - p) + xlogy(n01 + n11, p) - xlogy(n00, 1 - p01) - xlogy(n01, p01) - xlogy(n10, 1 - p11) - xlogy(n11, p11))
    return {"lr": float(lr), "p_value": float(chi2.sf(lr, 1)), "back_to_back": n11}


def backtest(pnl: np.ndarray, window: int = 250, test_days: int = 250) -> dict:
    """VaR from the previous `window` days only, against each of the last `test_days` days.

    Reported three ways: Basel's traffic light (count of exceptions), Kupiec's test of the exception rate,
    and Christoffersen's test that exceptions do not cluster. A p-value below 0.05 rejects the model.
    """
    start = max(window, len(pnl) - test_days)
    limits = np.array([-np.quantile(pnl[t - window:t], 0.01) for t in range(start, len(pnl))])
    breaches = pnl[start:] < -limits
    n = int(breaches.sum())
    return {"days": int(len(limits)), "exceptions": n, "expected": round(0.01 * len(limits), 1), "zone": "green" if n <= 4 else "yellow" if n <= 9 else "red",
            "kupiec": kupiec(breaches), "christoffersen": christoffersen(breaches)}


# ---------------------------------------------------------------------------------------------------------------
# A real book: the Federal Reserve's Treasury portfolio (System Open Market Account), priced on the Fed's own
# fitted Treasury curve. Holdings are published weekly by the New York Fed and the curve daily by the Board;
# both refresh with `python -m tapemark score`. Nothing here is a sample.

def soma_cash_flows(holdings, curve_day) -> tuple[np.ndarray, np.ndarray, dict]:
    """Remaining cash flows of nominal bills, notes and bonds: times in years from `curve_day`, amounts in dollars.

    Notes and bonds pay half their coupon every six months, on the maturity date and every six months before it.
    TIPS (principal indexed to inflation) and floating-rate notes are left out and counted.
    """
    import pandas as pd

    day = pd.Timestamp(curve_day)
    t, amt = [], []
    kept = holdings[holdings["securityType"].isin(["Bills", "NotesBonds"]) & (holdings["maturityDate"] > day)]
    for r in kept.itertuples():
        if r.securityType == "Bills" or not (r.coupon > 0):
            t.append((r.maturityDate - day).days / 365.25)
            amt.append(r.parValue)
            continue
        k, coupon = 0, r.parValue * r.coupon / 100 / 2
        while True:
            pay = r.maturityDate - pd.DateOffset(months=6 * k)
            if pay <= day:
                break
            t.append((pay - day).days / 365.25)
            amt.append(coupon + (r.parValue if k == 0 else 0.0))
            k += 1
    left = holdings[~holdings.index.isin(kept.index)]
    info = {"securities": int(len(kept)), "par": float(kept["parValue"].sum()), "left_out": {str(k): float(v) for k, v in left.groupby("securityType")["parValue"].sum().items()}}
    return np.array(t), np.array(amt), info


def soma_risk(holdings, zero_curve, horizon_days: int = 1500) -> dict:
    """The Fed's Treasury book under the six supervisory shocks, and its historical VaR by full repricing."""
    from tapemark import fast

    grid = np.arange(1.0, 31.0)
    hist = zero_curve[zero_curve.index <= holdings["asOfDate"].max()].tail(horizon_days + 10)
    day = hist.index[-1]
    base = hist.iloc[-1].values
    t, amt, info = soma_cash_flows(holdings, day)
    value = float(fast.revalue(t, amt, grid, base, np.zeros((1, 30)))[0])
    dv01 = float(fast.revalue(t, amt, grid, base, np.full((1, 30), 0.01))[0]) - value
    shocks = []
    for sc in SCENARIOS:
        moved = np.maximum(base + shift_bp(sc, grid) / 100.0, np.minimum(base, floor_bp(grid) / 100.0))
        shocks.append({"scenario": sc, "delta_eve": float(fast.revalue(t, amt, grid, base, (moved - base)[None, :])[0]) - value})
    z = hist.values
    out = {"holdings_day": str(holdings["asOfDate"].max().date()), "curve_day": str(day.date()), **info, "value": value, "dv01": dv01,
           "duration_years": round(-dv01 / value * 1e4, 2), "irrbb": {"rows": shocks, "worst": min(shocks, key=lambda r: r["delta_eve"])},
           "engine": "C++" if fast.available() else "NumPy"}
    for h, key in ((1, "one_day"), (10, "ten_day")):
        moves = z[h:] - z[:-h]
        pnl = fast.revalue(t, amt, grid, base, moves) - value
        out[key] = var_es(pnl) | {"days": int(len(pnl))}
        if h == 1:
            out["backtest"] = backtest(pnl)
            out["from"] = str(hist.index[0].date())
            out["benchmark"] = fast.benchmark(t, amt, grid, base, moves, repeat=2)
    return out
