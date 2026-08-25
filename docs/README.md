# Novel Forge documentation

The documentation set is intentionally small. Do not add chat summaries, one-off build plans, duplicate blueprints, or exact-SHA audit reports as current architecture documentation.

## Documentation authority

Precedence:

1. **Current implementation truth:** source code, migrations, executable entries/composition, tests and pinned runtime evidence.
2. **Canonical target architecture:** [`architecture/canonical-overall-design.md`](architecture/canonical-overall-design.md).
3. **Current-runtime companion views:** `architecture/overview.md`, `runtime.md`, `authority-model.md`, `production-execution.md`, `narrative-state.md`, `source-and-knowledge.md`.
4. **Active ADRs:** durable implementation decisions; if an ADR changes the target architecture, the Canonical Design must be updated in the same change.
5. **Product / operations / development guides:** derived views and procedures.

A target capability in prose is not implementation evidence. Code existence is not runtime proof. Fixture success is not long-form or production proof.

## Canonical target

- [`architecture/canonical-overall-design.md`](architecture/canonical-overall-design.md) — **the single target product/architecture Source of Truth**.

It covers Vision/Non-Goals, business/capability/system architecture, Authority/State, Agent/Skill/Tool boundaries, progressive planning, Narrative Arc OS, Chapter Mission/Production Packet, Narrative State, Context/Memory/MKAOS, Chapter production/Accepted Outcome, Quality, Reader learning, execution/recovery, liveness, governance, qualification, Target Architecture and Roadmap.

## Current-runtime companions

- [`architecture/overview.md`](architecture/overview.md) — reachable architecture and current proof boundary; includes the long-form liveness risk that must be reverified on latest code.
- [`architecture/runtime.md`](architecture/runtime.md) — API/worker/Operation/RuntimeJob/recovery view.
- [`architecture/authority-model.md`](architecture/authority-model.md) — PostgreSQL ownership/mutation rules.
- [`architecture/production-execution.md`](architecture/production-execution.md) — shared execution/provider boundary.
- [`architecture/narrative-state.md`](architecture/narrative-state.md) — current Narrative State v2/accepted-event contract.
- [`architecture/source-and-knowledge.md`](architecture/source-and-knowledge.md) — Source/MKAOS boundary and current structured Narrative Intelligence selection/lineage.

## Product views

- [`product/novel-production-flow.md`](product/novel-production-flow.md)
- [`product/capability-map.md`](product/capability-map.md)

These are derived from the Canonical Design and cannot independently change architecture.

## Development / Operations

Keep operational and development guides focused on executable procedures. Approved implementation specifications may live under `superpowers/specs/` only while active; completed or superseded delivery plans are removed once their durable decisions and qualification evidence have converged into the Canonical Design, ADRs, current-runtime companions, or qualification records.

Completed exact-SHA evidence:

- [Creative Engineering Convergence bounded qualification](qualification/2026-08-25-creative-engineering-convergence.md)
- [Canonical Hierarchy Closure bounded qualification](qualification/2026-08-26-hierarchy-closure.md)
- [Narrative Orchestration bounded qualification](qualification/2026-08-24-narrative-orchestration-qualification.md)
- [`qualification/2026-08-22-post-merge-runtime-hardening.md`](qualification/2026-08-22-post-merge-runtime-hardening.md)

The completed runtime-hardening design and superseded post-merge design/plan
were removed after review because they duplicated the Canonical Design and
current executable contracts. The exact-SHA qualification above is retained as
the durable evidence record.

Current repair runbook:

- [`operations/post-0094-projection-repair.md`](operations/post-0094-projection-repair.md)

## ADRs

`adr/` contains only durable decisions still constraining the system. It is not a project diary. ADR 0007 preserves Arc as an orthogonal planning dimension, establishes the qualified Foundation hierarchy, and places causal Narrative Realization inside Hierarchical Planning without adding a Plan scale or Authority. ADR 0003 is retained only to explain the superseded monolithic BookDesign decision.

## Documentation lifecycle labels

Use these during future reviews:

- `CURRENT` — valid current-runtime/procedure view.
- `CANONICAL` — target architecture source of truth (only the Canonical Overall Design).
- `SUPERSEDED` — replaced by a newer canonical decision; remove or archive when still historically useful.
- `OUTDATED` — factual/runtime claims no longer match executable evidence; update or remove.
- `DUPLICATED` — repeats another authoritative document without unique value; merge/remove.
- `CONFLICTING` — disagrees with higher-authority design/evidence; resolve in the same change.
- `HISTORICAL_ONLY` — useful evidence/history but never current design authority.

Do not keep an obsolete document merely because it was expensive to produce.

## Evidence vocabulary

Completion dimensions:

```text
DEFINED
WIRED
RUNTIME_REACHABLE
PERSISTED
AUTHORITY_GOVERNED
CONSUMED
UNIT/SMOKE_TESTED
```

Qualification remains separate: `REAL_PROVIDER_PROVEN`, `LONGFORM_PROVEN`, `MULTIBOOK_PROVEN`, and `PRODUCTION_QUALIFIED` are never implied by implementation evidence.

Repository maturity ladder where used:

```text
MISSING
SKELETON
IMPLEMENTED
WIRED
FIXTURE_PROVEN
REAL_PROVIDER_PROVEN
LONGFORM_PROVEN
MULTIBOOK_PROVEN
PRODUCTION_PROVEN
```

No lower evidence class implies a higher one. In particular, one successful Chapter does not establish Chapter-to-Chapter liveness or `LONGFORM_PROVEN`.
