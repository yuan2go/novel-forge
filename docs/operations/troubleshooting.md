# Troubleshooting

## API is live but not ready

Check `/readiness`. It reports migration head, PostgreSQL pool and connection budget, MinIO reachability, provider route status, operation definitions, and capability-pack activation. Fix the named dependency; do not bypass readiness.

## Runtime readiness is degraded

Check `/runtime/readiness` and `make authority-logs`. A worker may be absent, stale, dead-lettered, or unable to connect. Confirm that Compose started every group listed in the worker manifest and that service instance counts fit the PostgreSQL connection budget.

## Provider says `FIXTURE_ONLY`

This is expected for the default Compose configuration. It is not a failure for local tests and is not real-provider proof. A controlled real-provider run needs qualified route evidence, credentials supplied outside the repository, and a recorded ExternalEffect/receipt chain.

## Migration mismatch

Run `novel-forge authority-migrate` against the intended database, then inspect readiness again. Never edit the migration head table manually. For test failures, recreate the isolated test service and let the runner build a temporary database from the full chain.

## Job repeatedly retries

Inspect the operation, current Attempt, lease/fence, ExternalEffect, and last error. Do not resubmit a new business command until determining whether the stable idempotency key already identifies the work. An uncertain provider or database outcome requires reconciliation, not a blind retry.

## Source import is blocked

Review the repository URL, frozen commit, rights decision, path/extension/size policy, symlink/submodule/LFS status, and file fixture root. Controlled environments reject local repositories and unsafe objects by design.

## PostgreSQL or Docker unavailable

Local unit/architecture tests may still run, but PostgreSQL integration and migration-runtime validation are `ENVIRONMENT_BLOCKED`. Record the missing daemon/service accurately and rerun the gates when available.
