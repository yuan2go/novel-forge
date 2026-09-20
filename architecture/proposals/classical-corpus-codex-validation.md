# Classical Chinese corpus and Codex production validation

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — G1/G2 IMPLEMENTED; G3/G4 IN PROGRESS**
>
> **NOT_RUNTIME_AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Scope: bounded native ingestion, governed abstraction, exact knowledge consumption,
Codex account-entitlement execution, and four-arm creative validation
Reality baseline: `7c2a29d6a94cb1e6481f2f2e59a1112d4b596de1`
Baseline implementation identity:
`sha256:f65debf2295c8bbf330964b521be17d0cb152c10195d3d776f587d4f275f7186`

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-21",
  "review_due": "2026-10-08",
  "decision_free_since": "2026-09-08",
  "reality_baseline": {
    "sha": "7c2a29d6a94cb1e6481f2f2e59a1112d4b596de1",
    "implementation_tree_sha": "sha256:f65debf2295c8bbf330964b521be17d0cb152c10195d3d776f587d4f275f7186"
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

Current scope review (2026-09-21): Implemented identity, entitlement, corpus-ingestion
and Source/MKAOS mechanics are documented only in [current-system](../../docs/current-system.md).
The completed G1/G2 implementation plans and historical review paragraphs have been
removed. G3/G4 below specify a proposed bounded real-Provider campaign, not observed
results. Campaign sampling quotas and independent-input counts do not execute G3/G4
or establish calibrated judges. Native Chapter generator sampling now preserves the
original frozen task and approved producer contract in an isolated Kernel Saga; its
ineligible samples and scripted recovery tests do not execute the four-arm campaign. World reference sampling can now evaluate a generator sample without formal World generation; this does not supply calibrated judges or real corpus consumption. Scoped Chapter reference outcomes now feed the native routing benchmark with separate
label strata and protocol identities; no real reference observations exist from this WP.
The original Craft fixture corpus does not perform this campaign, establish
classical-text consumption, authorize model spend or supply independent editorial proof.

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

A campaign may evaluate bounded extraction envelopes without introducing a lifetime or
per-work knowledge limit. The current strict Craft discovery contract returns one
hypothesis per governed Observation; do not infer an envelope API from this proposal.
No candidate may be invented to satisfy a count. Candidates retain applicability, limitations, failure conditions, misuse
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
