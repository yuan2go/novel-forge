# Formal Data Import Production Chain

## Scope and evidence boundary

- Baseline branch: `feat/v7-content-intelligence-and-longform-proof`
- Runtime extension start HEAD: `e528013dbc92c5b873821052c334722b05b4e2cb`
- Authority: PostgreSQL + Command Kernel + immutable/versioned AssetVersion.
- This change proves protocol behavior with unit and PostgreSQL integration fixtures. It does not claim real-provider, million-character longform, multi-book, or production-environment verification.

## Current implementation audit

| Decision | Existing capability | Result |
|---|---|---|
| KEEP | Verified Blob, content-hash SourceDocument identity, governed rights state, versioned transform manifest, immutable SourceChunk Blob references | Reused as L0-L2 canonical Source Authority. No second Source database or upload path was added. |
| KEEP | Command Kernel Operation/Attempt/Lease/Fence, PostgreSQL AssetVersion, PEP/ProductionExecutionGateway evidence, MKAOS Candidate/Decision/Card/Pack | Reused as the only production execution and knowledge authority. |
| EXTEND | Source Authority | Added stable EvidenceSpan, structured multi-scale Observation commits, analyzer contract identity, dependency lineage, invalidation and reprocessing plans. |
| EXTEND | MKAOS Authority | Added Observation-first Candidate lineage, full dependency edges through Card/Pack, and explicit Pack supersession/rebuild. |
| REFACTOR | Hot-novel prompt contract | Replaced one-report semantics with dimension-scoped Observation contracts and lower-scale aggregation. Markdown remains operator handoff only. |
| REPLACE | Production LocalStorage source/MKAOS flow | PostgreSQL Source/MKAOS Authority is canonical. Local `source_intake`, `analysis`, MKAOS routes/modules are classified `LEGACY_ISOLATED`; retained only while migration/UI consumers remain. |
| REMOVE | Duplicate production reachability | No safe code deletion was found without breaking legacy development/migration consumers. Production Authority app does not mount those legacy routes. |

The Authority protocol at the start of this runtime extension was already sound. The missing production capability was external orchestration: callers still had to prepare Blob/Chunk and Provider evidence themselves, reprocessing stopped at a plan, and no product job represented a frozen repository import.

## Canonical architecture

```text
SourceImport Job + exact Git commit + immutable repository manifest
  -> content/rights/policy-aware manifest diff and durable file work
  -> L0 verified immutable raw/normalized/chunk Blob receipts
  -> L1 governed SourceDocument (content-hash identity, rights policy)
  -> L2 versioned SourceTransform + immutable SourceChunk + stable EvidenceSpan
  -> L3 dimension/scale Observation AssetVersion
       source-based analyzers cite EvidenceSpan
       aggregate analyzers cite lower-scale Observation versions
  -> L4 anti-copy Abstraction / Knowledge Candidate
  -> L5 governance Decision + active KnowledgeCard
  -> L6 deterministic, explicitly versioned KnowledgePack projection
       -> governed ContextBundle selection
```

Raw bytes remain in Blob storage. PostgreSQL stores identities, policies, manifests, structured observations and abstract knowledge. `source_document`, `source_chunk`, `source_deconstruction_observation`, and `source_reprocessing_plan` are forbidden from generation context and retrieval paths. Only an approved KnowledgeCard selected into a governed pack is context-eligible.

The product runtime exposes preview/create/list/status/files/work/downstream/resume and reprocessing apply/status routes. Operational reads also expose open/resolved invalidations and deterministic KnowledgePack composition/supersession diffs. GitHub discovery runs as `source.remote.fetch` ExternalEffect, freezes the 40-character commit, manifest hash, import policy and governance-policy hash, and then admits one content-hash file Operation per changed payload. Its non-shell Git transport is owned by the Production Execution plane and is bounded by executable allowlist, timeout, non-interactive environment, and output-size policy. The production command accepts GitHub repositories only. Local Git is fixture-only; local file/directory, HTTP, PDF, DOCX and EPUB remain explicit unsupported capability boundaries.

## Deconstruction contract

The analyzer registry covers:

`structure`, `pacing`, `hook`, `reward_payoff`, `reader_promise`, `conflict`, `character_mechanism`, `relationship_mechanism`, `emotion_curve`, `foreshadowing`, `information_progression`, `serialization`, `commercial_logic`, `originality_copyright_risk`.

Supported scopes are `CHAPTER`, `CHAPTER_WINDOW`, `CHAPTER_GROUP`, `ARC`, `VOLUME`, `BOOK`, and `CROSS_BOOK_PATTERN`. Each Observation freezes scope, analyzer/schema/prompt/Skill/capability/provider/aggregation versions, execution evidence, confidence, evidence class, EvidenceSpan/lower-Observation inputs, and lineage. A whole book is not a default single provider call. Higher-level aggregation prefers existing Observations over rereading Source text.

For non-fixture execution, an eligible execution AssetVersion is necessary but not sufficient: its immutable binding must match the analyzer contract, scope, EvidenceSpan/lower-Observation manifest, and structured Observation output hash. MKAOS applies the same rule to Candidate payload, abstraction policy, Evidence manifest, and Observation identities. This prevents an unrelated provider receipt from being attached to a fabricated result.

## Replay, invalidation and cost control

- Exact Source content reuses the governed SourceDocument identity.
- Exact repository snapshot plus policy and rights decision reuses the repository manifest; the same Commit with a different rights decision receives a distinct governed snapshot while still sharing content identities.
- Repository updates reuse unchanged and renamed/same-content rows and admit work only for added or modified content.
- Exact SourceTransform manifest reuses chunks and Blob receipts.
- Exact scope + analyzer contract + Observation hash reuses the existing Observation and consumes no new provider tokens.
- A desired-state reprocessing plan emits `REUSE`, `RECOMPUTE`, `RECOMPUTE_AGGREGATE`, `REABSTRACT`, `REGOVERN`, and `REBUILD_PROJECTION` items from current analyzer fingerprints and recursive dependency lineage.
- Only the changed dimension's Observation and its still-current downstream aggregate/Candidate/Card/Pack assets are invalidated. Unrelated dimensions and superseded history remain untouched.
- Successful Observation replacement resolves that Observation's OPEN invalidation; downstream invalidations remain OPEN until their owning abstraction, governance, or projection step is rebuilt.
- Reprocessing plans are deterministic and forbid provider execution.
- Command Kernel retry, lease takeover, output replay and fencing apply to Source import and intelligence Operations. A crash after a durable Provider receipt reuses that ExternalEffect and settles the existing budget reservation instead of calling the Provider again.
- KnowledgePack selector changes use an exact expected superseded Pack AssetVersion. The old Pack and AssetVersion become `SUPERSEDED`; history is never deleted.

## Data protocol and migration

Migration `20260811_0075_source_deconstruction_intelligence` established Observation/invalidation/reprocessing protocol. Runtime migrations `0076` through `0080` add:

- `authority_source_evidence_span`
- `authority_source_deconstruction_observation`
- `authority_source_deconstruction_observation_input`
- `authority_content_dependency`
- `authority_content_invalidation`
- `authority_source_reprocessing_plan`
- `authority_source_reprocessing_plan_item`
- `authority_source_import_job`
- `authority_source_repository_snapshot`
- `authority_source_repository_file`
- `authority_source_import_work`
- normalized Blob identity on SourceTransform
- executable reprocessing item specs/dependencies/results and expanded actions
- cross-project Source/Transform/ImportJob scope closure and indexed foreign keys
- a rights/license/copyright governance hash in repository snapshot identity

Project/workspace/AssetVersion/Operation/Source/Transform/ImportJob constraint triggers enforce cross-project lineage. Tables contain no raw text columns. The migrations are forward-only because the new rows are durable evidence and governance history.

## Formal admission

`SourceAuthorityQuery.data_import_admission()` and `GET /product/source-governance/data-import-admission` compute a fail-closed project report from PostgreSQL evidence. The report requires proof for:

- Source deduplication and Blob integrity;
- rights/copyright eligibility;
- versioned transforms and stable EvidenceSpan addressing;
- versioned deconstruction contracts;
- Observation-to-approved-non-fixture MKAOS lineage;
- replay, mixed selective reprocessing, durable invalidation and recovery;
- source/cross-project isolation;
- non-fixture token and cost traceability.

Fixture observations intentionally make `data_import_ready=false`. The endpoint reports capability presence separately from project qualification and cannot upgrade fixture evidence into production proof.

## Legacy boundary

The following remain only because existing development/migration/UI consumers have not all moved:

- `src/novel_forge/modules/source_intake` and `src/novel_forge/modules/analysis`: `LEGACY_ISOLATED`.
- LocalStorage MKAOS route and modules: `LEGACY_ISOLATED`.
- Direct SourceChunk-to-Candidate application command: `MIGRATION_ONLY_DIRECT_EVIDENCE`; the production API requires Observation AssetVersions.

They are not mounted as canonical PostgreSQL Authority production entrypoints and must not be used to support `DATA_IMPORT_READY=true`.

## Current qualification ceiling

`DATA_IMPORT_READY=false` until a controlled project produces non-fixture provider usage/cost evidence, approved non-fixture KnowledgeCard lineage, recovery evidence, and a passing machine admission report. A live GitHub discovery against `https://github.com/octocat/Spoon-Knife` resolved `main` to `d0dd1f61b33d64e29d8bc1372a94ef6a2fee76a9`, produced manifest `sha256:c6883bd0106e8c72c1511f395be2a234377de3d8bdcbdd0cbfb3fa2414fd782c`, and identified the README content without fixture transport. A product Preview of the same public repository also completed through a PostgreSQL Operation and created no Source or knowledge assets. No model-provider credential was present. `real_provider_proven`, `longform_proven`, `multi_book_proven`, and `production_verified` remain false.

## Validation evidence

- `make validate`: PASS, including Ruff ratchet, 80-migration manifest through `0080`, production reachability, architecture fitness, Authority-only Compose configuration, nine-worker manifest, and required test collection.
- `make authority-test`: `1728 passed` in 668.89 seconds, covering unit, architecture, and acceptance gates.
- `make sync-skills-dry-run && make check-skills`: PASS; root Skills and generated runtime copies are synchronized.
- `NOVEL_FORGE_DATABASE_URL=.../novel_forge_source_import_0080_test make postgres-authority-test`: `177 passed, 60 subtests passed` in 105.61 seconds on the isolated PostgreSQL database.
- `NOVEL_FORGE_DATABASE_URL=.../novel_forge_source_import_0080_test pytest -q tests/integration/test_source_import_runtime_postgres.py`: `3 passed` in 13.98 seconds.
- Focused Source/MKAOS PostgreSQL tests prove exact replay, duplicate command handling, worker restart recovery, durable Provider-receipt reuse after a post-receipt crash, analyzer-only invalidation, Observation evidence closure, Candidate/Card/Pack lineage, Pack supersession/diff, source isolation, and fixture admission blocking.

All evidence above is local fixture/protocol evidence. It establishes implementation and local validation, not real-provider, million-character longform, multi-book, CI, or production qualification.
