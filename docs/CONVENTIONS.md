# Product quirks and how the project treats them

Fixed income products come with rules that are easy to get wrong and that
change the price. This is the checklist of the ones that matter here, with an
honest status for each. A quirk marked "open" is a known gap, not an oversight
to be discovered later.

Status: **handled** (in code, tested) · **planned** (stage named) · **open** (known, not yet scheduled)

## Dollar SOFR swaps

| Quirk | Why it matters | Status |
|---|---|---|
| Starts two business days after the trade | Counting calendar days mislabels Thursday and Friday trades | Handled |
| Public holidays shift the start date | Needs a holiday calendar; three business days is allowed meanwhile | Open: no calendar yet |
| Swaps of a year or less pay once, at the end | They looked "non-standard" and 176 a day were wrongly excluded | Handled |
| Longer swaps pay yearly on both sides, Actual/360 | Any other schedule changes the rate | Handled |
| Early-termination rights embedded in the swap | The fixed rate includes the value of the right. The worst 10-year outlier on 12 Nov 2026 was one of these | Handled |
| Trade flagged by the reporter as non-standard | Unknown special terms | Handled |
| Spread added to the floating side | The fixed rate is offset by the spread | Handled |
| Side payment at the start | Fixed rate is deliberately off-market | Handled |
| Part of a package (curve trade, swap against a bond) | Each leg's rate reflects the bundle's price | Handled: excluded from clean set; to be studied in its own right |
| Starts in the future, or on a central bank meeting date | It is a forward rate, not today's rate | Handled: labelled; priced as forwards from stage 2 |
| Start date before the trade date | An old agreement being re-reported | Handled |
| Size capped in the public record | True size unknown for large trades | Handled: flagged |
| Large trades are published late | The print appears after the market moved | Handled: `known_date` kept; delay effect to be measured |
| Corrections and cancellations | Without them trades are wrong or double-counted | Handled |
| Compressions and novations reported as new | Not new prices | Handled |
| Uncleared swaps | Different collateral can mean a different rate | Kept and flagged (`cleared`); effect to be measured in stage 3 |
| Size that changes over the swap's life | Not comparable with a fixed-size swap | Open: column not yet loaded; about 3 a day |
| Floating side paying more often than yearly | Changes timing of cash | Open: column not yet loaded; about 3 a day |
| Payment made two business days after the period ends | Shifts discounting slightly | Planned, stage 1 |
| Overnight rate compounded daily, weekends weighted | The floating payment formula | Planned, stage 1 |
| Lookback and lockout variants | Different fixings are used | Open: not visible in public data |
| Month-end roll rules and odd first or last periods | Payment dates differ | Planned, stage 1 |
| Which clearing house | Small price differences between them | Open: not in public data |
| Who paid and who received fixed | Direction of flow | Open: not in public data |
| Fed funds swaps and term-rate swaps look similar | Different underlying rate | Handled: only SOFR overnight swaps selected |
| Swaps longer than a whole number of years | 76 of 848 clean swaps on one day | Handled in cleaning; exact dates used at pricing |

## Swap options

| Quirk | Why it matters | Status |
|---|---|---|
| "Call" and "put" labels do not say pay-fixed or receive-fixed | Wrong side gives the wrong price | Planned, stage 4: settled by price checks |
| Two-thirds trade inside packages such as straddles | The premium may belong to the bundle | Handled: flagged; standalone scored separately |
| Premium of zero or blank | Price sits on another leg | Handled |
| Premium paid at trade or at expiry | Changes discounting of the premium | Open: must be established from the data |
| Units of strike and premium | A unit error can still look plausible | Planned, stage 4: bounds and cross-checks |
| Settled in cash or by entering the swap | Changes the valuation formula slightly | Open |
| Early-exercise styles | Need a different model | Handled: only European selected |
| Underlying swap starts two business days after expiry | Dates of the swap being optioned | Planned, stage 4 |
| Volatility differs by strike | One number per option is not enough | Planned, stage 4 |
| About 48 standalone trades a day | Too few to fill a full grid daily | Handled in method: pooling stated, uncertainty shown |

## Curves

| Quirk | Why it matters | Status |
|---|---|---|
| Central bank meeting dates | The overnight rate steps on those dates, it does not glide | Planned, stage 2 |
| Month-end, quarter-end and year-end funding pressure | Overnight rates jump on those days | Open |
| Choice of interpolation | Changes forward rates between known points | Planned, stage 2: compared by out-of-sample error |
| Inputs from different times of day | A curve mixes stale and fresh prices | Planned: curve built as of a timestamp |
| The outside curve is a model too | It can be wrong in the same way | Handled in method: second referee |

## Bonds

Government bonds are taught in the lessons because every later idea builds on
them, but no bond data is in the project. The quirks below are therefore
lesson material, not code: interest accrued between coupon dates, half-yearly
coupons, prices quoted in 32nds, settlement one business day after trade,
newly issued versus older bonds, and bills quoted on a discount basis.

## What the public data cannot tell us

No identities, no direction of trade, no clearing house, no exact size above
the cap, and no quotes, only completed trades. Every conclusion is limited by
that, and reports say so.
