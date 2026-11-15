"""US government securities business days.

Dollar SOFR swaps follow the bond market calendar. A swap starts two business
days after the trade, so the holiday list changes real dates.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

import numpy as np


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    d = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    j, k = c // 4, c % 4
    m = (a + 11 * h) // 319
    r = (2 * e + 2 * j - k - h + m + 32) % 7
    month = (h - m + r + 90) // 25
    day = (h - m + r + month + 19) % 32
    return dt.date(year, month, day)


def holidays(year: int) -> list[dt.date]:
    """Days the US bond market is closed in ``year``."""
    fixed = [dt.date(year, 1, 1), dt.date(year, 7, 4), dt.date(year, 11, 11), dt.date(year, 12, 25)]
    if year >= 2021:
        fixed.append(dt.date(year, 6, 19))
    out = []
    for d in fixed:
        if d.weekday() == 6:  # Sunday -> Monday
            out.append(d + dt.timedelta(days=1))
        elif d.weekday() == 5:  # Saturday -> Friday, except New Year's Day
            if not (d.month == 1 and d.day == 1):
                out.append(d - dt.timedelta(days=1))
        else:
            out.append(d)
    out += [
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Presidents' Day
        _easter(year) - dt.timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
    ]
    return sorted(out)


@lru_cache(maxsize=1)
def _calendar() -> np.busdaycalendar:
    days = [d for y in range(2015, 2100) for d in holidays(y)]
    return np.busdaycalendar(holidays=np.array(days, dtype="datetime64[D]"))


def add_business_days(dates, n: int):
    """Shift date(s) by ``n`` business days. Accepts a date or an array of datetime64[D]."""
    arr = np.asarray(dates, dtype="datetime64[D]")
    return np.busday_offset(arr, n, roll="forward", busdaycal=_calendar())


def is_business_day(dates):
    return np.is_busday(np.asarray(dates, dtype="datetime64[D]"), busdaycal=_calendar())


def business_days_between(start, end):
    return np.busday_count(np.asarray(start, dtype="datetime64[D]"), np.asarray(end, dtype="datetime64[D]"), busdaycal=_calendar())
