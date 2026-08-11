# Authority Runtime Convergence Design

**Status:** Approved  
**Baseline:** `449c201b1dd4b9bd939bfe9bd0441926b50c4cce`  
**Branch:** `refactor/authority-runtime-convergence`  
**Date:** 2026-08-12

## Purpose

Converge Novel Forge on one PostgreSQL-authoritative production runtime by
retiring the interactive Legacy product plane, correcting Production Execution
composition ownership, moving Book coordination reads and mutations behind
explicit authority boundaries, and replacing historical documentation with a
small current-code-based documentation system.

This work changes architecture and removes superseded code. It does not add
novel-production capabilities or redesign Command Kernel, Operation/Saga,
Attempt, Lease/Fence, ExternalEffect, RuntimeJob, Canon, ChapterOutcome,
StoryState, planning semantics, or Provider execution.

## Evidence Baseline

The fetched target branch and local checkout both resolved to
`449c201b1dd4b9bd939bfe9bd0441926b50c4cce`. The worktree was clean before the
branch was created.

Baseline validation:

- Authority compile, Ruff ratchet, module/migration/worker/test/console
  manifests, architecture fitness, and head integrity passed.
- `tests/unit tests/architecture tests/acceptance`: 1,758 passed with 16 FastAPI
  `on_event` deprecation warnings.
- Web architecture tests: 11 passed.
- Authority, PostgreSQL-test, and Legacy Compose files parsed successfully.
- Docker was unavailable, so PostgreSQL integration and migration runtime tests
  were not executed at baseline.

Static Authority reachability found no production path to Static Agent profiles,
the old Agent Scheduler, old Workflow/Production Kernel, LocalStorage, the old
Context/Source/MKAOS pipelines, or the Legacy API/worker. The sole apparent path
to `production_execution/legacy.py` came from its package-level export, not a
production call site. Migration Authority does not depend on LocalStorage; it
uses its own snapshot scanner, codecs, validators, mappings, PostgreSQL records,
and verification flow.

The production composition does have a confirmed ownership inversion:
Planning, Reader Outcome, Source Import, Agent execution, and Book production
obtain the shared Production Execution Gateway, object-store adapter, or budget
configuration through `ChapterAuthorityApplication`. Book Supervisor and the
Book coordination worker also issue business-state SQL outside an explicit
query or authority-command boundary.

## Architecture Decisions

### 1. Legacy becomes migration-only

Retain only the bounded offline migration surface:

- immutable PostgreSQL migration history;
- Legacy snapshot schema recognition and scanning;
- codecs, reference parsers, validation, and domain import mappings;
- import, status, verify, and quarantine commands;
- migration-specific unit and PostgreSQL integration tests.

Delete the interactive Legacy product closure, including its CLI, Compose,
FastAPI, Celery, LocalStorage runtime, Workflow, Agent Scheduler, Production
Kernel, Static Agent profiles, local Agent run/message/tool gateway, local
Context/Source/MKAOS pipelines, and exclusive routers, UI, scripts, settings,
dependencies, tests, and documentation.

The normal operator CLI may dispatch an explicit offline migration command, but
the production API, workers, application composition, and Command Kernel must
not import migration-only code. Migration is not a fallback runtime and may not
register API routes, workers, schedulers, model execution, or business state
authority.

Architecture manifests will classify retained migration entrypoints and paths.
Fitness checks will fail if production roots can reach migration-only modules or
if retired runtime paths return.

### 2. Production Execution has independent ownership

A concrete `ProductionExecutionComposition` will own the existing shared
execution infrastructure:

- Provider adapter registry and immutable execution routes;
- Production Execution Gateway external-effect adapter;
- backend registry, recovery store, admission/fence verification, and payload
  resolution;
- object-store write adapter and read port;
- provider cost limit and shared budget caps;
- controlled-environment credential, route, object-store, and release checks.

It is an infrastructure composition object, not a new execution abstraction.
It delegates all execution to the existing PEP, Attempt, ExternalEffect,
Provider, and recovery implementations.

Chapter, Planning, Reader Outcome, Source Import, Agent, and Book become peer
consumers. Chapter retains only Chapter binder/stage policy, Chapter-specific
execution contracts, and its Saga. No peer may obtain shared execution objects
through `ChapterAuthorityApplication.model_port`, Chapter object-store fields,
or Chapter external-effect internals.

Each process composition root constructs shared resources once. Authority API
services share one composition. A bounded worker constructs one composition for
its process and passes explicit dependencies to the application it runs. No
hidden singleton or cross-process sharing is introduced.

### 3. Composition roots remain shallow

Cross-domain construction moves out of `api.authority_dependencies` into the
infrastructure composition boundary. The API module owns HTTP wiring only;
workers own polling, signals, health, and process lifetime only. Domain modules
receive already-constructed ports and authorities.

The change may introduce a small number of concrete builders around stable
resource lifetimes. It must not create interfaces for single implementations,
generic factories, service locators, registries for construction, or pass-through
facades.

### 4. Book coordination uses query and command boundaries

Book Supervisor and the Book worker will not import `AuthorityUnitOfWork` or
execute SQL.

Cross-table coordination reads belong to a concrete PostgreSQL Book production
read projection with methods named for Book decisions rather than tables.
RuntimeJob candidate selection belongs to the Book coordination query boundary.
Read methods may join multiple Authority tables because they are projections,
but they cannot mutate business state.

Book state changes go through existing Book Authority/Command Kernel execution.
CAS, expected version, transaction scope, checkpoint, outbox, trace,
idempotency, and failure semantics remain authoritative. No repository is
created per table and no generic repository framework is introduced.

The same audit will inspect production Supervisors, Schedulers, Workers, and
composition modules for equivalent direct business-state mutations. Only clear
instances of the same boundary violation are in scope.

### 5. Deletion is graph-based

Before deleting a candidate, check imports, entrypoints, Compose services,
workers, routers, registries/reflection, config, migrations, scripts, UI calls,
and tests. Delete the complete exclusive consumer closure and update manifests.
Tests that only characterize a retired product plane are deleted with it;
assertions protecting retained Authority behavior are not weakened.

After each deletion batch, rerun import collection, architecture checks, and
the focused retained tests. A deleted compatibility wrapper must not be replaced
with a differently named wrapper.

### 6. Documentation is reconstructed after code

Final documentation will use these stable areas:

- `docs/architecture/`
- `docs/product/`
- `docs/operations/`
- `docs/development/`
- `docs/adr/`

README remains an entrypoint. Current architecture documents describe runtime
and authority boundaries. Product documents describe the Book-to-Replan and
Source-to-MKAOS flows. Operations documents contain executable startup,
configuration, database, worker, and troubleshooting instructions. Development
documents cover repository structure, tests, capabilities, migrations, and
coding rules.

Historical blueprints, generated audits, completed plans, session reports,
prompts, duplicated current-state claims, and documents contradicted by code are
deleted rather than bulk-archived. A historical item survives only when its
decision remains binding, in which case the decision is compressed into an ADR.

Maturity language must distinguish implemented, runtime-wired, fixture-proven,
integration-proven, real-provider-proven, production-verified, and not-proven.

## Error, Recovery, and Safety Semantics

- Controlled environments remain fail-closed for Provider credentials, route
  identity, release identity, object store, budgets, and migration state.
- Deleting Legacy runtime does not delete source snapshots or PostgreSQL
  migration tables. No user data is mutated by repository cleanup.
- Existing migrations remain immutable. New migration changes are only allowed
  if required by a retained authority contract.
- Book mutations retain current OperationDefinition admission, expected-version
  checks, CAS, transaction checkpoints, outbox evidence, and recovery behavior.
- Production Execution cancellation and recovery continue to use the existing
  gateway and ExternalEffect records.
- A missing Docker daemon or Provider credential produces an explicit unverified
  result; fixture evidence is never promoted to production evidence.

## Verification Strategy

Focused checks run after each independently reviewable batch. Final validation
includes:

- compile and `git diff --check`;
- Ruff and configured static checks;
- module, migration, worker, console, test, and migration-surface manifests;
- architecture fitness, reachability, dependency, and head integrity checks;
- retained unit, architecture, and acceptance suites;
- Web tests and route/API contract checks;
- Compose validation;
- complete PostgreSQL integration and migration runtime validation when Docker
  is available;
- current-SHA evidence capture without claiming real Provider or production
  deployment proof.

## Delivery

Changes are committed as coherent review units: design/plan, Legacy retirement,
fitness and dependency cleanup, Production Execution composition, Book authority
boundary, documentation reconstruction, and final verification fixes. The final
branch is pushed and a Draft PR is created when GitHub access permits. The
worktree must be clean at handoff.
