# Source Import Production Runtime Design

## Status and scope

This specification is approved by the user request dated 2026-08-11. It extends the current `e528013` Source and MKAOS Authorities; it does not replace them.

The production path accepts a governed source locator, discovers and freezes an immutable snapshot, imports eligible bytes once, deterministically transforms them, runs dimension-scoped deconstruction through the Production Execution Plane, creates MKAOS Candidates through the same plane, and stops at the existing human governance boundary. Approval, KnowledgeCard activation, and KnowledgePack construction remain MKAOS Authority operations.

## Current implementation decisions

| Decision | Surface | Reason |
|---|---|---|
| KEEP | PostgreSQL Authority, Command Kernel, Operation/Attempt/Lease/Fence, ExternalEffect, AssetVersion, Source Authority, MKAOS Authority, ProductionExecutionGateway, object-store Blob protocol | These are already canonical and enforce the required identity, retry, governance, and evidence contracts. |
| EXTEND | Source worker and Source Authority API | They are the existing owner of Source operations and are the correct host for repository discovery, file processing, analysis execution, and reprocessing dispatch. |
| EXTEND | SourceTransform | Production transforms need an immutable normalized-text Blob plus automatic chunk creation; the existing transform commit remains the only business commit boundary. |
| EXTEND | Deconstruction/MKAOS execution | The current commit authorities require valid execution assets but callers still build those assets manually. Runtime execution will create them from frozen Attempt-bound PEP evidence. |
| REFACTOR | Reprocessing plan items | Plans must retain an executable scope/analyzer specification and durable per-item lifecycle, not only hashes. |
| LEGACY_ISOLATED | `source_intake`, LocalStorage repository ingestion, LocalStorage MKAOS extraction | They remain development/migration consumers and cannot be reachable from the PostgreSQL product import route. |

## Canonical flow

```text
SourceImport Job
  -> repository discovery Operation
       -> source.remote.fetch ExternalEffect
       -> exact commit + immutable manifest AssetVersion
       -> per-file processing Operations
            -> governed repository blob read
            -> content-hash Blob reservation/upload/verification
            -> SourceDocument Authority
            -> deterministic normalized Blob + chunk Blobs
            -> SourceTransform Authority
            -> per-profile Analyzer Operations
                 -> Attempt-bound PEP execution
                 -> structured validation + execution AssetVersion
                 -> Observation Authority
                 -> MKAOS extraction Operation
                      -> Attempt-bound PEP execution
                      -> anti-copy/source-isolation validation
                      -> execution AssetVersion
                      -> Knowledge Candidate Authority
                           -> existing human approval queue
                           -> KnowledgeCard Authority
                           -> KnowledgePack Authority
```

Every arrow that commits a business object calls its existing Authority. Import tables are orchestration/checkpoint state and query projections, not a second Source or Knowledge database.

## Source types and connector policy

The persistence model reserves `github_repository`, `local_file`, `local_directory`, and `https_resource`, but the product command contract enables only `github_repository` in this release. `file://` Git repositories are restricted to explicit allowlisted fixture roots in test/development. Local file/directory and HTTPS resource connectors remain capability-gated and fail closed; no direct-request fallback exists.

The Git adapter accepts normalized `https://github.com/<owner>/<repo>[.git]` locators. Test/development may additionally allow `file://` repositories inside configured fixture roots. It uses non-interactive Git with bounded timeout, disables LFS smudge, rejects embedded credentials, pins the resolved 40-character commit, discovers with `ls-tree`, blocks submodules and symlinks by policy, identifies LFS pointers and binary data, and never treats a branch name as snapshot identity.

Snapshot identity is `(project_id, repository_identity, resolved_commit_sha, import_policy_hash)`. The manifest hash covers the normalized locator, resolved commit, policy version, and sorted file identities. A later snapshot is diffed as `UNCHANGED`, `ADDED`, `MODIFIED`, `REMOVED`, `RENAMED_SAME_CONTENT`, or `BLOCKED`.

## Storage and transform boundary

Raw, normalized, and chunk bytes live only in the configured object store. PostgreSQL stores Blob receipts, hashes, sizes, encodings, policies, manifests, stable addresses, lineage, and structured intelligence.

Blob object keys are content addressed. Reservation identity is deterministic so retry after a crash cannot create another logical Blob for the same project/provider/purpose/content. Blob upload still uses the existing `object_store.put` ExternalEffect and verification protocol.

Normalization is deterministic and versioned. P0 supports UTF-8, UTF-8 BOM, GB18030/GBK, TXT, Markdown, JSON, and YAML text. It normalizes Unicode NFC, line endings, trailing whitespace, and final newline. JSON is parsed and canonically rendered. Binary, unknown encoding, oversize, LFS, symlink, and submodule inputs are blocked with an explicit reason. PDF/DOCX/EPUB remain unsupported in the canonical importer until a qualified parser is configured.

Chunking preserves structural boundaries where possible, then applies bounded paragraph segmentation. Stable chunk identity derives from normalized content, transform policy, and ordinal. Higher-scale analysis consumes lower-scale Observations by default instead of rereading whole-book source.

## Analysis profiles and cost control

An immutable analysis profile selects source class, scales, analyzers, and budgets. `web_novel` defaults to a bounded subset at chapter/window scale; `writing_theory`, `platform_rules`, and `professional_knowledge` use separate subsets. The caller may select fewer analyzers but cannot request an analyzer outside its governed profile.

The execution cache key includes the immutable input manifest plus analyzer/prompt/Skill/schema/provider-policy contract. Exact replay returns the existing Observation and consumes zero model tokens. MKAOS extraction keys include Observation versions and abstraction policy. Pack rebuild never reads Source bytes.

## Recovery and reprocessing

Repository discovery, each file transform, each Analyzer execution, each MKAOS extraction, and each reprocessing application are separate worker Operations. Import-file rows and reprocessing-item rows are durable checkpoints. A worker restart or lease takeover resumes only the incomplete Operation. If a Provider result was committed before a crash, the existing ExternalEffect/PEP execution identity is reconciled and reused.

Reprocessing plan lifecycle is `PLANNED -> RUNNING -> PARTIALLY_APPLIED -> APPLIED`, with terminal `FAILED` or `BLOCKED`. Item lifecycle is `PENDING`, `RUNNING`, `REUSED`, `APPLIED`, `FAILED`, or `BLOCKED`. `REUSE` schedules no work; recompute actions admit Analyzer operations; `REABSTRACT` admits MKAOS extraction; `REGOVERN` creates review work without approval; `REBUILD_PROJECTION` invokes the existing Pack Authority with explicit supersession.

## Product API and admission

The PostgreSQL Authority app adds:

- `POST /product/source-imports/preview`
- `POST /product/source-imports`
- `GET /product/source-imports`
- `GET /product/source-imports/{import_job_id}`
- `GET /product/source-imports/{import_job_id}/files`
- `POST /product/source-imports/{import_job_id}/resume`
- `GET /product/source-imports/{import_job_id}/preview`
- `GET /product/source-imports/{import_job_id}/work`
- `GET /product/source-imports/{import_job_id}/downstream`
- `POST /product/source-imports/reprocessing/apply`
- `GET /product/source-imports/reprocessing/{plan_asset_version_id}`
- downstream observation, candidate, governance, Card, Pack, lineage, evidence, and diff queries through the existing Source/MKAOS query owners.

Preview may perform repository resolution and deterministic discovery, but creates no SourceDocument, transform, Observation, Candidate, Card, or Pack and invokes no model Provider.

`resume` is the single idempotent recovery command for retryable discovery, file, intelligence, and reprocessing work; there is no second retry state machine. `data_import_admission` continues to distinguish `CAPABILITY_IMPLEMENTED` from `PROJECT_QUALIFIED`. Code presence never raises `DATA_IMPORT_READY`. Real-provider, longform, multi-book, and production flags remain independently false without matching runtime evidence.

## Acceptance

Tests use a controlled local bare Git repository through the same Git adapter contract to cover exact commit pinning, replay, incremental diff, rename/same content, binary, encoding, size policy, worker recovery, duplicate commands, selective analyzer upgrade, Source isolation, and PostgreSQL lineage through approved Card and Pack. A live GitHub and real Provider qualification is run only if credentials/network policy are configured and is reported separately.
