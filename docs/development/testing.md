# Testing and evidence

## Local gates

```bash
make validate
make authority-test
npm --prefix web/admin run lint
npm --prefix web/admin test
make authority-compose-config-check
git diff --check
```

These cover Python compilation, focused zero-diagnostic Ruff, repository Ruff debt ratchet, architecture manifests, architecture fitness, Authority-only composition, HEAD integrity, unit/architecture/acceptance suites, TypeScript checking, web route/component tests, and Compose parsing.

The repository does not currently configure mypy, pyright, or another whole-Python static type checker. Python compilation and Ruff must not be described as a full static type proof. The admin console's `lint` script runs `tsc --noEmit`.

## PostgreSQL gates

```bash
make postgres-authority-test-up
make authority-postgres-test
make authority-query-plan-release
make postgres-authority-test-down
```

The PostgreSQL runner is non-skippable and validates the full migration chain in a temporary database before integration tests. It is the evidence boundary for transaction, constraint, lease/fence, migration, query, and recovery behavior that memory fixtures cannot prove.

## Test placement

- Unit tests cover pure invariants, schema validation, and deterministic policy.
- Architecture tests cover import direction, runtime reachability, retired paths, and composition ownership.
- Acceptance tests exercise a user-visible vertical contract with controlled fixtures.
- Integration tests exercise PostgreSQL, MinIO, providers, or other real dependencies and must name the dependency.

A failing test may be removed only when its production path is proven retired and the obsolete implementation is removed with it. Never weaken an assertion or substitute a fixture to make a production gate green.

## Proof interpretation

| Test result | Permitted claim |
|---|---|
| Pure/unit green | behavior is `implemented` for covered inputs |
| Architecture green | forbidden dependency/reachability patterns were not found |
| Fixture acceptance green | bounded path is `fixture-proven` |
| Non-skippable PostgreSQL green | covered database behavior is `integration-proven` |
| Real provider receipt and assertions | covered call is `real-provider-proven` |
| Operated deployment evidence | named scenario may be `production-verified` |

Do not promote claims across rows. Missing Docker or credentials is `ENVIRONMENT_BLOCKED`, not a pass or product failure.
