# 20. Trade clustering is measured against the hour's usual course

Date: 2026-11-15

Status: Accepted

## Context

A self-exciting (Hawkes) model was fitted to trade timestamps to measure how much trading is a reaction to earlier trading, on mornings with a consumer price or jobs report and on other mornings. The first fit used a baseline that was flat within each hour, plus a single fading jump at 8:30. It gave 0.58 on release days against 0.32 on other days, which reads as trading feeding on itself after a release.

The picture of the data said otherwise. After a release, activity jumps and stays high for most of the hour. A flat baseline cannot represent that, so the model had nowhere to put the extra trades except "triggered by earlier trades". This is a known failure of the method, not a property of the market.

Timestamps are whole seconds, and a package is reported as several legs in the same second.

## Decision

- The baseline follows the average course of the hour across the days in the set, minute by minute, scaled for each morning by that morning's own level.
- The model is written in one-second steps. A second is either active or not, so several legs in one second count once.
- The naive fit is kept and published beside the corrected one.
- Uncertainty comes from refitting with one sixth of the days left out. The model is also scored on later days against a model with no triggering.

## Consequences

Release days score 0.23 (standard error 0.05) and other days 0.30 (0.02): no rise. The published headline is the size of the trap (0.56 naive against 0.23), which is the more useful thing to know.

What the corrected number means is narrower: clustering beyond the usual course of the hour. A release that produced an unusually long burst still leaks into it. Only two release types are in the calendar, so "other days" include days with other data.

A test builds a sequence with no triggering and a burst in the baseline, and requires the naive fit to report triggering and the corrected fit to report none.
