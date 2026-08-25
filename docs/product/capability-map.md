# Capability map

This is a derived product view of the [Canonical overall design](../architecture/canonical-overall-design.md). Current proof must be re-established against the SHA under review.

## 1. Core terminology

| Term | Canonical meaning |
|---|---|
| Conversational Role | Stable user-facing creative persona backed by AgentDefinition + capabilities + scope/context/tool/policy. Not an Authority. |
| Autonomous Agent | Multi-turn governed actor with goal decomposition, dynamic Tool choice, observation and adaptive replanning. Produces proposals/candidates, never business truth. |
| Typed Capability | One versioned semantic task producing an immutable candidate/evidence artifact. Ordinary LLM work belongs here. |
| Skill | Versioned procedure/method; binding a Skill never grants Tool or mutation permission. |
| Tool | Typed read query, Capability invocation or Authority Command submission endpoint. |
| Domain Service | Deterministic validation/reduction/comparison/diff/projection logic. |
| Durable Workflow | Explicit transitions, recovery and stop conditions deciding when bounded work executes. |
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
├ ChapterExecutionIntent / ChapterMemo
├ governed four-class Context Compiler
├ lexical-first long-form retrieval / bounded semantic rerank / compression
├ Scene architecture
├ prose generation
├ diagnosis / revision / re-review / Best Candidate
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

## 4. Autonomous Agents and conversational roles

A very small autonomous set is preferred:

- Studio/Director Agent;
- Research/Knowledge Agent.

User-facing creative roles may provide stable perspectives without becoming separate autonomous runtimes:

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

Worldbuilding, Character, Outline, Chapter Plan, Draft, Review, Revision and Canon Extraction remain Typed Capabilities unless their production behavior demonstrates a real multi-step dynamic Tool/replanning lifecycle.

## 5. Context / Memory / Knowledge boundary

```text
L0 Recent accepted verbatim      L5 Arc/debt state
L1 Current accepted state        L6 episodic summaries
L2 Canon fact graph              L7 lexical/vector/graph index
L3 character/relation timeline   L8 full accepted text archive
L4 obligation graph              L9 external knowledge/reference
```

Accepted lineage and L1/L2/L4/L5 are authoritative or deterministic accepted projections. L3/L6/L7 are rebuildable. L9 is Source/MKAOS evidence. No Agent-private memory may override these sources.

## 6. Current implementation boundary

Current code contains substantial runtime surfaces for PostgreSQL Authorities, Command Kernel/RuntimeJob, progressive planning, Chapter/Book production, Narrative State, PlanChange/Replan, Source/MKAOS, Agent Collaboration/Runtime, provider governance, quality/reader functions and recovery.

The following target semantics require latest-code verification and, where absent, implementation/proof:

- autonomous Chapter-to-Chapter liveness with advisory sidecars detached from the default critical path;
- explicit progress/stall explainability for Book production;
- sustained runtime proof for ChapterExecutionIntent/ChapterMemo Mission and four-class governed Context;
- production-scale proof for hybrid long-form retrieval and layered Narrative Memory;
- production qualification for Accepted-Reality Arc scheduling, composition and obligation-driven correction;
- persistent Best Candidate/minimum improvement/rollback;
- multi-turn dynamic Tool-calling Agent Harness;
- unified semantic lineage/invalidation;
- MKAOS Narrative Intelligence effectiveness, reader-linked fatigue evidence and sustained real-provider originality;
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
