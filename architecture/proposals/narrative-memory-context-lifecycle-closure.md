# Narrative Memory, Context, Retrieval, and Lifecycle Industrial Closure

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — GATE A IMPLEMENTED; GATES B–E UNRESOLVED**
>
> **NOT_RUNTIME_AUTHORITY**
>
> **REMAINING DESIGN SCOPE — NO RUNTIME AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Reality baseline: `8a1fc65bf5ecd80ec5ead17e6bf677d77a202e14`
Baseline implementation identity:
`sha256:25322467ecb8af4c2d5f48b395a11dc67a20dffaafceeba27989381a9d0a998b`

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-08",
  "review_due": "2026-10-07",
  "reality_baseline": {
    "sha": "8a1fc65bf5ecd80ec5ead17e6bf677d77a202e14",
    "implementation_tree_sha": "sha256:25322467ecb8af4c2d5f48b395a11dc67a20dffaafceeba27989381a9d0a998b"
  },
  "scope": [
    "src/novel_forge/modules/context_builder",
    "src/novel_forge/modules/chapter_authority/execution_gateway.py",
    "src/novel_forge/modules/production_execution",
    "src/novel_forge/storage/migrations",
    "src/novel_forge/workers/runtime_groups.py"
  ],
  "implemented_refs": [
    {
      "path": "src/novel_forge/modules/context_builder/governance.py",
      "symbol": "compile_effective_context_policy"
    },
    {
      "path": "src/novel_forge/modules/context_builder/domain.py",
      "symbol": "build_authority_context_bundle",
      "contains": "authority-context-bundle-v8"
    },
    {
      "path": "src/novel_forge/modules/context_builder/domain.py",
      "symbol": "replay_context_bundle"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/execution_gateway.py",
      "symbol": "_provider_effective_context_policy"
    },
    {
      "path": "src/novel_forge/modules/context_builder/reality_projection.py",
      "symbol": "project_role_context"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/provider_views.py",
      "symbol": "project_narrative_state_facts"
    },
    {
      "path": "src/novel_forge/modules/narrative_state/information.py",
      "symbol": "disclosed_fact_projection"
    }
  ],
  "superseding_refs": [],
  "remaining_decisions": [
    {
      "id": "digest-consumer-contract",
      "description": "DESIGN_REVIEW_REQUIRED: consumer-specific structured Digest coverage, deterministic generation and accepted-head timing.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/memory.py",
          "symbol": "NarrativeMemoryLayer"
        }
      ]
    },
    {
      "id": "diagnostic-retention-policy",
      "description": "DESIGN_REVIEW_REQUIRED: indexed per-source scan watermarks, replay/lookback bounds and observation receipt horizon.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/workers/runtime_groups.py"
        }
      ]
    },
    {
      "id": "representation-cutover-policy",
      "description": "DESIGN_REVIEW_REQUIRED: frozen coverage corpus, safe payload/header migration and fenced cutover/rollback behavior.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/production_retrieval.py"
        }
      ]
    }
  ],
  "remaining_work": [
    {
      "id": "gate-b-digest",
      "description": "Revision-bound structured Narrative Digest and freshness/head selection.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/memory.py"
        }
      ],
      "absent_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/digest.py"
        }
      ]
    },
    {
      "id": "gate-c-retention",
      "description": "Governed diagnostic projection, bounded retention and resumable GC.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/workers/runtime_groups.py"
        }
      ]
    },
    {
      "id": "gate-d-generations",
      "description": "Typed multi-source retrieval and active representation generations with prebuilt embeddings.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/production_retrieval.py"
        }
      ]
    },
    {
      "id": "gate-e-derived-lifecycle",
      "description": "Coverage-gated cutover, tombstone, grace and derived payload purge without protected-evidence deletion.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/embedding_projection.py"
        }
      ]
    }
  ]
}
-->

Gate A is implemented by the effective policy compiler, v8 Context manifest and frozen
replay contract, eligibility decisions and Provider admission accounting. Revision-bound
role projections now read accepted Reality through the same Context policy compiler.
World preparation also binds approved Foundation initial conditions and active Planning
inputs; Writer and Reader projections exclude undisclosed background state and private
causal explanations. These boundaries do not implement structured Digest or GC lifecycle.
Gates B–E
remain design scope. The detailed prescriptions below describe their intended
constraints; they cannot establish current capability or authorize implementation.

## 1. Reading and approval contract

This document is the canonical proposal for closing Narrative Memory, Context,
Retrieval, Diagnostic Retention, and derived-representation lifecycle gaps. It is not
evidence that any proposed type, table, operation, migration, worker, or guarantee
exists. Current runtime authority remains executable code, current migrations, runtime
wiring, tests, `architecture/reality-evidence.json`, and the canonical current-system
documentation.

The words `must`, `shall`, `owner`, and `gate` below specify the design that an
implementation PR must satisfy after approval. They do not change current behavior.
Implemented Gate A behavior is defined by its executable references above. The
remaining specification does not change production code, DDL, runtime instructions
or current-system documentation.

This is an umbrella work package. Implementation is split into PR-A through PR-E.
Each PR starts from the then-current merged `origin/main`, receives a fresh migration
identifier if it needs DDL, and must be qualified before the next dependent PR starts.

## 2. Mission, scope, and non-goals

The target closure is:

```text
Canonical PostgreSQL Authority
→ revision-bound Derived Narrative Memory
→ accepted-boundary selective retrieval
→ policy-compiled and provider-admissible working context
→ separately governed derived and diagnostic lifecycles
→ replayable, auditable evidence
```

It must sustain long-form production without allowing database presence to imply
retrievability or prompt eligibility, without treating a summary or embedding as
narrative truth, and without allowing operational noise to grow without bound.

This work package does not:

- change Accepted Actual, Canon, or Canonical Narrative State ownership;
- implement cold archive, immutable archival, or destructive retention for Authority
  or protected evidence;
- rewrite the Agent system, narrative methodology, or PostgreSQL Authority;
- add an external vector database;
- treat retrieval campaigns as a narrative roadmap;
- promise literary, human, reader, commercial, or million-character qualification;
- delete Context materializations, rejected-generation bodies, recap bodies, or bulky
  Source/MKAOS payloads; these are classified for later retention work only;
- introduce a generic lifecycle scheduler unless a concrete implementation seam proves
  that a narrower RuntimeJob executor is insufficient.

## 3. Current-reality delta

### 3.1 Evidence anchors

The current Chapter Memo uses the frozen ExecutionIntent and Provider admission, and
Canon support review uses final-prose evidence. These role contracts do not implement
the remaining structured Digest or retention/GC decisions below.

The design extends these current executable seams rather than creating replacements:

- `ContextClass` and `ContextCandidate` in
  `src/novel_forge/modules/context_contracts.py`;
- `ContextProfile`, `ContextSelection`, `select_context_candidates`, and
  `build_authority_context_bundle` in
  `src/novel_forge/modules/context_builder/domain.py`;
- `ProductionStageProfile` in
  `src/novel_forge/modules/production_preparation/policies.py`;
- production-execution `ContextPolicy` in
  `src/novel_forge/modules/production_execution/policies.py`;
- chapter-authority Context assembly in
  `src/novel_forge/modules/chapter_authority/handlers.py`;
- Provider admission and prompt rendering in
  `src/novel_forge/modules/chapter_authority/execution_gateway.py`;
- accepted-boundary metadata/lexical discovery and semantic reranking in
  `src/novel_forge/modules/context_builder/production_retrieval.py`;
- ExternalEffect-backed embedding projection and reconciliation in
  `src/novel_forge/modules/context_builder/embedding_projection.py`;
- embedding scheduling in `src/novel_forge/workers/chapter_authority.py`;
- Book-acceptance projection writes in
  `src/novel_forge/storage/book_authority_repositories.py`;
- bounded maintenance scans in
  `src/novel_forge/modules/command_kernel/maintenance.py` and the five explicit job
  kinds in `src/novel_forge/workers/runtime_groups.py`;
- current retrieval, embedding, and campaign schema in migrations
  `v20260820_0094_industrial_autonomous_novel_os.py`,
  `v20260821_0095_post_merge_correctness_repair.py`, and
  `v20260903_0107_retrieval_campaign_runtime.py`.

The current embedding scheduler selects missing projections from
`authority_narrative_retrieval_document` independently of a production read-selection
flag. This is sufficient evidence to require pre-cutover embedding construction for a
future inactive read generation. Gate D may need to widen its typed source contract,
but there is no demonstrated need for a `CUTOVER → semantic unavailable → rebuild`
window.

### 3.2 P0–P2 capability matrix

| Gate | Capability | Current state | Disposition | Delta closure |
|---|---|---|---|---|
| A | Context types and candidates | `IMPLEMENTED` | `KEEP` | Section/bucket/class limits and complete inclusion/exclusion decisions exist in the current selector. |
| A | Canonical assembly seam | `IMPLEMENTED` | `KEEP` | Existing assembly compiles frozen policy and emits a v8 manifest. |
| A | Eligibility/source isolation | `IMPLEMENTED` | `KEEP` | Stale/superseded/diagnostic denial precedes selection with explicit provenance. |
| A | Effective policy semantics | `IMPLEMENTED` | `KEEP` | Capability Pack/Execution, Stage and Context profiles compile to one effective contract. |
| A | Token accounting | `IMPLEMENTED` | `KEEP` | Provider/model accounting admission fails closed; estimates remain selection hints. |
| A | Manifest/replay | `IMPLEMENTED` | `KEEP` | v8 records compiler/admission evidence while v7 replay semantics remain frozen. |
| B | Structured Narrative Digest | `MISSING` | `NEW` | Add revision-bound, provenance-bound, rebuildable projections for scopes with real consumers. |
| B | Digest freshness/head selection | `MISSING` | `NEW` | Separate `CURRENT`, `VALID_AS_OF`, `SUPERSEDED`, and `INVALIDATED`; normal head advance preserves historical validity. |
| C | Diagnostic semantic classes | `PARTIAL` | `NEW` | Separate protected source evidence from redacted diagnostic projections. |
| C | Retention/deduplication/GC | `MISSING` | `NEW` | Add bounded aggregation, expiring observation receipts, dry-run, batch GC, resume, and audit. |
| D | Accepted-boundary retrieval | `EXISTING` | `EXTEND` | Preserve metadata-first and lexical-first discovery. |
| D | Semantic rerank/embedding recovery | `EXISTING` | `EXTEND` | Integrate Digest sources, source revision, inactive generation prebuild, and rebuild/reconciliation. |
| D | Retrieval campaign | `EXISTING` | `EXTEND` | Freeze representation/read-generation identity in intent, rounds, result, and replay. |
| D | Multi-source referential integrity | `MISSING` | `NEW` | Add typed FKs plus XOR and scope guards; never use an application-only polymorphic reference. |
| D | Active representation generation | `MISSING` | `NEW` | Exactly one active readable representation per logical source/range. |
| E | Derived representation assessment | `MISSING` | `NEW` | Assess only Digest/Retrieval/Embedding representations and their derived payloads. |
| E | Validated cutover/tombstone/purge | `MISSING` | `NEW` | Prebuild replacement, prove behavior, atomically switch read generation, then tombstone/grace/purge. |
| E | Authority/evidence destructive retention | out of scope | `NOT_APPLICABLE` | Mark protected; do not design archive or purge in this work package. |

### 3.3 Existing call paths and planned landing points

| Current production call path | Current limitation | Approved landing point |
|---|---|---|
| Chapter command → `handlers.build_context_bundle` → `build_authority_context_bundle` | Gate A complete; later Digest and generation contracts remain absent | Preserve compiler, accounting, complete decisions and frozen v8 manifest |
| Execution Gateway → rendered request → Provider ExternalEffect | Gate A admission is implemented; real Provider execution still requires separate current evidence | Preserve admission before ExternalEffect creation |
| Book acceptance transaction → accepted projection set → retrieval documents | flat text projections; no formal Digest identity or freshness | PR-B adds post-acceptance Digest projection through the existing operation/runtime boundary |
| Retrieval intent → accepted-boundary discovery → lexical/structured set → optional semantic rerank → frozen round/result | only AssetVersion source; no representation generation | PR-D adds typed Digest source and generation membership without changing truth ownership |
| Chapter-authority worker → schedule missing embedding → attempt/effect/reconcile | only current document source shape | PR-D extends source loading and permits PREPARING-generation embeddings before activation |
| Maintenance worker → five explicit RuntimeJob kinds → bounded scans | no diagnostic retention executor; maintenance is not a generic scheduler | PR-C adds only the narrow Diagnostic GC job/executor(s) actually required |
| No current derived-representation lifecycle | delete-first would be unsafe | PR-E adds plan/fence/receipts/read-pointer cutover/tombstone/grace/payload purge |

## 4. Final architecture and invariants

### 4.1 Authority topology

```text
Accepted Actual / Canon / Canonical Narrative State (Authority or governed projection)
                              │ immutable accepted boundary
                              ▼
             Narrative Digest Projection (non-authoritative)
                              │ typed source + provenance
                              ▼
       Retrieval Document / Lexical Index / Embedding Projection
                              │ active read-generation membership
                              ▼
              Context Candidates (eligible, scored, explained)
                              │ compiled policy + token accounting
                              ▼
             Context Manifest / Provider Admission Evidence
```

Operational diagnostics follow a separate path:

```text
RuntimeJob / Audit / ExternalEffect / worker event (source evidence)
                              │ redact + bound before persistence
                              ▼
       Diagnostic observation / aggregate (non-authoritative projection)
                              │ TTL / bounded batch / dry-run / audit
                              ▼
                 Diagnostic GC (never Narrative compaction)
```

### 4.2 Non-negotiable invariants

1. PostgreSQL remains the sole Canonical Narrative Authority.
2. Digest, retrieval document, lexical index, embedding, Context selection, and compact
   artifact are derived and non-authoritative.
3. Stored, retrieval-eligible, selected, promptable, and Provider-admissible are distinct
   states with explicit gates.
4. A Digest never becomes Canon. Canonical change must enter through the existing owner
   and acceptance command.
5. Accepted-head advance never invalidates a historically correct Digest. It changes
   its view from `CURRENT` to `VALID_AS_OF`.
6. Historical Digest identity and source lineage remain sufficient for exact-boundary
   retrieval, version-frozen replay, and future-only replan.
7. Only one representation is active and readable for one logical source/range in one
   read generation.
8. Metadata eligibility and accepted-boundary filtering precede lexical and semantic
   scoring. Vector similarity cannot introduce an otherwise ineligible candidate.
9. Replacement lexical and semantic projections are ready and validated before the
   active read pointer changes.
10. Context selection is allowlist-based. Diagnostic/debug/provider-noise classes are
    denied unless a versioned Agent/operation contract explicitly permits them.
11. ContextBundle budget is not the Provider request budget. A Provider call is admitted
    only under a complete, route-specific token accounting contract.
12. If the selected provider/model serialization cannot be bounded, Provider admission
    fails closed before an ExternalEffect is created.
13. Historical v7 Context replay uses frozen v7 semantics and is never recompiled under
    a newer policy, tokenizer, freshness, or budget rule.
14. Narrative Derived Lifecycle and Diagnostic Retention Lifecycle share only generic
    transaction, UoW, lease, fence, RuntimeJob, and observation primitives. Their data
    ownership, eligibility, receipts, and retention policy are separate.
15. The first destructive lifecycle clears only rebuildable derived payload or expired
    diagnostic/ephemeral payload that carries no recovery, audit, qualification, or
    Provider-effect proof duty.
16. Accepted Actual, Canon, Canonical Narrative State, required Authority/event lineage,
    Audit, Qualification Evidence, Recovery Evidence, Provider-effect Evidence, and
    required source lineage are `PURGE_PROTECTED` for this work package.
17. `PURGE_PROTECTED` does not authorize unbounded or secret-bearing persistence.
    Redaction and size bounds apply before evidence or diagnostics are written.
18. No purge occurs before validated compaction, atomic read cutover, retrieval
    verification, tombstone, and elapsed grace period.
19. Every lifecycle command is idempotent, lease/fence checked, bounded, resumable, and
    produces structured evidence. Duplicate invocation cannot double-cutover or purge.
20. A continuity-critical coverage or retrieval witness blocks `VALIDATED_READY`,
    cutover, and purge. An LLM judge cannot override that block.

## 5. Revised data-classification and retention matrix

`PURGE_PROTECTED` is deliberately narrow. `DEFERRED_RETENTION` means this work package
does not delete the payload and does not assert that it must remain hot or permanently
resident. `RETENTION_MANAGED` means Gate C or E owns a bounded policy now.

| Data class / example | Class | Owner | Rebuildable | Default Context eligibility | Retention treatment in this WP | Compact eligible | Purge eligible in this WP | Protection reason / split |
|---|---|---|---|---|---|---|---|---|
| Accepted Actual | Authority | Book Acceptance / accepted-history owner | no | accepted-boundary allowlist | `PURGE_PROTECTED` | no | no | accepted narrative truth |
| Canon facts/projection | Authority | Canon owner | deterministically rebuildable where lineage is complete, but authoritative read contract is protected | protected accepted context | `PURGE_PROTECTED` | no | no | current correctness and conflict decisions |
| Canonical Narrative State | Authority | Narrative State owner | deterministic where complete | protected accepted context | `PURGE_PROTECTED` | no | no | current correctness and future planning boundary |
| Authority/event lineage and acceptance decisions | Authority | owning Authority | no | evidence only unless contract requires | `PURGE_PROTECTED` | no | no | identity, ordering, causality, ownership |
| Audit, qualification, recovery, Provider-effect evidence | Evidence | respective governance owner | no | denied from narrative prompt by default | `PURGE_PROTECTED`, but only redacted bounded structure/identity/hash/decision | no | no | proof, reconciliation, exact-SHA claim scope |
| Digest header, identity, provenance, source-set hash, validation disposition | Derived | Narrative Memory Projection | yes from protected sources | eligible only through Retrieval | `PURGE_PROTECTED` header/lineage | no | no | prevents ambiguous replay, duplicate generation, and lost provenance |
| Digest structured payload | Derived | Narrative Memory Projection | yes | eligible by scope, boundary, state, policy | `RETENTION_MANAGED` | yes | yes after Gate E | payload separated from protected header |
| Retrieval document header, logical/equivalence key, generation membership, receipts | Derived | Retrieval Projection | yes, but retained for cutover/replay evidence | candidate metadata only | `PURGE_PROTECTED` identity/lineage; retired memberships remain non-readable | no | no | no parallel active representation; replay trace |
| Retrieval `content_text`, lexical materialization | Derived | Retrieval Projection | yes | only active generation and accepted boundary | `RETENTION_MANAGED` | yes | yes after Gate E | payload separated from document header |
| Embedding vector | Derived | Embedding Projection | yes with frozen model/route/source identity | semantic rerank only | `RETENTION_MANAGED` | yes | yes after Gate E | never Authority; rebuildable ExternalEffect output |
| Context Manifest header, selected IDs, policy/compiler/accounting identities, hashes, decisions | Evidence | Context assembly/Production Execution | no for exact historical decision | evidence, not narrative prose | `PURGE_PROTECTED` | no | no | exact replay/admission proof |
| Materialized Context body / rendered safe context / request envelope | Evidence | Production Execution | sometimes rebuildable from protected source versions | exact run only | `DEFERRED_RETENTION`; no deletion here | no in this WP | no in this WP | split from protected header; future governed retention required; credentials are never valid payload |
| Rejected generation body | Ephemeral | Chapter production | not necessarily | denied | `DEFERRED_RETENTION`; no deletion here | no in this WP | no in this WP | not Authority, but current revision/recovery contracts need separate review |
| Rejected-generation identity/hash/decision | Evidence | Chapter production/Quality | no | evidence only | `PURGE_PROTECTED` bounded fields | no | no | rejection and retry lineage |
| Recap body | Derived | Recap projection | rebuildability must be established per type | denied unless explicit context contract | `DEFERRED_RETENTION`; no deletion here | no in this WP | no in this WP | current semantics are not audited sufficiently for purge |
| Recap identity/source refs/hash/decision | Evidence | Recap owner | partially | evidence only | `PURGE_PROTECTED` bounded header | no | no | replay and source trace |
| Source/MKAOS bulky source or transformed payload | Authority | Source/MKAOS owner | source-dependent | denied from generation unless exact source policy permits; normally abstract-only | `DEFERRED_RETENTION`; no deletion here | no in this WP | no in this WP | rights, lineage, and transformation work is independent |
| Source/MKAOS identity, rights, hashes, lineage, decisions | Evidence | Source/MKAOS owner | no | evidence only | `PURGE_PROTECTED` | no | no | copyright, provenance, legal/rebuild source identity |
| RuntimeJob state/fence/checkpoint and structured recovery error envelope | Evidence | RuntimeJob Authority | no | denied | `PURGE_PROTECTED`, pre-redacted and bounded | no | no | retry/replay/fencing; no raw payload entitlement |
| Worker/provider diagnostic observation body | Diagnostic | Diagnostic Projection | yes from recent source evidence when available | denied | `RETENTION_MANAGED` | aggregate only | yes after TTL/reference checks | redacted and bounded before write |
| Diagnostic fingerprint/window aggregate | Diagnostic | Diagnostic Projection | yes | denied | `RETENTION_MANAGED` | yes | yes after retention horizon | operational trend, not proof Authority |
| Diagnostic observation idempotency receipt | Ephemeral diagnostic control | Diagnostic Projection | replaceable by bounded scan/window rules | denied | `RETENTION_MANAGED` with explicit horizon | aggregate/delete | yes | cannot become a permanent per-event table |
| Build/CI output and tool debug output | Ephemeral | build/runtime environment | yes | denied | TTL/outside Narrative lifecycle | no | yes when not retained qualification evidence | qualification summary/hash is stored separately |

## 6. Gate A — Context Governance Closure

### 6.1 One canonical assembly seam

Gate A keeps `build_authority_context_bundle` and its direct selection helpers as the
canonical seam. A `ContextAssembler` class is permitted only if it hides material
policy compilation, token accounting, or persistence orchestration behind a smaller
stable interface. A forwarding class that merely calls the existing functions is
forbidden.

The canonical flow becomes:

```text
typed stored artifacts
→ candidate construction
→ eligibility / freshness / source-policy filtering
→ deterministic effective-policy compilation
→ deduplication by logical source and equivalence key
→ required-first section/bucket/class selection
→ permitted truncation with provenance
→ ContextBundle accounting
→ immutable Context Manifest
→ complete Provider admission accounting
→ ExternalEffect admission or fail-closed result
```

Every candidate receives stable fields for source kind and ID, logical source key,
source revision/hash, accepted boundary, Context class, section, bucket, token cost,
required/optional disposition, eligibility state, provenance, and deterministic
tie-break identity. Existing AssetVersion candidates remain supported.

Default-denied inputs include build logs, stack traces, raw exceptions, Provider debug
payloads, retry chatter, tool debug output, SQL/debug logs, obsolete revisions,
rejected generations, superseded planning, unrelated workflow artifacts, and every
unknown asset/context type. An Agent or operation contract may allow a diagnostic type
only for a diagnostic/recovery task; that permission never leaks into a prose context.

### 6.2 Effective Context policy compiler

The compiler is a pure, versioned contract. It consumes immutable snapshots of:

1. Capability Pack and Production Execution `ContextPolicy`;
2. `ProductionStageProfile`;
3. `ContextProfile`;
4. command/requested Context limit, which may only reduce a limit;
5. Provider route capability constraints relevant to Context representation.

It emits one `EffectiveContextPolicy`, a compiler receipt, or a typed fail-closed error.
The compiler rules are:

| Conflict | Deterministic rule |
|---|---|
| allowed types | intersection of every applicable allowlist; absence is not implicit permission |
| denied types/modes | union; deny wins over allow and required |
| total, section, bucket, and class limits | minimum of every applicable positive limit; a caller can narrow, never widen |
| raw-source ratio/risk | most restrictive limit and mode |
| compression/truncation | permitted only when every applicable policy permits the exact method for that class |
| required sources/types | union after alias normalization; each item must survive all denies and be uniquely satisfiable |
| required item conflicts with deny | compile error `CONTEXT_REQUIRED_SOURCE_DENIED` |
| required items exceed any effective limit | admission error `CONTEXT_REQUIRED_BUDGET_UNSATISFIABLE` |
| missing/unknown policy identity or unsupported version | `CONTEXT_POLICY_UNRESOLVED`; fail closed |
| ambiguous aliases or duplicate policy identity with different hash | `CONTEXT_POLICY_IDENTITY_CONFLICT`; fail closed |

An unspecified per-section limit does not create an unlimited section. It falls back to
the most restrictive applicable safety ceiling and the total limit. Section, bucket,
and class budgets are all enforced; satisfying one never permits exceeding another.

The new Manifest freezes:

- every input policy ID, version, content hash, and snapshot reference;
- compiler identity/version and normalized compiler inputs;
- the complete compiled allow/deny/required sets;
- total, section, bucket, and class limits;
- source, compression, truncation, and dedupe rules;
- compile result and reason codes.

### 6.3 Selection, truncation, deduplication, and observation

Selection remains deterministic. The sort key is frozen by manifest version and must
end in a stable unique identity. Required candidates are processed before optional
candidates, but being required does not bypass denial, staleness, provenance, or any
budget.

Deduplication uses the logical source/equivalence key, not text equality alone. It emits
a winner, loser, equivalence basis, and `DUPLICATE_REPRESENTATION` reason. A candidate
whose representation is not in the active read generation is rejected before ranking.

Truncation is type-specific and deterministic. It is forbidden for protected Context
classes and for any candidate without a declared truncation strategy, source coverage,
and resulting content hash. Partial arbitrary string slicing is not a semantic
compaction method.

Every candidate has exactly one final decision:

```text
SELECTED | DROPPED | TRUNCATED_THEN_SELECTED | ERROR_REQUIRED_UNAVAILABLE
```

Reason codes include at least denied type, wrong project/book, wrong accepted boundary,
stale/invalidated, superseded representation, wrong read generation, missing
provenance, duplicate representation, section limit, bucket limit, class limit, total
Context limit, source risk, wrong workflow stage, wrong allowed use, invalid accounting,
and explicit contract exclusion.

The Manifest and metrics record:

```text
total_candidate_tokens
accepted_tokens
tokens_by_section
tokens_by_bucket
tokens_by_class
candidate_count
accepted_count
dropped_count
truncated_count
decision_count_by_reason
source_revision
policy_input_identities
compiler_version
token_accounting_identity
```

### 6.4 Provider/model-bound TokenAccounting contract

Generic `len(text) / 4`, UTF-8 byte ratios, or similar estimates may be retained only
for ranking or early pessimistic screening. They are not a hard Provider admission
guarantee.

`TokenAccountingContract` freezes:

- provider and route identity;
- model identity and revision/alias resolution evidence;
- tokenizer/accounting implementation identity and version;
- message serialization/framing version;
- tool and output-schema serialization version;
- accounting method: exact tokenizer or conservatively proven upper bound;
- evidence/calibration identity for an upper-bound method;
- model context limit;
- output reserve policy;
- safety-margin policy and amount;
- unsupported content/multimodal cases;
- result precision: `EXACT`, `PROVEN_UPPER_BOUND`, or `UNPROVEN`.

Two separate budgets are mandatory:

```text
ContextBundle budget
  = selected narrative working-memory content only

Complete Provider admission budget
  = system instructions
  + runtime/role/Skill instructions
  + tool definitions
  + input/output schemas
  + request/message envelope
  + ContextBundle
  + non-context task payload
  + output reserve
  + safety margin
```

Admission requires the complete sum to be less than or equal to both the selected
route/model limit and the applicable execution/cost policy limit. If any serialized
component cannot be counted or conservatively bounded for that exact provider/model,
the result is `UNPROVEN` and the call fails closed before ExternalEffect creation.
Observed Provider usage is recorded for reconciliation and calibration; it does not
retroactively prove pre-admission correctness.

### 6.5 Manifest versioning and replay

The current `authority-context-bundle-v7` and
`authority-context-selection-v2-four-class` semantics are frozen as a legacy replay
implementation. A new manifest/bundle version must use an explicit version dispatcher.

Historical v7 replay:

- consumes the exact v7 inputs and frozen ordering/estimate rules;
- never invokes the new policy compiler or TokenAccounting contract;
- never reinterprets v7 freshness, class, or budget decisions;
- verifies historical hashes and emits a replay comparison;
- is allowed to report that v7 lacked a new proof, but cannot rewrite the old result.

New manifests freeze the effective policy, accounting contract, read generation,
candidate decisions, selected payload hashes, and complete Provider admission receipt.

## 7. Gate B — Structured Narrative Digest

### 7.1 Authority boundary

The Narrative Digest is a schema-validated projection of accepted sources. It can be
programmatically derived, LLM-assisted, or mixed, but every field declares derivation
mode and provenance. It cannot activate a plan, accept a chapter, change Canon, or write
Canonical Narrative State. A missing or failed Digest never prevents the canonical
accepted-state read path.

Deterministic fields are projected first. LLM-derived fields remain explicitly marked
and must pass structural and source-coverage validation. A retry creates or resumes the
same idempotent projection identity; it cannot create competing current truth.

### 7.2 First-version scopes are consumer-driven

Gate B implements only scopes used by a current production Context/Retrieval consumer:

| First-version scope | Current consumer and evidence | Payload responsibility |
|---|---|---|
| `CHAPTER` | accepted-boundary chapter generation/review retrieval; current L3/L4 retrieval documents and `chapter_episodic_summary` candidate type | accepted chapter summary, nested scene outcomes, revealed facts, world/timeline/location changes, causal consequences |
| `CHARACTER_STATE` | character/entity filters and continuity Context; current `character_ids`, state facts, and L1/L2 channels | character deltas, knowledge, goal/status/location changes, continuity constraints |
| `RELATIONSHIP_STATE` | relationship filters and continuity Context; current `relationship_ids` channel | trust/power/alignment/obligation changes and evidence boundaries |
| `CONTINUITY_THREAD` | obligation and long-distance fact retrieval; current `obligation_ids`, foreshadow/clue/state facts | open/resolved thread, setup/payoff/clue/foreshadow/obligation status, due/closure evidence |

Standalone `SCENE` is deferred because current production retrieval is chapter-anchored;
scene data is nested in `CHAPTER` v1. `ARC` is deferred because current accepted arc
projection and L5 retrieval already serve the consumer, and another Arc digest would
duplicate state without a proven need. `VOLUME` is deferred because no current
production retrieval call requests a Volume Digest. These are design extension points,
not schema values, qualified capabilities, or placeholders that must be populated.

### 7.3 Structured payload contract

Each first-version payload is bounded and typed. Applicable fields include:

```text
summary
scene_outcomes
character_state_changes
relationship_changes
revealed_facts
world_state_changes
timeline_events
causal_consequences
location_changes
foreshadowing
clues
open_threads
resolved_threads
reader_promises
obligations
continuity_constraints
```

Not every scope owns every field. The schema defines allowed/required fields by scope,
cardinality and byte limits, stable fact/thread/entity identifiers, accepted chapter
coordinates, and per-field provenance. An unbounded catch-all JSON object is forbidden.

### 7.4 Digest identity and source model

Digest identity is the canonical hash of:

```text
project_id
book_id
branch_identity (= current book_run_id; no new generic branch Authority)
scope_type
scope_key
accepted_from_chapter
accepted_through_chapter
source_set_hash
payload_schema_version
generator_identity
generator_version
```

`source_set_hash` is computed from a sorted list of typed source identities, source
revisions/content hashes, accepted coordinates, and derivation roles. Digest rows are
immutable. A retry with the same identity is idempotent; a different source set,
schema, or generator is a different Digest.

The proposed storage split is:

- Digest header: identity, scope, accepted range, source-set hash, schema/generator
  identity, timestamps, disposition, operation/attempt/fence, and payload hash;
- Digest source membership: typed FK to each accepted source AssetVersion plus role,
  revision/hash, and accepted range;
- Digest payload: bounded schema-validated structured payload, derivation annotations,
  and validation hash;
- Digest head pointer: one pointer for each `(project, book, book_run, scope_type,
  scope_key)` logical scope.

The header/source/pointer is protected lineage; the payload is rebuildable and managed
by Gate E.

### 7.5 Freshness and disposition state model

The public `DigestFreshness` model is:

| State | Meaning | Retrieval/replay behavior |
|---|---|---|
| `CURRENT` | valid Digest selected by the logical-scope head pointer, and its accepted boundary equals the canonical accepted head bound by that pointer | eligible for current-head retrieval |
| `VALID_AS_OF` | valid Digest for an earlier accepted boundary, or a valid non-head boundary explicitly requested | eligible for matching historical accepted-boundary retrieval, exact replay, and future-only replan |
| `SUPERSEDED` | another validated Digest or representation replaced this one for the same logical scope and exact accepted boundary | excluded from normal retrieval; addressable by frozen historical manifest/round |
| `INVALIDATED` | source membership/hash, provenance, schema validation, or correctness has been revoked or proven corrupt | excluded from all new retrieval and Context; replay reports invalidation and cannot silently substitute it |

`CURRENT` is pointer-derived, not inferred from creation time. Stored disposition marks
valid, superseded, or invalidated rows; the head pointer plus accepted boundary exposes
`CURRENT` versus `VALID_AS_OF`. This prevents mass status rewrites and makes normal
accepted-head advancement safe.

The transitions are semantic, not age-based:

| Event | Prior view | Result |
|---|---|---|
| accepted head advances to a later chapter | `CURRENT` at the old boundary | `VALID_AS_OF`; the old Digest remains eligible for that exact historical boundary |
| new validated Digest is installed for the new head | no `CURRENT` at the new boundary | new row becomes `CURRENT`; earlier rows remain `VALID_AS_OF` |
| new schema/generator representation replaces a Digest for the same exact scope and boundary | `CURRENT` or `VALID_AS_OF` | old row becomes `SUPERSEDED`; frozen manifests/rounds may still address it |
| an accepted correction is appended at a later boundary | valid earlier Digest | remains `VALID_AS_OF` for the earlier boundary; the correction belongs to a later Digest |
| source identity/hash, provenance, or validation is proven false/corrupt | any valid view | `INVALIDATED`; never selected for a new request |

Changing a generator version by itself does not invalidate an older Digest. It creates
a different identity, and only a validated same-boundary replacement may supersede the
older representation.

On accepted-head advance:

1. the previous Digest remains valid;
2. it is exposed as `VALID_AS_OF`, never `INVALIDATED` or `SUPERSEDED` merely because a
   later chapter was accepted;
3. there may temporarily be no `CURRENT` Digest while the new accepted-head Digest is
   built;
4. canonical state remains readable during that gap;
5. a newly validated Digest atomically becomes the head pointer for that logical scope.

The database enforces one pointer per logical scope. A trigger or equivalent constrained
transaction verifies that the pointer target has the same project/book/book_run/scope,
is valid, and binds the pointer's accepted head. Two rows cannot both be `CURRENT`
because only the pointed row is current.

### 7.6 Generation, failure, and recovery

Digest generation enters through the existing Authority operation/attempt/lease/fence
runtime. Its output role is `derived_projection_candidate`. If a Provider is used, its
call uses the existing ExternalEffect and reconciliation path. The activation
transaction verifies the accepted head/source hashes again before installing the head
pointer.

Partial field extraction, lost worker, stale fence, and unknown effect do not publish a
payload or pointer. A bounded retry reuses the digest identity and missing-field plan.
A final failure records bounded structured evidence and leaves the canonical read path
unchanged. Rebuild selects a new generator/schema identity or reconstructs the same
identity only when its deterministic output hash agrees.

## 8. Gate C — Diagnostic Retention and GC

### 8.1 Separate lifecycle and source evidence

Gate C never compacts Narrative Memory. It projects operational observations from
existing runtime/effect/audit sources, while those protected sources retain their own
owners and policies. Deleting a diagnostic projection cannot mutate RuntimeJob,
Audit, Qualification, Recovery, or ExternalEffect evidence.

Diagnostic classes are:

```text
OPERATIONAL_DIAGNOSTIC
PROVIDER_DIAGNOSTIC
BUILD_CI_OUTPUT
EPHEMERAL_DEBUG_DATA
```

The source classification is stored independently:

```text
AUTHORITY_ACCEPTED_LINEAGE
AUDIT_EVIDENCE
QUALIFICATION_EVIDENCE
RECOVERY_EVIDENCE
PROVIDER_EFFECT_EVIDENCE
```

Only the first list enters ordinary diagnostic TTL/GC. A record cannot be protected
merely by calling raw logs “evidence.”

### 8.2 Pre-persistence redaction and bounding

All diagnostic ingestion passes through a versioned normalizer before persistence. It:

- drops credentials, authorization/cookie headers, secrets, API keys, signed URLs,
  request/response bodies, tool debug payloads, and arbitrary Provider payloads;
- allowlists structured fields such as error code/class, retryability, component,
  operation/job/effect identity, attempt/fence, timestamps, and bounded message excerpt;
- normalizes volatile identifiers before fingerprinting where policy permits;
- limits per-field length, object depth, array cardinality, and total serialized bytes;
- stores truncation/redaction decisions and policy version;
- rejects an observation that cannot be safely normalized.

Gate C also audits RuntimeJob and other protected error ingress. Protected recovery
evidence retains only the structured state transition, identity/fence, error
classification, retry decision, and required hashes. It does not retain unbounded stack
traces, headers, credentials, or raw Provider/debug data.

### 8.3 Bounded aggregation and receipt design

Repeated observations aggregate by:

```text
fingerprint
component / diagnostic class
bounded time window
first_seen
last_seen
occurrence_count
representative_sample
latest_bounded_context
```

The representative and latest samples are bounded and redacted. Updating the aggregate
does not append every stack trace.

An observation receipt exists only where exactly-once projection within a replay window
is necessary. Its identity binds source kind/ID/event or transition hash, normalizer
version, and aggregate window. Receipts are not permanent by default:

- active/retryable source receipts remain through the maximum retry/recovery horizon;
- terminal source receipts remain through `scan lookback + retry horizon + safety
  margin`;
- sealed-window receipts may be compacted into a bounded window summary and deleted;
- scanners never rescan events older than their explicit watermark/lookback;
- a small watermark per stream/partition may be protected; a permanent row per
  observation is forbidden;
- a receipt requiring longer retention must name a concrete unresolved recovery or
  qualification dependency and is reclassified as that source evidence, not as an
  immortal diagnostic receipt.

### 8.4 Retention and GC protocol

Each diagnostic policy declares class, normalizer version, aggregate window, hot
retention, receipt horizon, body expiry, protected-reference tests, batch size, and
deletion reason. GC is:

```text
ASSESS / DRY_RUN
→ lease and fence bounded batch
→ recheck expiry and protected/active references in transaction
→ delete or clear payload
→ write bounded batch summary/hash
→ advance checkpoint/watermark
```

It uses `FOR UPDATE SKIP LOCKED` or the repository's equivalent bounded lease pattern,
never a full-table long transaction. A crash can replay the same batch; deleted rows
are idempotently absent and aggregate/summary writes use stable keys. The GC audit
records policy, time range, counts, reason counts, aggregate hash, executor, operation,
attempt, and fence—not one immortal receipt per deleted observation.

The maintenance abstraction is not promoted into a generic scheduler. PR-C adds only
the minimum explicit RuntimeJob kind and executor needed for observation projection
and/or GC, using the current runtime group, lease, checkpoint, and failure paths.

## 9. Gate D — Retrieval Lifecycle Closure

### 9.1 Preserved retrieval order

The canonical order remains:

```text
accepted-boundary and read-generation eligibility
→ metadata/entity/timeline filters
→ deterministic/lexical candidate discovery
→ optional compatible semantic rerank
→ deterministic merge/tie-break
→ Context candidate with scores, reasons, and provenance
```

Semantic similarity is never the only channel and never introduces a candidate that
failed project/book, accepted range, source revision, Digest disposition, active
generation, entity/time, or policy eligibility. If a semantic embedding is unavailable
under a contract that requires it, retrieval fails closed. If the frozen contract says
semantic is optional, the recorded deterministic fallback is allowed and explicit.

### 9.2 Database-enforced typed source references

Gate D supports both existing AssetVersion sources and Narrative Digest sources. The
retrieval document therefore uses two nullable typed FKs:

```text
source_asset_version_id  FK → authority_asset_version
source_digest_id         FK → narrative_digest header
CHECK (num_nonnulls(source_asset_version_id, source_digest_id) = 1)
```

Equivalent portable XOR enforcement is acceptable. Application-only
`(source_kind, source_id)` is forbidden. Composite scope guards or triggers verify that
the chosen source belongs to the document's project/book/book_run, source revision and
accepted range. Embedding projection is FK-bound to the retrieval document and its
source/projection hash, rather than carrying an unchecked parallel polymorphic source.

Upgrade is backfilled and validated before constraints become `NOT NULL`/valid. The
existing AssetVersion source column remains the only populated arm for legacy rows;
new Digest documents populate only the Digest arm. Compatibility fields cannot become
two writable truth paths.

### 9.3 Logical representation, equivalence, and read generation

Definitions:

- **Logical source identity:** `(project, book, book_run, logical_source_key,
  accepted_from, accepted_through)`; it names narrative coverage, not a storage row.
- **Representation identity:** logical source identity + representation kind, source
  identity/revision, schema/generator/projection version, and payload hash.
- **Equivalence identity:** source-set hash plus deterministic coverage hash for the
  continuity-critical structured fields the replacement promises to preserve.
- **Read generation:** an immutable set of retrieval representation memberships for one
  project/book/book_run, selected by one active pointer.

Proposed constraints:

- read generation states are `PREPARING`, `VALIDATED_READY`, `ACTIVE`, `RETIRED`, or
  `INVALIDATED`;
- generation membership has a unique key on
  `(generation_id, logical_source_key, accepted_from, accepted_through)`;
- each membership references exactly one retrieval document;
- only one active-generation pointer exists per project/book/book_run;
- a pointer target must be `ACTIVE` and scope-matched;
- an active generation cannot contain an invalidated/superseded source;
- retrieval discovery joins the selected generation; table presence alone never makes
  a document readable.

This prohibits an old AssetVersion document and a replacement Digest document from
both entering the same candidate set for one logical source/range. Frozen historical
retrieval rounds/manifests keep their generation and representation IDs; exact replay
does not substitute the current generation.

### 9.4 Pre-cutover lexical and embedding construction

A replacement generation is populated while `PREPARING`. Its document payload and
generated lexical vector are created before validation. Compatible embedding
projections are then built or reconciled against those inactive documents using the
existing attempt/lease/fence/ExternalEffect semantics.

The current embedding scheduler already discovers missing document projections without
depending on a production-active flag. Gate D preserves that property and widens the
source loader to the typed Digest source. Production retrieval continues to join only
the active generation. Thus build visibility and read visibility are separate:

```text
Embedding worker visibility: PREPARING + VALIDATED_READY + ACTIVE documents
Production retrieval visibility: active generation membership only
```

Model identity, dimensions, projection version, route snapshot, source hash, document
hash, receipt, and failure status remain explicit. Partial indexing is observable but
cannot make the generation `VALIDATED_READY`. Lost-index rebuild is idempotent from the
protected header and Digest/source payload while it still exists.

### 9.5 Retrieval campaign and Context integration

Retrieval intent, every immutable campaign round, and final result freeze:

- accepted boundary;
- read generation ID;
- query/metadata constraints;
- lexical algorithm/version;
- semantic mode/model/dimensions/projection version;
- eligible document/representation IDs and source revisions;
- scores and reasons by channel;
- drop/dedup reasons;
- deterministic merge/tie-break version.

The final result yields candidates, scores, reasons, token cost, and provenance to Gate
A. It never returns an unexplained block that bypasses Context eligibility or budget.

## 10. Gate E — Derived Narrative Representation Compaction/Purge

### 10.1 Scope and protected boundary

Gate E is formally named **Derived Narrative Representation Compaction/Purge**. It
operates only on:

- structured Digest payloads;
- retrieval document payload/lexical materializations;
- embedding vectors and rebuildable projection payloads;
- their non-authoritative compact replacements.

It does not compact or purge Accepted Actual, Canon, Canonical Narrative State, active
planning Authority, required Authority/event lineage, Audit, Qualification, Recovery,
Provider-effect Evidence, or required source lineage. It also does not delete the
`DEFERRED_RETENTION` classes listed in section 5.

### 10.2 Eligibility

A source representation is eligible only when all are true:

- it is derived and marked `RETENTION_MANAGED`;
- its Authority/source lineage, hashes, accepted boundary, and rebuild contract exist;
- it is not the only representation required by an active or frozen historical
  manifest/round/recovery operation;
- no pending/running job, attempt, lease, effect, reconciliation, qualification run, or
  future-only replan references its payload;
- the replacement coverage is explicit and no accepted range is omitted;
- the policy permits this representation type and age;
- there is no legal/operational hold or continuity-loss witness.

Eligibility is a calculated fact captured in an immutable receipt. It is not a new
Authority status.

### 10.3 Compact artifact and manifest

A **Compact Artifact** is the prepared replacement set: Digest payloads, retrieval
documents/lexical materializations, compatible embeddings, and one immutable read
generation membership. It is derived, non-authoritative, and non-readable while being
prepared.

A **Compaction Manifest** is the protected plan header plus source and replacement
identities, policy/compiler versions, accepted coverage, equivalence identity, probe
corpus, operation/attempt/fence, state, and hashes of every required receipt. It does
not copy Accepted Actual, Canon, or Canonical Narrative State payloads.

### 10.4 Minimal persisted plan state

Only boundaries with distinct crash, recovery, fencing, or cutover invariants are
primary states:

| Persisted state | Why it must persist | Required evidence before transition |
|---|---|---|
| `PLANNED` | freezes source membership, target logical coverage, policy, operation, attempt, and fence before any replacement work | assessment/eligibility receipt |
| `PREPARING` | replacement rows and possibly in-flight lexical/embedding ExternalEffects exist; recovery must know what to resume/reconcile | prepared-artifact identity and build checkpoints |
| `VALIDATED_READY` | establishes the only state from which the active pointer may change | deterministic coverage receipt, probe-corpus retrieval receipt, complete required embedding receipt |
| `CUTOVER` | active read pointer has changed atomically, but post-cutover production-read verification/tombstone may not have completed | cutover transaction receipt with old/new generation IDs and fence |
| `TOMBSTONED` | old representation is durably non-readable and the grace clock has begun | post-cutover verification receipt and tombstone receipt |
| `PURGED` | protected header remains but managed payload is physically absent | grace/reference recheck and purge receipt |

There is no primary `ASSESSED`, `ELIGIBLE`, `LEXICAL_BUILT`, `INDEX_REBUILT`,
`VERIFIED`, or `PURGE_ELIGIBLE` state:

- assessment and eligibility are deterministic receipt contents attached to `PLANNED`;
- lexical build is a payload fact/checkpoint;
- embedding readiness is read from typed projection rows and summarized by a receipt;
- validation and post-cutover verification are immutable receipts;
- purge eligibility is recomputed from tombstone time, grace policy, active references,
  holds, and DB time immediately before purge.

A failed action leaves the plan in its last safe state with a bounded failure receipt.
Manual `BLOCKED` disposition may exist only for a non-retryable governance decision; it
is not another automatic phase.

Read-generation state and compaction-plan state are not duplicate workflows. A read
generation expresses whether one immutable representation set is discoverable;
the compaction plan records the fenced destructive operation, validation receipts,
grace, and purge outcome. Their transitions are cross-checked but owned separately.

### 10.5 Ordered lifecycle

```text
ASSESS / PLAN
→ PREPARE replacement
→ build lexical projection
→ prebuild or reconcile embedding projection
→ deterministic coverage validation
→ retrieval-behavior validation
→ VALIDATED_READY
→ atomic CUTOVER of active read-generation pointer
→ post-cutover verification through production read path
→ TOMBSTONE old representation
→ grace period
→ reference/hold/recovery recheck
→ PURGE managed payload
→ physical storage maintenance outside the cutover transaction
```

No deletion occurs before cutover, and no cutover occurs before the replacement's
required semantic projections are ready. A failed prebuild leaves the old generation
active. A failed post-cutover verification leaves the old payload intact and triggers a
fenced rollback of the read pointer when the old generation remains valid; it never
purges.

The cutover transaction locks the plan and active pointer, verifies the current fence,
revalidates `VALIDATED_READY`, makes the new generation active, retires the previous
generation, and records one immutable receipt. A duplicate request observes the same
pointer/receipt and returns replayed success. A stale fence cannot change either
generation.

Tombstone means excluded from every new read and from ordinary rebuild scheduling; it
does not mean payload deleted. Grace uses database time. Purge clears/deletes only the
payload rows and vectors, leaves protected header/lineage/tombstone/purge receipt, and
is idempotent when payload is already absent.

### 10.6 Deterministic coverage and retrieval-behavior qualification

Structured validation compares protected source/old representation and replacement for
sets and transitions covering at least:

```text
characters
relationships
timeline events/order
known/revealed facts
open/resolved threads
foreshadowing and clues
obligations
continuity constraints
accepted source lineage
```

Gate E also freezes a representative probe corpus in a schema-backed validation
artifact. It includes character, relationship, timeline, exact fact, open thread,
foreshadow/clue, obligation, and historical-callback probes. For each probe, the
contract defines required source/coverage identities, accepted-boundary eligibility,
minimum deterministic/lexical recall, optional semantic expectations, forbidden stale
or duplicate representation, and stable reason evidence.

Validation runs the same frozen probes before and after cutover and requires:

- every required recall witness remains present;
- no source beyond the requested accepted boundary appears;
- no old/new duplicate logical representation appears;
- no superseded/invalidated source is active;
- every result retains traceable provenance;
- continuity-critical structured coverage is equal or an explicitly stronger
  deterministic superset under the approved schema.

An LLM judge may add qualitative evidence but cannot admit destructive purge. Any
continuity-critical loss witness makes validation fail and prohibits
`VALIDATED_READY`, cutover, tombstone, and purge until a new replacement is prepared.

## 11. Authority ownership matrix

| Fact or action | Single owner | Non-owner participants |
|---|---|---|
| Accepted Actual and chapter acceptance | existing Book/Chapter acceptance Authority | Digest generator observes only |
| Canon | existing Canon owner | Digest/retrieval project accepted facts |
| Canonical Narrative State | existing Narrative State owner | Context reads exact boundary |
| Digest identity, payload validation, head pointer | Narrative Memory Projection owner | Agent/Provider creates candidate fields only |
| Retrieval document and read-generation membership | Retrieval Projection owner | Digest/AssetVersion are typed sources |
| Embedding projection/effect reconciliation | Embedding Projection runtime under existing operation/effect Authority | Provider returns candidate vector only |
| Effective Context policy and selection result | Context assembly contract | Capability/Stage/Context policies constrain; Agent cannot widen |
| Provider admission decision | Production Execution/Gateway policy boundary | tokenizer/accounting implementation supplies proof |
| Diagnostic projection/retention | Diagnostic Lifecycle owner | RuntimeJob/Audit/Effect remain source-evidence owners |
| Derived compaction plan, cutover, tombstone, payload purge | Derived Representation Lifecycle owner | Retrieval pointer and projection repositories participate transactionally |

A repository persists an owner's decisions but is not the owner. A worker coordinates
commands but is not Authority. A Provider and Agent emit candidate content or evidence;
neither may set Digest currentness, read generation, Context admission, or purge state.

## 12. Crash, retry, recovery, and cutover invariants

| Failure point | Required recovery behavior | Forbidden result |
|---|---|---|
| Context compile/selection retry | same frozen inputs/compiler version yield same decisions and hashes | policy widening or reordered selection |
| crash after Manifest, before Provider effect | replay finds Manifest/admission receipt and creates at most one effect | duplicate Provider call |
| Digest generation partial output | no head pointer; resume/retry same identity with current fence | partial/current Digest |
| Digest accepted head advances during generation | activation rejects stale target; generated Digest may remain `VALID_AS_OF` if its sources validate | old boundary mislabeled invalid or current |
| embedding effect unknown | query/reconcile through ExternalEffect; no blind resend | double bill/vector ambiguity |
| one document embedding fails in PREPARING generation | generation remains non-active; bounded retry or blocked failure | semantic availability gap after cutover |
| crash after all builds, before validation | receipts/checkpoints allow validation to resume | duplicate representation becomes readable |
| duplicate compaction invocation | stable plan key returns same plan or explicit conflict | concurrent plans for same logical coverage |
| stale compaction fence | all state/pointer/purge mutations reject | stale worker cutover/purge |
| crash before cutover commit | old generation stays active | partial membership swap |
| crash after cutover commit, before verification | plan resumes at `CUTOVER`; both payloads retained | purge or ambiguous active pointer |
| post-cutover verification failure | no tombstone/purge; fenced rollback when safe or block for operator | continuity-loss acceptance |
| crash after tombstone, during grace | resume grace/reference checks; old payload remains | early purge |
| crash during bounded purge | retry checks each payload idempotently; header/receipt persists | double mutation or lost lineage |
| worker restarts after purge | observes `PURGED` and absent payload as replayed terminal state | representation resurrection |
| diagnostic projection duplicate | stable source/window receipt increments once | double occurrence count |
| diagnostic GC interruption | resume bounded batch/checkpoint and recheck references | deletion of active/protected evidence |

All lifecycle mutations use existing UoW transactions, RuntimeJob or Authority
operation attempt identities, leases, fences, structured checkpoints, and bounded retry.
New generic infrastructure is not justified unless an implementation PR demonstrates
two independent real consumers and a smaller stable abstraction.

## 13. Database constraints and migration ownership

No migration is created by this specification. Every implementation PR uses the next
available migration ID after fetching its then-current `origin/main`; this document
does not reserve `0108` or any later number.

| PR | Proposed schema ownership | Required database invariants |
|---|---|---|
| PR-A | preferably none; Context/Manifest artifacts use existing AssetVersion/evidence persistence | contract-version checks, frozen manifest hashes, immutable/replayable version dispatch; add DDL only if current storage cannot preserve the full receipt without an unbounded blob |
| PR-B | Narrative Memory Projection | immutable Digest header; typed source membership FKs; bounded payload contract/version; unique digest identity; one logical-scope head pointer; pointer scope/boundary/disposition guards; operation/attempt/fence lineage; indexes by book_run/scope/boundary/state |
| PR-C | Diagnostic Lifecycle | diagnostic class/policy checks; bounded byte/count fields; unique fingerprint/window aggregate; expiring observation receipt; expiry/scan indexes; active/protected-source guards; bounded GC receipt/summary |
| PR-D | Retrieval Projection | nullable typed AssetVersion and Digest FKs with XOR; composite project/book/book_run/range guards; immutable generation membership; one active pointer; unique logical source/range per generation; source/projection hash matching; indexes for accepted boundary, metadata, FTS, and embedding recovery |
| PR-E | Derived Representation Lifecycle | unique active compaction plan per logical coverage; legal transition check/trigger; plan attempt/fence FK; mandatory receipt FK/check before `VALIDATED_READY`, cutover, tombstone, purge; DB-time grace/reference guards; payload/header split or equivalent safe physical-clear boundary |

Every DDL PR must prove fresh migration and supported upgrade. Backfills run in bounded,
observable steps where table size requires it. Constraints are added `NOT VALID` then
validated where necessary to avoid unsafe locks, and become enforced before the new
write/read path is enabled. A schema change cannot leave vOld/vNext writable in
parallel.

The migration authority remains the repository's existing migration registry. Domain
modules own semantics; storage repositories and migration constraints enforce them
near persistence.

## 14. End-to-end proof design

### 14.1 Narrative derived artifact

The first real vertical slice uses one accepted chapter from the PostgreSQL Book
acceptance path:

```text
Accepted Chapter
→ Canon / Narrative State accepted boundary
→ CHAPTER + related state/thread Digests
→ typed retrieval documents
→ metadata/lexical/semantic candidates
→ Context policy/filter/dedup/budget
→ provider-admissible chapter-generation Context
```

The same source then proves:

```text
old accepted retrieval representation
→ prepare Digest-backed replacement generation
→ lexical + embedding prebuild/reconciliation
→ structured coverage + frozen retrieval probes
→ atomic cutover
→ post-cutover production retrieval
→ tombstone + grace
→ physical clear of old retrieval text/vector payload only
→ post-purge retrieval/context equivalence
```

The test asserts characters, relationships, timeline, facts, threads,
foreshadow/clues, obligations, continuity constraints, accepted boundary, provenance,
and no duplicate/stale representation. It uses real PostgreSQL repositories and worker
runtime, not a fixture-only in-memory path.

### 14.2 Diagnostic payload

The first Diagnostic vertical slice executes a real maintenance RuntimeJob that emits a
bounded worker exception/operational observation:

```text
RuntimeJob failure source evidence
→ pre-persistence redaction and bounds
→ diagnostic fingerprint/window aggregate
→ duplicate observation replay
→ expiry assessment/dry-run
→ bounded leased GC
→ interrupted-GC resume
→ diagnostic payload absent
→ protected RuntimeJob recovery identity/state/hash still present
```

The proof includes secret-shaped headers/tokens and oversized exception material at the
ingress and verifies none is persisted in either diagnostic projection or protected
RuntimeJob evidence.

## 15. PR dependency and acceptance matrix

The umbrella work package is delivered as separate sequential/stacked PRs, never as one
long-lived implementation branch:

```text
PR-A Context Governance Closure
  └─→ PR-B Structured Narrative Digest
        └─→ PR-D Retrieval Lifecycle Closure
              └─→ PR-E Derived Narrative Representation Compaction/Purge

PR-C Diagnostic Retention + GC may proceed independently after its shared runtime
dependencies are available, but it does not block B/D design work and never shares
Narrative lifecycle state.
```

| PR | Depends on | Implementation acceptance before merge | Exact-SHA requalification before next dependent PR |
|---|---|---|---|
| A — Context Governance Closure | approved Spec, current main | policy compiler conflicts; section/bucket/class/total budgets; required preservation; optional eviction; stale/superseded/diagnostic rejection; dedupe/truncation reasons; provider/model-bound admission; v7 replay fixtures; real Provider gateway fail-closed integration | fresh + supported upgrade if DDL; PostgreSQL/context/replay/recovery; canonical validation; exact-SHA evidence |
| B — Structured Narrative Digest | merged A | four consumer-driven scopes only; structured projection; provenance/source-set hash; `CURRENT`/`VALID_AS_OF`/`SUPERSEDED`/`INVALIDATED`; head advance; rebuild; invalid source; partial failure/retry; chapter aggregation correctness; canonical read remains available | fetch new main/new worktree; fresh/upgrade PostgreSQL; operation/effect/recovery; exact-SHA evidence |
| C — Diagnostic Retention + GC | approved Spec and required merged runtime primitives | classification; redaction/size bound; no secrets; aggregation/dedup; receipt expiry; protected source never deleted; TTL/dry-run/bounded batch; active reference; interruption/resume; real RuntimeJob vertical slice | fetch new main/new worktree; fresh/upgrade PostgreSQL; RuntimeJob lease/fence/recovery; exact-SHA evidence |
| D — Retrieval Lifecycle Closure | merged B; merged A for Context integration | typed FK/XOR; accepted-boundary metadata/lexical/semantic order; Digest integration; active generation uniqueness; no duplicate old/new; inactive lexical/embedding prebuild; partial indexing and effect reconciliation; stale exclusion; loss/rebuild; campaign/replay generation freeze | fetch new main/new worktree; fresh/upgrade PostgreSQL; query-plan proof; embedding/provider recovery; Context E2E; exact-SHA evidence |
| E — Derived Narrative Representation Compaction/Purge | merged D; Gate C infrastructure may be reused only at primitive level | eligibility/dry-run; minimal state guards; prebuild/coverage/probe validation; atomic cutover; post-verify; tombstone/grace; reference protection; crash at every boundary; idempotent payload purge; post-purge semantic/retrieval proof; zero Authority/evidence deletion | fetch new main/new worktree; fresh/upgrade PostgreSQL; query plans; Compose/runtime/recovery; resource cleanup; canonical exact-SHA evidence |

After each merge, the next PR must:

1. fetch latest `origin/main`;
2. record exact baseline and implementation identity;
3. create a new isolated branch/worktree;
4. run baseline Reality/Documentation/Instruction/Test/Historical/architecture gates;
5. implement only that PR's gate;
6. run focused unit, integration, PostgreSQL, migration, concurrency, recovery, and
   replay tests before requesting merge;
7. run repository canonical validation, fresh and supported upgrade migration, relevant
   query-plan/Compose/resource-cleanup proof, and exact-SHA qualification;
8. mark unrun proof `NOT_RUN`, never inferred `PASS`.

## 16. Gate-level proof ceilings

Passing a PR proves only the implemented local/PostgreSQL engineering slice. It does not
prove real-provider quality unless credentialed exact-SHA evidence is actually run and
retained. It never proves long-form literary quality, human editorial acceptance,
reader response, commercial performance, or safe destructive archival of protected
Authority/evidence.

The umbrella acceptance gate is:

```text
CONTEXT_GOVERNANCE = PASS
STRUCTURED_NARRATIVE_DIGEST = PASS
DIAGNOSTIC_RETENTION_GC = PASS
SELECTIVE_RETRIEVAL = PASS
SEMANTIC_RETRIEVAL = PASS
DERIVED_REPRESENTATION_COMPACTION = PASS
DERIVED_PAYLOAD_PURGE = PASS
RECOVERY_REPLAY = PASS
POSTGRES_MIGRATION = PASS
AUTHORITY_INTEGRITY = PASS
EXACT_SHA_EVIDENCE = PASS
```

and:

```text
NO_PARALLEL_NARRATIVE_AUTHORITY
NO_RAW_DIAGNOSTICS_IN_DEFAULT_NARRATIVE_CONTEXT
NO_UNBOUNDED_CONTEXT_ASSEMBLY
NO_UNBOUNDED_DIAGNOSTIC_RETENTION
NO_UNVALIDATED_DESTRUCTIVE_PURGE
NO_STALE_RETRIEVAL_AS_ACTIVE_TRUTH
```

An umbrella `GO` is forbidden until every merged gate has current exact-SHA evidence.

## 17. Unresolved risks and trade-offs

These are implementation-time design checks, not permission to widen scope:

1. **Tokenizer availability and serialization fidelity.** Some Provider SDKs may not
   expose the exact tokenizer/framing. PR-A must either prove a conservative
   provider/model-bound upper bound or fail closed for that route. It must not silently
   fall back to character estimates.
2. **Context policy source duplication.** Current Context, Stage, and Execution policies
   overlap. The compiler closes behavior without moving ownership. A later ownership
   consolidation is not authorized here; PR-A must surface contradictory current
   policy inputs as failures rather than guess intent.
3. **Digest generator choice.** Deterministic projection is preferred. Any LLM-derived
   field adds Provider/retry/cost variability and must have a real consumer and a
   deterministic coverage validator.
4. **Book branch identity.** Current executable production uses `book_run_id`; the Spec
   binds to it. If main introduces a first-class branch Authority before PR-B, the PR
   must re-audit and either map or revise the Spec before DDL.
5. **Digest timing.** Asynchronous generation deliberately permits no `CURRENT` Digest
   briefly after head advance. Canonical state stays correct; Context contracts must
   state whether `VALID_AS_OF` is acceptable or whether the task waits/fails.
6. **Payload/header split upgrade cost.** Current retrieval text and generated search
   vector share the document table. PR-D/E must benchmark safe backfill and query plans;
   the split cannot create dual writable payloads.
7. **Embedding prebuild cost and provider availability.** Prebuild is architecturally
   possible with the current scheduler seam, but a policy-required semantic generation
   may stay PREPARING during Provider outage. Availability is preserved by retaining
   the old active generation, not by cutting over early.
8. **Frozen historical read generations.** Retaining headers/memberships has growth
   cost. This work package bounds bulky payload but intentionally keeps the small
   lineage required for exact replay. Archival of that lineage is out of scope.
9. **Diagnostic source scan ordering.** Current source tables differ in event ordering.
   PR-C must choose an indexable watermark/lookback per concrete source rather than
   invent a universal event bus.
10. **Observation receipt horizon.** Too short permits old duplicate projection; too
    long increases storage. PR-C must derive the horizon from actual max recovery,
    replay, and scan lookback settings and prove bounded growth.
11. **Cutover rollback concurrency.** A new accepted head or independent representation
    change during post-cutover verification could make rollback unsafe. PR-E must lock
    or compare the active pointer generation/fence and block for operator review rather
    than overwrite a newer generation.
12. **Probe corpus representativeness.** The frozen corpus proves named retrieval
    invariants for the qualification fixture, not all future narrative semantics.
    Coverage schema and production incidents may add probes only through versioned
    evidence; no probe may be weakened to manufacture a pass.
13. **Qualified semantic equivalence.** Exact structured coverage and required recall
    are necessary destructive gates. They do not establish prose equivalence or human
    narrative quality.

## 18. Approval boundary

Final approval of this Spec authorizes planning and implementation of PR-A only under
its listed acceptance gate. It does not authorize simultaneous PR-A–PR-E production
changes, reservation of migration numbers, protected-data archive/purge, or alteration
of current Authority ownership.

Remaining decisions require design review before their dependent contracts can be
implemented. Completed Gate A is governed by executable code and current evidence;
this retained proposal cannot supersede that behavior or confer qualification.
