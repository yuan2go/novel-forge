# Source Intelligence Router Design

## Status and evidence baseline

This design is approved by the 2026-08-11 operator decision to classify every
new or invalidated logical document with one bounded model call and to replay an
identical classifier contract at zero model cost.  The implementation baseline
is `421e2f60e4876022c8137e9ddadfd453277fb80f` on
`feat/v7-content-intelligence-and-longform-proof`.

The current production path already has governed Git discovery, immutable Blob,
SourceDocument, SourceTransform, SourceChunk, Observation, MKAOS Candidate,
PostgreSQL AssetVersion, Command Kernel, PEP, budget, Evidence and trace
boundaries.  This change extends those owners.  It does not add another source
database, model execution plane, Agent, or knowledge authority.

## Confirmed breakpoints

1. `SourceImportPolicy.analysis_profile` currently participates in the import
   policy hash and repository snapshot identity.  One job-level value is then
   applied to every transformed file.
2. `plan_analysis_tasks()` binds every non-copyright dimension to
   `hot-novel-deconstruction`, and PEP materializes the same generic Skill text
   even when `AnalyzerContract.skill_id` differs.
3. snapshot/file reuse bypasses analysis admission.  The PEP cache is scoped to
   an Operation, so a new job cannot rely on it for cross-job semantic replay.
4. SourceTransform is file-scoped and its chunk contract loses logical-document
   semantics.  Treating that scope as a Book would permanently encode a false
   assumption.

## Boundary decisions

### Source identity

`SourceImportPolicy` owns only connector, byte, normalization and chunking
policy.  Its hash continues to participate in repository snapshot identity.
Classifier, routing, Analyzer, Prompt, Skill and methodology versions never
participate in SourceDocument, SourceTransform, SourceChunk, Blob or repository
snapshot identity.

### Analysis identity

`SourceIntelligencePolicy` separately freezes classifier, signal, sampling,
logical-document boundary and routing policy versions plus confidence and margin
thresholds.  A governance override is stored in this analysis policy envelope,
never in Source identity.

Analysis identity is the immutable chain:

```text
LogicalDocumentScope + SourceChunk manifest
  -> SourceContentProfile AssetVersion
  -> SourceAnalysisPlan AssetVersion
  -> AnalyzerContract + exact Skill methodology digest
  -> Observation AssetVersion
  -> MKAOS Candidate lineage
```

Every edge is stored in the existing PostgreSQL content-dependency graph.
Superseding a Profile or Plan creates invalidations for active descendants.

## Logical-document contract

This release introduces an explicit `LogicalDocumentScope` protocol.  The
default resolver emits `FILE_DOCUMENT`, not `BOOK`, and freezes its boundary
policy version, SourceTransform, ordered SourceChunk versions and scope hash.
Classification can report `boundary_review_required`, `suspected_document_count`
and `MIXED` without silently analyzing a suspected collection as one Book.

Full anthology/book/section splitting is deferred because it requires new Blob
span ownership, title hierarchy and cross-file assembly semantics.  Future
resolvers can emit multiple scopes for one transform without changing Profile,
Plan, Observation or MKAOS identities.

## Classification

The classifier receives a bounded, stratified beginning/middle/end sample from
governed SourceChunk objects.  PostgreSQL stores only sample span identities,
hashes and deterministic signals; Source text remains object-store-only.

Deterministic evidence includes media/format metadata, byte and character
measures, heading/paragraph/dialogue/citation/list/table/year/first-person
features, generic path tokens and structural marker counts.  Paths are hints,
not routing rules.  No repository, title, author or sample-specific mapping is
permitted.

The PEP capability `source.content.classify` returns a bounded taxonomy result:

- `WEB_NOVEL`
- `PUBLISHED_FICTION`
- `CLASSIC_LITERATURE`
- `WRITING_THEORY`
- `PROFESSIONAL_KNOWLEDGE`
- `HISTORY_SOCIAL_SCIENCE`
- `BIOGRAPHY_MEMOIR`
- `PHILOSOPHY_ESSAY`
- `PLATFORM_RULES`
- `UNKNOWN`
- `MIXED`

Automatic admission requires a supported non-UNKNOWN/non-MIXED type, confidence
at or above the policy threshold, top-two margin at or above the margin
threshold, no boundary review and a valid Provider/fixture evidence class.
Otherwise the Profile is committed as `NEEDS_REVIEW` and no AnalysisPlan or
Analyzer Operation is admitted.

A manual override still runs and retains the classifier result.  It requires an
exact `LogicalDocumentScope` hash, explicit type, reason and governance decision
reference and produces a new Profile AssetVersion with
`resolution_mode=GOVERNANCE_OVERRIDE`.  An Import-level request can therefore
target one governed LogicalDocument but cannot silently force every document in
an heterogeneous Repository onto one profile; a missing/stale target fails into
governance review.

## Resolver and methodologies

The resolver maps a routable content type to a versioned profile whose analyzer
list is dimension-specific.  Profiles may use more than one Skill.  The
required production routes are:

| Content type | Primary methodology | MKAOS target |
|---|---|---|
| Web Novel | `hot-novel-deconstruction` | knowledge |
| Published Fiction | `published-fiction-craft-analysis` | template |
| Classic Literature | `classic-literary-depth-analysis` | knowledge |
| Writing Theory | `multidisciplinary-knowledge` | rule |
| Professional Knowledge | `multidisciplinary-knowledge` | knowledge |
| History / Social Science | `multidisciplinary-knowledge` | knowledge |
| Biography / Memoir | published-fiction craft plus multidisciplinary knowledge | knowledge |
| Philosophy / Essay | `multidisciplinary-knowledge` | rule |
| Platform Rules | `platform-strategy-os` | rule |

The registry reads canonical root `skills/<skill-id>/SKILL.md`, validates the
frontmatter identity and freezes the exact bytes, declared methodology version
and SHA-256 digest.  The digest is part of `AnalyzerContract.fingerprint`, plan
identity, PEP input/cache identity, materialization evidence and Observation
lineage.  A missing file, identity mismatch or digest drift fails closed before
Provider execution.

PEP receives the exact methodology text; `skill_id` is no longer an audit-only
label.  Classifier methodology remains a separately versioned built-in
classifier contract because none of the fiction/knowledge Skills describes
source taxonomy classification.

## Runtime and recovery

```text
Source Import discovery
  -> immutable Source/Normalize/Chunk (new content only)
  -> LogicalDocument profiling Operation
       -> deterministic signals + sample manifest
       -> ExternalEffect + PEP classification
       -> SourceContentProfile Authority commit
  -> deterministic Analysis Planning Operation
       -> exact root Skill materialization
       -> SourceAnalysisPlan Authority commit
  -> per-plan Analyzer Operations
       -> Observation Authority commit
  -> MKAOS extraction Operations
       -> existing review/approval/Card/Pack Authority
```

Profiling and planning are durable Source Import work kinds with their own
Operation/Attempt/Lease/Fence state.  Worker restart resumes only incomplete
work.  Identical Profile, Plan, Observation and Candidate contracts are checked
at their owning PostgreSQL Authority before model dispatch, enabling zero-cost
cross-job replay.

Reimporting an identical repository with a newer intelligence policy reuses the
snapshot, SourceDocument, transform and chunks, then reconciles Profile and Plan
desired state.  A Profile or Plan upgrade invalidates descendants and schedules
only the necessary Analyzer/MKAOS work.

## PostgreSQL ownership

Migration `0081` adds Source Profile and Analysis Plan projections, their input
tables, analysis policy columns on import jobs, file projections, new work/status
values, dependency relationships and invalidation causes.  AssetVersion remains
the immutable business record; tables are query and constraint projections.
There are no raw-text columns.

Database triggers enforce project/workspace/SourceTransform/AssetVersion/
Operation scope.  Profile and Plan assets are source-analysis-only and forbidden
from generation context.  Observation commits must reference their exact
AnalysisPlan AssetVersion.

## Acceptance

Tests must prove:

- heterogeneous files in one repository resolve to different strategies;
- fiction and professional sources materialize different exact Skill text and
  digests;
- identical source and full analysis contract reuse Profile, Plan, Observation
  and Candidate without another model effect;
- classifier, routing, Analyzer, Skill version or Skill content digest changes
  reprofile/replan/recompute without Source/Transform/Blob writes;
- an existing transform can be reconciled through a new import analysis policy
  without refetching bytes;
- automatic production composition includes classifier PEP and methodology
  registry dependencies;
- UNKNOWN, MIXED, low confidence, missing capability and Skill drift stop before
  Analyzer admission;
- PostgreSQL exposes confidence, evidence, resolved type/profile, classifier,
  Skill version/digest, trace and downstream lineage.
