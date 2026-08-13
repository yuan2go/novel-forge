# Canonical Narrative Architecture Convergence Implementation Plan

> **For Codex:** Execute this plan in the current session using TDD and the repository's Canonical production path. Do not create parallel Authority, Workflow, Agent, State, or Proof planes.

**Goal:** Converge long-form timeline planning, cross-cutting narrative arcs, character development, knowledge/disclosure, executable chapter planning, and bounded task-specific provider context on the existing PostgreSQL Authority and Production Execution runtime.

**Architecture:** Keep ArcPlan as the existing cross-volume graph contract and remove its accidental Volume containment in generated planning. Add immutable `narrative_segments` to VolumePlan and reference them from ChapterGroup/Chapter plans. Upgrade generated ChapterPlan to an execution contract that binds arc roles, character trajectories, knowledge/disclosure boundaries, scene execution, transitions, reader effect, and exit state. Extend the existing Narrative State event/reducer vocabulary for reader knowledge and disclosures. Preserve full Authority inputs in execution evidence while rendering one minimal Provider Task View and one Provider Context View.

**Tech Stack:** Python 3.12, PostgreSQL migrations, immutable AssetVersion JSON contracts, Command Kernel, Production Execution Gateway, Provider Runtime, pytest, Ruff/mypy/build tooling already present in the repository.

---

### Task 1: Correct timeline and arc semantics in existing Planning Authority

**Files:** `src/novel_forge/modules/story_planning_runtime/{domain,execution,application}.py`, `src/novel_forge/modules/hierarchical_planning/{domain,application}.py`, relevant unit/integration tests.

1. Add failing contract tests proving VolumePlan owns versioned narrative segments, ChapterGroup/Chapter reference a segment, and generated ArcPlan has no containment parent while binding cross-volume segments/memberships.
2. Extend existing plan schemas and deterministic validators; keep `Thread -> Arc -> Arc Segment` graph semantics orthogonal to `Book -> Volume -> Narrative Segment -> Chapter Group -> Chapter`.
3. Remove `arc_plan.generate -> volume_plan` parent enforcement and preserve exact version references as dependencies/memberships.
4. Run targeted story-planning and hierarchical-planning unit/PostgreSQL integration tests.

### Task 2: Upgrade ChapterPlan into an executable narrative contract

**Files:** `src/novel_forge/modules/chapter_authority/chapter_plan_views.py`, Story Planning provider schema/projection, chapter-plan tests.

1. Add failing v4 tests for chapter intent, arc schedule roles, setup/payoff, character participation, knowledge boundaries, disclosures, state transitions, reader experience, scene plan, and expected exit state.
2. Generate and validate those fields directly rather than fabricating a generic v3 runtime projection.
3. Retain read compatibility for accepted old AssetVersions, but require v4 for newly generated strict production candidates.
4. Keep prose execution chapter-sized for this slice while using scene/scene-group plans as the bounded execution and correction unit; do not add an unproven multi-call workflow.

### Task 3: Extend the single Narrative State plane for knowledge, belief, character trajectory, and disclosure

**Files:** `src/novel_forge/modules/narrative_state/{contracts,reducers,measurements}.py`, `src/novel_forge/modules/canon_graph/domain.py`, `src/novel_forge/modules/chapter_authority/provider_output_contracts.py`, Canon/Narrative State tests.

1. Add failing tests for Story Truth versus character knowledge/belief versus reader knowledge/disclosure identities and accepted-lineage reduction.
2. Add Reader Knowledge as current state and Disclosure Event as append-only presentation evidence; reuse existing Character Knowledge, Character Belief, Character Arc, relationship, power, and resource state.
3. Wire provider extraction through Canon validation into ChapterOutcome and Narrative State reduction.
4. Normalize/validate initial resource balances before acceptance so the latest long-form failure is corrected without weakening the reducer.

### Task 4: Introduce a single bounded Provider View

**Files:** new focused provider-view module under `chapter_authority`, `chapter_authority/{handlers,execution_gateway,domain_handlers}.py`, capability prompt template/pack, Context tests.

1. Add failing prompt-composition tests demonstrating the current duplicated full ContextBundle and a state-light versus long-history bounded-growth invariant.
2. Build a stage-specific Provider Task View and Provider Context View from immutable Authority inputs; exclude manifests, rejected inputs, audit metadata, duplicate stage/actual views, and unrelated state facts.
3. Filter state to participating characters, scheduled arcs, explicit knowledge/disclosure references, due obligations, and relevant truth/world constraints; preserve asset/version/hash lineage in evidence rather than prose prompt.
4. Deduplicate selected MKAOS knowledge by version/content hash and render only provider-safe task knowledge.
5. Record per-component characters/tokens, final prompt estimate, selected-to-provider ratio, and representation amplification in ExternalEffect materialization evidence; fail closed on unsupported source/context shapes.

### Task 5: Safe upgrade projections and migration

**Files:** new `v20260813_0088_*` migration, migration registry/manifest, migration tests.

1. Add failing migration-chain and PostgreSQL projection tests.
2. Add forward-safe read projections for active narrative segments, arc graph contracts, and chapter execution plans; do not rewrite immutable historical assets.
3. Update migration head/manifest and verify upgrade from the prior head plus clean rebuild.

### Task 6: Prove canonical production composition

**Files:** production composition/integration tests and only the minimum fixtures needed.

1. Add a real composition test for Book/Volume/Segment -> Arc Graph -> Chapter Execution Plan -> task Context -> Provider materialization -> Chapter/Canon/Narrative State -> next-chapter Context.
2. Prove accepted lineage, idempotent replay, retry/recovery, lease/fence behavior, future-only replan behavior, and independent Quality gate dependencies remain intact.
3. Prove Chapter 1 and a synthetic long-history chapter produce bounded/explainable Provider Context rather than history-proportional prompt growth.

### Task 7: Exact-SHA Engineering Qualification and runtime evidence

**Files:** no feature changes after the final qualification commit unless qualification is restarted.

1. Run targeted suites continuously, then repository unit/integration/PostgreSQL/migration/lint/typecheck/Capability Pack/Skill/build/recovery/Canon/Planning/Context/Chapter/Book/Replan qualification commands discovered from current project tooling.
2. Commit the converged tree, record the exact SHA, and rerun the complete qualification on that SHA.
3. If the configured real Provider route is available, run a Chapter 1 -> Chapter 2 stateful continuation smoke on the exact SHA and retain append-only evidence. Otherwise report the exact provider/authentication blocker without substituting fixture evidence.
4. Perform a final code/evidence review and give a go/no-go decision for restarting the 30 Chapter Proof.
