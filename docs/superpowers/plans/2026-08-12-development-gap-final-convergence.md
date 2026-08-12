# Development Gap Final Convergence Implementation Plan

1. Freeze the resolved Source Analysis Strategy and fingerprint in the
   `ANALYSIS_PLANNING` child command; validate it against the Profile and route
   at execution; add unit and PostgreSQL invalidation/reuse cases.
2. Introduce Narrative Runtime Measurement v2 observation semantics, expected
   context-set metrics, and Provider/Planning/MKAOS evidence normalization.
3. Add upstream Provider evidence and ChapterPlan assets to the Quality frozen
   input snapshot in both synchronous and scheduler production paths.
4. Add migration 0084 for the one non-derivable Book Replan re-evaluation fact,
   corrective lineage projection, provider-backed Context/MKAOS
   selection-consumption projections, indexes, and constraints.
5. Add corrective lineage and MKAOS selection/consumption queries; connect Book
   Replan activation to a governed later re-evaluation checkpoint.
6. Extend production-path and PostgreSQL tests for false-zero semantics,
   Provider evidence, planning evidence, Quality correction resolution and
   escalation, Replan re-evaluation, MKAOS selection versus consumption, and
   duplicate/replay behavior.
7. Run fresh and previous-head migrations, focused tests, full unit/integration/
   PostgreSQL suites, lint, type checking, Skill/Capability Pack validation, and
   package/build validation; fix failures and remove local overengineering.
8. Commit on the convergence branch, push, create a Draft PR, verify remote SHA,
   and leave the worktree clean.
