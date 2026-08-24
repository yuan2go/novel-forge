# Source, Intelligence, and MKAOS

This document describes the current/target boundary for governed source-derived knowledge. It is subordinate to the [Canonical overall design](canonical-overall-design.md).

## 1. Source pipeline

```text
Source / Repository / Document
→ governed acquisition + immutable source identity
→ normalization / structural chunking
→ rights / eligibility / provenance
→ source-type classification
→ source-specific deconstruction / observation
→ abstraction and evidence validation
→ cross-source generalization where appropriate
→ MKAOS candidate
→ governance / approval / versioning
→ Knowledge Asset / Pack
→ task-specific selection
→ usage / effectiveness evidence
```

Raw copyrighted expression, quotes, distinctive source-specific sequences, or ungoverned source text must not become prose-generation material by default.

## 2. Source-specific analysis

Different source classes support different intelligence:

- **Web fiction:** structure, serialization, hooks, payoff cadence, escalation, status/resource progression, reader-commercial mechanisms.
- **Published/classic fiction:** character contradiction, subtext, relationship tension, moral ambiguity, delayed consequence, theme embodiment.
- **Writing theory:** explicit craft methods and diagnostic frameworks.
- **History / politics / economics / sociology / military / law / medicine / other professional domains:** causal mechanisms, constraints, realistic consequences and domain facts.
- **Philosophy:** competing positions, dilemmas, choice/consequence structures; not ready-made speeches.

Analysis-profile routing should follow actual source type/evidence and remain governable/versioned.

## 3. Narrative Intelligence Layer

MKAOS should support reusable assets such as:

```text
NarrativePrimitive
NarrativeMechanism
ArcPattern / ArcBeatPattern
Conflict / Escalation / Reversal / Payoff Pattern
CharacterTransformation / Relationship Pattern
Mystery / Clue / Reveal Pattern
WorldConsequence / FactionDynamics Pattern
Power / Resource Progression Pattern
ReaderPleasure / EmotionalCurve Pattern
ThemeDialectic / MoralDilemma Pattern
Scene / Interaction Pattern
AntiPattern / FailureCondition
Professional / Domain Causal Knowledge
```

These names describe semantic asset families, not a requirement for one database table/class per line.

## 4. Four-layer boundary

Keep separate:

1. **Source Observation** — still bound to exact source/provenance/evidence.
2. **Generalized Knowledge** — abstract reusable mechanism with source-specific expression removed.
3. **Project Candidate** — proposed use for one Book/Arc/Scene.
4. **Project Planning Authority** — approved future intent for the Book.

MKAOS owns layers 1–2 and governed knowledge selection. It does not own layer 4.

## 5. Production selection

A Story/Arc/Scene capability should query by structured need, for example:

```text
current state
+ desired target state
+ narrative scope
+ genre / reader promise
+ current conflict
+ desired reader effect
+ theme
+ hard constraints
```

Selection returns relevant mechanisms/patterns/domain evidence, not a complete source-derived plot. Arc Architect/Narrative Composer then creates a project-specific solution constrained by current Narrative State and planning.

The current Planning runtime implements this through the existing MKAOS
Authority query and Planning Context path. It builds a bounded need from current
state terms, desired transformation, scope, genre, conflict, reader effect,
theme, hard constraints and recent repetition keys. Active, clear,
production-eligible KnowledgeCards are ranked deterministically; selected
mechanisms, applicability, failure conditions, review checks and provenance are
frozen into the Planning Context and Provider Task View for Story, Arc, Chapter
and Scene-oriented planning stages.

## 6. Governance

Reusable promotion should consider:

- provenance and rights;
- removal of source-specific expression/entities/event sequences;
- abstraction quality;
- cross-source support when relevant;
- originality/leakage risk;
- semantic deduplication/clustering;
- versioning;
- usage and effectiveness evidence;
- repetition/fatigue evidence;
- anti-patterns and failure modes;
- retirement/supersession.

A useful pattern records where it works, where it fails, common misuse, and observed downstream effects rather than only a positive recipe.

## 7. Learning boundary

Possible future evidence chain:

```text
Knowledge Asset
→ Arc / Chapter usage
→ accepted content
→ Quality / Reader Outcome
→ effectiveness / fatigue evidence
→ MKAOS update proposal
```

This loop may improve future selection. It never directly mutates Canon or active Book planning.

## 8. Current proof boundary

The repository contains governed Source Import, Source
Authority/Intelligence, MKAOS candidate/approval/pack, structured Narrative
Intelligence families, originality-boundary validation, task-specific Planning
selection and bounded usage lineage:

```text
KnowledgeCard
→ Planning Context selection
→ Provider input / Planning Candidate
→ optional active Plan binding
```

Ready-made plots, source-specific event sequences and entity-replacement
templates are forbidden candidate fields. Fixture-derived cards are excluded
from production Planning selection. The 2026-08-24 bounded PostgreSQL
qualification proves that a production-eligible governed-card snapshot enters
the frozen Planning Context, the Provider Task View, the Planning Candidate and
a frozen Plan binding. A technical retry reuses the same Context AssetVersion
even if a new card appears; card revocation or governance drift fails closed.
The usage query distinguishes frozen Context, materialized Candidate, fixture
versus real-provider consumption evidence and optional active/frozen Plan
binding without granting MKAOS Planning Authority.

The consumed provider path in that qualification was explicitly scripted
fixture protocol. Real-provider Narrative Intelligence consumption,
source-specific effectiveness, cross-source generalization quality,
reader-linked effectiveness and production qualification remain unproven.
