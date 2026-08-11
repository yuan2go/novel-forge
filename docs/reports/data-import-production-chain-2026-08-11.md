# Formal Data Import Production Chain

## Scope and evidence boundary

- Baseline branch: `feat/v7-content-intelligence-and-longform-proof`
- Baseline HEAD: `d602cd7bd3fbd068a84a1df71e594e086fddaad0`
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

The main missing capability was not Source upload or MKAOS CRUD. It was the formal L3 boundary between Evidence and Knowledge: versioned Observations, explicit analyzer identity, selective staleness propagation, and a machine-evaluated project admission gate.

## Canonical architecture

```text
L0 Verified immutable Blob receipt
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

## Deconstruction contract

The analyzer registry covers:

`structure`, `pacing`, `hook`, `reward_payoff`, `reader_promise`, `conflict`, `character_mechanism`, `relationship_mechanism`, `emotion_curve`, `foreshadowing`, `information_progression`, `serialization`, `commercial_logic`, `originality_copyright_risk`.

Supported scopes are `CHAPTER`, `CHAPTER_WINDOW`, `CHAPTER_GROUP`, `ARC`, `VOLUME`, `BOOK`, and `CROSS_BOOK_PATTERN`. Each Observation freezes scope, analyzer/schema/prompt/Skill/capability/provider/aggregation versions, execution evidence, confidence, evidence class, EvidenceSpan/lower-Observation inputs, and lineage. A whole book is not a default single provider call. Higher-level aggregation prefers existing Observations over rereading Source text.

For non-fixture execution, an eligible execution AssetVersion is necessary but not sufficient: its immutable binding must match the analyzer contract, scope, EvidenceSpan/lower-Observation manifest, and structured Observation output hash. MKAOS applies the same rule to Candidate payload, abstraction policy, Evidence manifest, and Observation identities. This prevents an unrelated provider receipt from being attached to a fabricated result.

## Replay, invalidation and cost control

- Exact Source content reuses the governed SourceDocument identity.
- Exact SourceTransform manifest reuses chunks and Blob receipts.
- Exact scope + analyzer contract + Observation hash reuses the existing Observation and consumes no new provider tokens.
- A desired-state reprocessing plan emits `REUSE`, `RECOMPUTE`, `RECOMPUTE_AGGREGATE`, `REABSTRACT`, `REGOVERN`, and `REBUILD_PROJECTION` items from current analyzer fingerprints and recursive dependency lineage.
- Only the changed dimension's Observation and its still-current downstream aggregate/Candidate/Card/Pack assets are invalidated. Unrelated dimensions and superseded history remain untouched.
- Successful Observation replacement resolves that Observation's OPEN invalidation; downstream invalidations remain OPEN until their owning abstraction, governance, or projection step is rebuilt.
- Reprocessing plans are deterministic and forbid provider execution.
- Command Kernel retry, lease takeover, output replay and fencing apply to Source intelligence Operations.
- KnowledgePack selector changes use an exact expected superseded Pack AssetVersion. The old Pack and AssetVersion become `SUPERSEDED`; history is never deleted.

## Data protocol and migration

Migration `20260811_0075_source_deconstruction_intelligence` adds:

- `authority_source_evidence_span`
- `authority_source_deconstruction_observation`
- `authority_source_deconstruction_observation_input`
- `authority_content_dependency`
- `authority_content_invalidation`
- `authority_source_reprocessing_plan`
- `authority_source_reprocessing_plan_item`

Project/workspace/AssetVersion/Operation constraint triggers enforce cross-project lineage. Tables contain no raw text columns. The migration is forward-only because the new rows are durable evidence and governance history.

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

`DATA_IMPORT_READY=false` until a controlled project produces non-fixture provider usage/cost evidence, approved non-fixture KnowledgeCard lineage, recovery evidence, and a passing machine admission report. `real_provider_proven`, `longform_proven`, `multi_book_proven`, and `production_verified` remain false unless separate evidence establishes them.

## Validation evidence

- `make validate`: PASS, including Ruff ratchet, 75-migration manifest, production reachability, architecture fitness, Authority-only Compose configuration, and required test collection.
- `make sync-skills-dry-run && make check-skills`: PASS; root Skills and generated runtime copies are synchronized.
- `NOVEL_FORGE_DATABASE_URL=.../nf_source_intel_binding_20260811_test make postgres-authority-test`: `177 passed, 60 subtests passed` on a fresh database migrated through 0075.
- `NOVEL_FORGE_DATABASE_URL=.../nf_source_intel_binding_20260811_test make test`: `2037 passed, 2 skipped` for Python and `11 passed` for the admin Web suite.
- Focused Source/MKAOS tests prove exact replay, duplicate command handling, worker restart recovery, analyzer-only invalidation, Observation evidence-closure enforcement, Candidate/Card/Pack lineage, Pack supersession, source isolation, and fixture admission blocking.

All evidence above is local fixture/protocol evidence. It establishes implementation and local validation, not real-provider, million-character longform, multi-book, CI, or production qualification.
