# 3. Files and Parquet, no database server

Date: 2026-11-14

Status: Accepted

## Context

The project must run from a fresh clone on any machine. Data volume is tens of thousands of rows a day.

## Decision

Parquet files on disk, read with pandas.

## Consequences

No concurrent writers. Acceptable for a daily batch tool.
