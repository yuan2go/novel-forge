# Production execution

The Production Execution Plane (PEP) is the shared mechanism for governed model and object-store effects. It is infrastructure, not a Chapter subcomponent and not a second business authority.

## Composition ownership

`ProductionExecutionComposition` is created once per API or worker process. It owns:

- the governed production execution gateway and provider routes;
- the ExternalEffect-backed object-store adapter;
- the source object reader backed by that adapter;
- runtime environment and cost/budget caps;
- provider session shutdown.

Chapter, Planning, Reader, Source Import, Agent, and Book compositions receive this shared object or its explicit ports. They do not access `ChapterAuthorityApplication.model_port`, Chapter object-store internals, or Chapter external-effect adapters.

```text
Provider registry + object store + environment
                    │
                    ▼
       ProductionExecutionComposition
          ├── Chapter composition
          ├── Planning generation
          ├── Reader / recap follow-up
          ├── Source import / intelligence
          ├── Agent execution
          └── Book coordination
```

Reader/recap uses an isolated Book Followup deployment executor, not an additional execution plane. Admission is a `book_followup` RuntimeJob sourced from committed Chapter acceptance; model work is still a Command Kernel Operation with the common Attempt, lease/fence, ExternalEffect, Provider, receipt, and domain-output lifecycle. The executor consumes frozen accepted lineage and cannot update Book production state.

## What remains domain-owned

Chapter keeps its binder, node/stage policies, saga definition, and chapter-specific work-order contracts. Planning, Reader, Source, Agent, and Book keep their own admission, validation, and commit authority. PEP cannot decide that a plan, chapter, reader finding, source analysis, or Agent candidate is accepted.

The target Unified Agent Harness is another governed PEP client, not a replacement runtime. Admission freezes Definition, role, Tool/Skill/Capability Pack, prompt/context policy, provider/model/reasoning/route, release, accepted boundary and aggregate budget identity. Each model turn or remote Tool call is an Attempt-bound ExternalEffect with a receipt. Every Attempt validates its execution binding against the admission contract; restart or deployment drift cannot silently substitute a new runtime. Delegated Capability and Tool effects remain authoritative in their child Operations and ledgers, and aggregate to the parent Session through Operation lineage. The Harness may resume a transcript and choose another allowed Tool; it cannot own plan activation, Canon/State mutation, Arc/Obligation advancement or Chapter acceptance.

## Effect lifecycle

A governed call freezes the capability, provider route, model profile, request hash, budget, timeout, and operation lineage. The Command Kernel creates an ExternalEffect identity before network work. A worker executes or reconciles the effect, records a receipt, and submits a fenced result. The owning Domain Authority then validates and commits business output.

This separation preserves exactly-once business commitment without claiming exactly-once behavior from an external provider.

All retrieval, embedding, compression and semantic/model evaluation required by a Chapter must finish before Book acceptance. The acceptance transaction consumes immutable qualified evidence and performs only deterministic reducers, CAS/fence validation, authoritative writes/current-pointer advancement and outbox.

## Provider status

Provider routing is fail-closed in controlled environments. The default development Compose route is scripted and supports fixture proof only. Real-provider qualification and an actual real-provider run are separate evidence requirements; neither follows from a buildable route or a green mock run.
