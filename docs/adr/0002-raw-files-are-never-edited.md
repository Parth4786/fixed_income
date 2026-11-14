# 2. Raw files are never edited

Date: 2026-11-14

Status: Accepted

## Context

Cleaning rules change as understanding improves. Both bugs below were fixed by a rebuild, with no re-download.

## Decision

Downloads are stored exactly as received. Everything else is rebuilt from them.

## Consequences

Disk space, about 1.3 GB for two years.
