# Unresolved industrial Novel OS decisions

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — REMAINING DECISIONS REQUIRE DESIGN REVIEW**
>
> **NOT_RUNTIME_AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Scope: unresolved target narrative domain and business architecture decisions
Current-reality baseline: `a1b87a745619704c696abc0d578911e9c064cd78`
Baseline implementation identity: `sha256:5b1aec78dbc38705e56f8adc925f70a92a2454b46d67b7cf63fb877ebf2aaf88`

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-20",
  "review_due": "2026-10-08",
  "reality_baseline": {
    "sha": "a1b87a745619704c696abc0d578911e9c064cd78",
    "implementation_tree_sha": "sha256:5b1aec78dbc38705e56f8adc925f70a92a2454b46d67b7cf63fb877ebf2aaf88"
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


## WP-NARRATIVE-PRODUCTION-CLOSURE-01 execution checklist

PROPOSAL / NOT_RUNTIME_AUTHORITY. This native follow-up uses baseline
`e41a2c22e4f24fdb89e6bb2db8a3e00039e7e332`, implementation identity
`sha256:adf61a4234405b63f0edcfbd2ab942156bd98e0e544e3ad19b97fafd95778eed`,
and migration head `20260920_0139_narrative_reference_sampling`.
The former creative assimilation proposal was removed by `adf3cd97` after projection;
its WP01 audit remains fixed at `c2ff5775f9b636ad983f8b1c77425f3bd0f9aaf4`
in Git. This checklist neither restores that terminal proposal nor renumbers WP02–WP05.
Current Craft delivery is reused; catalog expansion is outside this batch.

| Priority / item | Verified gap and native owner | Deliverable / dependency | Acceptance |
| --- | --- | --- | --- |
| P0 WP02 contracts | Review window subtracts UTF-8 bytes from token allocation; ReReview provider view drops original prose; generic judgment enum admits invalid category combinations | Review/Chapter/Production Execution meter, versioned schema, exact comparison and edit scopes; preserve old frozen contracts | Chinese boundary and overflow; schema-normalization-domain combinations; materialized request contains before/after; exact Unicode edits and scene consistency |
| P0 Cross-Chapter × Craft | ordinary and Quality repair use different payloads | Chapter handlers retain adopted strategy, source window and diagnosis lineage through corrective paths and selection | combined provider-input, old-candidate retention and unresolved multi-round tests; PostgreSQL receipt/commit-loss replay |
| P0 bounded experiment | previous campaign has no grant for this scope; no independent editorial evidence | extend native campaign/Book/Chapter commands with original six-task controls, freeze/resume/export and stage caps; no new ledger | two-case admission before six-case expansion; failures and unknown effects retained; real calls require matching grant and qualification |
| P1 WP05 exact author edit | EditorPage edits only local state and sends disk-path requests; no actual text submission | Chapter-owned exact-version candidate command/query, trusted permissions, CAS/idempotency; editor before/after, save and accept/reject | cross-Book and stale-base rejection, duplicate/retry recovery; real browser edit-save-review-decision journey |
| P1 long manuscript review | accepted observations/recaps cannot establish prose coverage | existing Book Follow-up/Review frozen manifest, bounded windows, evidence aggregation and native action consumers | exact coverage/exclusions, drift, incremental resume and findings-to-revision/Plan Change/editorial pending item |
| P1 Craft effect | delivery controls do not prove literary benefit | separate frozen Craft intervention and blinded human evaluation input with disagreements | adoption/implementation/model/human evidence separated; no synthetic reader certification |
| P2 private actors | optional comparison has no benefit evidence | bounded private-observation action proposals and world adjudication inside World Preparation | no private leakage, partial failure does not advance world; disabled path unchanged |
| P2 semantic impact | exact dependencies do not prove semantic effects | evidence-located impact candidates and explicit confirmation in Plan Change/workbench | inferred impacts cannot authorize invalidation; approved future scope only |
| P2 completion | native case records only BLOCKED/REJECTED without an authorized human policy | versioned policy, exact manuscript/coverage signatures and revocation within Book completion | missing authority/evidence blocks; drift invalidates current signature while retaining history |

Implementation proceeds in the order above with independent consumers developed in
parallel, then integrated against one release identity. Run focused tests during changes,
then complete exact-SHA PR governance, Web checks and browser acceptance. A new migration
is allowed only for a demonstrated persistence invariant. Engineering, real Provider,
human, longitudinal and production evidence remain separate. Each unexecuted experiment
retains its exact missing grant/credential/qualification fields and executable resume path.

Market observations remain HOLD pending a rights-backed source, comparable cohort and
missing/time semantics consumed by topic proposals. A generic graph remains HOLD pending
a concrete query not served by native accepted/inferred indexes. New content formats
remain HOLD pending a version-bound accepted-manuscript consumer and separate resource
or publication authorization. These do not block P0/P1 and add no platform in this batch.
