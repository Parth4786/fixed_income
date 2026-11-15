# 21. The futures engine and the margin rule are checked against what the exchange publishes

Date: 2026-11-15

Status: Accepted

## Context

Eris SOFR swap futures copy the cash flows of a swap and are quoted as `100 + A + B - C`: value to come, amounts already paid, and interest on daily margin payments. The exchange publishes all three parts, the risk and the margin for every listed contract each day, and a file of every cash flow. That makes a pricing engine checkable to the cent, which no other part of this project's data allows.

A comparison of margin cost between a cleared swap and the equivalent future needs a margin model. Clearing houses do not publish theirs. A model taken from memory or from marketing material would be an unverified assumption sitting in a pricing tool.

## Decision

- The cash-flow conventions were read off the exchange's cash-flow file, written into the engine, and then tested against the published values on every contract for 60 days.
- Amounts already paid are rebuilt from New York Fed SOFR fixings, an independent source, instead of being copied from the file. Contracts that began on LIBOR are excluded from that one check, with the count published.
- The margin rule is `DV01 x (the move not exceeded on q of past h-day windows)` on six years of daily curves. Sixteen combinations of h and q are scored against the published margins, and the best one is used for futures. The swap side uses the same rule at five days, the minimum US rules set for cleared swaps.
- The funding spread is an input the user types. It is not estimated.
- The funding cost is computed with the curve held still and the trade shortening over time. No scenarios are generated.

## Consequences

Value to come matches within $0.27 a contract at worst and risk within 0.1%. The best margin rule is two days at 99%, which is the close-out period the exchange states and the confidence floor in the regulation; it fits the typical contract within 12.5%.

The swap side has no published per-trade number to check against. Its low end follows what is public about the clearing house's model: five days, at least 99%, past moves rescaled to current volatility and paired with unscaled moves. On this history that gives 1.5 times the futures margin, the same as plain history today because current volatility is close to its six-year norm. The same rescaling was tried on futures, where there are published margins to judge it by, and fitted no better (13.6% typical miss against 12.5%).

Both rules are then tested the way a margin model is meant to be tested: for each of 1,025 days after the first 500, the margin set from the past alone is compared with the move over the following days. The futures rule covered 99.13% and the swap rule 99.44%, against the regulatory standard of 99%. The weakest year was 2022 (98.89%), when rates moved more than anything in the earlier history. The exchange's own material says futures margin is "up to 65% lower" than swaps, a wider gap than this rule gives. That is a marketing statement with no published method behind it, so it is quoted on the screen as context and used in no calculation.

The same exchange files include settled options on the futures. The normal-model option pricer reproduces all 89,014 settled prices within one price step. The project's own volatility grid, built from public swap-option premiums, sits within about 7 bp of the exchange's level at short option lives, but its daily changes do not follow the exchange's. That is recorded on the Accuracy screen as a limit of the grid.

This is one trade on its own. A real margin calculation nets a whole portfolio, and a real funding-cost calculation simulates the margin forward. Both are out of scope and said so on the screen.

The anonymous Eris file server closes on 1 January 2027; the files used are archived locally by the fetch step.
