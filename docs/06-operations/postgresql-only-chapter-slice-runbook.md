# PostgreSQL-only Single-Chapter Slice Runbook

Status: deterministic PostgreSQL-only handler proof implemented; real-provider and long-form proofs remain deferred.

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

The repository now provides these prerequisites through:

- `novel_forge.modules.chapter_authority.definitions` for the root and eight
  versioned node definitions;
- `novel_forge.modules.chapter_authority.handlers` for the typed handler port
  and deterministic fixture handlers;
- `novel_forge.modules.chapter_authority.runtime` for fenced, idempotent,
  operation-scoped output materialization;
- `novel_forge.modules.chapter_authority.orchestrator` for dynamic standard
  admission, Attempt execution, Saga coordination, recovery, and Export delivery;
- `novel_forge.modules.chapter_authority.evidence` for the read-only evidence
  manifest.

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

The deterministic fixture proof is implemented and passes without LocalStorage
or a real model provider. It proves:

- one root plus eight child Operations use standard admission;
- all child outputs are ACTIVE/ELIGIBLE/CLEAR AssetVersions bound to their
  producing Operation with content hashes and latest effective qualification;
- Attempts use leases and fencing, including one injected Draft crash followed
  by Saga `FORWARD_RECOVERY` and a second Attempt;
- Export uses the Generic ExternalEffect dispatcher, records a post-send
  `UNKNOWN`, blocks blind retry, records ambiguous reconciliation, rejects a
  stale dispatch result, replays a duplicate receipt, verifies the Blob, and
  binds it to the Export AssetVersion before Completion;
- the root succeeds only after every child Completion Contract is satisfied.

Run the bounded proof with the isolated PostgreSQL test service:

```bash
make postgres-authority-test-up
NOVEL_FORGE_DATABASE_URL=postgresql://novel_forge:novel_forge@127.0.0.1:55432/novel_forge_authority_test \
  .venv/bin/python -m unittest tests.integration.test_postgresql_only_chapter_slice -v
make postgres-authority-test-down
```

Remaining blockers for a production provider-backed slice:

- the deterministic fixture handlers do not call a model and are not proof of
  prose quality or provider readiness;
- the existing Chapter Production Bus and related services still write
  LocalStorage business assets and have not been converted into projections;
- production handler adapters must preserve AgentRun, ContextBundle,
  model-call, cost-ledger, ReviewIssue, Canon, and publish-gate contracts without
  restoring LocalStorage as command authority;
- automatic compensation is intentionally not declared for append-only chapter
  evidence; a production object-store retention/cleanup policy remains a
  separate design decision;
- no 30/50/100-chapter or real-provider run is claimed.
