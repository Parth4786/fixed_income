# 17. The frontend has no build step

Date: 2026-11-15

Status: Accepted

## Context

The project must run from a fresh clone with one command. A JavaScript toolchain would add an install step, a lock file and a second runtime.

## Decision

The frontend is plain HTML, CSS and ES modules served by the Python service. Charts are small hand-written SVG functions.

## Consequences

No framework conveniences, and chart features are limited to what was written. In return: one process, no node_modules, and every chart is fully controlled.
