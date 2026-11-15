"""Discount curve and swap pricing for dollar SOFR swaps.

Conventions used throughout
---------------------------
- Fixed and floating sides both pay yearly, counted Actual/360. A swap of a
  year or less has a single period.
- Payment dates are generated backwards from the maturity date; any short
  period falls at the front.
- One curve both projects the overnight rate and discounts. With that, the
  floating side of a swap from E to M is worth DF(E) - DF(M) per unit, and

      par rate = (DF(E) - DF(M)) / sum_i alpha_i * DF(T_i)

- Between curve dates, ln DF is interpolated in a straight line, so the
  overnight forward rate is constant between dates.

Not modelled: the two-business-day payment delay and business-day adjustment
of each payment date. Tests against an independent library and an outside
curve measure what that costs (well under a tenth of a basis point).
"""

from __future__ import annotations

import numpy as np

from tapemark.pricing.calendar import add_business_days

D = "datetime64[D]"
MAX_YEARS = 51
SHORT_MONTHS = {0.25: 3, 0.5: 6, 0.75: 9}


def shift_years(dates: np.ndarray, years: int) -> np.ndarray:
    """Same day of month, ``years`` earlier or later (29 Feb rolls to 1 Mar)."""
    return shift_months(dates, 12 * years)


def shift_months(dates: np.ndarray, months: int) -> np.ndarray:
    dates = np.asarray(dates, dtype=D)
    month = dates.astype("datetime64[M]")
    day = dates - month.astype(D)
    return (month + np.timedelta64(int(months), "M")).astype(D) + day


class Curve:
    """Discount factors on a set of dates, log-linear in between."""

    def __init__(self, asof, node_dates, node_dfs):
        self.asof = np.datetime64(asof, "D")
        days = (np.asarray(node_dates, dtype=D) - self.asof).astype(float)
        order = np.argsort(days)
        self.days = np.concatenate([[0.0], days[order]])
        self.logdf = np.concatenate([[0.0], np.log(np.asarray(node_dfs, dtype=float)[order])])

    def df(self, dates) -> np.ndarray:
        """Discount factor on each date. Beyond the last node the last forward rate continues."""
        x = (np.asarray(dates, dtype=D) - self.asof).astype(float)
        y = np.interp(x, self.days, self.logdf)
        slope = (self.logdf[-1] - self.logdf[-2]) / (self.days[-1] - self.days[-2])
        y = np.where(x > self.days[-1], self.logdf[-1] + slope * (x - self.days[-1]), y)
        return np.exp(y)

    def zero_rate(self, dates) -> np.ndarray:
        """Continuously compounded rate to each date, Actual/365."""
        x = (np.asarray(dates, dtype=D) - self.asof).astype(float)
        return -np.log(self.df(dates)) / np.maximum(x, 1.0) * 365.0

    @classmethod
    def from_par(cls, asof, tenors_years, par_rates_pct) -> Curve:
        """Bootstrap from spot-starting par swap rates.

        Rates between the given tenors are interpolated in a straight line and
        held flat beyond the last one; then every yearly node has a closed form:

            DF_n = (DF_E - S_n * sum_{i<n} alpha_i DF_i) / (1 + S_n * alpha_n)
        """
        asof = np.datetime64(asof, "D")
        tenors = np.asarray(tenors_years, dtype=float)
        rates = np.asarray(par_rates_pct, dtype=float) / 100.0
        start = add_business_days(asof, 2)
        short = float(np.interp(tenors.min(), tenors, rates))
        df_start = 1.0 / (1.0 + short * float((start - asof).astype(int)) / 360.0)

        dates, dfs = [start], [df_start]
        for tenor, months in SHORT_MONTHS.items():  # single-period swaps under a year
            if tenors.min() <= tenor:
                end = shift_months(start, months)
                s = float(np.interp(tenor, tenors, rates))
                dates.append(end)
                dfs.append(df_start / (1.0 + s * float((end - start).astype(int)) / 360.0))
        annuity, prev = 0.0, start
        for n in range(1, MAX_YEARS):
            end = shift_years(start, n)
            alpha = float((end - prev).astype(int)) / 360.0
            s = float(np.interp(n, tenors, rates))
            df_n = (df_start - s * annuity) / (1.0 + s * alpha)
            annuity += alpha * df_n
            dates.append(end)
            dfs.append(df_n)
            prev = end
        return cls(asof, np.array(dates, dtype=D), np.array(dfs))

    @classmethod
    def from_discount_factors(cls, asof, dates, dfs) -> Curve:
        dates = np.asarray(dates, dtype=D)
        keep = dates > np.datetime64(asof, "D")
        return cls(asof, dates[keep], np.asarray(dfs, dtype=float)[keep])


def annuity_and_float(curve: Curve, effective, maturity) -> tuple[np.ndarray, np.ndarray]:
    """For each swap: (sum of alpha_i * DF(T_i), DF(E) - DF(M)). Vectorised over swaps."""
    eff = np.atleast_1d(np.asarray(effective, dtype=D))
    mat = np.atleast_1d(np.asarray(maturity, dtype=D))
    annuity = np.zeros(len(eff))
    later = mat.copy()  # payment date of the period being added
    for k in range(1, MAX_YEARS + 1):
        earlier = np.maximum(shift_years(mat, -k), eff)  # start of that period
        live = later > eff
        if not live.any():
            break
        alpha = (later - earlier).astype(float) / 360.0
        annuity += np.where(live, alpha * curve.df(later), 0.0)
        later = earlier
    return annuity, curve.df(eff) - curve.df(mat)


def par_rate(curve: Curve, effective, maturity) -> np.ndarray:
    """Fair fixed rate, in percent."""
    annuity, floating = annuity_and_float(curve, effective, maturity)
    return floating / annuity * 100.0


def payer_value(curve: Curve, effective, maturity, fixed_rate_pct, notional=1.0) -> np.ndarray:
    """Value today of paying fixed and receiving the overnight rate."""
    annuity, floating = annuity_and_float(curve, effective, maturity)
    return notional * (floating - np.asarray(fixed_rate_pct, dtype=float) / 100.0 * annuity)


def spot_start(asof):
    """Standard start date for a swap traded on ``asof``."""
    return add_business_days(np.datetime64(asof, "D"), 2)
