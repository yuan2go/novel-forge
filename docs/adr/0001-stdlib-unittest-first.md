# ADR 0001: Standard Library Test Runner First

## Status

Superseded on 2026-08-10 by the repository's pytest-first test gate.

## Context

The V5 target architecture prefers pytest, but the current environment does not have pytest installed and this rebuild must not install dependencies.

## Decision

Use Python stdlib `unittest` for Phase 1-7 acceptance. Keep `pyproject.toml` dependency-free and make `make test` run without network access.

## Consequences

This decision was valid for the dependency-free rebuild. It is no longer the
active runner policy because the repository now contains pytest-style tests and a
declared pytest test dependency. Pytest is canonical and continues to execute
existing unittest classes.
