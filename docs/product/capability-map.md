# Capability map

This product view is subordinate to the [Canonical overall design](../architecture/canonical-overall-design.md). Runtime/proof claims must be re-established at the current SHA.

## 1. Agent, role, capability, Skill, and Capability Pack

| Term | Meaning |
|---|---|
| **Conversational Role** | A user-facing creative persona such as Chief Editor or Chapter Editor. It is expressed through versioned AgentDefinition, scope/context policy, capabilities, tools, and approval policy. It is not a Domain Authority or separate runtime service. |
| **Agent** | A governed reasoning executor with a versioned definition, scope, permissions, budgets, tools, context, and candidate output. Its durable execution reuses the canonical production execution plane. It is not a Domain Authority. |
| **Capability** | A versioned unit of work with typed input/output and risk/qualification contracts. |
| **Skill** | A reusable, versioned procedure bound by content hash, contracts, dependencies, invocation limits, and drift policy. It owns no business Authority. |
| **Capability Pack** | A validated, compiled, content-addressed manifest that freezes compatible roles, workflows, capabilities, Skills, prompts, tools, policies, gates, and release compatibility. |
| **Authority** | The owning domain boundary that accepts/rejects and commits business state. Agent/role/provider output remains a proposal until Authority semantics accept it. |

Conversational roles are deliberately few; capabilities may be numerous and composable. Do not multiply one Agent persona per narrative level or literary concept.

## 2. Target conversational role map

| Role | Core capability families | Primary interaction |
|---|---|---|
| Chief Editor | story/reader/theme/commercial synthesis, decision coordination | Book-wide/default entry |
| Story Architect | Book/Volume/Segment/Arc architecture, ending reachability | long-form structure |
| Character Director | identity/state/knowledge/relationship/development | character design and behavior |
| World Architect | world rules/structure/state/consequence/realization | world design and consistency |
| Theme & Philosophy Advisor | value conflict, theme embodiment, philosophical framing | thematic design |
| Reader & Commercial Strategist | reader promise, hooks, rewards, serialization | reader/commercial fit |
| Plot Doctor | diagnosis, alternative simulation, structural repair | existing plot problems |
| Research & Material Curator | provenance/research/creative seed transformation/placement | source and idea integration |
| Chapter Director | chapter/scene function, conflict, reveal, pacing, hook | pre-writing/local design |
| Chapter Editor | text/scene/chapter revision and change escalation | post-draft editing |
| Long-form Retrospective | drift, debt, Arc/character/world longitudinal diagnosis | rolling/Volume/Book review |
| Reader Outcome Analyst | reader evidence, attribution, calibration | post-publication learning |

Optional consultant roles may include Canon/Continuity Consultant, Quality Editor, and Style/Voice Editor. Quality Judge remains an evaluation role/boundary rather than a conversational persona whose result can be negotiated.

## 3. Capability architecture

```text
Creative Interaction
├ session/scope/context
├ decision capture
├ proposal / semantic diff
├ impact / risk
└ author editing

Story Intelligence
├ topic / genre / premise
├ reader positioning
├ commercial patterns
└ story-potential evaluation

Narrative Design
├ Novel DNA / Book Architecture
├ Volume Portfolio / Narrative Segments
├ Arc Graph
├ Character Development
├ World Realization
├ Theme / Philosophy
├ Disclosure / Obligations
└ Scheduling

Narrative Execution
├ Chapter / Scene planning
├ Context Compiler
├ Prose / Dialogue / Description / Action
└ Revision

Narrative Correctness
├ Canon / Narrative State / Narrative Events
├ knowledge / belief / disclosure
├ temporal / spatial / causal constraints
└ obligations

Knowledge
├ Source Intelligence / Research
├ MKAOS
└ Retrieval

Quality / Governance
├ deterministic correctness
├ independent semantic evaluation
├ narrative / reader / commercial quality
├ longitudinal quality
├ qualification / approval / activation
└ replan / Production Admission

Platform
├ Command Kernel / RuntimeJob
├ Provider / Tool execution
├ Agent Runtime / Collaboration
├ PostgreSQL Authority
├ trace / metrics / cost
└ retry / recovery / replay
```

## 4. Narrative hierarchy vs Agent architecture

The temporal hierarchy is:

```text
Book → Volume → Narrative Segment → Chapter → Scene → Beat
```

Arc is an orthogonal cross-time graph. Do not create `BookCharacterAgent`, `VolumeCharacterAgent`, `ArcCharacterAgent`, etc. A stable role/capability operates with a `NarrativeScope` and context contract.

## 5. Narrative change capability

Narrative change is a protocol across existing domains, not a new universal Authority:

- Agent Collaboration: proposal/challenge/impact/human decision;
- Revision/Corrective Action: Draft/prose repair;
- PlanChange/Replan: future plan semantic changes;
- Story/Book Design: foundational future design;
- Canon/Narrative State: accepted reality boundary.

Change levels are L0 Text, L1 Scene, L2 Chapter Structural, L3 Arc/Volume Future, and L4 Book/Canon Critical. Routing/escalation follows impact, not whichever Agent the author happened to open.

## 6. Knowledge and memory boundary

- PostgreSQL accepted/design Authority = durable business memory.
- Context snapshot = bounded working memory.
- conversation/collaboration evidence = episodic interaction evidence, not story truth.
- search/vector indexes = rebuildable retrieval memory.
- MKAOS = reusable method/professional knowledge, not per-Book memory.

No Agent-owned private memory may silently override these sources.

## 7. Current runtime capability/evidence boundary

The repository already contains implementation surfaces for Authorities, progressive design/planning, Chapter production, Narrative State, PlanChange/Replan, Source/MKAOS, Agent Collaboration/Runtime, provider control/qualification, quality/reader functions, publishing, and recovery infrastructure. Exact proof must be established at the SHA under review.

| Capability family | Current evidence boundary |
|---|---|
| Project/workspace/task/asset Authority | Implemented/runtime-wired in the current architecture. |
| Story/Book Design + progressive planning | Implemented/runtime-wired; exact current qualification evidence must be checked. |
| Narrative Semantic Evaluation / qualification | Current code contains explicit semantic-evaluation infrastructure; independent trust/evidence must be verified, not inferred from file presence. |
| Chapter production and acceptance | Implemented/runtime-wired with bounded test evidence in the repository. |
| Canonical Narrative State / accepted-event lineage | Implemented/runtime-wired with rebuild/integration evidence in the repository. |
| PlanChange / Book replan | Implemented/runtime-wired with semantic diff/risk concepts. |
| Source Intelligence / MKAOS | Implemented/runtime-wired with bounded fixture/integration evidence. |
| Agent Collaboration / Agent Runtime | Implemented foundation/production slices; broad human conversational product workflow is not proven. |
| Conversational role profiles | **Target capability; implementation/proof to be audited.** |
| Conversation → Decision Capture → owning Authority | **Target capability; not proven as a complete canonical flow.** |
| Chapter Editor selected-text/scene/chapter flow | **Target capability; not proven as a complete canonical flow.** |
| Author Intent projection into Context/Quality | Existing future-intent/state primitives may support it; canonical end-to-end semantics are **not proven**. |
| Real-provider sustained Book run | Requires explicit pinned evidence; code/config existence is insufficient. |
| 30/100/300-chapter long-form correctness | Not established by ordinary bounded tests. |
| Multi-book production correctness | Not proven. |
| Production admission/operated deployment | Not proven by documentation. |

## 8. Proof model

Repository capability maturity:

```text
MISSING
SKELETON
IMPLEMENTED
WIRED
FIXTURE_PROVEN
REAL_PROVIDER_PROVEN
LONGFORM_PROVEN
MULTIBOOK_PROVEN
PRODUCTION_PROVEN
```

Engineering reports additionally distinguish:

```text
CODE_IMPLEMENTED
CANONICAL_WIRED
TEST_EXECUTED
RUNTIME_PROVEN
PRODUCTION_QUALIFIED
```

These are not interchangeable. `TEST_EXECUTED` states that named tests ran; it does not promote fixture evidence to real-provider or production proof.
