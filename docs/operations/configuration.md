# Configuration

Configuration is read from process environment and `.env`; process environment wins. `IndustrialSettings` rejects any production storage authority other than PostgreSQL.

## Core settings

| Variable | Purpose | Development default |
|---|---|---|
| `NOVEL_FORGE_ENVIRONMENT` | `development`, validation, or controlled production behavior | `development` |
| `NOVEL_FORGE_STORAGE_AUTHORITY` | Business authority backend; only `postgresql` is valid | `postgresql` |
| `NOVEL_FORGE_DATABASE_URL` | PostgreSQL DSN | required outside Compose |
| `NOVEL_FORGE_APPLICATION_BUILD_ID` | Release/build identity recorded on operations | Compose fixture value |
| `NOVEL_FORGE_COMMIT_SHA` | Source identity recorded on operations | zero fixture SHA in Compose |
| `NOVEL_FORGE_MODEL_PROVIDER` | Provider route family | `mock` in Compose |
| `NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID` | Local operator principal | `compose-operator` |
| `NOVEL_FORGE_NARRATIVE_EVALUATOR_PRINCIPAL_ID` | Independent Narrative Semantic Evaluator principal | required in production |
| `NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE` | Principal project scope | `*` locally |

## Object storage

`NOVEL_FORGE_MINIO_ENDPOINT`, access key, secret key, secure flag, and bucket names configure raw, artifact, and export storage. Compose injects service-local MinIO settings. Secrets must not be committed or placed in trace payloads.

## Database runtime

Statement, lock, and idle-transaction timeouts are controlled by `NOVEL_FORGE_DB_STATEMENT_TIMEOUT`, `NOVEL_FORGE_DB_LOCK_TIMEOUT`, and `NOVEL_FORGE_DB_IDLE_TRANSACTION_TIMEOUT`. Service instance variables feed the connection-budget check against PostgreSQL `max_connections`.

Book coordination and advisory follow-up use distinct database roles and instance budgets: `NOVEL_FORGE_DB_BOOK_INSTANCES` and `NOVEL_FORGE_DB_BOOK_FOLLOWUP_INSTANCES`. The Book Followup worker identity is configured by `NOVEL_FORGE_BOOK_FOLLOWUP_WORKER_ID`.

## Fixtures and controlled environments

- `NOVEL_FORGE_MODEL_PROVIDER=mock` is a scripted provider.
- `NOVEL_FORGE_MKAOS_ALLOW_FIXTURE_ACTIVATION` defaults to false and is rejected in controlled environments.
- Local file source imports require a fixture-allowed environment and an explicit `NOVEL_FORGE_SOURCE_IMPORT_FILE_FIXTURE_ROOT`.

Never interpret `fixture_only=true` readiness as real-provider qualification. Controlled profiles should fail closed when provider routes, pack activation, migrations, PostgreSQL, MinIO, or worker heartbeat evidence is absent.

## Release identity

Non-fixture runs must provide a real build ID and current Git SHA. HEAD integrity checks reject dangling or untracked runtime wiring, but they do not repair incorrect environment identity supplied at deployment.
