# Regression Tests (Merged)

The maintained verification matrix now lives in
[`../05-testing/testing-strategy.md`](../05-testing/testing-strategy.md).

This path remains for older links. Do not use former Authority-only Compose,
unittest-only discovery, historical counts, or file-existence checks as current
evidence. Current gates use pytest, `compose.yml`, non-zero collection checks,
and exact-SHA reporting.

## Runtime Growth Focused Regression

`make runtime-growth-regression` checks write-growth budgets and retained
runtime evidence. It excludes chapter sequence acceptance and provider proof;
those remain separate, slower evidence gates.

## Source Governance Focused Regression

`make source-governance-regression` checks source isolation, leakage preflight,
governed context, and release-gate evidence. It excludes connector execution, chapter acceptance, and provider proof.
