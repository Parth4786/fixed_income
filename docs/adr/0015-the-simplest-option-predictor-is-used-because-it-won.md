# 15. The simplest option predictor is used because it won

Date: 2026-11-15

Status: Accepted

## Context

Five ways of predicting an option trade's volatility were compared out of sample. A smooth surface missed by 11.1 bp; the last similar trade by 4.0 bp. Adding a strike adjustment or anchoring the surface to the last trade did not beat it.

## Decision

The app prices options from the last similar trade when it is at most three days old, and falls back to the surface otherwise.

## Consequences

The surface remains for coverage where nothing has traded. The result is reported as a loss for the more complex model.
