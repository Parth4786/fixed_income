# 25. Bermudan options are priced two ways and anchored to the exact European

Date: 2026-11-15

Status: Accepted

## Context

Callable bonds and cancellable swaps contain an option that can be used on any of several dates. No closed form exists for it, so a numerical engine is needed. A numerical price is only as good as the evidence that it is right. The public record has no Bermudan trades to score against.

## Decision

- Two independent engines on the same model (Hull-White, one factor, centred form): a finite-difference PDE (Crank-Nicolson, Rannacher smoothing after each exercise) and Longstaff-Schwartz Monte Carlo on exact simulation.
- Both are checked where an exact answer exists: with one exercise date they must reproduce direct integration (hullwhite.exact_payer_price). This is run on every calibrated real day, not only in tests.
- Monte Carlo fits its exercise rule on one set of paths and prices on another, so it is a lower bound. The PDE is the reference.
- The model is calibrated to that day's real option trades (the existing Hull-White fit). Because European prices do not identify mean reversion, the Bermudan's sensitivity to it is computed and shown, with the European held fixed.
- The PDE operates on x, not r, and applies the deterministic drift exactly between steps, so the curve is fitted by construction rather than by a numerical theta.

## Consequences

The engine's accuracy is shown on real days (0.022% at worst against exact). Its real limitation is model risk, also shown: an 11% spread across speeds that fit the European equally well. Calibrating to the co-terminal European set with a time-dependent sigma would be the next step and needs the variance formulas generalised. One-factor models make swap rates on different dates move almost together, which understates switch value relative to two-factor models.
