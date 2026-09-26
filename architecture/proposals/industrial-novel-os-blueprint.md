# Unresolved industrial Novel OS decisions

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — REMAINING DECISIONS REQUIRE DESIGN REVIEW**
>
> **NOT_RUNTIME_AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Scope: unresolved target narrative domain and business architecture decisions
Current-reality baseline: `5bb9d91dcb64260956c901a50316badca560094e`
Baseline implementation identity: `sha256:eefb6fcb8676064f5d75c7dd91ab501e99a67a0c6281dc1c5e4cd727c8eeecfc`

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-27",
  "review_due": "2026-10-11",
  "reality_baseline": {
    "sha": "5bb9d91dcb64260956c901a50316badca560094e",
    "implementation_tree_sha": "sha256:eefb6fcb8676064f5d75c7dd91ab501e99a67a0c6281dc1c5e4cd727c8eeecfc"
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
    },
    {
      "path": "src/novel_forge/modules/book_authority/editorial.py",
      "symbol": "completion_editorial_evidence"
    },
    {
      "path": "src/novel_forge/modules/book_authority/editorial_domain.py",
      "symbol": "validate_finding_disposition"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/author_editor.py",
      "symbol": "reconcile_author_scenes"
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
      "description": "Implementation contract required: immutable Book-owned editions preserve accepted originals, bind exact base manifests and revalidate affected facts before controlled switching; this is authorized WP02 scope, not a request for another approval.",
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
      "description": "Implementation contract required: immutable Book-owned editions preserve accepted originals, bind exact base manifests and revalidate affected facts before controlled switching; this is authorized WP02 scope, not a request for another approval.",
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
    },
    {
      "id": "closure02-backend",
      "description": "Complete package-wide collaboration checks after global-review and admission contracts land; exact signature groups, bounded dispositions, mapped Scene edits, successful-child cancellation and unresolved-budget replacement blocking now have focused backend regression coverage.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/book_authority/editorial.py"
        }
      ]
    },
    {
      "id": "closure02-global-editor",
      "description": "Automatic Follow-up, bounded remote-anchor pair discovery, incremental manifests, native dispositions and counter-review now have focused native PostgreSQL evidence. Remaining: qualified real reviewer execution and independent assessment of missed relations beyond the declared lexical retrieval coverage.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/book_followup_authority/prose_coordinator.py"
        }
      ]
    },
    {
      "id": "closure02-inferred-impact",
      "description": "Frozen plan/prose impact hypotheses, explicit confirmation/false-positive/defer decisions and precise future-only native invalidation/revalidation now have focused PostgreSQL evidence. Remaining: real accepted-manuscript impact decisions and long-range false-positive/coverage assessment; hypotheses never become hard dependency edges.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/plan_change_authority/semantic_impact.py"
        }
      ]
    },
    {
      "id": "closure02-continuous-actors",
      "description": "Accepted private state and owned commitments now continue across native acceptances and process rebuild; immutable receipt replay, exact obligation versions and complete role input have focused evidence. Remaining: qualified real Actor execution and separately authorized comparative benefit/leakage assessment; one bounded action round per preparation remains policy.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/story_planning_runtime/world_preparation.py"
        }
      ]
    },
    {
      "id": "closure02-generator-admission",
      "description": "Generator, Actor and prose-reviewer native samples now feed separate task/producer/risk/context-scoped Router metrics with independent human adjudication, frozen-input/content deduplication and holdout exclusion. Remaining: actual current-model independent calibration references, sufficient positive/negative evidence and live native grant/ledger checks; fixture passage is not model qualification.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/production_execution/routing_runtime.py",
          "symbol": "PostgresRoutingRegistry"
        }
      ]
    },
    {
      "id": "closure02-native-hierarchy",
      "description": "After matching per-task admission, execute the bounded native Formation/Opening/Book/Chapter/Review/Revision/acceptance closure and subsequent accepted boundaries; missing paid authorization or trusted human evidence remains incomplete.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/book_authority/production.py"
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
7. `IN_SCOPE_IMPLEMENTATION_REQUIRED`: retrospective correction creates an immutable edition
   bound to an exact base manifest under Book/Editor ownership. Revalidate affected facts
   and projections from the earliest changed boundary; atomic switching must preserve the
   old edition and settle in-flight work. Future-only Plan Change keeps its current meaning.

Unresolved design decision count: **6**; the edition direction is decided and its implementation remains required. Foundation ownership is resolved by the implemented
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
| Textual novel and scene screenplay adaptation | Exact accepted source edition; distinct chapter/scene-dialogue contracts and review rules; source/output rights | REQUIRED IN WP02: implement through existing Editor and Authorities. Image, audio and video production are outside this scope; publication remains separately authorized |

## WP-NARRATIVE-CAPABILITY-AND-MODEL-ADMISSION-CLOSURE-02

The active continuation is based on fetched `origin/main`
`6c501c8148c705a1e3466867fdcc4ff15d3ffdd6`, identical to the requested historical
reference. Existing historical experiments and failures retain their original implementation
identities. The table distinguishes current gaps rather than re-opening closed baseline work.

| Capability | Existing implementation and actual consumer | Baseline gap | Required observable evidence |
| --- | --- | --- | --- |
| Task admission | Native Chapter/World/Planning samples, adjudicated references, `PostgresRoutingRegistry` and `ProductionProviderRouter.select` | Generator feedback was not connected; Actor and global prose reviewer sample paths were missing | Independent task/producer/risk/context-bound scores change routing; native Effects retain decisions; samples remain ineligible |
| Hierarchy and acceptance | Formation/Opening, Book Supervisor, Hierarchical Planning, ChapterGroup, Chapter, Book Acceptance | Existing implementation needed current execution evidence; no replacement tree is needed | Frozen lower tasks, accepted-only facts, rolling windows, cross-volume Arc and preserved executed plans |
| Craft feedback | KnowledgeCard translation, Chapter strategy, located review/repair and acceptance | Operational delivery receipts were consumed as recent use | Exact final accepted prose/review locations feed the next selection; discarded versions and replayed receipts do not count |
| Automatic global review | Book Follow-up manifest/window review and native dispositions | Automatic continuation and bounded remote-pair discovery were missing | Pause/resume, incremental append, paired evidence, native disposition and located counter-review; coverage remains separate from relationship correctness |
| Implicit impact | Plan Change semantic diff and explicit dependency invalidation | Bounded hypothesis discovery, evidence confirmation and native inferred impact activation were missing | Frozen plan/prose corpus, positive/false-positive/deferred decisions, future-only activation and recoverable revalidation |
| Persistent characters | World Preparation actor isolation and accepted Narrative State | Accepted commitments were not required continuations; later rounds lacked execution proof | Stable obligation identity, exact accepted source/version, private knowledge projection, multi-acceptance and receipt/rebuild recovery |


Implementation order follows the six remaining-work entries above. Existing sampling,
reference calibration, cross-chapter token accounting, Craft preservation and accepted
state reducers are dependencies to reuse, not replacement Authorities. The earlier
window-review and single-round actor claims describe their bounded runtime only; they
do not close global editing, inferred dependency discovery or continuous agency.

Acceptance requires backend commands and exact native consumers for every stage,
independent positive/negative evidence and recoverable Effect receipts. In particular,
coverage cannot imply a global verdict, a proposed revision cannot imply resolution,
reference agreement cannot qualify a generator, and samples never become formal assets.
The completion quorum remains a policy decision. Retrospective editions and textual
adaptation are explicitly in this work package; lack of implementation is not an approval
blocker or a reason to move them to another package.

Verification is restricted by the execution request to focused backend unit, native
PostgreSQL vertical/recovery, applicable migration and static manifest checks. Full P0,
backend/PostgreSQL/Compose collections and Web/UI tests are NOT_RUN; this restriction
cannot confer QUALIFIED or replace the existing full gate. Paid model execution and
independent human evidence require matching existing authorization and identities.
All historical fixed-SHA failures, campaign counters and unknown Effects are retained.

The current native continuation is checked in the [versioned evidence record](../live-evidence/narrative-capability-admission-closure-02/20260926-native-continuation/status.json). It separates final focused execution, inspectable native artifacts, retained failures and still-blocked real qualification; the earlier backend and campaign records remain unchanged.

The expanded WP02 scope and current implementation boundary are tracked in the
[continuation evidence](../live-evidence/narrative-capability-admission-closure-02/20260927-composition-runtime/status.json).

| Work | Current category | Remaining required behavior |
| --- | --- | --- |
| P0-1 persistent environment | Implemented, partially verified | Original PostgreSQL/MinIO volumes recovered and forward-upgraded with backup/restore comparison; one historical timeout and unknown costs remain retained. No authorized production worker has restarted |
| Craft composition and usage | Implemented, focused verification | Deterministic dependency/scene/frequency search, explicit typed phases, older open-instance retrieval and accepted feedback; Provider-rejection reselection and arbitrary supported scene applicability remain incomplete |
| Semantic prose/impact retrieval | Implemented, focused verification | Exact accepted-state multi-passage retrieval and typed changed-state hypotheses consume native review/Plan Change; unindexed semantics and empirical precision/recall remain unproven |
| Continuing multi-step Actor | Missing implementation | Existing one-action private projection and commitment dispositions must be extended through judged plans and accepted cross-round state |
| Whole-manuscript editions | Missing implementation | Book-owned base manifests, mapped structural edits, isolated fact revalidation, concurrent/recoverable admission, controlled switch and Editor/CLI/API consumers |
| Multiple textual forms | Missing implementation | Novel plus scene screenplay adaptation; distinct input/structure/generation/review/export contracts and exact source-version invalidation |
| P0-2 same-Book joint validation | Missing wiring/verification | Native Craft continuity is demonstrated with scripted transport; the combined Actor/global review/impact/edition/adaptation chain is not complete |
| P0-3 real sampling/admission | Implementation and external conditions missing | Freeze the complete enabled task closure after required engineering; existing grants have expired and independent human references are missing |
| P0-4 real production/effect controls | External conditions and upstream implementation missing | Current task admissions, finite account authorization, human/reader references, same-Book production and representative controlled comparisons |

The supported output matrix for this package is textual novel (Book/Volume/Arc/Chapter/Scene)
and a scene screenplay adaptation (Scene/action/dialogue, source fidelity and actor-knowledge
review). Source editions, analysis, plans and review reports remain input or intermediate
assets; file extensions do not constitute output forms. Neither form is newly declared
complete by this scope decision. These gaps are mandatory work within WP02, not optional
future recommendations. No engineering result here grants publishing authority or proves
literary, reader, long-form or cost benefit.
