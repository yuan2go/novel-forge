# Track B Book + BookDesign Authority Slice

Updated: 2026-08-03

```text
input_task=Track B minimal vertical slice from Architecture Closure request
schema_types=book-authority.v1, book-design.v1, book-read-model.v1, book-design-read-model.v1
code_commit_sha=ea6876476287e90a206ec4a10b2345a881f67656
output_authority=PostgreSQL
object_evidence=AssetVersion/blob lifecycle metadata
validation_status=PASS
quality_gate_status=TRACK_B_MINIMAL_PASS
```

## Implemented chain

```text
HTTP Create Project
→ trusted server Principal and Project/Workspace scope
→ idempotent Create Book Transaction Command
→ PostgreSQL Book + Book AssetVersion commit
→ typed BookDesign Candidate validation
→ AssetVersion + dependency/evidence
→ Approval Decision
→ Activation
→ versioned query projection and Outbox
→ supersession and stale-version checks
→ worker/API restart recovery
→ Legacy writer disabled
```

The Book scope persists `project_id`, `workspace_id`, `book_id`, principal, service identity, production profile, runtime policy and release identity. BookDesign rejects missing/wrong `schema_version`, unsupported fields, weak protagonist shapes, empty/duplicate world rules and invalid chapter counts. Payload hash is canonical and stable.

## Shared capability use

- Transaction Commands reuse the existing Operation/Attempt/Lease/Fence/Idempotency kernel; Book/BookDesign are not forced into a Saga.
- `Asset`, `AssetVersion`, `AssetDependency`, `AssetDecision`, `AssetActivation`, `AssetSupersession` and `AssetEvidence` share metadata while BookDesign retains a typed domain validator.
- PostgreSQL owns state; Outbox rows are committed atomically; Redis is delivery-only and is not queried as task Authority.
- Object lifecycle metadata includes content hash, object reference, content type, size, retention class, encryption metadata, orphan detection and GC candidate selection. Physical deletion remains an explicit External Effect.
- Cross-domain reads use `BookDesignAuthorityQuery` versioned read models rather than another domain's repository implementation.

## Runtime evidence

The isolated `compose.authority-only.yml` stack ran PostgreSQL, Redis, MinIO, a one-shot migration service, Authority API, Authority Worker and Maintenance Worker. `/ready` returned:

```text
runtime_profile=track-b-minimal
postgresql.authority=true
postgresql.migration_head=20260803_0051_book_design_authority_slice
object_store.reachable=true
outbox.authority=postgresql
queue.role=delivery_only
queue.authority=false
legacy_write_enabled=false
silent_fallback_enabled=false
```

Worker health projection contained `authority-worker-1` and `maintenance-worker-1` in `READY` with successful polls and no fatal error. After restarting API and both workers, the active BookDesign projection remained queryable.

After evidence capture, the dedicated Compose containers, network and three Track B test volumes were deleted. The runtime proof is retained in this SHA-bound report; no test database or object-store data remains running.

The HTTP proof created Book `track-b-runtime-book`, materialized one typed candidate, replayed the duplicate command against the same Operation/AssetVersion, approved and activated it, then queried Book version 2 with status `DESIGN_ACTIVE`. Outbox projection contained committed Book create, propose, decide and activate events.

## Legacy cutover record

```text
legacy_source=legacy_local:projects/books/design
authority_target=postgresql:authority_book+authority_asset_version
import=legacy migration scanner/service and resumable migration records implemented
validation=hash/count/quarantine validation implemented and PostgreSQL tested
writer_cutover=DISABLED in Track B production-minimal profile
reader_compatibility_until=2026-09-02 for runtime proof row
retirement_deadline=2026-10-02 for runtime proof row
```

The broader Legacy development surface remains present. No claim is made that all residual Legacy readers/writers across the repository are retired.

## Tests

- Unit: Book/BookDesign schema, hash, scope and execution classification included in the 1,169-test pass.
- PostgreSQL: `test_authority_book_design_postgres.py` covers full chain, supersession, replay, projection, stale version, invalid candidate rollback and Legacy cutover.
- PostgreSQL focused suite: 141/141, zero skipped.
- Architecture: production LocalStorage writes, silent fallback, direct Provider calls, repository crossings, manifests and classifications are machine checked.
- Runtime: real local Docker API/worker/object-store/restart smoke passed.

## Gate

```text
project_book_scope_authority_proven=true
typed_book_design_asset_proven=true
minimal_authority_only_runtime_verified=true
production_legacy_write_blocked=true
duplicate_replay_proven=true
query_projection_proven=true

authority_only_runtime_verified=false
```

The final broader flag stays false because Track E deployment hardening, authenticated public boundary, backup/PITR, SLO/capacity and production operations are not proven. The narrower Track B minimal runtime gate is true.

## Proof classification

```text
architecture_defined=true
implementation_present=true
unit_verified=true
postgres_integration_verified=true
deployment_verified=true  # isolated local Track B runtime
external_execution_proven=false
longform_proven=false
production_verified=false
```
