# 12. The curve is a filter updated by every trade

Date: 2026-11-15

Status: Accepted

## Context

Trades arrive one at a time, at irregular moments, each for a different swap length. Taking a median per length ignores that rates of different lengths move together, and gives no measure of confidence.

## Decision

The curve is the state of a Kalman filter: par rates at 14 lengths. Each trade is an observation of a straight-line blend of two neighbouring lengths. The covariance of daily rate changes, estimated from the past only, spreads each trade's information across the curve.

## Consequences

Each prediction is made before its trade is used, so the gap is an out-of-sample error by construction: 0.26 bp median against 0.41 bp for the last trade. The assumption of normal errors is wrong in the tails, which ADR 13 addresses.
