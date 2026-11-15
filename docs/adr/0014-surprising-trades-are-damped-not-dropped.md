# 14. Surprising trades are damped, not dropped

Date: 2026-11-15

Status: Accepted

## Context

A few prints are absurd (a 20-year at 9.05% in a 4.15% market). Dropping surprises would also drop the first trade after real news.

## Decision

A trade more than three standard deviations from expectation updates the curve as if it were exactly three away. A genuine move is confirmed by the trades that follow.

## Consequences

Without damping the median miss rises from 0.26 to 0.70 bp and the 95th percentile from 3 to 11.5 bp. With it, about 15% of trades are damped.
