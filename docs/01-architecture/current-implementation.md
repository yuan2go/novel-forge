# Current Implementation Architecture

Updated: 2026-08-11

This document describes runtime-reachable code, not the product blueprint.

## Runtime topology

```text
Authority API
  → Authority applications / queries
  → Domain Authorities
  → Command Kernel
  → PostgreSQL

Authority Workers
  → shared composition functions
  → Domain scheduler/coordinator
  → Production Execution Gateway
  → Provider adapter/backend
  → validation
  → PostgreSQL Authority commit

Object Store
  ← blobs referenced by committed PostgreSQL manifests
```

`compose.yml` deploys PostgreSQL, MinIO, migrations, the Authority API, and
Chapter, Agent, Content, Source, MKAOS, Book, Outbox, and Maintenance workers.
The deleted `compose.authority-only.yml` was a stale duplicate. The isolated
development compatibility topology remains `compose.legacy.yml`.

## Canonical composition roots

| Composition | Path | Consumers |
|---|---|---|
| Authority API | `api/authority_app.py:create_authority_app` | API process |
| Book production | `api/authority_dependencies.py:build_book_production_composition` | Authority API and Book Worker |
| Chapter production | `api/authority_dependencies.py:build_chapter_authority_application` | Book/Chapter/Planning/Reader/Agent composition |
| Provider adapters | `modules/provider_control/composition.py:build_provider_adapter_registry` | API and workers |

The API constructs a single Provider registry and passes it to Chapter and
Provider callback composition. Planning and Reader bind routes on the Chapter
Production Execution Gateway. Controlled composition fails before serving when
required dependencies, Provider adapter credentials, or Authority release
identity are missing.

## Authority and execution boundaries

| Component | Owns | Must not own |
|---|---|---|
| Domain Authority | business invariant, candidate/approval/activation, accepted commit | raw Provider transport |
| Command Kernel | Operation, Saga, Attempt, Lease, Fence, ExternalEffect, retry/recovery | creative/domain policy |
| Production Execution Gateway | frozen route, backend dispatch, provider recovery, result evidence | Authority activation |
| RuntimeJob Authority | durable scheduling envelope for Book ticks and maintenance scans | business attempt/effect/commit semantics |
| Worker Health | process freshness and drain state | business completion |

RuntimeJob accepts only the five governed operational contracts. Chapter,
Planning, Reader, Agent, Content, Source, and MKAOS business work remains
Command-Kernel/Authority work.

## Environment and Provider model

`RuntimeEnvironment` is the only environment type:

```text
development ┐
test        ┴─ LOCAL, fixture allowed
validation  ┐
production  ┴─ CONTROLLED, fixture forbidden
```

Provider qualification, real-provider proof, long-form proof, and production
verification are independent evidence dimensions. They are not environments.

Formal Provider adapter construction uses `ProviderAdapterFactory` and
`ProviderAdapterRegistry`. Scripted adapters exist only in local environments;
OpenAI composition requires its credential; Codex CLI remains a governed
execution backend. Production-reachable model work uses the Production Execution
Gateway rather than stage-specific direct transport factories.

## Book and Replan runtime

`BookProductionComposition` contains the existing Book Authority, Planning
generation application, ChapterGroup Authority, Production Preparation,
Followup/Reader/Recap, PlanChange, input resolver, Replan coordinator, and
Supervisor. API and Worker use this exact graph.

The Replan worker path stops at `APPROVAL_PENDING`. Approval is a separate
Authority command permission. After approval, the same composition activates the
replacement plan, derives the new input snapshot, resumes the Book, and proceeds.

## Knowledge and Context

Production Preparation resolves typed, versioned assets and freezes the input
snapshot. Stage profiles exclude raw source expression. `knowledge_pack` is
allowed but optional by default. Generation Capability Packs must declare their
project Knowledge Pack policy and may require it by stage/capability. A required
missing pack blocks admission; an optional missing pack does not produce a fake
empty asset.

## Production reachability

`novel_forge.tools.production_reachability` derives a machine-readable manifest
from:

- the governed production-entry inventory;
- Python import paths from real entrypoints to applications;
- `pyproject.toml` console scripts;
- `compose.yml` commands and worker operation labels;
- the current Git SHA.

The result separates `code_exists`, `composed`, `deployed`,
`runtime_reachable`, `authority_backed`, and `worker_backed`. Its proof level is
`ARCHITECTURE_REACHABLE` at most; runtime, Provider, long-form, and production
claims require separate evidence.

## Legacy classification

| Surface | Classification | Current disposition |
|---|---|---|
| legacy import Authority | `MIGRATION_ONLY` | keep until retained records migrate |
| legacy CLI/API/LocalStorage/Celery | compatibility/development fixture | isolated from controlled production |
| old workflow/loop kernel | `LEGACY_ISOLATED` | no canonical production consumer; delete after remaining local consumers retire |
| old production kernel | `LEGACY_ISOLATED` | retained only behind legacy product surface |
| old agent scheduler | `LEGACY_ISOLATED` | replaced in production by AgentRuntime Authority |
| legacy context services | `LEGACY_ISOLATED` | replaced in production by frozen Preparation inputs |
| D0 fixture worker | development fixture | controlled execution rejected; credentialed qualification uses canonical adapter composition |

Generic runtime worker aliases and the stale Authority-only Compose duplicate
have been removed. Deeper legacy source deletion remains gated by call-graph and
migration-consumer removal, not compatibility sentiment.

## Evidence ceiling

Current code supports fixture-backed, PostgreSQL-integrated Book production and
recovery. It does not prove a real Provider, sustained long-form quality, or a
production deployment.
