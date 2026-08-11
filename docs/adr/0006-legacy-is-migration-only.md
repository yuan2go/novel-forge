# ADR 0006: Legacy is migration-only

Status: Accepted

## Context

The repository retained an interactive Legacy product runtime alongside PostgreSQL Authority: CLI/API/Celery entry points, workflow and Agent schedulers, production kernels, LocalStorage, duplicate source/MKAOS pipelines, UI, scripts, and compatibility adapters. Production reachability analysis found no current consumers that required this second execution plane.

Historical frozen data still needs a bounded import path.

## Decision

Retain only the offline `novel-forge-migrate` surface: snapshot scan/parser, necessary schemas/codecs/validators/mappers, resumable import status, typed Authority materialization, verification, and quarantine. Classify the entire surface `MIGRATION_ONLY`.

Retire the interactive Legacy runtime and its exclusive dependency, test, configuration, script, UI, and documentation closure. Production roots may not import `legacy_migration`, and the migration CLI may not be registered as an API or worker runtime. Do not add a facade, adapter, fallback, feature flag, or bridge that recreates the retired plane.

The migration-surface manifest and architecture fitness tests enforce the retained and forbidden paths.

## Consequences

- PostgreSQL Authority and the current Command Kernel are the only product runtime.
- Frozen snapshots remain importable with hash, validation, reconciliation, and quarantine evidence.
- Legacy decode success does not imply activation or production readiness.
- New Legacy formats require a migration codec within the existing offline boundary, not a new runtime.
