# Architecture overview

Novel Forge is a local-first production backend for creating and governing long-form fiction assets. It is an early Novel Operating System runtime: operations are versioned and traceable, business state belongs to named Authorities, model and object-store calls are fenced external effects, and accepted outputs become immutable assets.

It is not a complete autonomous Agent Center, a publishing service, or evidence of sustained long-form production.

The authoritative design progression, qualification lifecycle, and production
admission rules are defined in
[`canonical-overall-design.md`](canonical-overall-design.md).

## Runtime shape

```text
Operator / Admin UI / client
              │
              ▼
       Authority FastAPI
              │ admits commands
              ▼
     Domain Authority applications ─── concrete read projections
              │
       Command Kernel / Saga
              │ creates RuntimeJobs
              ▼
       specialized workers
              │
              ▼
 ProductionExecutionComposition
     ├── governed model gateway
     └── object-store adapter
              │
              ▼
 PostgreSQL Authority + MinIO + configured provider
```

The production roots are `novel_forge.api.authority_app`, the CLI modules in `pyproject.toml`, and the workers listed in `architecture/manifests/worker-manifest.yaml`. The accepted operations are enumerated in `production-entry-manifest.yaml`; undocumented imports do not establish a production entry.

## Stable boundaries

- PostgreSQL is the only production business authority. Memory implementations are fixtures only.
- Domain mutations go through a named Authority application and the Command Kernel when the operation contract requires it.
- Queries are concrete business read projections. They may join authority tables but do not mutate them.
- `ProductionExecutionComposition` owns shared process-level provider and object-store execution infrastructure. Chapter, Planning, Reader, Source, Agent, and Book are peer consumers.
- Chapter owns its 18-node saga, stage policy, binder, and chapter-specific execution contract—not the shared execution plane.
- Agents produce governed candidates; the relevant Domain Authority decides and commits business state.
- Legacy code is migration-only and cannot be imported by production roots.

## Current evidence

| Area | Current repository evidence |
|---|---|
| Authority API, workers, PostgreSQL schema | `implemented`, `runtime-wired`; PostgreSQL test suites exist |
| Command Kernel, Attempt/Lease/Fence, ExternalEffect, RuntimeJob | `implemented`, `runtime-wired`, `fixture-proven`; PostgreSQL integration gates exist |
| Chapter 18-node production saga | `implemented`, `runtime-wired`, `fixture-proven`; integration tests exist |
| Progressive design lifecycle and production admission | `runtime-wired`, `PostgreSQL-fixture-validated`; immutable layer receipts, aggregate Book admission, and dispatch-time freshness checks are exercised by current tests |
| Book coordination, reader/recap, governed replan | `implemented`, `runtime-wired`, `fixture-proven`; selected PostgreSQL tests exist |
| Source import, source governance/intelligence, MKAOS | `implemented`, `runtime-wired`, `fixture-proven`; selected PostgreSQL tests exist |
| Agent candidate execution and capability-pack authority | first production slice is `implemented` and `runtime-wired`; coverage is bounded |
| Admin web console | route and component tests are `fixture-proven`; it is not a complete operator console |
| Real external provider | `not-proven` by the default Compose profile or this documentation |
| Sustained long-form, multi-book scale, external publishing | `not-proven` and outside the current convergence scope |
| Complete autonomous Agent Center | `not-proven` |
| Deployed production operation | `not-proven` |

The API readiness payload deliberately reports `real_provider_proven=false`, `longform_proven=false`, and `production_verified=false`. A healthy fixture stack must not override those facts.
