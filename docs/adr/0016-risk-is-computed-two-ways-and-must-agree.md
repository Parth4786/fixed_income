# 16. Risk is computed two ways and must agree

Date: 2026-11-15

Status: Accepted

## Context

Rebuilding the curve once per input is simple and obviously right but slow. Automatic differentiation is fast but easy to get subtly wrong.

## Decision

Both are implemented. A test requires them to agree on spot and forward-starting swaps. The app uses automatic differentiation.

## Consequences

Risk to all 14 curve points takes about 6 ms instead of 64 ms, with a permanent cross-check.
