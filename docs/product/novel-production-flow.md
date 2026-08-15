# Novel production flow

This document is a product/workflow view derived from the [Canonical overall design](../architecture/canonical-overall-design.md). It describes the target end-to-end business flow while explicitly separating target interaction features from current proof.

## 1. End-to-end target flow

```text
Human Intent / Material / Question
        ↓
Conversational Creative Studio
Chief Editor or specialist direct entry
        ↓
Proposal / Decision / Semantic Diff
        ↓
Impact / Risk / Human Approval
        ↓
Story / Book Design + Future Intent
        ↓
Book Architecture
        ↓
Volume Portfolio + orthogonal Arc Graph
        ↓
Character / World Realization
        ↓
Disclosure / Obligations / Scheduling
        ↓
Chapter Execution Plan + Scene Architecture
        ↓
Progressive Qualification
        ↓
CHAPTER_PRODUCTION_ADMITTED
        ↓
Context Compiler
        ↓
Provider → Draft
        ↓
Review ↔ Chapter Editor ↔ Revision
        ↓
Correctness / Narrative Event Extraction
        ↓
Canon / Narrative State projection candidate
        ↓
Quality
        ↓
Accepted Chapter Lineage
        ↓
Publish → Observe → Reader Outcome
        ↓
Retrospective / Attribution / Drift
        ↓
Governed Replan / Adaptation
```

The current production backend already implements substantial portions of the Design → Chapter → Acceptance → Reader/Recap/Replan spine. The **Conversational Creative Studio and Chapter Editor interaction lifecycle are target product capabilities and must not be treated as proven merely because Agent Collaboration, Revision, and PlanChange modules exist.**

## 2. Human creative collaboration

The author may begin with the Chief Editor or directly select a specialist such as Story Architect, Character Director, World Architect, Theme & Philosophy Advisor, Plot Doctor, Research & Material Curator, Chapter Director, or Chapter Editor.

The role changes reasoning/capability/context selection, not Domain ownership. Agent output remains a proposal until an owning Authority commits an accepted design/revision/plan change.

```text
Conversation
→ candidate decisions
→ Accepted / Rejected / Open / Deferred
→ proposal + rationale
→ semantic diff if an existing design changes
→ impact / risk
→ human/policy decision
→ owning Authority
```

A conversation transcript is never copied wholesale into Canon or active planning.

## 3. Book and design authority

Book creation/design produces versioned Story/Book Design assets. Accepted design decisions may include premise, target reader, reader promise, theme, tone, foundational world/character constraints, central conflict, ending intent, and commercial/serialization constraints.

Production resolves exact current Authority inputs and qualification evidence into a frozen input snapshot. An upstream design layer that is stale, superseded, unqualified, or not current cannot silently become a production dependency.

## 4. Progressive long-form planning

The temporal hierarchy is:

```text
Book → Volume → Narrative Segment → Chapter → Scene → Beat
```

Arc is a cross-time graph dimension and may span multiple Volumes. It is not inserted as a tree parent between Volume and Chapter.

Planning progressively elaborates Strategic → Tactical → Operational horizons. Active future plans bind exact upstream versions. `LONGFORM_DESIGN_QUALIFIED` and `CHAPTER_PRODUCTION_ADMITTED` are computed admission results over current qualified dependencies, not caller assertions.

`ChapterGroup` remains a production/scheduling/checkpoint concept; Narrative Segment is a story-design concept.

## 5. Material / creative seed integration

```text
Source or Human Idea
→ Material / Creative Seed
→ research / provenance / deconstruction when needed
→ compatibility and placement analysis
→ Narrative proposal
→ decision
→ future design / planning
→ Draft
→ acceptance
→ Canon
```

Material, idea, proposal, plan, draft, accepted story, and Canon are distinct lifecycle states.

## 6. Chapter production

Current governed chapter production follows the existing Chapter/Book production runtime and production execution plane. The semantic target is:

```text
Current Accepted State
+ active qualified design
→ Chapter admission
→ Context
→ Draft
→ Review / Revision / Re-review
→ Narrative Event extraction
→ correctness
→ Canon / StoryState candidate
→ Quality
→ acceptance transaction
```

A successful provider response alone cannot complete a Chapter.

Book acceptance commits governed accepted outcome/event evidence, Canon/StoryState projections and the accepted cursor using current Authority/CAS semantics. Only accepted lineage is visible as current story truth to later chapters.

## 7. Author chapter editing

After a Draft exists, the default conversational surface is **Chapter Editor**. The author may work at whole-Chapter, Scene, paragraph, or selected-text scope.

Changes are classified before being allowed to escape local scope:

| Level | Scope | Example | Route |
|---|---|---|---|
| L0 | Text | wording/style/line compression | Revision |
| L1 | Scene | dialogue/action/local disclosure | Chapter Editor + specialist capability as needed |
| L2 | Chapter structural | scene order, reveal, hook, climax | Chapter Director/Plan + Revision |
| L3 | Future Arc/Volume | major future trajectory change | PlanChange/Replan + impact/requalification |
| L4 | Book/Canon critical | core world rule, ending, major identity/fate | explicit high-risk governance / future replan / correction policy |

The user should not need to manually route every edit to the correct internal Agent. The Chapter Editor/Creative Studio can consult specialists, but Authority routing remains deterministic by domain and change type.

Drafts may be revised. Accepted content is never mutated in place. A correction to accepted content creates explicit governed superseding/corrective lineage; published content requires explicit correction/retcon semantics rather than ordinary editing.

## 8. Context and knowledge

Context is compiled from exact accepted/design versions and task requirements. It may include current Narrative State, relevant Canon, active Arc schedule, relevant characters/world horizon, knowledge boundaries, due obligations, reader-experience target, relevant Author Intent, pending proposal status, and selected MKAOS/research evidence.

Provider input must remain Minimum Sufficient Context and must distinguish accepted truth from future intent, proposals, and derived retrieval results.

## 9. Reader and recap follow-up

After accepted chapters the governed Book scheduler/runtime may submit Reader Outcome, recap, ending-reachability, longitudinal quality, or other follow-up work.

```text
Accepted Chapter
→ Reader Outcome / Observation
→ Attribution / Calibration
→ Recap / Drift / Narrative Debt
→ Replan proposal
```

These are evidence/proposal flows. Reader results never directly mutate Canon or active plans.

## 10. Replan

When governed evidence requests a future change:

```text
Accepted Reality
→ evidence / human request
→ semantic PlanChange
→ impact analysis
→ approval according to risk
→ minimal affected future dependency closure STALE
→ regenerate
→ requalify
→ activate new versions
→ resume
```

Accepted past events remain evidence. Future design is changed through versioning and activation, not by mutating existing rows or bypassing owning Authorities.

## 11. Stop and recovery behavior

Book, Chapter, Agent/collaboration, and follow-up work may pause, fail, retry, reconcile, or wait for approval without erasing prior Attempts. Stable idempotency, leases, fences, checkpoints, CAS/versioning, immutable receipts, and outbox/effect records allow another process to recover from PostgreSQL Authority.

Technical retry is not semantic revision. A poor but successfully generated Draft enters Review/Revision; it is not retried as if the provider timed out.

## 12. Evidence boundary

The following must remain distinct:

- `CODE_IMPLEMENTED`
- `CANONICAL_WIRED`
- `TEST_EXECUTED`
- `RUNTIME_PROVEN`
- `PRODUCTION_QUALIFIED`

The repository's proof ladder further distinguishes fixture, real-provider, long-form, multi-book, and production evidence. Ordinary code existence or bounded tests do not prove the complete flow above.
