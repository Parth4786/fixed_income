# 24. Risk frameworks run on real books, and a C++ kernel does the repricing

Date: 2026-11-15

Status: Accepted

## Context

The bank frameworks for interest rate risk (Basel IRRBB shocks, the EBA outlier test, VaR with a backtest) need a portfolio. A made-up example portfolio would make every number on the screen invented. The project's rule is real data only. Full-repricing VaR is also the one place where speed matters: every cash flow times every historical day.

## Decision

- Two books only: the swaps the user saves, and the Federal Reserve's Treasury holdings as published weekly by the New York Fed. The sample-trades button is removed.
- The Fed book is priced on the Board's published zero-coupon Treasury curve (1 to 30 years). Inflation-protected and floating-rate notes are left out and the amount is shown.
- Shock sizes, formulas and floor come from the EBA's final draft standard on supervisory outlier tests, which restates BCBS 368. Basel recalibrated the sizes in 2024; those values could not be read from the BIS site, so the 2016 sizes are used and the screen says so.
- The inner loop (cash flows × days, linear interpolation and an exponential) is C++ called through ctypes, with a NumPy version kept as the reference. A test requires them to agree; CI builds the kernel.

## Consequences

Everything on Book risk is either the user's own position or published data, and it refreshes when `score` fetches new holdings and curves. The Fed figures are illustrative of the measures, not of the Fed's own risk management: it does not mark holdings to market. The C++ kernel is 2.6-3x faster than NumPy here and uses no large intermediate matrix; NumPy remains the fallback where no compiler exists.
