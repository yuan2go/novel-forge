# PostgreSQL-only Single-Chapter Slice Runbook

Status: readiness contract; execution deferred until the remaining handlers are implemented.

## Scope

The first bounded proof is one project and one chapter:

```text
Project
-> ChapterPlan
-> ContextBundle
-> Draft
-> Review
-> Revision
-> Canon
-> Quality Gate
-> Export Asset / Blob
```

It must use one root Operation, admitted child Operations, Attempts with fenced
leases, explicit output AssetVersion bindings, Completion Contracts, and a
fenced Saga coordinator. It must not execute a 30/50/100 chapter run.

## Required evidence contract

Each node must preserve:

- admitted command identity and frozen OperationDefinition;
- project/workspace/trace/correlation identity;
- Attempt lifecycle and lease fencing evidence;
- operation-scoped output binding with content hash;
- latest effective Asset qualification;
- required audit actions and outbox events;
- Blob role/status/verification evidence when bytes leave PostgreSQL;
- ExternalEffect receipt or reconciliation evidence for external calls;
- Completion result and parent/Saga transition evidence.

The root may succeed only when every required child and gate is complete. A
worker result alone is insufficient.

## Runtime prerequisites

1. Apply migrations through `20260716_0021_saga_coordination`.
2. Register enabled, versioned definitions for each slice node and its
   compensation where applicable.
3. Register focused handlers that call existing domain services through typed
   commands and bind every output AssetVersion.
4. Configure Generic ExternalEffect adapters for provider/object-store work.
5. Provide an isolated PostgreSQL database and deterministic fake provider for
   the fixture proof.

## Acceptance harness design

The fixture harness must:

1. admit the root and child Operations through `admit_command`;
2. transition each child through Attempt lease, worker result, and Completion;
3. inject one retryable crash and prove forward recovery;
4. inject one post-send UNKNOWN effect and prove reconciliation blocks retry;
5. verify duplicate receipts replay and stale fencing tokens are rejected;
6. verify an unrelated project Asset, revoked qualification, and admission
   audit cannot complete a node;
7. query StateEvent, AuditLog, Outbox, receipt, output binding, and Saga evidence;
8. produce a small evidence manifest without calling a real model provider.

## Current blockers

- Node-specific PostgreSQL handlers for the whole chapter chain are not yet implemented.
- Existing Chapter Production Bus and related services still write LocalStorage business assets.
- Saga compensation child admission is not yet automatic; current work provides reverse planning, coordinator fencing, and standard forward-child lifecycle proof.
- No PostgreSQL-only single-chapter fixture has therefore been claimed as passed.
