# 23. The short end steps on Fed meeting dates, and is kept beside the smooth curve

Date: 2026-11-15

Status: Accepted

## Context

Forward-starting swaps shorter than a year were the model's measured weak spot: about 1.1 bp against 0.5 bp for forward swaps overall. The curve model interpolates smoothly between its 3-month, 6-month, 1-year and 2-year points. The overnight rate it stands for does not move smoothly: it changes, if at all, the day after a scheduled Federal Open Market Committee meeting. A short forward swap is a bet on particular meetings, and a smooth curve spreads that bet across the year.

## Decision

- `models/meeting_curve.py` rebuilds the first two years of any curve as an overnight rate that is constant between meeting dates. It reproduces the curve's own discount factor at every short-end point exactly and, among all step paths that do, takes the smoothest (least squared change from one meeting to the next). Beyond two years the curve is unchanged.
- Meeting dates are the Board's published calendar. Nothing is stepped beyond the last published meeting.
- It is scored beside the smooth curve on the same forward swaps, at the same moment, from the same curve points, and compared trading day by trading day.
- It is shown, not substituted: Price a trade lists it as its own row with its own record, and Today shows the overnight rate it implies after each meeting.

## Consequences

On 12,893 forward swaps shorter than a year the typical miss falls from 1.10 to 1.07 bp, better on 56% of 447 days (t 3.1): small and reliable. On swaps one to two years long there is no reliable difference (0.90 against 0.91 bp, t 1.3). Most of the short-end miss is in the curve points themselves, which only move as fast as trades arrive; reshaping between them cannot fix that. A better short end needs a second source of short-end prices, such as SOFR futures settlements.

The meeting path on Today is a reading of the curve, the market's average expectation weighted by risk, not a forecast of decisions.
