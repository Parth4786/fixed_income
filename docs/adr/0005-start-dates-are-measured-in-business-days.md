# 5. Start dates are measured in business days

Date: 2026-11-14

Status: Accepted

## Context

Standard swaps start two business days after the trade. Counting calendar days excluded every Thursday and Friday trade. Three, not two, absorbs a public holiday until a holiday calendar is added.

## Decision

A swap is "spot" when it starts within three business days of the trade.

## Consequences

A few same-day and next-day starts are grouped with standard ones. Exact dates are used when pricing.
