# Authority Worker Fleet E2E Contract

Core OS CI runs seven isolated Compose scenarios. Each matrix job starts fresh
PostgreSQL and MinIO volumes, submits work belonging to that runtime group,
forces a worker loss, waits for lease expiry, proves a higher fencing token and
stale-result rejection, converges, drains, and checks zero leaked connections.

| Worker | Scenario | Required domain evidence | Explicit non-claim |
|---|---|---|---|
| Chapter | full fixture Chapter Saga | Root/Saga, 18 nodes, quality/canon/export/final gate, restart | no real Provider or novel-quality proof |
| Content | Creative Brief | Operation, Attempt, output AssetVersion, Audit/Outbox | fixture content only |
| Source | MinIO object to Source projection | Put, Blob receipt, register, transform, projection | fixture object, not production storage |
| MKAOS | candidate to approved card and pack | SourceChunk evidence, independent approval, active version selection | fixture execution evidence |
| Book | coordination tick | legal Book run, completed Chapter child, accept/follow-up, Runtime Job resume | no autonomous next-chapter loop |
| Outbox | internal delivery | claim, lease, fence, ack, replay, poison, expiry/recovery | no external broker delivery proof |
| Maintenance | recovery scans | expired operation/attempt/outbox plus unknown effect handling | no fabricated Provider query success |

Every scenario artifact contains `commit_sha`, worker/runtime group, worker id,
work id, Attempt or Runtime Job id, lease id, fencing token, checkpoint, restart,
recovery, stale rejection, drain and connection-leak result. The summary builder
rejects missing, duplicate, wrong-SHA, health-only or single-fence evidence.

Artifacts are named `worker-e2e-<worker>-<GITHUB_SHA>.json`; the summary is
`worker-fleet-summary-<GITHUB_SHA>.json`. Only the summary artifact can set
`worker_fleet_e2e_proven=true`, and only when all seven inputs are `PASS` for the
same full SHA.

The checked-in implementation defines the proof. The exact remote conclusion is
owned by the Actions artifact and qualification tag.
