# Authority Worker Fleet E2E Status

Status: `AUTHORITY_WORKER_FLEET_E2E_PARTIAL`.

The current evidence deliberately distinguishes PostgreSQL worker integration
from Compose E2E. The 11-service Compose smoke executes and restart-recovers a
Content operation. Starting, heartbeating, draining or releasing connections
does not prove that another worker executed its domain operation.

| Worker | Domain operation evidence | Identity evidence | Restart/recovery | Compose E2E | Result |
|---|---|---|---|---|---|
| Chapter | Fixture-provider Chapter saga integration: root, saga, attempt, lease, output, quality, Audit, Outbox | worker, attempt, lease and fencing asserted in PostgreSQL tests | scheduler recovery tests exist | not an isolated Compose scenario | PARTIAL |
| Content | Creative Brief operation through Command Kernel | worker, attempt, lease, fence and output asserted | forced container restart; stale fence rejected | yes | PROVEN_FOR_FIXTURE_CONTENT |
| Source | verified synthetic blob register/transform through Source Authority | worker and operation attempt/lease asserted | scheduler retry/recovery tests | not an isolated Compose scenario | PARTIAL |
| MKAOS | synthetic candidate, explicit approval, knowledge and pack chain | worker and operation attempt/lease asserted | scheduler retry/recovery tests | not an isolated Compose scenario | PARTIAL |
| Book | synthetic Book run advances a legal scheduler tick and rejects duplicate chapter acceptance | worker/runtime group asserted; tick is not modeled as a Command Kernel attempt/lease/fence | restart continuation integration exists | not an isolated Compose scenario | PARTIAL |
| Outbox | durable internal claim, lease, fenced delivery, ack, replay and poison recovery | worker, lease, fencing and runtime group asserted; no Authority Attempt row | restart/replay integration exists | not an isolated Compose scenario | PARTIAL |
| Maintenance | expires timed-out operations/attempt leases, requeues/dead-letters Outbox and marks unknown effects query/manual-required | worker/runtime group asserted; cycle is not an Authority Attempt/lease/fence | idempotent repeat/recovery integration exists | not an isolated Compose scenario | PARTIAL |

Outbox currently implements durable internal consumer delivery and acknowledgement.
It is not evidence of an external broker, webhook or publishing delivery.

## Missing proof for fleet completion

1. Seven isolated Compose scenarios, each submitting work owned by that runtime
   group.
2. Per-scenario persisted `claimed_by`, `worker_id`, `attempt_id`, `lease_id`,
   `fencing_token`, `runtime_group`, output and recovery evidence.
3. A deliberate attempt/lease/fence contract for Book ticks, Outbox deliveries
   and Maintenance cycles, or an approved typed equivalent with the same stale
   worker protection.

Until those exist, `worker_fleet_e2e_proven=false` even when the local
PostgreSQL integration suite and the Content Compose smoke pass.
