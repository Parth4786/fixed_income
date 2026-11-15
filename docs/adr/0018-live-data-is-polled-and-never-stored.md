# 18. Live data is polled and never stored

Date: 2026-11-15

Status: Accepted

## Context

The public ticker is not a stream. It returns the latest 100 reports and has no history.

## Decision

A background task polls it every 45 seconds, prices new clean dollar swaps against the model, updates the model, and pushes them to browsers. Nothing is written to disk; the nightly fetch brings the complete official file.

## Consequences

A restart loses the day's live view. Stored history is never mixed with unverified live rows.
