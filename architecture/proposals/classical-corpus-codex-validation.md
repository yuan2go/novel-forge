# Classical Chinese corpus and Codex production validation

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — G1/G2 IMPLEMENTED; G3/G4 IN PROGRESS**
>
> **NOT_RUNTIME_AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Scope: bounded native ingestion, governed abstraction, exact knowledge consumption,
Codex account-entitlement execution, and four-arm creative validation
Reality baseline: `a57b8dbb959f790c606c59c98fccfbe863434a40`
Baseline implementation identity:
`sha256:3b9e80602491186094d5caf94d0556fb65210ba8dc05f9cbc29abc7e0601ff36`

2026-10-05 baseline revalidation includes work Quality semantics and Context routing.
Remaining proposal decisions retain their declared status. MOCK_E2E does not establish
full backend qualification, real-Provider qualification or literary quality.

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-10-05",
  "review_due": "2026-10-30",
  "decision_free_since": "2026-09-08",
  "reality_baseline": {
    "sha": "a57b8dbb959f790c606c59c98fccfbe863434a40",
    "implementation_tree_sha": "sha256:3b9e80602491186094d5caf94d0556fb65210ba8dc05f9cbc29abc7e0601ff36"
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

Current scope review (2026-10-03): Native editorial decisions now require exact approved knowledge inputs and located application in Planning. Scoped retrieval removes deferred and other-chapter editorial semantics. This supplies an input/application connection only; G3 corpus coverage, G4 real creative comparison, independent approval and literary benefit remain incomplete.

Current scope review (2026-10-01): Task-scoped Context, 512,000-token system support, governed extractive compression/fidelity and frozen Provider recovery refine the existing consumers. Published sampling contracts and Pack identities remain readable alongside separately versioned new samples; this compatibility does not execute a campaign. They do not execute G3/G4, supply real corpus observations, authorize spend or prove literary gain.  Implemented identity, entitlement, corpus-ingestion
and Source/MKAOS mechanics are documented only in [current-system](../../docs/current-system.md).
The completed G1/G2 implementation plans and historical review paragraphs have been
removed. G3/G4 below specify a proposed bounded real-Provider campaign, not observed
results. Campaign sampling quotas and independent-input counts do not execute G3/G4
or establish calibrated judges. The native paired-sample budget v5 and author-input
review/revision campaign reuse the same ledger and isolation boundary. Their two-plus-six
original scenes do not replace the twenty-work ingestion/consumption cohort or the G4
four-arm twelve-chapter experiment. A matching new grant, real corpus consumption and
independent editorial evidence remain missing for those original acceptance conditions. Native Chapter and World reference sampling
retains frozen task/producer contracts, independent label strata and routing protocol
identities. These isolated scripted sampling paths do not execute G3/G4 or supply real
reference observations. Evidence-bound editorial dispositions and exact Scene mapping
preservation change the existing review/revision consumer contract; G4 must bind the new
implementation identity and cannot reuse the older contract's qualification. These backend
repairs supply no real corpus consumption or independent generator evaluation. The original Craft fixture corpus does not perform this campaign, establish
classical-text consumption, authorize model spend or supply independent editorial proof.

Current scope review (2026-09-26): Native generator, Actor and longform reviewer feedback now uses independent adjudications and task-scoped routing; accepted Craft realization influences later selection. This is engineering wiring, not G3 corpus coverage or G4 controlled creative evidence. Original campaign failures, finite authorization and independent editorial requirements remain unchanged.

Current scope review: WP02 typed Craft and structured review/impact inputs change the
Planning/Context contracts. G3/G4 must bind their exact versions; recovered historical
account costs and expired grants do not supply fresh campaign authorization.

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

Current scope review (2026-10-02): Restricted private Source observation now retains UNKNOWN rights, whole-work integrity issues and exact source slices through analysis admission. Reference Context uses an observation boundary; production still requires accepted Canon. Strict Codex Schema projection and empty optional lineage normalization retain raw responses. These changes do not resolve remaining production, creative-validation or literary-quality qualifications.
