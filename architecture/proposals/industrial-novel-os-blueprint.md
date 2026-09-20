# Unresolved industrial Novel OS decisions

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — REMAINING DECISIONS REQUIRE DESIGN REVIEW**
>
> **NOT_RUNTIME_AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Scope: unresolved target narrative domain and business architecture decisions
Current-reality baseline: `f5ba1faf058af2613f7116904a6230eac1f0e02c`
Baseline implementation identity: `sha256:2a0f369f4e29d34f5d56bbf9dcd9d0401c568c0188050d3a389640d95bbfb408`

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-20",
  "review_due": "2026-10-08",
  "reality_baseline": {
    "sha": "f5ba1faf058af2613f7116904a6230eac1f0e02c",
    "implementation_tree_sha": "sha256:2a0f369f4e29d34f5d56bbf9dcd9d0401c568c0188050d3a389640d95bbfb408"
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
      "description": "DESIGN_REVIEW_REQUIRED: independent human/editorial completion evidence and quorum by publication class.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/chapter_quality_authority/qualification.py"
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
  "remaining_work": []
}
-->

Current scope review (2026-09-20): Current ontology, Authority, production descent and
Craft behavior are documented only in [current-system](../../docs/current-system.md)
and the checked reality inventory. Implemented architecture and obsolete gap matrices
have been removed from this proposal. The seven decisions below remain unresolved;
Craft engineering does not establish human completion quorum, reader-data policy or
accepted-history correction authority.

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
