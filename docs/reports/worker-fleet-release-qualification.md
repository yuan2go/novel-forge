# Worker Fleet Release Qualification

## Gate

`AUTHORITY_WORKER_FLEET_E2E_PROVEN` is eligible only when seven independent Core
OS CI matrix jobs produce PASS artifacts for the same full `GITHUB_SHA`, and the
fail-closed fleet summary validates all of them.

| Worker | Work authority | Recovery authority | Required proof |
|---|---|---|---|
| Chapter | Authority Operation/Saga | Attempt lease/fence | 18-node fixture saga and restart convergence |
| Content | Authority Operation | Attempt lease/fence | Creative Brief output and audit/outbox |
| Source | Source Authority + Blob receipt | Attempt lease/fence | MinIO Put/register/transform/projection |
| MKAOS | MKAOS Authority | Attempt lease/fence | evidence/candidate/approval/card/pack |
| Book | Book Authority | Runtime Job | accept child/follow-up/resume |
| Outbox | Outbox delivery authority | Outbox lease/fence | ack/replay/poison/expiry/recovery |
| Maintenance | owning Authorities | Runtime Job | four bounded recovery scans |

Each artifact must contain non-empty worker/work/attempt-or-job/lease identifiers,
a replacement fencing token greater than one, checkpoint/result, restart,
recovery, stale rejection, graceful drain and zero leaked connections. Health or
heartbeat alone is invalid evidence.

The exact work ids, attempts, leases, fences, durations and artifact hashes are
run evidence and are intentionally not checked into Git. They are available in
`worker-e2e-<worker>-<SHA>.json` and
`worker-fleet-summary-<SHA>.json` for the tagged SHA.

All scenarios are fixtures. Real Provider, story quality, production object
storage, external broker delivery and autonomous next-chapter behavior remain
unproven.
