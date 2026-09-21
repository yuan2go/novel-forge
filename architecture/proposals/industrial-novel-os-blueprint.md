# Unresolved industrial Novel OS decisions

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — REMAINING DECISIONS REQUIRE DESIGN REVIEW**
>
> **NOT_RUNTIME_AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Scope: unresolved target narrative domain and business architecture decisions
Current-reality baseline: `da7533c6eae818e41d4811b0691160e41c77441b`
Baseline implementation identity: `sha256:7e9227225e6f3270c206eb13ebe91874f931701176981dd74f977f4127d46391`

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-21",
  "review_due": "2026-10-08",
  "reality_baseline": {
    "sha": "da7533c6eae818e41d4811b0691160e41c77441b",
    "implementation_tree_sha": "sha256:7e9227225e6f3270c206eb13ebe91874f931701176981dd74f977f4127d46391"
  },
  "scope": [
    "src/novel_forge/modules/story_design_authority",
    "src/novel_forge/modules/book_design_authority",
    "src/novel_forge/modules/hierarchical_planning",
    "src/novel_forge/modules/book_authority",
    "src/novel_forge/modules/chapter_group_authority",
    "src/novel_forge/modules/book_followup_authority",
    "src/novel_forge/modules/reader_judge_authority",
    "src/novel_forge/modules/context_builder",
    "src/novel_forge/storage/migrations",
    "src/novel_forge/storage/book_authority_repositories.py",
    "src/novel_forge/modules/narrative_state",
    "src/novel_forge/modules/worldbuilding"
  ],
  "implemented_refs": [
    {
      "path": "src/novel_forge/modules/hierarchical_planning/domain.py",
      "symbol": "validate_planning_contract"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/domain.py",
      "symbol": "_validate_scene_architecture"
    },
    {
      "path": "src/novel_forge/modules/book_design_authority/foundation.py",
      "symbol": "FoundationBinding"
    },
    {
      "path": "src/novel_forge/modules/story_design_authority/application.py",
      "symbol": "PostgresStoryDesignAssetAuthority"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/chapter_contracts.py",
      "symbol": "ChapterMission"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/chapter_contracts.py",
      "symbol": "SceneArchitecture"
    },
    {
      "path": "src/novel_forge/modules/chapter_group_authority/policy.py",
      "symbol": "ChapterGroupExecutionPolicy"
    },
    {
      "path": "src/novel_forge/modules/book_followup_authority/reader_policy.py",
      "symbol": "ReaderProxyPolicy"
    },
    {
      "path": "src/novel_forge/modules/book_authority/completion.py",
      "symbol": "PostgresBookCompletionAuthority"
    },
    {
      "path": "src/novel_forge/modules/context_builder/governance.py",
      "symbol": "compile_effective_context_policy"
    },
    {
      "path": "src/novel_forge/modules/context_builder/reality_projection.py",
      "symbol": "project_role_context"
    },
    {
      "path": "src/novel_forge/modules/narrative_state/reality.py",
      "symbol": "NarrativeRealityRevision"
    },
    {
      "path": "src/novel_forge/modules/worldbuilding/foundation.py",
      "symbol": "WorldFoundation"
    },
    {
      "path": "src/novel_forge/modules/worldbuilding/dynamics.py",
      "symbol": "WorldTransition"
    },
    {
      "path": "src/novel_forge/modules/hierarchical_planning/causal_application.py",
      "symbol": "PostgresCausalPlanningApplication"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/realization_composition.py",
      "symbol": "compile_realization_contract"
    },
    {
      "path": "src/novel_forge/modules/book_authority/control_application.py",
      "symbol": "PostgresBookControlApplication"
    },
    {
      "path": "src/novel_forge/modules/story_planning_runtime/world_preparation.py",
      "symbol": "PlanningWorldPreparation"
    },
    {
      "path": "src/novel_forge/modules/canon_graph/background.py",
      "symbol": "attach_background_proposals"
    },
    {
      "path": "src/novel_forge/modules/narrative_state/causal_batch.py",
      "symbol": "compile_causal_batch"
    },
    {
      "path": "src/novel_forge/modules/story_design_authority/author_input.py",
      "symbol": "compile_provider_author_projection"
    },
    {
      "path": "src/novel_forge/modules/story_design_authority/author_input.py",
      "symbol": "validate_author_decisions"
    },
    {
      "path": "src/novel_forge/modules/book_authority/editorial.py",
      "symbol": "BookEditorialWorkflow"
    },
    {
      "path": "src/novel_forge/modules/book_followup_authority/prose_coordinator.py",
      "symbol": "BookProseReviewCoordinator"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/author_editor.py"
    },
    {
      "path": "src/novel_forge/modules/worldbuilding/actor_isolation.py",
      "symbol": "actor_task"
    },
    {
      "path": "src/novel_forge/modules/plan_change_authority/semantic_impact.py"
    }
  ],
  "superseding_refs": [],
  "remaining_decisions": [
    {
      "id": "optional-volume",
      "description": "DESIGN_REVIEW_REQUIRED: optional Volume versus an implicit persisted Volume and its constraints.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/hierarchical_planning/domain.py",
          "symbol": "PlanContractType"
        }
      ]
    },
    {
      "id": "segment-boundaries",
      "description": "DESIGN_REVIEW_REQUIRED: segment identity and boundary changes across accepted chapters.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/hierarchical_planning/domain.py",
          "symbol": "validate_planning_contract"
        }
      ]
    },
    {
      "id": "trajectory-storage",
      "description": "DESIGN_REVIEW_REQUIRED: typed common trajectory persistence versus separate physical schemas.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/hierarchical_planning/domain.py",
          "symbol": "_validate_arc_relations"
        }
      ]
    },
    {
      "id": "strategic-approval-risk",
      "description": "DESIGN_REVIEW_REQUIRED: strategic risk classification, delegated approval and mandatory human quorum beyond the implemented versioned operator ControlPolicy modes.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/story_design_authority/domain.py",
          "symbol": "DesignApproval"
        }
      ]
    },
    {
      "id": "completion-human-quorum",
      "description": "DESIGN_REVIEW_REQUIRED: publication-class-specific minimum independent human/editorial quorum and actual approved policy/signatures; runtime versioned policy, coverage and signature gates are implemented.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/chapter_quality_authority/qualification.py"
        },
        {
          "path": "src/novel_forge/modules/book_authority/editorial_domain.py"
        }
      ]
    },
    {
      "id": "reader-data-policy",
      "description": "DESIGN_REVIEW_REQUIRED: real reader consent, cohort retention, privacy and causal attribution policy.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/reader_judge_authority/domain.py"
        }
      ]
    },
    {
      "id": "retrospective-correction",
      "description": "DESIGN_REVIEW_REQUIRED: erratum, compensating fact or edition boundaries for accepted factual errors.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/storage/book_authority_repositories.py"
        }
      ]
    }
  ],
  "remaining_work": [
    {
      "id": "closure-authorized-pilot-and-exploration",
      "description": "Execute the original two-case pilot, then six-task native-path comparison under matching finite authorization, current qualifications and exact independent inputs; retain all failures and unknown usage.",
      "evidence_refs": [
        {
          "path": "scripts/narrative_closure_campaign.py"
        },
        {
          "path": "config/production/narrative-closure/authorization-request.json"
        }
      ]
    },
    {
      "id": "craft-independent-effect-evaluation",
      "description": "Run separate Craft intervention and collect real blind reader judgments, disagreements and adverse effects; do not infer generation quality from fixed-input revision controls.",
      "evidence_refs": [
        {
          "path": "scripts/narrative_closure_review.py"
        },
        {
          "path": "config/production/narrative-closure/protocol.json"
        }
      ]
    },
    {
      "id": "actor-isolation-controlled-benefit",
      "description": "Compare optional isolated actors against unified preparation with separately authorized budget and independent prose assessment; default remains unchanged without demonstrated benefit.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/worldbuilding/actor_isolation.py"
        }
      ]
    }
  ]
}
-->

Current scope review (2026-09-21): Native author candidates, exact cross-chapter/Craft
repair, bounded prose-review windows, Plan Change semantic candidates, optional isolated
actors and versioned editorial signatures are projected in
[current-system](../../docs/current-system.md). The execution checklist for
WP-NARRATIVE-PRODUCTION-CLOSURE-01 is superseded by those executable consumers and
[runtime operations](../../docs/runtime-operations.md); the remaining evaluation work is
listed below. The former creative assimilation proposal stays terminal, and its WP01 audit
retains the historical Git baseline `c2ff5775f9b636ad983f8b1c77425f3bd0f9aaf4`.
Existing WP02–WP05 identities are unchanged. Runtime policy/signature support does not
choose the independent human quorum for a publication class, grant model consumption,
establish creative benefit or authorize retrospective accepted-history correction. Native human adjudications for
bounded semantic evaluator calibration remain separate from whole-book completion
quorum, strategic approval and accepted-history mutation.

## Unresolved design decisions

These are unresolved policy/schema choices. An evidence-backed design decision is
required before changing the affected current contract.

1. `DESIGN_REVIEW_REQUIRED`: whether Volume remains optional in persisted domain data or
   every Book receives an implicit Volume for uniform constraints.
2. `DESIGN_REVIEW_REQUIRED`: exact Narrative Segment identity and boundary-change rules
   after chapters within the segment have been accepted.
3. `DESIGN_REVIEW_REQUIRED`: one generic trajectory storage protocol with typed payloads
   versus separate physical schemas for Narrative, Character, Relationship, and Theme.
4. `DESIGN_REVIEW_REQUIRED`: risk policy specifying which strategic changes require
   mandatory human approval and which may use delegated approval.
5. `DESIGN_REVIEW_REQUIRED`: minimum independent human/editorial evidence and quorum for
   Whole-book Completion at each publication class.
6. `DESIGN_REVIEW_REQUIRED`: reader-data privacy, consent, cohort retention, and causal
   attribution policy before real behavior can drive adaptation proposals.
7. `DESIGN_REVIEW_REQUIRED`: correction semantics when an accepted factual error cannot
   be repaired prospectively—erratum, compensating canon fact, or new edition boundary.

Unresolved decision count: **7**. Foundation ownership is resolved by the implemented
single Story Design owner and Book Design's immutable binding; a physical service split
is not a prerequisite for one-fact/one-Authority semantics.


## Remaining bounded evaluation and decisions

The original two-case pilot and six-task exploration now have native freeze/run/resume
and evidence-export commands. Execution still requires a matching finite account grant,
current Provider/Pack qualification and exact independent Book/Group/plan/author-input
versions. Current same-implementation A/B runs compare declared native paths, not the
historical defective SHA; neither those controls nor fixtures establish literary benefit.
A system contract failure stops expansion. UNKNOWN effects require native reconciliation.

Craft controls remain a separate fixed-author-input review/revision intervention.
Generation quality and independent reader preference require additional evidence;
HYPOTHESIS is not upgraded by adoption counts, lexical matches or model self-review.
The optional actor path remains experimental pending a separately authorized comparison
of privacy, motivation, surprise, prose naturalness, cost and latency. Editorial completion
still waits for an approved policy and named human signatures against exact current prose,
coverage and issue dispositions. Public release is separately authorized.

| Direction | Native consumer and unresolved prerequisite | Decision / exit condition |
| --- | --- | --- |
| Market observations | Topic proposal; one rights-backed source, comparable cohort, observation time and missing-value semantics | HOLD until source authorization and a testable topic-quality hypothesis exist; then one bounded input adapter |
| General association graph | A concrete query unmet by existing accepted/inferred indexes; exact source and relation provenance | HOLD until that query and measured improvement are specified; never merge inferred relations into accepted truth |
| Short form, scripts or multimedia | Explicit version of accepted prose and an identified downstream adapter; source/output rights | HOLD until the consumer and useful output are approved; model/resource generation and publication need separate authorization |
