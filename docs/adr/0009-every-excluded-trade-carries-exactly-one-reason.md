# 9. Every excluded trade carries exactly one reason

Date: 2026-11-14

Status: Accepted

## Context

A single true/false "clean" flag hides why a trade was dropped. Two real errors were found only by looking inside the excluded and included sets: 176 short swaps a day were excluded for a payment schedule that is normal for them, and swaps with embedded early-termination rights were being treated as clean prices.

## Decision

Rules are an ordered list. Each trade records the first rule it fails, or blank. The data report shows the counts as a waterfall that must add up.

## Consequences

Rule order becomes part of the contract: changing it changes the counts. A trade that fails several rules is reported under one only.
