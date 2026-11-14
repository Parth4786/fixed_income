# 4. Corrections are applied before any product filter

Date: 2026-11-14

Status: Accepted

## Context

A correction can reclassify a trade. Filtering first left 53 superseded trades in a ten-day sample.

## Decision

Every correction and cancellation is kept through the lifecycle step, whatever product it names.

## Consequences

Slightly larger staging tables.
