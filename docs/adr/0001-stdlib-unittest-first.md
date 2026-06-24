# ADR 0001: Standard Library Test Runner First

## Status

Accepted.

## Context

The V5 target architecture prefers pytest, but the current environment does not have pytest installed and this rebuild must not install dependencies.

## Decision

Use Python stdlib `unittest` for Phase 1-7 acceptance. Keep `pyproject.toml` dependency-free and make `make test` run without network access.

## Consequences

The suite is immediately runnable. Pytest can be added later through a dependency ADR.
