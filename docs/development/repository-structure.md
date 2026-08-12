# Repository structure

| Path | Responsibility |
|---|---|
| `src/novel_forge/api/` | FastAPI composition and HTTP routers; no business-state SQL. |
| `src/novel_forge/infrastructure/` | Environment, shared production execution, and database runtime infrastructure. |
| `src/novel_forge/modules/` | Domain and application modules grouped by business authority or stable capability. |
| `src/novel_forge/storage/` | PostgreSQL repositories, UoW, migrations, and object-store implementation. |
| `src/novel_forge/workers/` | Thin worker entry points and scheduler composition. |
| `src/novel_forge/cli/` | Current Authority CLI and offline Legacy migration CLI. |
| `architecture/manifests/` | Machine-checked runtime, worker, migration, test, console, and fitness declarations. |
| `tests/unit/` | Pure/domain and bounded component tests. |
| `tests/architecture/` | Import, reachability, ownership, and structural constraints. |
| `tests/acceptance/` | Fixture-backed vertical behavior and product contracts. |
| `tests/integration/` | External dependency and PostgreSQL integration tests. |
| `web/admin/` | Next.js operator/admin surface and its tests. |
| `skills/` | Repository Skill source of truth; `.claude/skills/` is generated. |
| `docs/` | Current architecture, product, operations, development guidance, and durable ADRs. |

## Dependency direction

```text
pure domain contracts
        ↑
Authority applications / concrete queries
        ↑
API, worker, and Book/Chapter coordinators

infrastructure implementations → explicit ports/contracts
```

Domain files must not import API, storage, provider SDK, HTTP clients, subprocess, or Celery. A composition root may construct concrete infrastructure but must not decide business state.

## Choosing a module boundary

Create a module when it owns a stable business authority, state transition vocabulary, or substantial reusable policy. Do not create a Factory/Registry/Manager/Facade for a single caller solely to reduce file size. Prefer one concrete query or repository with business semantics over a generic CRUD framework.

## Source of truth order

When code and prose disagree, inspect in this order: production composition and runtime, API/CLI/worker entry points, migrations and PostgreSQL repositories, operation definitions, call/import graph, integration/acceptance tests, unit tests, then documentation.
