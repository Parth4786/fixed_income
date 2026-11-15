# 19. A one-factor rate model is kept as a measured negative result

Date: 2026-11-15

Status: Accepted

## Context

Roles on exotic rates desks expect term-structure models. A Hull-White one-factor model was implemented, checked against its exact price, calibrated daily to earlier trades and scored on the same walk-forward test as every other option predictor. It missed by about 16 bp of volatility against 4 for the last similar trade, and its pull-back speed sat at the edge of its allowed range on 61% of days.

## Decision

Keep the model, its test and its score in the project and the app's model comparison, labelled as not used. Do not present it as a pricing recommendation.

## Consequences

The project shows a term-structure model implemented and validated, and shows the judgement not to use a model that loses. Matching the whole surface needs more factors or time-dependent volatility, which is future work.
