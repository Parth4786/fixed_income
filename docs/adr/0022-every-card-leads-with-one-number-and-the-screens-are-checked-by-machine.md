# 22. Every card leads with one number, and the screens are checked by machine

Date: 2026-11-15

Status: Accepted

## Context

The frontend had passed its own author's review several times. An independent review of rendered images of every screen then found fifteen problems the author had not seen. The pattern behind most of them: screens answered with sentences where a number would do, tables were shown where a verdict was wanted, and the same idea had different names, colours and number formats on different screens. Two of the findings were not cosmetic: the Trades screen opened with a table of "not scored" rows, which read as the model failing, and the list of "clean" trades mixed trades a little outside the normal range with trades 150 basis points from fair that were plainly agreed on other terms.

Separately, three defects had reached the screens without any check noticing: charts that stayed blank in a background tab, notes erased by the chart drawn above them, and a headline figure built from two rates of different dates.

## Decision

- Each card states one number, its label and a verdict first. Tables and method notes sit behind a closed "details" element. A chart, where there is one, comes between the two.
- The pricing screen opens with four numbers (fair rate, normal range, your rate against fair, gain per basis point) before any sentence.
- One name per idea across the app: typical miss, last trade, normal range, closing curve. One colour per series: blue for the model, orange for the last trade, grey for everything it is compared with; green and red only for money gained and lost.
- Numbers go through four formatters with fixed decimals and a true minus sign; dates through one.
- A clean trade more than 25 basis points from fair is labelled "off-market terms" and listed apart from "unusual" ones.
- Results that found nothing are gathered in one table, "things that do not predict", instead of a card each.
- `tools/render_screens.py` renders every screen at desktop, phone and dark settings, checks layout and accessibility, records load times, and saves images. It exits with an error if any screen has a problem.

## Consequences

Patterns and Accuracy are roughly a third shorter and can be read from their headlines alone. A reader who wants the evidence opens the details; nothing was removed.

The machine check catches overflow, overlap, blank charts, contrast and missing names. It does not catch a wrong number or a missing note, which is how the two worst defects got through; those were found by looking at the rendered images and by an outside reviewer. Both steps stay in the process.

"Off-market" is a threshold, not a fact: the public record does not say why a trade was far from fair.
