# Classical Chinese corpus and Codex production validation

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — G1/G2 IMPLEMENTED; G3/G4 IN PROGRESS**
>
> **NOT_RUNTIME_AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Scope: bounded native ingestion, governed abstraction, exact knowledge consumption,
Codex account-entitlement execution, and four-arm creative validation
Reality baseline: `c2ff5775f9b636ad983f8b1c77425f3bd0f9aaf4`
Baseline implementation identity:
`sha256:4b4a0cbca7dccbaf8e09dc6032c30c5c3d5dd320679560f6d2a4a918643cf838`

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-19",
  "review_due": "2026-10-08",
  "decision_free_since": "2026-09-08",
  "reality_baseline": {
    "sha": "c2ff5775f9b636ad983f8b1c77425f3bd0f9aaf4",
    "implementation_tree_sha": "sha256:4b4a0cbca7dccbaf8e09dc6032c30c5c3d5dd320679560f6d2a4a918643cf838"
  },
  "scope": [
    "src/novel_forge/api/authority_dependencies.py",
    "src/novel_forge/modules/authority_security",
    "src/novel_forge/modules/book_design_authority",
    "src/novel_forge/modules/command_kernel/budget_runtime.py",
    "src/novel_forge/modules/context_builder",
    "src/novel_forge/modules/mkaos_authority",
    "src/novel_forge/modules/production_execution",
    "src/novel_forge/modules/source_import",
    "src/novel_forge/modules/story_planning_runtime",
    "src/novel_forge/storage",
    "src/novel_forge/workers/book_authority.py",
    "config"
  ],
  "implemented_refs": [
    {
      "path": "src/novel_forge/modules/authority_security/service.py",
      "symbol": "TrustedPrincipalResolver.resolve_book_formation_worker_principal"
    },
    {
      "path": "src/novel_forge/modules/production_execution/backends.py",
      "symbol": "CodexCliExecutionBackend"
    },
    {
      "path": "src/novel_forge/modules/source_import/classical_corpus.py",
      "symbol": "CorpusWorkSpec"
    },
    {
      "path": "src/novel_forge/modules/source_import/classical_corpus.py",
      "symbol": "parse_classical_work"
    },
    {
      "path": "src/novel_forge/modules/source_import/corpus_ingestion/narrative_execution.py",
      "symbol": "execute_reading"
    },
    {
      "path": "src/novel_forge/modules/command_kernel/creative_budget_scope.py",
      "symbol": "require_business_scope"
    },
    {
      "path": "src/novel_forge/modules/story_planning_runtime/execution.py",
      "symbol": "PostgresPlanningExecutionPreparer"
    }
  ],
  "superseding_refs": [],
  "remaining_decisions": [],
  "remaining_work": [
    {
      "id": "g3-bounded-analysis-and-consumption",
      "description": "Complete variable mechanism candidate sets, Chinese applicability selection and exact-context production evidence for all twenty works; the bounded curated chapter observation/review/repair path is implemented, with scripted engineering evidence only.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/source_import/analysis_profiles.py",
          "symbol": "plan_analysis_tasks"
        },
        {
          "path": "src/novel_forge/modules/mkaos_authority/domain.py",
          "symbol": "select_narrative_intelligence"
        },
        {
          "path": "src/novel_forge/modules/mkaos_authority/query.py",
          "symbol": "MkaosAuthorityQuery"
        }
      ]
    },
    {
      "id": "g4-creative-comparison-and-recovery",
      "description": "Run four exactly isolated knowledge arms through the canonical Formation-to-Acceptance chain, continue arm D to twelve chapters, inject one receipt-to-business-commit interruption, resume without duplicate inference, and export bounded comparison evidence.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/story_planning_runtime/execution.py",
          "symbol": "PostgresPlanningExecutionPreparer"
        },
        {
          "path": "src/novel_forge/modules/context_builder/domain.py"
        },
        {
          "path": "src/novel_forge/workers/book_authority.py",
          "symbol": "execute_story_formation_claim"
        }
      ]
    }
  ]
}
-->

Current scope review (2026-09-19): Provider routing now carries repair Operation lineage, separates benchmark challengers from production outcomes, and requires bounded bootstrap authorization before validation challenger calls. Shared priced/account-entitlement lanes retain finite call/token accounting and unknown entitlement monetary cost. These changes do not execute the twenty-work analysis or four-arm creative experiment: G3/G4 remain outstanding. No real-Provider, independent editorial or production evidence is added by this document review.

Prior implementation delta review at `b10a4a8c5cf6410ba1557ad850a90d12a632d9fe` (2026-09-13; code-agent review, not human qualification): The single-Book policy uses the same cumulative ledger for separate Source, design, early/late chapter and repair scopes. Author-guided Context compilation now keeps scoped fragment semantics and frozen provenance; it does not consume classical-source knowledge or establish any of the proposed four-arm outcomes. G3 and G4 remain outstanding. The relevant checks are native author Formation wiring and single-Book budget isolation; these are scripted engineering evidence, not real Provider or independent editorial evidence.

Prior lifecycle baseline retained for provenance: `abe2e0df7c817ed5faf1fd07839f19d796304371`, `sha256:4fdeaef231e3670b3ffe8240045ee0879f58e05d4a648bf74eec9c06f5fb8d03`. The earlier review below is preserved.


Current implementation review (2026-09-13): The changed Source and Provider budget seams now bind fixed experiment allocations, cumulative phase grants, curated target-Book use and retry receipts. This does not run or qualify the proposed four-arm classical-corpus experiment; G3/G4 remain outstanding. The Rain pilot authorization is separate from this proposal. No real Provider or independent editorial evidence is added by this review.


## 1. Decision and proof boundary

The approved implementation extends the existing Command Kernel, RuntimeJob,
Source/MKAOS, Planning, Context, ExternalEffect, Book and Chapter Authorities. It does
not add another corpus database, workflow engine, Provider runtime, budget owner, Canon
writer, acceptance writer, or qualification-only execution path.

The batch proves only a bounded local conversion of classical Chinese fiction and
poetry/prose sources plus a twenty-one-chapter controlled creative comparison. It does
not prove source-text copyright completeness, modern professional-text analysis, modern
web-fiction commercial performance, human editorial quality, real reader response,
million-character stability, or production deployment.

## 2. Frozen source and execution identity

The repository baseline is
`dd97911944a92aca9f511f3b4913beb2f7816956`. Source repositories are frozen as:

- `luoxuhai/chinese-novel@aecdc1a1b8153011f3446ebc5a0d89c3a24fc122`;
- `chinese-poetry/chinese-poetry@b8594f81a89752241442f2ce267d6f66f96704ee`.

Repository licenses and per-file provenance are recorded separately from the rights
decision for underlying editions, modern annotations, comments, and compilations. Raw
text remains local and is never a prose-generation input.

The first real execution candidate is the absolute executable
`/Applications/ChatGPT.app/Contents/Resources/codex`, CLI `0.153.4`, authenticated by
the existing ChatGPT account, with model `gpt-5.6-sol` and reasoning effort `high`.
Cache discovery is not qualification. The model, executable digest, relevant flags,
account authentication class, route, prompt/Skill/schema identities, and configuration
are frozen only after a successful production-Gateway probe. Failure does not select a
different model or billing method.

## 3. G1 — identity, approval, CLI, and budget lifecycle

### 3.1 Identity and approval

RuntimeJob claim and execution use the same trusted worker Principal. Admission retains
the initiating operator identity; governance decisions retain their exact reviewer or
AUTO policy identity.

Worker permissions are role profiles, not a shared approval superset. The Formation
execution role receives only its required execute permissions. AUTO decisions use a
separate project- and Formation-bound authorization whose immutable contract includes:

- project, workspace, Book, Formation and policy version;
- allowed approve/activate action names;
- exact candidate AssetVersion and content hash at decision time;
- authorizing operator, authorization reference and expiry/run boundary.

Manual mode persists any Foundation stage as `WAITING_APPROVAL`, completes the technical
RuntimeJob without consuming retry allowance, and retains the already-generated exact
candidate. Explicit approval and activation then schedule continuation from the same
frozen stage; they do not generate another candidate.

### 3.2 Account-entitlement accounting

`ACCOUNT_ENTITLEMENT` is a funding/accounting basis inside the existing Provider budget
and ExternalEffect lifecycle. It is accepted only for the controlled `codex-cli` route,
an explicit authorization reference, measured usage support, finite application-call and
token ceilings, and fail-closed reconciliation.

The monetary receipt is `availability=UNAVAILABLE`, `measurement=UNKNOWN`, never zero.
Measured terminal CLI usage is authoritative only after the model turn. Pre-call token
control remains an estimated/frozen admission ceiling and must be reported as such.
Application invocation, local CLI process, and observable model turn are separately
counted. Successful receipt replay adds no model invocation. Submitted failures and
permitted semantic repairs do.

The initial maximum application calls are 180 for the source/knowledge chain, 420 for
creative production, and 8 for model judging. Concurrency is at most two. A generated
budget manifest freezes the normal path, bounded repair branches, token estimates,
timeouts, and phase ceilings before corpus-wide model work; it may reduce but never
increase these limits automatically.

### 3.3 Context and process isolation

Each execution uses an empty isolated working directory, persistent operation-specific
receipt directory, `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, structured
output schema, read-only sandbox, no resume, no inherited project instructions/Skills/MCP,
and an environment allowlist that retains only the authentication material needed by the
existing account.

Evidence separately binds application AssetVersions, compiled provider view, stdin hash,
CLI argv/config hash, process receipt, JSONL events, terminal usage, last-message result,
and the limit of final Provider-request observability. No stdin hash is called a complete
remote request receipt.

## 4. G2 — work-aware native corpus ingestion

`SourceWork` and `SourceUnit` are Source Authority identities and version manifests, not
a new knowledge store. Their payloads reuse AssetVersion, authority blobs, operation
input lineage, SourceTransform, SourceChunk, reprocessing, invalidation and object-store
contracts. A narrow migration is permitted only where relational uniqueness, resume, or
query reconciliation cannot be enforced by existing Authority records.

The corpus profile registry has two governed parser families:

- `chinese-novel-html.v1` reads `info.json`, maps catalogue position to numeric HTML
  filename, parses block/`br` boundaries and character references, rejects scripts and
  markup noise, and classifies preface/body/appendix without lexical filename sorting;
- `chinese-poetry-json.v1` has explicit shape adapters for the ten frozen collections,
  preserves poem/entry/line boundaries, aggregates multi-file collections, and excludes
  notes, comments, pinyin, author introductions and abstracts from body text while
  retaining them as typed metadata where allowed.

Every unit records work identity, order, kind, title, author, raw file hash, parser and
normalization version, JSON Pointer or HTML source range, original-to-normalized mapping,
and normalized hash. Traditional/simplified conversion is a versioned retrieval
projection only.

The machine corpus manifest reports per work: selected paths, unit/body counts, raw and
normalized character counts, missing/empty/duplicate units, catalogue mismatches, parse
failures, exclusions, rights boundary, source SHA and completion state. All twenty works
must reconcile; directory metadata alone is not body evidence.

## 5. G3 — bounded analysis, governance, retrieval, and consumption

Analysis planning is work-genre aware. Long novels cover continuous opening, middle and
ending windows plus one complete conflict unit. Story collections use complete stories.
Poetry/prose collections use work, form and structure strata, with full coverage for
small sets. Conceptual texts distinguish claims, values, rhetoric, myth and historical
context.

A composite call may return multiple independently typed Observations, each with its own
dimension, evidence spans, validation status and error. One failed dimension is repaired
without re-sending unaffected source content. Actual scope and uncovered material are
persisted per work.

MKAOS extraction returns a bounded 1–6 candidate envelope per call, not a lifetime or
per-work knowledge limit. Empty useful output is valid; no candidate is invented to fill
the envelope. Candidates retain applicability, limitations, failure conditions, misuse
risk and anti-copy boundaries. Experimental AUTO review is explicitly labelled and never
reported as human review.

Selection queries beyond the newest 500 cards use bounded pagination or an exact corpus
allowlist so the twenty works cannot be silently truncated. Chinese lexical projection
supports stable CJK segmentation, near-synonym aliases and traditional/simplified forms.
Negative controls and applicability conflicts must remain unselected.

Evidence reports the distinct states: registered/retrievable, selected, frozen into
Context, actually sent through a successful ExternalEffect, claimed by model output,
located in a downstream design/draft, and human-confirmed. Only exact successful
Context/Attempt/Capability Pack/result lineage is consumption.

## 6. G4 — isolated comparison and recovery

The four arms use independent Book, Formation, runtime, state, execution and export
identities. A frozen knowledge-scope contract is enforced during Foundation, Planning,
Context, Draft, Review and Revision:

- A: explicit empty allowed set with fallback forbidden;
- B: exact approved versions derived from the novel repository;
- C: exact approved versions derived from the poetry/prose repository;
- D: the exact union of B and C.

No database row is copied. Project-level isolation is used instead if the existing
contract cannot prove an explicit empty set and exact version allowlist throughout every
stage. Cache, summary, prior Book output and CLI conversations cannot cross arms.

All arms use the same frozen brief, model, reasoning effort, instructions, schema,
planning depth, 2,000–3,500 Han-character target and revision ceiling for chapters 1–3.
Arm D alone continues to chapter 12. Its future constraint change occurs after chapter 3
through the existing plan/change and invalidation Authorities, changes only a legal future
goal or mutable parameter, and leaves accepted facts and world invariants immutable.

One real run is interrupted after a valid CLI receipt is durable and before business
result commit. Resume must reconcile and reuse the same effect/receipt without duplicated
inference or acceptance. This proves only that explicit window; other failure classes use
deterministic regression evidence.

Model judging runs in isolated sessions against a frozen rubric and is labelled
`MODEL_JUDGE`. Without a real editor, `HUMAN_EDITORIAL=NOT_RUN`.

## 7. Implementation and verification plan

### WP-01 / G1

1. Reproduce the Principal mismatch, missing AUTO permission and manual-wait retry
   consumption with focused tests.
2. Add role-bound Formation authorization and approval-wait contracts; pass exact worker
   identities through production workers and creation runner.
3. Add account-entitlement budget/cost semantics to the existing budget and Gateway
   records; retain unchanged positive monetary gates for billed Providers.
4. Record executable/config/context observability identities and validate CLI isolation.
5. Run focused unit and isolated PostgreSQL regressions, then the real structured Gateway
   probe. Commit WP-01.

### WP-02 / G2

1. Add frozen corpus specification and parser contracts.
2. Implement HTML locator-aware parsing and every observed JSON shape with direct parser
   regressions, including catalogue anomalies and excluded commentary.
3. Materialize work/unit manifests through Source Authority with idempotent aggregation,
   deduplication, update invalidation and resumable work.
4. Clone/import both exact source SHAs through the production GitHub entrance; reconcile
   every one of the twenty works and retain the machine manifest. Commit WP-02.

### WP-03 / G3

1. Replace dimension Cartesian tasks with composite, independently validated Observation
   envelopes and genre-specific coverage manifests.
2. Add variable candidate envelopes, explicit experimental governance and complete
   pagination/allowlist selection.
3. Add Chinese retrieval projections, exact version scope, negative controls and
   selection-versus-consumption reporting.
4. Run one-work-per-repository model slices first, freeze the actual budget DAG, then run
   remaining works with resume checkpoints and twenty consumption probes. Commit WP-03.

### WP-04 / G4

1. Extend the native creation runner/export/comparison entry points with exact knowledge
   scopes and four independent arm identities.
2. Run A/B/C/D chapters 1–3, continue D through chapter 12, apply the post-comparison
   future change, and preserve all review/revision/canon/acceptance lineage.
3. Inject and recover the one real receipt-to-commit interruption.
4. Export manuscripts, diffs, issue lineage, knowledge-use evidence, anonymized judge
   packs, model judgments and comparison results. Commit WP-04.

### Final convergence

Run focused risk regressions throughout. After implementation identity freezes, run the
complete applicable P0 once, retaining old failures and any repaired rerun separately.
Generate the final status matrix and reusable commands. Project completed facts into
canonical current/operations documentation and machine reality evidence where required,
then delete this resolved proposal.
