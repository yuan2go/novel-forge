# Architecture overview

Novel Forge is a local-first production backend for creating and governing long-form fiction assets. The **target product** is a Human-AI Collaborative Long-form Narrative Operating System with a Governed Autonomous Production Runtime, as defined in [`canonical-overall-design.md`](canonical-overall-design.md).

The **current runtime** is an early but substantial Novel Operating System backend: operations are versioned and traceable, business state belongs to named Authorities, model and object-store calls are fenced external effects, accepted outputs become governed/versioned assets, and Narrative State is derived from accepted lineage.

The target Conversational Creative Studio is not yet equivalent to a proven user-facing product. Existing Agent Collaboration/Runtime, Planning/PlanChange, Revision, Narrative State, and Authority modules are the foundation that future conversational creative workflows must reuse; they must not create a second chat/runtime/authority plane.

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

- PostgreSQL is the only production business Authority. Memory implementations are fixtures only.
- Domain mutations go through a named Authority application and the Command Kernel when the operation contract requires it.
- Queries are concrete business read projections. They may join authority tables but do not mutate them.
- `ProductionExecutionComposition` owns shared process-level provider and object-store execution infrastructure. Chapter, Planning, Reader, Source, Agent, and Book are peer consumers.
- Chapter owns its chapter-specific saga/stage policy/binder/execution contract, not the shared execution plane.
- Agents produce governed candidates/proposals; the relevant Domain Authority decides and commits business state.
- Conversational Agent roles are target product profiles over the same Agent/Capability/Authority foundation, not new Authorities.
- Plan changes reuse PlanChange/Replan and owning design Authorities; a second generalized Narrative Change runtime is not part of the target design.
- The canonical temporal hierarchy is `Book → Volume → Narrative Segment → Chapter → Scene → Beat`; Arc is an orthogonal cross-time graph dimension.
- Legacy code is migration-only and cannot be imported by production roots.

## Current evidence boundary

The table below is a repository-evidence summary, not a production claim. Exact evidence must always be re-established at the SHA being qualified.

| Area | Current repository evidence boundary |
|---|---|
| Authority API, workers, PostgreSQL schema | Implemented/runtime-wired; PostgreSQL test suites exist. |
| Command Kernel, Attempt/Lease/Fence, ExternalEffect, RuntimeJob | Implemented/runtime-wired; fixture and PostgreSQL evidence exists in the repository. |
| Chapter production saga | Implemented/runtime-wired with bounded test evidence; successful provider output is not Chapter acceptance. |
| Progressive long-form design, qualification, and Chapter admission | Implemented/runtime-wired in current modules; exact-SHA engineering qualification remains required. |
| Canonical Narrative State / accepted event lineage / temporal query | Implemented/runtime-wired; rebuild and PostgreSQL evidence exists. |
| Book coordination, reader/recap, PlanChange/Replan | Implemented/runtime-wired with bounded fixture/PostgreSQL evidence. |
| Source Import, Source Intelligence, MKAOS | Implemented/runtime-wired with bounded fixture/PostgreSQL evidence. |
| Agent Collaboration/Agent Runtime/capability-pack foundation | Implemented first production slices; broad product-role and human conversational coverage is not proven. |
| Conversational Creative Studio, Chapter Editor interaction, Conversation→Decision product lifecycle | **Target architecture; not proven as a complete canonical user/runtime flow.** |
| Real external provider over sustained narrative production | Not established by documentation alone; requires pinned runtime evidence. |
| 30/100/300-chapter long-form correctness | Not proven by ordinary fixture/integration tests. |
| Multi-book production scale | Not proven. |
| External publishing + real-reader closed loop | Partial modules/interfaces may exist; end-to-end operated proof is not established here. |
| Production deployment/admission | Not proven by this document. |

Do not infer a higher proof state from the existence of code, fixtures, or one successful bounded run. Use the evidence vocabulary in [`../README.md`](../README.md) and the qualification model in the Canonical overall design.
