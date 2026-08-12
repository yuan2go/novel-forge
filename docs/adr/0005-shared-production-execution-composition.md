# ADR 0005: Shared production execution composition

Status: Accepted

## Context

Planning, Reader, Source Import, Agent, and Book compositions previously obtained model or ExternalEffect infrastructure indirectly from `ChapterAuthorityApplication`. This made a domain application the owner of process-level execution infrastructure and allowed peer modules to depend on Chapter internals.

## Decision

Each API or worker process constructs one `ProductionExecutionComposition`. It owns the governed provider gateway, object-store ExternalEffect adapter, source object reader, execution environment, budget caps, and provider-session shutdown. Chapter and other domain applications are peer consumers.

Chapter continues to own its binder, stage policy, 18-node saga, and chapter-specific execution contracts. PEP, Attempt, ExternalEffect, provider routing, and business Authorities are unchanged.

Architecture fitness forbids peer compositions from borrowing Chapter-owned model/object-store/external-effect internals and prevents duplicate runtime construction.

## Consequences

- Shared provider and object-store resources have explicit process ownership.
- Domain dependency direction no longer runs through Chapter.
- Adding a consumer requires an explicit PEP port or composition dependency, not a compatibility adapter.
- `ProductionExecutionComposition` remains infrastructure and cannot accept domain output.
