# 11. Coded fields are read without regard to letter case

Date: 2026-11-14

Status: Accepted

## Context

The month-by-month data report showed the share of swaps flagged as part of a package at 0.1% until October 2025 and about 63% from November 2025. The trades had not changed. On 3 November 2025 the public files switched three true/false fields (package, block trade, prime brokerage) from lowercase to uppercase. The code matched only uppercase, so a year of package legs was counted as clean prices. Tests on ten recent days could not have shown this.

## Decision

True/false fields are trimmed and upper-cased before comparison. A test covers each spelling. The report keeps the month-by-month table, because that table is what exposed the break.

## Consequences

A future change in the meaning of a field, not just its spelling, would still pass unnoticed by this rule. The monthly table and the nightly run are the guard for that.
