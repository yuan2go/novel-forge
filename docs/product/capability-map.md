# Capability map

This is a derived product view of the [Canonical overall design](../architecture/canonical-overall-design.md). Current proof must be re-established against the SHA under review.

## 1. Core terminology

| Term | Canonical meaning |
|---|---|
| Conversational Role | Stable user-facing creative persona backed by AgentDefinition + capabilities + scope/context/tool/policy. Not an Authority. |
| Agent | Governed reasoning actor that produces typed proposals/candidates. Not business truth owner. |
| Capability | Versioned semantic task contract — what can be done. |
| Skill | Versioned procedure/method — how a capability is performed. |
| Capability Pack | Immutable compatible deployment binding of capabilities, Skills, prompts, provider/model route, tools, context/eval/budget/policy. |
| Rule | Deterministic constraint. |
| Knowledge Asset | Governed reusable narrative/professional knowledge. |
| Authority | Domain boundary that accepts/rejects and commits business state. |

## 2. Capability families

```text
Creative Interaction
├ Chief Editor / specialist conversations
├ decision capture / semantic diff / impact
└ Chapter Editor / author approval

Story Intelligence
├ premise / genre / reader / commercial positioning
└ story potential / differentiation / ending direction

Narrative Design
├ Story Foundation / Book Architecture
├ World / Character / Relationship
├ Narrative Threads / Transformation Maps
├ Narrative Arc OS
│  ├ Arc architecture / relations / obligations
│  ├ Arc scheduling / working set
│  ├ Narrative composition
│  └ Arc progress analysis
├ Volume / Narrative Segment
└ progressive planning / replan

Narrative Execution
├ Chapter Mission
├ Evidence / Context Compiler
├ Scene architecture
├ prose generation
├ diagnosis / revision / polish
└ narrative verification

Narrative Authority
├ Accepted Chapter / Accepted Outcome
├ Canon / Narrative Events
├ Narrative State / temporal query
└ plan activation / PlanChange / Replan

Knowledge
├ Source Import / Source Intelligence
├ MKAOS Narrative Intelligence
├ professional/domain knowledge
└ retrieval projections

Quality & Learning
├ deterministic correctness
├ independent semantic evaluation
├ prose/character/world/structure quality
├ longitudinal quality
├ Reader Outcome / attribution
└ governed adaptation

Platform
├ Command Kernel / RuntimeJob
├ shared ProductionExecutionComposition
├ Provider / Tool external effects
├ Agent Runtime / Collaboration
├ PostgreSQL Authority / object artifacts
├ retry / recovery / replay
├ trace / metrics / cost
└ qualification / admission
```

## 3. Narrative Arc capabilities

Arc capabilities do not imply a separate Arc runtime or Authority stack.

- **Arc Architect:** converts desired state transitions into Arc proposals.
- **Arc Scheduler:** selects a bounded current working set using plan/state/dependency/debt/cadence/capacity evidence.
- **Narrative Composer:** compresses several Arc contributions into a small number of natural events.
- **Arc Progress Analyst:** extracts proposed progress evidence from accepted outcomes.
- **Narrative Obligation management:** durable setup/payoff/question/commitment tracking when needed.
- **Arc evolution:** future-only split/merge/spawn/supersede/abandon/reopen under planning governance.

Do not implement one Agent per Arc type or every possible relation as a separate service/type without a concrete use.

## 4. Target conversational roles

A small stable role set is preferred:

- Chief Editor;
- Story Architect;
- Character Director;
- World Architect;
- Theme & Philosophy Advisor;
- Reader & Commercial Strategist;
- Plot Doctor;
- Research & Material Curator;
- Chapter Director;
- Chapter Editor;
- Long-form Retrospective;
- Reader Outcome Analyst.

Quality Judge is an evaluation boundary, not a negotiable conversational persona.

## 5. Context / Memory / Knowledge boundary

```text
Authority Memory      accepted/design truth in PostgreSQL
Working Memory        frozen task-specific Context
Interaction Evidence  conversation / rationale / rejected alternatives
Retrieval Memory      rebuildable search/vector projections
MKAOS                  reusable methods/patterns/domain intelligence
```

No Agent-private memory may override these sources.

## 6. Current implementation boundary

Current code contains substantial runtime surfaces for PostgreSQL Authorities, Command Kernel/RuntimeJob, progressive planning, Chapter/Book production, Narrative State, PlanChange/Replan, Source/MKAOS, Agent Collaboration/Runtime, provider governance, quality/reader functions and recovery.

The following target semantics require latest-code verification and, where absent, implementation/proof:

- autonomous Chapter-to-Chapter liveness with advisory sidecars detached from the default critical path;
- explicit progress/stall explainability for Book production;
- plan-driven Chapter Mission / bounded Production Packet convergence;
- richer Arc OS runtime/working-set/obligation/progress semantics;
- MKAOS Narrative Intelligence selection/effectiveness;
- sustained real-provider long-form quality;
- calibrated Reader Outcome / real feedback loop;
- multi-book production qualification.

## 7. Evidence model

Report separately:

```text
CODE_IMPLEMENTED
CANONICAL_WIRED
TEST_EXECUTED
RUNTIME_PROVEN
LONGFORM_PROVEN
PRODUCTION_QUALIFIED
```

And, where the repository maturity ladder is used:

```text
MISSING → SKELETON → IMPLEMENTED → WIRED → FIXTURE_PROVEN
→ REAL_PROVIDER_PROVEN → LONGFORM_PROVEN → MULTIBOOK_PROVEN → PRODUCTION_PROVEN
```

Never promote fixture/mock/code-reading evidence to a higher proof class.
