# ADR: Authority Runtime Job Is the Non-Business Execution Plane

- Status: Accepted
- Date: 2026-08-04

## Context

Chapter, Content, Source and MKAOS already use Operation/Attempt/Lease/Fence.
Book coordination, Maintenance scans and Outbox delivery had separate loops.
Forcing every loop into a business Operation would misrepresent authority;
leaving unfenced loops would permit duplicate or stale worker commits.

## Decision

Create Authority Runtime Job for non-business execution state. It owns schedule,
claim, Attempt, lease, fencing, heartbeat, checkpoint, result, bounded retry,
dead-letter, recovery and worker identity. It does not own product intent or
domain outcome.

The boundaries are:

- Business Task owns product/workflow intent;
- Authority Operation owns atomic commands and resumable business executions;
- Runtime Job owns non-business worker execution;
- Outbox owns internal delivery state;
- ExternalEffect owns side-effect receipt/reconciliation;
- each domain Authority owns its projection and transitions.

Book uses `BOOK_COORDINATION_TICK` with Book run as subject. Maintenance uses
deduped bounded jobs for Operation deadline, Attempt lease expiry, Outbox
recovery and ExternalEffect reconciliation. Outbox retains its specialized
delivery tables but conforms to the same lease/fence/checkpoint/stale-result
contract instead of copying delivery authority into Runtime Job.

## Invariants

- only the current attempt/lease/fencing token may checkpoint or complete;
- a replacement claim has a monotonically higher fence;
- dedupe keys prevent concurrent work for one subject/purpose;
- checkpoint/result hashes are immutable evidence;
- business mutation still passes through the owning Authority;
- an unknown effect never becomes success without an authoritative query receipt.

## Consequences

Migration 0062 adds Runtime Job tables/indexes/constraints. Migration 0063 adds
fleet operational projections and hardened Outbox evidence. Book and Maintenance
now share one recoverable execution contract without creating another business
Task system. Migrations 0064–0066 bind Job, current Attempt, Lease, Worker,
Fence, Checkpoint, Result and Event identities with composite database
constraints; they also ensure an
expired final Attempt converges to Dead Letter rather than remaining active.
