# 10. Outcomes are summarised by median and tail, not mean

Date: 2026-11-14

Status: Accepted

## Context

A handful of mislabelled trades can sit hundreds of basis points from the market. In a ten-day sample the typical spread inside a five-minute window was about 1 bp while the worst was 287 bp. A mean would describe the mislabelled trades, not the model.

## Decision

Every accuracy figure is reported as the median and the 95th percentile of the absolute error, with the count and the coverage.

## Consequences

Results are robust to bad rows but can hide a small number of large real errors, so the worst cases are also listed and inspected.
