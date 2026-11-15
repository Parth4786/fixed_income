# 13. Uncertainty bands are calibrated on past errors

Date: 2026-11-15

Status: Accepted

## Context

The filter's own variance assumes normal errors. Real errors have fat tails: 15% fall beyond three standard deviations, and a nominal 90% band held only 70% of trades.

## Decision

The band is the filter's standard deviation times a multiplier equal to the 90th percentile of standardised absolute errors over the previous 5,000 trades (split conformal calibration, past data only).

## Consequences

Coverage is 89.8% against a 90% target and between 88% and 92% in most months. The band is wider than theory says, which is the honest width.
