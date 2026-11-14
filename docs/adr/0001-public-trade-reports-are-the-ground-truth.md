# 1. Public trade reports are the ground truth

Date: 2026-11-14

Status: Accepted

## Context

Daily rate tables are already smoothed by someone else's model. Trades are what people actually paid.

## Decision

Models are judged against individual reported trades, not against published daily rates.

## Consequences

The data is messy. Most of the engineering is cleaning.
