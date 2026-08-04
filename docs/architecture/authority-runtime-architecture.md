# PostgreSQL Authority Runtime Architecture

## Authority boundaries

```text
Business Task       product intent and human/workflow ownership
Authority Operation atomic domain command or resumable business execution
Runtime Job         non-business claim/lease/fence/checkpoint execution plane
Outbox Delivery     durable internal event-delivery authority
ExternalEffect      side-effect intent, receipt and reconciliation authority
```

Runtime Job never becomes a second Task or domain authority. Book Authority owns
Book state, Operation owns command/execution state, Outbox owns delivery state,
and ExternalEffect owns side-effect outcome. Runtime Job only discovers, claims,
leases, fences, checkpoints, retries, dead-letters and records worker execution.

## Default Compose plane

The default stack contains PostgreSQL, MinIO, a one-shot migration service,
Authority API and seven workers: Chapter, Content, Source, MKAOS, Book, Outbox
and Maintenance. No Legacy or Web service is in the Authority topology.

Chapter, Content, Source and MKAOS execute Authority Operations. Book coordination
uses `BOOK_COORDINATION_TICK` Runtime Jobs. Maintenance uses bounded singleton/
deduped jobs for operation deadlines, expired Attempt leases, Outbox recovery and
ExternalEffect reconciliation. Outbox retains its dedicated authority while
providing the same lease/fence/stale-result guarantees; it is not duplicated into
a second delivery state machine.

## Runtime Job model

`authority_runtime_job` stores kind/group/subject/project/dedupe input and
scheduling state. Attempt, lease, checkpoint, result and event tables preserve
worker identity, attempt number, fencing token, heartbeat, bounded retries,
dead-letter and recovery. Claims use transactional row locking and database
uniqueness/CAS; a replaced worker cannot checkpoint or complete with its stale
token.

Book ticks can accept a completed Chapter once, create legal follow-up state and
resume after restart without generating the next chapter automatically.
Maintenance scans are bounded and idempotent. Unknown external effects become
query/manual-required unless a real Provider adapter supplies a result.

## Migration execution

Legacy import first reaches archival reconciliation. The 18 core domain types
then require server-side `migration.item.validate`, an independent Validation-ID
decision, dependency-ordered activation and projection reconciliation. Structured
reference edges define the activation DAG; missing, ambiguous, cross-project,
incompatible or cyclic required edges fail closed.

## Health and metrics

Worker health reports active Operation/Runtime Job/Attempt, leases and current
fence, completion/failure counters, polls/heartbeats/database outcomes and drain
state. Database status is derived, never unconditionally written `READY`.

Pool registry identity is:

```text
database identity fingerprint + role + service + pool-config fingerprint
```

Fleet metrics are worker-written PostgreSQL projections suitable for later
Prometheus/OpenTelemetry export. They aggregate pool, transaction/retry/error,
backlog, unknown-effect and stale-worker facts without exposing DSNs.

## Evidence model

Architecture Contract is stable and checked in. Implementation Tree Identity is
deterministically recomputed from semantic inputs. Volatile evidence is emitted
only by CI and binds the tested SHA. Seven independent Compose scenarios prove
fixture execution, forced stop, lease expiry, replacement fence, stale rejection,
recovery, drain and zero leaked connections. A fail-closed summary accepts only
seven matching-SHA PASS documents.

This boundary proves backend fixture behavior only. It does not prove real
Provider execution, story quality, external broker delivery, production load,
long-form/multi-book operation, PITR or autonomous Book Loop behavior.
