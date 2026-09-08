# Industrial Novel OS canonical narrative and business blueprint

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — REMAINING DECISIONS REQUIRE DESIGN REVIEW**
>
> **NOT_RUNTIME_AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Scope: unresolved target narrative domain and business architecture decisions
Current-reality baseline: `90a74b8204e252aacb8716c9900a1531b2332871`
Baseline implementation identity: `sha256:b3a179e18ccff0cd5e3f262d172304cea2e853b291f3f7c30d9844ccccd24c25`

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-09",
  "review_due": "2026-10-08",
  "reality_baseline": {
    "sha": "90a74b8204e252aacb8716c9900a1531b2332871",
    "implementation_tree_sha": "sha256:b3a179e18ccff0cd5e3f262d172304cea2e853b291f3f7c30d9844ccccd24c25"
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

The retained scope is the seven unresolved decisions below. Typed Chapter Mission and
Scene Architecture, immutable Foundation bindings, versioned execution/reader policy,
whole-book completion cases and governed Context compilation exist in executable code.
Accepted-source Reality revisions, causal future selection, structured Scene realization
and versioned operator ControlPolicy are also implemented by the references above.
Native world generation, causal preparation, governed background acceptance and
same-chapter causal batches now share the existing Planning and Book acceptance chain.
Their presence does not establish narrative, human, reader, longitudinal or production
qualification. Every implementation change
inside the declared scope invalidates this lifecycle review until the baseline is
refreshed against code.

## Reading contract

This is one isolated To-Be design artifact. It does not describe a capability as
implemented, activate an Authority, define a runtime contract, qualify a Provider, or
alter the current proof ceiling. Current facts remain solely in
`architecture/reality-evidence.json` and the canonical current documentation.

The labels above apply to every section. Terms such as `target`, `shall`, `Authority`,
and `gate` describe the proposed design only. The current code is used as As-Is fact,
engineering constraint, and gap evidence—not as proof that its narrative semantics are
the correct final design.

## 1. Product goal and non-goals

### Goal

The target product is an Industrial Autonomous Novel OS: a local-first, recoverable,
auditable production system that can sustain a high-quality million-character serial
novel with bounded human intervention. It must preserve accepted history, plan and
replan the unaccepted future, compile evidence-bounded context, generate and revise
prose, measure quality at every abstraction level, learn from readers without treating
feedback as truth, and close a whole book through an explicit acceptance decision.

Autonomy means bounded execution under approved contracts, budgets, gates, and stop
conditions. It does not mean that an Agent or Provider owns narrative truth.

### Non-goals

- A one-shot prompt-to-novel generator.
- A single hierarchy that forces every narrative concept into containment.
- A chapter-count ladder that substitutes quantity for narrative capability.
- Automatic self-certification of human, editorial, reader, or commercial quality.
- Retrospective rewriting of accepted history through a future-plan edit.
- Treating source material, retrieval results, model output, or reader reaction as
  accepted narrative fact.
- Treating unresolved design prescriptions as an implementation claim.

## 2. Design inputs and evidence boundary

### Current As-Is inputs

The exact-SHA baseline establishes the following engineering facts, not final product
semantics:

- PostgreSQL-backed Authorities, command admission, attempt/lease/fence ownership,
  ExternalEffect reconciliation, migrations, workers, and recovery are executable and
  executable under exact-implementation qualification gates.
- Candidate Story Design, typed hierarchical plans, Narrative Realization contracts,
  ChapterGroup coordination, chapter production, quality, Book acceptance, Canon,
  Narrative State, reader evidence, and future-only Plan Change exist.
- Accepted chapter outcome is invisible to accepted projections until Book acceptance.
- Narrative Arc is already independent of Volume containment and may cross volumes.
- Current Book `COMPLETED` is a production cursor result, not a whole-book editorial
  acceptance.
- ChapterGroup limits and reader-proxy thresholds are versioned owned policy, not
  universal domain invariants. The default execution cap is configurable.
- Whole-book Completion has independent immutable case/rejection/block commands;
  acceptance remains blocked pending native whole-book editorial policy and evidence.
- Current qualification ceiling is local backend engineering. It does not establish a
  credentialed Provider, human editorial quality, longitudinal stability, production
  operation, or an Admin UI path.

### External design inputs only

These sources inform decisions but are neither repository facts nor product proof:

- Re3 separates overarching planning, state-aware generation, reranking, and factual
  revision, and evaluates the result with people. This supports plan/realize/revise
  separation, not Re3's exact data model: [Re3 paper](https://arxiv.org/abs/2210.06774).
- DOC reports stronger long-story coherence and controllability from detailed,
  hierarchical outline control and human evaluation. This supports abstraction gates
  before prose: [DOC paper](https://aclanthology.org/2023.acl-long.190/).
- CONCOCT expands the vaguest outline elements and evaluates pacing separately. This
  supports semantic readiness rather than fixed chapter counts as the descent rule:
  [CONCOCT paper](https://aclanthology.org/2023.findings-emnlp.723/).
- DOME combines dynamic hierarchical outlining with temporal knowledge-graph memory.
  This supports an adaptive future plan plus temporal accepted-state view, while its
  implementation remains merely a research input:
  [DOME paper](https://aclanthology.org/2025.naacl-long.63/).
- The Long Story Generation Challenge uses both automatic and human protocols, which
  supports keeping engineering, continuity, and human-quality claims separate:
  [LSGC report](https://aclanthology.org/2024.inlg-genchal.4/).
- LLM evaluators can prefer their own generations; an LLM judge therefore cannot be the
  sole source of a human-quality claim:
  [self-preference study](https://arxiv.org/abs/2404.13076).
- NIST's AI RMF calls for documented, repeatable evaluation, deployment-relevant
  conditions, and independent/domain-expert assessment. This supports explicit evidence
  classes and independent review:
  [AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/).
- Event-sourcing guidance distinguishes immutable events from rebuildable projections
  and uses compensating events rather than history edits. This supports Accepted Actual
  and projection separation without requiring every target module to use full event
  sourcing: [Event Sourcing pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing).

## 3. Design principles

1. **One fact, one Authority.** Coordinator, Agent, Provider, repository, and projection
   are not Authority substitutes.
2. **Intent descends; evidence ascends.** Higher-level intent constrains lower-level
   design. Accepted lower-level outcomes update actual trajectories and projections.
3. **Candidate is not truth.** Generated plans, prose, reviews, and extraction results
   remain candidates or evidence until the owning Authority accepts them.
4. **Accepted history is append-only.** Corrections use explicit superseding or
   compensating facts; future replanning cannot overwrite accepted events.
5. **Structure is not trajectory.** Volumes, segments, chapters, scenes, and beats locate
   material. Arcs, relationships, themes, and obligations evolve across those locations.
6. **Planning depth follows uncertainty.** The system elaborates the next narrative
   decision when its parent is accepted and the child gate is ready—not after an
   arbitrary number of chapters.
7. **Execution artifacts do not define ontology.** Windows, bundles, prompts, retrieval
   campaigns, attempts, and realization packets serve execution and may change without
   changing the narrative model.
8. **Context is compiled, not remembered informally.** Every included item has type,
   authority, temporal boundary, lineage, relevance, and compression treatment.
9. **Autonomy is budgeted and recoverable.** Every loop has an idempotency identity,
   budget, checkpoint, stop condition, and escalation state.
10. **Evidence ceilings are claim ceilings.** Machine checks, LLM judgments, human
    reviews, reader behavior, and production outcomes prove different things.

## 4. Canonical narrative ontology decisions

The disposition is a target decision; the current mapping records compatibility, not
implementation.

| Current or required concept | Decision | Target nature | Target meaning and boundary |
|---|---|---|---|
| Story Intent | `NEW_REQUIRED_CONCEPT` | `PLAN` | Smallest strategic statement of topic, premise, audience, form, and creative risk; precedes Foundation. |
| Story Foundation | `KEEP` | `PLAN` | Approved composite snapshot referencing exact Theme, Reader Promise, Ending Intent, World, Character, and Relationship versions; it does not copy their state. |
| Book Design | `RENAME` | `CANDIDATE` then `PLAN` | Becomes Book Architecture Candidate before approval and Book Architecture after activation. |
| Story Design | `KEEP` | `AUTHORITY` | Owns activation of the six Foundation semantic asset roles. Book Design binds their exact immutable qualified versions without copying semantic ownership. |
| World | `KEEP` | `PLAN` | Versioned rules, costs, institutions, resources, geography, and permitted change mechanisms. |
| Character | `KEEP` | `PLAN` | Identity, drives, constraints, competencies, initial state, and intended transformation envelope. |
| Relationship | `SPLIT` | `PLAN` plus `PROJECTION` | Separate relationship definition/constraints from accepted relationship state and its trajectory. |
| Theme | `KEEP` | `PLAN` | Dramatic question, pressure tests, counterclaims, and anti-preaching constraints; not a slogan to repeat in prose. |
| Reader Promise | `KEEP` | `PLAN` | Auditable expectations for genre experience, pacing, payoff, tone, and forbidden betrayals; not a popularity claim. |
| Ending Intent | `KEEP` | `PLAN` | Target closure conditions and acceptable variation; it constrains but does not dictate every event. |
| Book | `KEEP` | `STRUCTURAL_CONTAINER` | Narrative/product identity and ordered chapter timeline; cursor state is separate from completion acceptance. |
| Volume | `KEEP` | `STRUCTURAL_CONTAINER` | Optional publication and macro-structure interval; volumes partition an assigned span but do not own arcs. |
| Narrative Segment | `KEEP` | `STRUCTURAL_CONTAINER` | A bounded story-phase interval used for causal and pacing design; it is not an Arc parent. |
| Narrative Arc | `KEEP` | `TRAJECTORY` | Plot/conflict transformation with trigger, escalation, turns, cost, outcome, and closure; independent of Volume. |
| Character Arc | `SPLIT` | `TRAJECTORY` | Split from generic Arc: change in belief, capability, allegiance, identity, or desire across structural spans. |
| Relationship Arc | `SPLIT` | `TRAJECTORY` | Split from generic Arc: change in trust, power, intimacy, obligation, conflict, or alignment across spans. |
| Thematic Trajectory | `NEW_REQUIRED_CONCEPT` | `TRAJECTORY` | Accumulated dramatic evidence for competing thematic claims; distinct from Theme intent. |
| Obligation | `KEEP` | `TRAJECTORY` | Setup/question/debt/promise with provenance, dependency, due window, carry state, and explicit resolution or retirement. |
| ChapterGroup | `DEMOTE_TO_EXECUTION_ARTIFACT` | `POLICY` | Adaptive rolling planning/production window. It is not a mandatory narrative container. |
| `3–8 Chapters` | `DEMOTE_TO_POLICY` | `POLICY` | Remove it as a domain rule. An operational profile may cap a window by cost/context, but no universal minimum or maximum is a narrative invariant. Terminal and risk-driven windows may be any positive size. |
| Chapter Plan | `SPLIT` | `PLAN` plus `EXECUTION_CONTRACT` | Split into Chapter Mission and Scene Architecture; a compatibility projection may expose a composite Chapter Execution Plan. |
| Chapter Mission | `NEW_REQUIRED_CONCEPT` | `PLAN` | The chapter's required narrative change: function, conflict, information gain, trajectory deltas, obligation actions, payoff, and exit pressure. |
| Scene | `KEEP` | `STRUCTURAL_CONTAINER` plus `PLAN` | Ordered unit with viewpoint, time/place, goal, resistance, turn, outcome, and transition. |
| Beat | `KEEP` | `PLAN` | Atomic narrative action/reaction/revelation/decision unit within a Scene; stable identity supports traceability. |
| Narrative Realization | `KEEP` | `EXECUTION_CONTRACT` | Frozen binding of approved intent, accepted boundary, plan versions, context manifest, Provider contract, budgets, and attempt lineage. It is not accepted story content. |
| Draft | `KEEP` | `CANDIDATE` | Immutable prose candidate tied to one realization attempt and exact context/instruction/provider identity. |
| Revision | `KEEP` | `CANDIDATE` | New candidate plus issue-resolution map and diff lineage; never an in-place overwrite. |
| Accepted Actual | `KEEP` | `ACCEPTED_FACT` | Immutable accepted narrative events/outcomes at an exact chapter boundary. This is the source for accepted-history projections. |
| Canon | `KEEP` | `PROJECTION` with governed approvals | Queryable accepted facts and approved interpretations derived from Accepted Actual; conflicts require a decision, not silent last-write-wins. |
| Narrative State | `KEEP` | `PROJECTION` | Deterministic entity, temporal, knowledge, resource, location, and obligation state at an accepted boundary. |
| Reader State | `KEEP` and rename to Reader Evidence View | `EVIDENCE` / `PROJECTION` | Versioned observations and derived hypotheses about readers; never Canon or direct plan mutation. |
| Completion Case | `NEW_REQUIRED_CONCEPT` | `CANDIDATE` then decision record | Whole-book closure dossier and independent acceptance decision, distinct from the terminal production cursor. |

### Relationship types

Every persisted relationship declares exactly one of these semantics:

| Relationship | Meaning | Example |
|---|---|---|
| Structural containment | Where an authored unit lives | Scene is contained by Chapter. |
| Causal dependency | What must cause or enable what | Revealed evidence enables a later decision. |
| Temporal trajectory | How a subject changes across accepted boundaries | Trust rises, collapses, and is partially restored. |
| Planning dependency | What must be approved before elaboration | Book Architecture precedes an active Volume plan. |
| Execution dependency | What an attempt must freeze or consume | Prose Realization consumes one Chapter Mission and Context Manifest. |
| Accepted-fact projection | What can be rebuilt from accepted history | Narrative State at chapter 120 is projected from Accepted Actual through 120. |

No generic `parent_id` may stand in for more than one relationship type.

## 5. Structural hierarchy and cross-cutting trajectories

### Structural location model

```text
Book (ordered chapter timeline)
├── Volume [optional, non-overlapping macro interval]
├── Narrative Segment [bounded story-phase interval]
└── Chapter
    └── Scene
        └── Beat
```

Volumes and Segments are typed intervals over the Book's chapter timeline. A Segment is
assigned to the Book and, where volumes exist, normally lies within one Volume; an
approved exception must be explicit. Chapters remain the accepted-history boundary.

### Cross-cutting trajectory model

```text
Narrative Arc ────────────────┐
Character Arc ────────────────┤
Relationship Arc ─────────────┼─ links to spans, missions, scenes, and accepted outcomes
Thematic Trajectory ──────────┤
Obligation ───────────────────┘
```

A trajectory is not contained by a Volume or Segment. It declares intended checkpoints
against structural spans and separately accumulates accepted actual progress. One Arc
may cross volumes; one Segment may advance several trajectories; a Chapter Mission must
name the exact trajectory and obligation contributions it intends to make.

### Arc and Segment decision

- A Segment answers: **what bounded phase of the story timeline is this?**
- An Arc answers: **what conflict or transformation is changing, why, and toward what
  closure?**
- Segment boundaries may be useful checkpoints for an Arc but do not own it.
- Arc status is derived from accepted outcomes, not from the cursor merely entering or
  leaving a Segment.

## 6. Narrative descent and layer contracts

Narrative validation descends by semantic readiness. Chapter count is only an execution
parameter or evaluation sample size.

| Layer | Required input | Authority-owned output | Lifecycle | Gate before descent | Failure/revision semantics |
|---|---|---|---|---|---|
| Story Intent | idea, audience hypothesis, source-safe inspiration | approved Story Intent | candidate → reviewed → approved | distinct premise, audience fit, originality boundary, feasible form | reject or create a new candidate; do not patch approval history |
| Foundation | approved intent | versioned Theme, Promise, Ending, World, Character, Relationship assets plus composite snapshot | candidate → qualified → approved → active | cross-asset consistency, dramatic pressure, ending feasibility, promise integrity | revise only affected candidate versions; requalify dependent assets |
| Book Architecture | active Foundation | Book structure, optional Volume intervals, Segment design, macro turns and closure envelope | candidate → reviewed → approved → active | causal completeness, escalation capacity, ending path, length elasticity | replace future architecture; preserve accepted boundary and impact report |
| Trajectory portfolio | Book Architecture and Foundation | typed Arcs, Character/Relationship/Thematic trajectories, Obligation ledger | proposed → qualified → active → closed/retired | dependencies, checkpoint coverage, contradiction and orphan-obligation checks | revise future checkpoints; accepted progress remains immutable |
| Chapter Mission | active future plan, actual trajectories, obligations, accepted boundary | one semantically necessary mission | proposed → qualified → approved → active → executed/superseded | clear change, conflict, information movement, payoff/setup, trajectory contribution | replace mission before execution; after acceptance use future consequence, not history rewrite |
| Scene Architecture | active Chapter Mission | ordered Scene and Beat plans | proposed → qualified → frozen | mission coverage, causal transitions, viewpoint/knowledge/time validity, prose feasibility | local revision or return to mission if failure is structural |
| Prose Realization | frozen scene plan, accepted-only context, approved style/policy | immutable realization contract and Draft candidate | prepared → running → checkpointed → candidate/failed/unknown | contract identity, source isolation, context budget, Provider hard stop | retry by policy with new attempt; reconcile unknown effects before resend |
| Review and Revision | Draft, rubric, continuity evidence | issues, evaluations, revised candidate | review → revise → re-review → gate decision | blocking issues resolved, fidelity and continuity demonstrated | bounded loop; escalate when budget/attempt limit or structural defect reached |
| Accepted Actual | quality-passed candidate, governed background decisions and exact source evidence | chapter acceptance event and actual outcomes | proposed → acceptance decision → accepted | owner authorization, exact lineage, no stale boundary, atomic projection inputs | rejection preserves candidate; accepted fact corrected only by explicit compensating decision |
| Whole-book Completion | terminal cursor plus full accepted history | Completion Case and completion decision | opened → assessed → needs remediation/accepted/rejected | closure, consistency, defect, human/editorial, publication-readiness gates | remediation creates future/corrective work or a new edition case; never silently flips history |

## 7. Lifecycle and truth-state model

### Design and plan lifecycle

```text
DRAFT_CANDIDATE → QUALIFIED → APPROVED → ACTIVE → FROZEN → EXECUTED
       │              │          │         │
       └→ REJECTED    └→ REVISE  └→ SUPERSEDED (future only)
```

`APPROVED` means acceptable but not necessarily selected. `ACTIVE` is the sole future
plan version an owner exposes to downstream work. `FROZEN` binds one execution. An
executed plan is historical evidence; it is never reactivated or mutated.

### Prose and actual lifecycle

```text
Draft Candidate → Review Issues → Revision Candidate → Quality Passed
                                                     → Rejected
Quality Passed → Acceptance Decision → Accepted Actual
```

Quality does not accept narrative truth. Acceptance does not prove human quality. The
accepting Authority records which candidate and evidence became historical actual.

### Obligation lifecycle

```text
PROPOSED → OPEN → DUE → FULFILLED
                    ├→ DEFERRED (new due window + approved reason)
                    ├→ RETIRED  (explicit impact decision)
                    └→ VIOLATED (unresolved defect evidence)
```

An obligation cannot disappear through context compression or plan replacement.

## 8. Target Authority model

### Ownership rules

- An Authority owns decisions and mutations for a fact class.
- A Coordinator orders commands but cannot commit another Authority's state.
- An Agent produces a candidate, proposal, evaluation, or command request.
- A Provider returns untrusted output or an ExternalEffect receipt.
- A Repository persists an Authority decision but does not make it.
- A Projection is rebuildable and cannot accept its own inputs.
- Evidence supports a decision but is not the decision.

### Current-to-target Authority decisions

| Current Authority or boundary | Decision | Target owner and sole fact ownership |
|---|---|---|
| Project Authority | `KEEP` | Project/workspace identity, lifecycle, bindings, and tenancy. |
| Story Design Authority | `KEEP` | Owns the six Foundation semantic asset roles; specialization does not create duplicate or physically separate owners. |
| Book Design Authority | `KEEP` | Owns Book Architecture and immutable QualifiedFoundationSet binding; typed structural plan activation remains Planning Authority-owned. |
| Planning Authority | `SPLIT` | Trajectory Authority owns typed trajectory plans; Chapter Planning Authority owns Chapter Mission and Scene Architecture activation. |
| Narrative Realization Authority | `KEEP` | Independent logical owner of the frozen execution contract; Command Kernel owns attempts, leases and fences. It owns no narrative truth. |
| Plan Change Authority | `KEEP` | Narrow it to Change Authority ownership of impact cases, approvals, and command requests; each affected domain owner commits its own replacement. |
| Book Authority | `SPLIT` | Book Production Authority owns cursor/admission; Book Acceptance Authority owns atomic accepted chapter actuals. |
| ChapterGroup Authority | `RETIRE` | Retire it as a domain Authority. Rolling Window Coordinator schedules bounded work and owns only window execution state. |
| Chapter Authority | `KEEP` | Clarify it as Chapter Production Authority, owning attempts, drafts, revisions, receipts, and release candidates. |
| Quality Authority | `KEEP` | Rubric versions, evaluation evidence, issues, and gate decisions; never Accepted Actual. |
| Canon Authority | `KEEP` | Canon candidate decisions, conflict decisions, and canonical fact view inputs. |
| Narrative State | `KEEP` | It remains a projection rather than an Authority; Narrative State Projector deterministically derives state from accepted inputs. |
| Reader Evidence Authority | `KEEP` | Reader observations, cohort definitions, derived hypotheses, and evidence quality. |
| Source / MKAOS Authorities | `KEEP` | Source lineage, rights, abstraction, knowledge candidates, and pack selection; no narrative truth. |
| Agent Runtime | `KEEP` | Agent definitions, permissions, runs, checkpoints, budgets, tool receipts, and transcript provenance. |
| Provider Effect Authority | `KEEP` | ExternalEffect intent, send boundary, receipt, cost, and reconciliation. |
| Runtime Job | `KEEP` | Keep it as a coordinator for durable scheduling/recovery state only. |
| Whole-book completion | `ADD` | Book Completion Authority owns Completion Cases and terminal quality acceptance. |
| Publication | `ADD` | Publication Authority owns release readiness/decision and publication receipts, never editorial truth. |

### Acceptance flow without ownership leakage

```text
Agent/Provider → candidate/evidence
Quality Authority → gate decision
Book Acceptance Authority → Accepted Actual
Canon Authority → canon decision/input
Narrative State Projector → rebuildable state
Trajectory Projector → actual progress
Book Completion Authority → whole-book decision
```

## 9. End-to-end business blueprint

Rows in each table are ordered by their primary downstream dependency: an accepted or
active output is the next row's input unless another dependency is named explicitly.
Cross-cutting feedback and replan edges are described in the final table and the change
protocol.

### Design and planning

| Stage | Owner | Input → output | State and gate | Human / Agent / Provider | Persistence and recovery |
|---|---|---|---|---|---|
| Idea/topic discovery | Story Foundation Authority | market/source-safe evidence → Story Intent candidates | candidate; originality and feasibility gate | Agent proposes; human may select; Provider assists only | candidate lineage; retries create new versions |
| Foundation | Story Design Authority | approved Intent → six Foundation semantic asset roles, including Character/Relationship definitions | qualified then approved | specialist Agents; human risk-based approval | versioned assets; immutable qualified bindings; partial failure resumes per asset |
| Book architecture | Book Architecture Authority | active Foundation → Book/Volume/Segment architecture | approved active future architecture | Book Architect Agent proposes; human approves strategic risk | immutable versions and active pointer; replacement after impact analysis |
| Trajectory planning | Trajectory Authority | architecture + Foundation → Arc/Character/Relationship/Theme trajectories and obligations | active portfolio gate | planner Agents propose; independent review | graph versions, dependencies, checkpoints; no accepted-state mutation |
| Rolling planning | Rolling Window Coordinator | actual boundary + active future plans → bounded mission queue | policy-bounded, not chapter-count qualification | deterministic coordinator; Agents elaborate | window state disposable/rebuildable; leases and checkpoints |
| Chapter mission | Chapter Planning Authority | trajectory needs + obligations + promise → Chapter Mission | semantic readiness gate | Chapter Planner proposes; editor approves by policy | versioned mission; future replacement only |
| Scene/beat design | Chapter Planning Authority | active Mission → frozen Scene Architecture | execution-readiness gate | Scene Designer proposes; deterministic validation | stable scene/beat ids; retry or return to Mission |

### Production and acceptance

| Stage | Owner | Input → output | State and gate | Human / Agent / Provider | Persistence and recovery |
|---|---|---|---|---|---|
| Context compilation | Context Compiler service under Production Execution | accepted boundary + exact plans + allowed knowledge → Context Manifest/Bundle | source isolation, coverage, leakage, token gates | retrieval may rank; no model-selected truth | immutable manifest and candidate union; deterministic replay |
| Realization preparation | Narrative Realization Authority | frozen plan/context/policy → Realization Contract | identity/budget/permission gate | Agent requests; no narrative decision | independent frozen contract; kernel-owned command/attempt/lease/fence |
| Prose generation | Chapter Production Authority | Realization Contract → Draft Candidate | schema and receipt gate | Prose Agent invokes Provider through governed effect | ExternalEffect intent/receipt/cost; reconcile unknown before resend |
| Review/diagnosis | Quality Authority | Draft + plans + accepted state → Review Issues/evaluations | independent rubric gates | machine checks + independent LLM judges + optional human | evidence immutable; judge identity recorded |
| Revision | Chapter Production Authority | candidate + accepted issue set → Revision Candidate | issue-resolution and regression gate | Editor Agent proposes patch; Provider bounded | new artifact/version/diff; bounded attempts and escalation |
| Chapter quality gate | Quality Authority | candidate and evidence → pass/revise/block decision | no self-certification | independent judge; human for policy/risk cases | decision and evidence ids; replay returns same decision |
| Chapter acceptance | Book Acceptance Authority | quality-passed candidate + exact boundary → Accepted Actual | atomic lineage/staleness gate | authorized command; Agent cannot accept | one transaction commits acceptance and projection inputs |
| Canon/state projection | Canon Authority and projectors | Accepted Actual → Canon decisions, Narrative State, actual trajectories, obligation state | conflict and deterministic replay gates | extraction Agent proposes; owner decides conflicts | append-only inputs, rebuildable projections, repair evidence |

### Adaptation, completion, and operation

| Stage | Owner | Input → output | State and gate | Human / Agent / Provider | Persistence and recovery |
|---|---|---|---|---|---|
| Reader observation | Reader Evidence Authority | feedback/behavior → normalized observations | provenance, cohort, privacy, quality gate | readers provide evidence; Reader Analyst proposes hypotheses | raw access controlled; derived evidence versioned |
| Adaptation proposal | Change Authority | reader evidence + defects + trajectory state → Impact Case | causal uncertainty and accepted-boundary gate | Replan Agent proposes; human approves high-impact change | change case, dependency closure, decision receipts |
| Future replan | each affected plan owner | approved Impact Case → replacement future versions | no executed/accepted mutation | Agents draft replacements; owners activate | atomic pointer changes; rollback restores prior future pointer |
| Rolling stability review | Quality Authority | accepted spans + projection diagnostics → longitudinal evidence | continuity/drift/pacing gate | automated trend checks, independent editorial samples | periodic evidence windows; failures open issues, not history edits |
| Production cursor close | Book Production Authority | final planned chapter accepted → terminal cursor | completeness-of-execution only | coordinator | idempotent cursor transition |
| Whole-book completion | Book Completion Authority | terminal cursor + full Completion Case → accepted/remediation/rejected | all completion gates | independent human/editorial decision required for human-quality claim | versioned case/decision; remedial edition remains traceable |
| Publication | Publication Authority | accepted completion + release package → publish decision/receipt | platform, rights, packaging, operational gate | human approval by policy; Provider cannot publish itself | external effect receipt, reconciliation, rollback/withdrawal record |
| Observe/learn | Reader Evidence and policy owners | real outcomes → evidence and policy proposals | evidence-class and causality gate | analysts propose; owner approves policy change | versioned cohorts/models; never direct Canon/plan mutation |

## 10. Validation architecture: how the system proves it can write novels

### Evidence classes

| Evidence class | What it can establish | What it cannot establish |
|---|---|---|
| Engineering Correctness | schema, ownership, transactionality, idempotency, recovery, source isolation, deterministic projections | narrative quality or reader value |
| Narrative Design Correctness | required fields, causal graph, coverage, dependencies, promise/ending/trajectory alignment | prose quality or actual reader response |
| Narrative Continuity | accepted-fact consistency, temporal/knowledge/state validity, obligation accounting | artistic merit or commercial success |
| Editorial Quality | rubric-grounded craft judgment, comparative preference, issue resolution | population-level reader behavior unless sampled accordingly |
| Human Review | attributable judgments from qualified reviewers under a defined protocol | general market success from a tiny or biased sample |
| Reader Evidence | cohort-specific reaction, retention, completion, comments, conversion observations | unconfounded causality by default |
| Longitudinal Stability | quality/continuity behavior across sufficiently long accepted spans and recovery events | a finished-book verdict without closure review |
| Commercial / Production Evidence | real operational reliability and measured platform outcomes | universal literary quality or portability to another market |

### Gates by abstraction

| Gate | Machine-verifiable minimum | LLM-judge role | Human/reader requirement | Failure action |
|---|---|---|---|---|
| Story Intent | schema, source rights, distinctness metadata, target constraints | compare premise clarity and risk | strategic approval for expensive production | reject/new candidate |
| Foundation | cross-reference closure, contradictions, version freshness | adversarial thematic/world/character critique | human approval for Reader Promise and Ending risk | revise affected assets |
| Book Architecture | span validity, causal graph, ending reachability, trajectory coverage | developmental critique and alternative stress test | human approval before large-scale descent | replace future architecture |
| Trajectory portfolio | dependency cycles, checkpoint/orphan obligation checks | escalation, transformation, and payoff critique | sample review at major risk points | revise future trajectory |
| Chapter Mission | required change, contribution references, accepted-boundary freshness | necessity, tension, pacing, and novelty critique | policy-based sampling, not every chapter by default | replace mission |
| Scene/Beat | order, knowledge/time/state legality, mission coverage | scene dynamics and redundancy critique | optional high-risk review | local revise or return upward |
| Draft/Revision | contract fidelity, leakage, continuity, issue closure | independent multi-dimension judgment; never sole human proxy | calibrated editorial sampling; human gate for claimed human quality | bounded revision/escalation |
| Chapter Acceptance | exact lineage, quality decision, stale-plan check, atomic inputs | no acceptance authority | authorized acceptance policy | reject or accept atomically |
| Longitudinal window | drift, repetition, obligation aging, trajectory actual-vs-plan | diagnose patterns across spans | periodic blind editorial comparison | open issues/replan proposals |
| Whole book | structural/trajectory/obligation closure and unresolved-defect accounting | synthesize dossier, cannot self-accept | independent editorial acceptance required | remediation or rejection |
| Publication/market | rights, package, receipt, operational metrics | summarize evidence | real readers/production required for market claim | adjust policy through proposal |

Rules:

- The generator and its evaluator identities must be recorded; self-evaluation is never
  the only evidence for an editorial claim.
- A fixed number of evaluators is not a domain invariant. Evaluator independence,
  calibration, disagreement handling, and risk determine quorum policy.
- Thresholds are versioned policies tied to rubric and evidence class, not eternal
  narrative constants.
- “One chapter”, “eight chapters”, or “fifty chapters” may define a sample, load test, or
  longitudinal window. None is a Narrative Capability maturity level.
- AI cannot promote its output to Human Review, Reader Evidence, or Commercial Evidence.

## 11. Context, memory, and retrieval model

### Context planes

| Plane | Allowed content | Prose-generation rule |
|---|---|---|
| Accepted history | Accepted Actual, approved Canon facts, Narrative State, actual trajectory progress, obligation state | authoritative; include exact boundary and provenance; never mix later facts |
| Active future plan | approved Book/Volume/Segment architecture, active trajectories, Chapter Mission, frozen Scene Architecture | instructions for intended future, visibly typed as plan, never stated as accomplished fact |
| Execution contract | Realization Contract, style/rubric policy, tool/budget constraints | frozen per attempt and fully traceable |
| Proposal space | inactive candidates, alternatives, rejected ideas, replan drafts | excluded from prose context; allowed only in design/review/change tasks |
| Reader evidence | attributable observations and hypotheses | excluded from prose by default; may enter adaptation analysis, then only approved plan effects reach prose |
| Source/MKAOS knowledge | rights-cleared abstract facts/mechanisms with lineage | only approved abstract Knowledge Packs; raw reference expression is forbidden |
| Historical operations | old attempts, receipts, failures, prior plan versions | available for recovery/audit, not narrative content unless explicitly summarized as execution guidance |

### Compilation contract

Every Context Manifest records target operation, accepted chapter boundary, temporal
query, included asset/version ids, authority and truth type, retrieval query/candidate
union/ranking, exclusion reasons, compression method, token budget, instruction identity,
and digest. Protected facts and constraints may not be lossy-compressed. Summaries are
projections with lineage, never replacements for their sources.

Retrieval is bounded by stage-specific coverage and stop conditions. Iterative expansion
may continue only while a declared hard-evidence gap remains, budget is available, and a
new immutable candidate union can be formed. The current bounded retrieval campaign is
an As-Is execution seam that fits here; it is not the narrative architecture or a
product progression model.

### Leakage and conflict rules

- Prose generation may read accepted history only through its accepted boundary.
- Future plans are labeled `PLANNED`; rejected/superseded proposals are excluded.
- A retrieved item cannot upgrade its own truth type.
- Conflicting accepted facts block context compilation until Canon conflict resolution
  selects an interpretation or records an explicit unresolved condition.
- Character knowledge is projected separately from global truth.
- Every context-dependent review must retain the actual sent Context Manifest.

## 12. Replan and change semantics

```text
Accepted History = immutable
Active Future Plan = replaceable by its owner
Trajectory Intent = re-evaluable after each accepted boundary
Trajectory Actual = append-only projection from accepted outcomes
Obligation = carry, fulfill, defer, retire with reason, or record violation
```

### Change protocol

1. Open an Impact Case with reason, evidence class, accepted boundary, requested scope,
   and affected Authority owners.
2. Compute dependency closure across World rules, Characters, Relationships, Book
   Architecture, trajectories, obligations, missions, scene plans, and frozen attempts.
3. Reject any request that edits Accepted Actual or executed plan history.
4. Produce replacement candidates only for the unaccepted future.
5. Require each owning Authority to approve and activate its own replacement in one
   coordinated change set; the Change Authority cannot impersonate them.
6. Invalidate stale missions, contexts, realization contracts, and unstarted attempts.
   Reconcile already-sent ExternalEffects before retry or cancellation.
7. Project impact on ending feasibility, Reader Promise, open obligations, and whole-book
   completion conditions.
8. Resume from a new checkpoint with exact before/after versions and rollback pointers.

### Change examples

| Requested change | Target behavior |
|---|---|
| World rule | New rule version applies prospectively. If history contradicts it, refine the future explanation or open a Canon correction case; never pretend the old event did not occur. |
| Character route | Replace future Character Arc checkpoints and dependent missions; retain actual prior choices and state. |
| Narrative Arc | Re-evaluate closure and dependencies; replace future Arc plan and carry/resolve affected obligations explicitly. |
| Volume/Segment | Repartition only unaccepted spans; accepted chapter locations remain historical. |
| Insert/delete future chapter | Change mission/structural plan versions and renumber through stable ids plus display-order projection; do not change accepted ids. |
| Reader-driven adaptation | Store observations and causal uncertainty, approve an Impact Case, then let the proper plan owners activate changes. Feedback never writes plans directly. |

## 13. Whole-book completion

`Book terminal cursor != Whole-book quality acceptance`.

The Book Production Authority may mark execution terminal after the last planned chapter
is accepted. A separate Book Completion Authority evaluates a Completion Case containing:

- structural closure for Book, declared Volumes, and Segments;
- major Narrative Arc closure or explicitly accepted open-series continuation;
- Character and Relationship trajectory closure against approved Ending Intent;
- every Obligation fulfilled, deliberately deferred to a declared continuation, or
  explicitly retired with impact evidence;
- Canon consistency and successful full projection replay;
- finalized Narrative State and terminal character-knowledge snapshots;
- unresolved defect inventory with severity and waiver authority;
- longitudinal continuity, repetition, pacing, and quality evidence;
- independent editorial/human evidence for any human-quality claim;
- rights, source-isolation, packaging, and publication-readiness evidence.

Completion decisions are `NEEDS_REMEDIATION`, `ACCEPTED`, or `REJECTED`. Acceptance names
the exact Book edition and accepted chapter boundary. A later corrected edition gets a
new Completion Case; it does not overwrite the earlier decision.

## 14. Agent, Skill, and prompt target architecture

These are target contracts, not current Agent claims. Every Agent output is one of
`CANDIDATE`, `PROPOSAL`, `EVALUATION`, or `COMMAND_REQUEST`.

| Target Agent | Purpose and input | Output contract | Allowed context | Authority boundary | Tools / Skill capability | Gate and failure semantics |
|---|---|---|---|---|---|---|
| Story Strategist | turn product intent/evidence into Story Intent options | Story Intent candidates + risk comparison | market evidence, source-safe abstractions, product constraints | cannot approve intent | search/analysis; topic and strategy skills | originality/feasibility gate; return insufficient-evidence or alternatives |
| Foundation Designer | coordinate Theme, Promise, Ending candidates | specialized candidates + composite proposal | approved intent and relevant abstract knowledge | cannot activate specialized assets | structured generation; foundation capability pack | cross-asset gate; failed asset does not erase passed siblings |
| World Designer | propose rules and consequence systems | World candidate + contradiction report | intent, theme, promise, approved knowledge | cannot mutate Character/Canon | worldbuilding, consequence modeling | rule-cost/consistency gate; revise candidate |
| Character & Relationship Designer | propose characters, relationships, starting states | versioned candidates + dependency map | active World/Foundation | cannot write accepted character state | character/relationship design | dramatic-function and contradiction gate |
| Book Architect | design Book/Volume/Segment structure | Book Architecture candidate | active Foundation and target form | cannot own trajectories or approve architecture | long-outline, narrative-beat design | causal/ending/elasticity gate; new version on failure |
| Trajectory Planner | design typed arcs and obligations | trajectory portfolio candidate | active Foundation/Architecture | cannot mark actual progress | arc, continuity, pacing skills | dependency/coverage/payoff gate |
| Chapter Planner | select next necessary change | Chapter Mission candidate | accepted state, active plans, due obligations | cannot accept or execute chapter | chapter-outline, temporal query | semantic-readiness gate; escalate structural defects upward |
| Scene Designer | realize a mission as scene/beat causality | Scene Architecture candidate | one active mission and accepted boundary | cannot generate accepted prose | beat design, chapter-outline | mission-coverage and knowledge gate |
| Context Compiler Agent | propose retrieval/selection where deterministic rules need assistance | ranked candidate set with reasons | only allowed context planes and retrieval indices | cannot change truth type or final manifest | bounded retrieval/source-isolation | deterministic compiler validates; fail closed on leakage/gaps |
| Prose Generator | create prose from frozen execution contract | Draft candidate + usage/effect evidence | exact Context Manifest only | cannot revise plan, accept prose, or bypass Provider Effect Authority | prose-generation capability pack | schema/budget/hard-stop; new attempt after recoverable failure |
| Continuity Reviewer | detect fact/time/knowledge/state/obligation conflicts | evidence-grounded Review Issues | draft, accepted state, plan contract | cannot edit draft or Canon | continuity graph, temporal query | unresolved high severity blocks quality gate |
| Developmental Editor | diagnose causality, character, pacing, payoff | review + revision proposal | draft, missions, trajectories, rubric | cannot overwrite candidate or accept | quality review, pacing | bounded revisions; escalate mission/architecture defects |
| Quality Judge | independently evaluate declared dimensions | Evaluation with confidence/evidence | candidate, rubric, allowed comparison set | cannot claim human preference or accept truth | quality/evaluation pack | calibrated quorum policy; disagreement stays visible |
| Reader Analyst | convert attributable observations into hypotheses | Reader Evidence view + adaptation proposal | privacy-approved reader evidence and accepted history | cannot mutate plans/Canon | reader-feedback, statistics | cohort/causality gate; weak evidence lowers claim ceiling |
| Replan Agent | build impact closure and replacement requests | Impact Case + owner-specific command requests | actual boundary, future plans, reader/defect evidence | cannot activate any replacement | planning/change/continuity tools | block accepted-history changes; checkpoint partial impact work |
| Completion Reviewer | assemble and challenge whole-book dossier | Completion evaluation | complete accepted edition and all evidence classes | cannot issue completion decision | whole-book analysis and audit | missing evidence yields needs-remediation, never inferred PASS |
| Publishing Agent | prepare release package and monitor receipts | release proposal/command request/observation | accepted completion and platform policy | cannot publish without Publication Authority command | release-gate/platform skills | rights/package/effect gates; reconcile ambiguous publish outcome |

### Skill contract

Each target Skill must define purpose, typed input, typed output, allowed context planes,
Authority boundary, deterministic pre/postconditions, quality criteria, failure classes,
and required evidence. Creative method guidance may help produce a candidate but cannot
relax schema, source, Provider, acceptance, or recovery boundaries. Skill versions are
resolved through governed capability packs and frozen into attempts.

### Prompt contract

Prompt semantics are derived in this order:

```text
Domain schema and Authority contract
→ Skill contract
→ runtime role and permission envelope
→ Context Manifest
→ rendered system/task instructions
```

A prompt cannot create a domain field, state transition, permission, or truth type. Its
identity includes schema version, Skill version, template digest, runtime profile,
Provider/model route, allowed tools, rubric, and context digest. Any change invalidates
the relevant instruction qualification and requires requalification at the appropriate
evidence ceiling.

### Autonomous loop contract

Every Agent loop declares goal, owner-request id, accepted boundary, allowed commands,
budget (turn/token/cost/time/tool calls), checkpoint schema, progress test, stop reasons,
review gate, maximum revision cycles, escalation target, and recovery identity. Budget
exhaustion, repeated non-progress, unresolved critical issue, stale context, ambiguous
ExternalEffect, or lost Authority approval causes a hard stop—not an improvised bypass.

## 15. As-Is to To-Be gap matrix

| Target capability | Current state | Current owner | Gap type | Action | Dependency | Risk | Design confidence |
|---|---|---|---|---|---|---|---|
| Story Intent as approved strategic object | Formation inputs exist, but no independent approved object | Story Design Authority | `MISSING_DOMAIN_CONCEPT` | `ADD` | Foundation contracts | medium | high |
| Foundation ownership | Six semantic roles have one Story Design owner; Book Design owns immutable qualified bindings | Story Design Authority | `IMPLEMENTED` | `KEEP` | native binding validation | bounded | high |
| Book Architecture terminology/lifecycle | Book Design candidate and current pointer exist | Book Design Authority | `WRONG_HIERARCHY` | `REFACTOR` | compatibility projection | medium | high |
| Relationship definition/state/trajectory separation | Data is distributed across character, plans, and state views | Story Design / Planning; Narrative State is projection | `MISSING_DOMAIN_CONCEPT` | `ADD` | Character and Trajectory Authorities | high | high |
| Segment as structural interval, not Arc parent | Segment exists as a typed plan; relationship typing is incomplete | Planning Authority | `WRONG_HIERARCHY` | `REFACTOR` | structural relation schema | medium | high |
| Typed cross-structure trajectories | Arc is first-class; character/relationship evolution lacks an equal lifecycle | Planning Authority; actual progress is projected | `MISSING_DOMAIN_CONCEPT` | `ADD` | Trajectory Authority | high | high |
| Thematic actual trajectory | Theme contract exists without accepted-evidence progression | Story Design Authority | `MISSING_DOMAIN_CONCEPT` | `ADD` | Accepted Actual projection | medium | medium |
| Adaptive rolling execution window | ChapterGroup coordination consumes a versioned configurable execution policy | ChapterGroup execution policy owner | `IMPLEMENTED` | `KEEP` | exact frozen policy binding | bounded | high |
| Chapter Mission separated from execution detail | Typed Mission is owned by the Chapter plan, independently referenced by Scene Architecture | Planning Authority | `IMPLEMENTED` | `KEEP` | schema-backed planning activation | bounded | high |
| Scene/Beat production contract | Scene Architecture binds exact Mission and validates mission coverage | Planning and Chapter Authorities | `IMPLEMENTED` | `KEEP` | typed planning contract | bounded | high |
| Realization as execution-only contract | Separate owner/lifecycle distinguishes frozen contract from plan and actual; kernel retains attempts | Narrative Realization Authority | `IMPLEMENTED` | `KEEP` | execution boundary | bounded | high |
| Chapter acceptance distinct from Book cursor | One Authority owns cursor and atomic chapter acceptance | Book Authority | `WRONG_OWNERSHIP` | `REFACTOR` | atomic acceptance transaction | high | medium |
| Typed Canon conflict/correction decisions | Approval/re-extraction exists; retrospective correction is incomplete | Canon Authority | `MISSING_ACCEPTANCE` | `ADD` | Accepted Actual and projection versioning | high | medium |
| Reader evidence causality and privacy gates | Proxy thresholds have versioned owned policy; privacy/causal qualification remains unresolved | Reader Evidence Authority | `MISSING_EVIDENCE` | `DESIGN_REVIEW_REQUIRED` | cohort and privacy contracts | high | high |
| Whole-book Completion Authority | Immutable full-history cases and independent rejection/block decisions exist; acceptance cannot bypass missing native human policy | Book Completion Authority | `MISSING_ACCEPTANCE_POLICY` | `DESIGN_REVIEW_REQUIRED` | typed native whole-book editorial policy/evaluator | critical | high |
| Layer-specific narrative gates | Progressive layers exist, but not the full target approval chain | Story Design, Planning, and Quality Authorities | `MISSING_GATE` | `REFACTOR` | ontology and evidence taxonomy | high | high |
| Human editorial evidence protocol | Blind protocol support exists; no whole-book human acceptance proof | Quality Authority | `MISSING_EVIDENCE` | `ADD` | reviewer identity/privacy and Completion Case | high | high |
| Real reader/production learning | Evidence objects exist; current proof is fixture/scripted | Reader Evidence Authority | `MISSING_EVIDENCE` | `ADD` | publication and privacy | high | high |
| Longitudinal million-character stability | Bounded/local tests only | Quality Authority | `MISSING_EVIDENCE` | `ADD` | stable projections and completion model | critical | high |
| Agent role coverage for target stages | Runtime and Skills exist; operation coverage is partial | Agent Runtime Authority | `MISSING_AGENT_CAPABILITY` | `REFACTOR` | target Authorities and capability packs | high | high |
| Agent hard-stop/rollback across all business loops | First production slice exists; business coverage is incomplete | Agent Runtime / Command Kernel / Provider Effect Authorities | `ENGINEERING_GAP` | `REFACTOR` | ExternalEffect and checkpoints | critical | high |
| Context plane typing | Strong source/accepted-boundary controls exist; target planes are incomplete | Context/retrieval composition | `MISSING_GATE` | `REFACTOR` | target ontology and Context Manifest | high | high |
| Multi-owner atomic future change set | Future replacement exists; cross-owner activation protocol is incomplete | Plan Change Authority | `ENGINEERING_GAP` | `REFACTOR` | Change Authority and owner commands | critical | medium |
| Publication Authority and receipts | Release-gate concepts exist without an independent end-to-end owner | No current independent owner | `MISSING_DOMAIN_CONCEPT` | `ADD` | Completion acceptance and ExternalEffect | high | medium |
| Target Skill/prompt qualification | Current Skills and packs describe current contracts only | Skill governance / Capability Pack Authority | `MISSING_AGENT_CAPABILITY` | `ADD` | schemas, roles, validation | high | high |

No row is an implementation commitment or delivery sequence.

## 16. Key design decisions

1. The target ontology is a typed graph, not a single hierarchy.
2. Book/Volume/Segment/Chapter/Scene/Beat provide structural location; trajectories cross
   those boundaries.
3. Narrative Arc remains independent of Volume. Segment is a bounded phase, not an Arc
   owner.
4. Character, Relationship, and Thematic trajectories become first-class typed
   trajectories rather than fields buried in a generic outline.
5. ChapterGroup is retired as a domain container and retained only as a rolling execution
   window concept.
6. The universal `3–8` range is removed from domain semantics. Operational window limits
   are versioned policy and may not block terminal fragments.
7. Chapter Plan is split into Chapter Mission and Scene Architecture.
8. Narrative Realization is a frozen execution contract, not a hierarchy level or fact.
9. Accepted Actual is immutable; Canon, Narrative State, and actual trajectory state are
   governed projections or decisions over accepted inputs.
10. Production cursor closure and whole-book quality acceptance are different decisions
    with different owners.
11. Validation descends through narrative abstraction gates. Chapter quantity is merely
    sample size or load.
12. Agents and Providers can propose, evaluate, and request; only Authorities accept.

## 17. Unresolved design decisions

The blueprint is coherent without resolving these policy/schema choices, but each must
receive an explicit human decision before its affected contract can be implemented.

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

## 18. Implementation implications and approval boundary

Approval of this proposal would imply changes to domain schemas, Authority partitions,
state machines, migration/compatibility mappings, Context contracts, gates, capability
packs, Agent operations, Skills, and qualification evidence. Those changes are outside
this artifact and must not be inferred from it.

Any implementation must preserve these already-proven engineering constraints:

- exact command identity, attempt/lease/fence ownership, and atomic mutation boundaries;
- no blind resend after an ambiguous ExternalEffect;
- deterministic reconstruction of accepted projections;
- source isolation and actual sent-context evidence;
- future-only replacement with explicit impact and invalidation;
- evidence claims limited to the exact implementation identity and proof scope.

The seven unresolved decisions need explicit evidence-backed review before the affected
contracts can change. Implemented dispositions above are projections of executable
references, not authority granted by this proposal. This retained design input never
overrides current implementation, current documentation or qualification evidence.
