# Claude Code Prompt — Canonical Design to Production Code

This file is the reusable implementation handoff. It is subordinate to `docs/architecture/canonical-overall-design.md`; it does not define an independent architecture.

---

# Novel Forge / Autonomous Novel OS — Canonical Implementation & Qualification

Repository:

```text
https://github.com/yuan2go/novel-forge
```

Goal: continuously converge the latest real code toward the Canonical Design for an Industrial Autonomous Novel OS capable of reliable, recoverable, verifiable high-quality long-form production.

## 1. Before coding: establish truth

Do not mechanically implement this prompt or an old Roadmap.

Before any modification:

```text
pull latest main
→ record HEAD / worktree / environment / migration head
→ read docs/README.md
→ read docs/architecture/canonical-overall-design.md completely
→ read relevant current-runtime docs / active ADRs
→ trace the real production entries and code path
→ inspect Domain / Authority / Runtime / persistence / provider / downstream consumers
→ compare Design with code and runtime evidence
→ identify OUTDATED / SUPERSEDED / LEGACY / DEAD / DUPLICATED / FIXTURE_ONLY / UNWIRED / AUTHORITY_BYPASS / PARALLEL_RUNTIME
→ safely remove or converge only what evidence proves obsolete
→ identify the highest-priority real gap
→ then implement
```

If Design and code disagree, determine whether the document is stale, the code has not converged, or a later implementation has legitimately superseded the design. Preserve the better architecture and update both code and Canonical documentation when the target decision changes.

## 2. Canonical constraints

Preserve unless the same change deliberately updates the Canonical Design:

- PostgreSQL is production business Source of Truth.
- Agents/models/conversations/drafts/retrieval/MKAOS do not own Story Truth.
- Agents propose; owning Authorities commit.
- Planning/Arc = future intent; Accepted Outcome/Canon/Narrative State = accepted reality.
- structural hierarchy is `Book → Volume → Narrative Segment → Chapter → Scene → Beat`; Arc is an orthogonal cross-time transformation graph.
- `ChapterGroup` is a production/checkpoint construct, not automatically Narrative Segment.
- future planning is progressively elaborated; do not pre-detail the whole Book.
- Context is Minimum Sufficient Context and must stay bounded as the Book grows.
- MKAOS supplies governed generalized narrative/domain intelligence, never copied source plots or story truth.
- one durable production execution plane: `Command → Operation → Attempt → Lease/Fence → ExternalEffect → Provider/Tool → Receipt → Domain Commit`.
- technical retry != semantic revision.
- accepted history is immutable; Replan is future-only.
- Reader/long-form/MKAOS/analytics sidecars are non-blocking by default unless explicit persisted governance marks them `HARD_BLOCKING`.
- no new execution plane/Authority/Registry/framework merely to mirror a literary noun.

## 3. Production-grade, not Maximum Complexity

Do not use:

```text
Minimal Implementation
Stub
Placeholder
Fixture-only implementation
Mock-only proof
Temporary architecture
Parallel runtime
Test-only production bypass
```

But also do not add speculative abstractions, Interfaces, Adapters, Registries, Authorities, configuration frameworks, compatibility layers or generic engines without concrete value.

Prefer convergence and reuse of correct existing boundaries.

## 4. Functionality must enter the canonical runtime

A new capability is not complete as a DTO/Domain Type/helper/standalone service/fixture/unit test.

Trace and prove the required path according to the real architecture, potentially including:

```text
Entry
→ Application
→ Domain contract
→ Owning Authority
→ RuntimeJob / Command Kernel / worker
→ shared production execution
→ Provider / Tool
→ Persistence
→ Quality / Governance
→ State mutation
→ downstream consumer
→ Trace / Metrics / Cost
```

Do not force layers that are not actually needed; do prove every layer the capability depends on.

## 5. Reliability and failure semantics

Implement only mechanisms required by actual risk, while explicitly evaluating:

- idempotency;
- transaction/atomicity;
- technical retry;
- semantic revision;
- recovery/resume;
- replay;
- concurrency / CAS;
- lease/fence ownership;
- versioning/migration;
- external-effect uncertainty;
- audit/lineage;
- trace/metrics/cost.

Never let provider success equal business success, stale workers commit after ownership transfer, or recovery depend on reconstructed in-memory workflow state.

## 6. Highest-priority Work Package

Reinspect latest `main` first. If not already closed with real evidence, prioritize:

> **WP-LIVE-01 — Chapter-to-Chapter Liveness & Critical Path Closure**

Observed failure to explain/reproduce: a real long-form run produced Chapter 1 and then failed to advance to Chapter 2 for hours.

Do not guess the exact incident root cause from code alone. Start from PostgreSQL Authority evidence and trace:

```text
Book state / accepted_through
→ last progress time
→ expected next transition
→ active/blocked Operation / RuntimeJob / Attempt
→ follow-up state/retry
→ Chapter 2 request existence
→ Chapter 2 first provider call
```

Then prove the real code path from Chapter N acceptance to N+1 dispatch.

Required architectural invariant:

```text
Accepted N
→ required Accepted Outcome / Canon / Narrative State commit
→ next planning/admission eligibility
→ dispatch N+1
```

Reader Outcome, Long-form recap/diagnostics, MKAOS feedback, calibration and noncritical analytics must be detached from the default critical path. They may block only through an explicit persisted `HARD_BLOCKING` governance decision.

Also ensure every nonterminal Book state is claimable or explicitly waiting on a durable condition, and add/repair progress explainability/stall detection using existing Authority/runtime data rather than inventing a second scheduler.

Do not bypass Canon/Narrative State/acceptance correctness merely to make progression faster.

### Liveness verification

At minimum prove, as environment permits:

- Chapter 1→2 automatic bounded progression;
- slow/failing/retrying sidecar does not block N+1 by default;
- worker/API crash and lease expiry recover;
- provider timeout/retry ends in progress or explicit wait/failure, never silent stall;
- acceptance is idempotent;
- worker scheduling covers every actionable nonterminal state;
- unattended 10-chapter campaign.

If the latest code has already closed WP-LIVE-01 with pinned real evidence, do not reimplement it. Move to the highest-value next gap from the Canonical Design.

## 7. Next target after liveness

Do not implement everything at once. The next coherent target is **Hierarchical Narrative Production convergence**, reusing existing Planning/Narrative State/Context/Chapter runtime:

```text
Progressive planning + Arc working set
→ Chapter Mission
→ current accepted Narrative State
→ task-specific evidence
→ bounded Chapter Production Packet
→ Scene composition
→ Draft / Diagnosis / Revision / Polish
→ Narrative Verification / Quality
→ Accepted Outcome
→ Canon / Narrative State / Arc progress evidence
```

After that, extend the existing Arc planning toward the target Narrative Arc OS only where concrete production needs justify it: Thread/transformation semantics, relations/dependencies, Narrative Obligations, working-set scheduling, Chapter contributions, progress evidence, and governed future Arc evolution. Do not implement every named relation/object from the design as boilerplate.

MKAOS Narrative Intelligence should provide generalized mechanisms/patterns to creative capabilities; it must not become a second planning system or copy source-specific narrative sequences.

## 8. Testing and qualification

Run all verification appropriate to the change, at minimum where applicable:

```text
Unit Test
Contract / Architecture Test
Integration Test
PostgreSQL Integration
Fresh Migration
Upgrade Migration
Lint
Type Check
Build / package validation
```

When the touched path depends on them, continue to:

```text
Real Provider
Canonical Runtime E2E
Retry / Recovery Proof
Replay Proof
Chapter-to-Chapter Liveness Proof
Long-form Proof
Multi-book Proof
```

If an external dependency is unavailable, report `NOT_RUN / BLOCKED` with the exact reason. Never substitute a Mock/Fixture and upgrade the conclusion.

Report separately:

```text
CODE_IMPLEMENTED
CANONICAL_WIRED
TEST_EXECUTED
RUNTIME_PROVEN
LONGFORM_PROVEN
PRODUCTION_QUALIFIED
```

Bind claims to commit SHA, migration head, provider/config mode, executed commands, test results and evidence/receipt/trace when available.

## 9. Work-package execution rule

Do not stop after one minimal TODO.

```text
understand design
→ inspect real code/evidence
→ clean proven obsolete paths/docs
→ identify highest-value blocker
→ complete one coherent Work Package
→ run verification
→ fix real failures inside the same target chain
→ re-review the canonical runtime
```

Continue until the Work Package has a maintainable business/Authority/runtime/failure/verification closure, unless a genuine external block prevents it. Do not expand into unrelated Future scope.

## 10. Git / PR

- start from latest `origin/main` on an isolated feature branch;
- preserve user worktree changes;
- keep commits coherent and diff free of unrelated changes;
- push and create a Draft PR;
- PR must state actual implementation, verification commands, NOT_RUN items and evidence level;
- keep final worktree clean.

## 11. Final report

Keep the report concise:

1. starting HEAD / final HEAD;
2. design/code deviations found before development;
3. obsolete docs/Legacy/dead/duplicate paths cleaned;
4. actual capability completed;
5. key architecture decisions;
6. Canonical Runtime change;
7. tests and real runtime verification;
8. current evidence level;
9. unresolved real gaps;
10. next highest-priority Work Package.

Finally output:

```text
# 下一阶段 Claude Code Prompt
```

Generate the next self-contained prompt from the **new latest code and evidence state**, not from the old roadmap.

## Final decision rule

The goal is not more Agents, more documents, more abstractions, or green tests in isolation. The goal is a single coherent architecture that can demonstrably preserve long-form narrative truth and quality while continuing Chapter-to-Chapter under real provider/runtime failure conditions.
