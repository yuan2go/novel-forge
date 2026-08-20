# Architecture overview

Novel Forge's target architecture is defined only by [`canonical-overall-design.md`](canonical-overall-design.md). This file is a current-runtime view and must not promote target design to current proof.

## Current runtime shape

```text
Operator / API / workers
        ↓
Domain Authority applications
        ↓
Command Kernel / RuntimeJob
        ↓
specialized workers
        ↓
ProductionExecutionComposition
  ├ governed model/provider gateway
  └ object/artifact effects
        ↓
PostgreSQL Authority + object storage + configured provider
```

Stable current boundaries:

- PostgreSQL is the production business Authority; memory implementations are fixtures.
- Domain mutations go through owning applications/command semantics rather than Agent direct writes.
- ProductionExecutionComposition is shared execution infrastructure, not Chapter-owned infrastructure.
- Chapter/Book, Planning, Agent, Source/MKAOS, Quality/Reader and Provider systems are peer users of the shared execution plane.
- accepted Chapter/Book lineage is the boundary from candidate output to story truth.
- Narrative State is projected from accepted evidence; Context/retrieval are derived.
- current planning already supports multiple Arc plan versions at a chapter cursor and cross-Arc planning semantics; this is not yet the complete target Narrative Arc OS described in the Canonical Design.
- Legacy remains migration-only.

## Target semantic shift

The converged target moves chapter production from broad context-driven generation toward:

```text
Progressive Plan + Arc Working Set
→ Chapter Mission
→ Current Narrative State
→ task-specific evidence
→ bounded Production Packet
→ Scene composition
→ prose
→ verification / quality
→ Accepted Outcome
```

This should extend existing Planning/Narrative State/Context/Chapter Authority rather than create a second narrative runtime.

## Current liveness risk to reverify

At the 2026-08-20 design review baseline, current Book coordination code still contains a structural liveness risk that must be reverified against the latest SHA before implementation:

- accepted-chapter Reader/Long-form follow-up work is advanced before the supervisor reaches next-chapter planning/dispatch in some states;
- follow-up advancement may execute/recover durable provider work rather than merely enqueue and return;
- the Book worker's coordination-state whitelist does not visibly cover every nonterminal state handled by the supervisor.

This is consistent with the observed real failure mode “Chapter 1 completes, Chapter 2 does not advance for hours.” It is a code-proven risk structure, **not proof of the exact incident root cause without PostgreSQL Operation/Attempt/Book-state evidence**.

Until bounded Chapter 1→2 forward progress is proven on current code, long-form liveness is not proven even if local correctness/unit/PostgreSQL tests pass.

## Evidence boundary

The repository contains substantial implementation/runtime/test evidence for:

- Command Kernel, Operation/Attempt/Lease/Fence, ExternalEffect, RuntimeJob;
- PostgreSQL Authorities and migrations;
- Chapter/Book production and acceptance;
- progressive planning and semantic evaluation;
- Narrative State / temporal replay / accepted lineage;
- PlanChange/Replan;
- Source/MKAOS;
- Agent Collaboration/Runtime;
- quality/reader surfaces;
- qualification infrastructure.

Current documentation does **not** establish by itself:

- sustained real-provider Book production;
- Chapter-to-Chapter bounded liveness;
- 30/100/300-chapter correctness/quality;
- target Chapter Mission/Production Packet and full Narrative Arc OS semantics;
- real-reader learning closure;
- multi-book production;
- Production Admission.

Use the evidence vocabulary in [`../README.md`](../README.md). Exact status must be re-established at the SHA under qualification.
