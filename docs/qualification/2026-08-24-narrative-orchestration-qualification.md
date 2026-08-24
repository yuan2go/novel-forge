# Narrative Orchestration bounded qualification — 2026-08-24

This is an exact-SHA qualification record, not an architecture source.
Canonical target semantics remain in
[canonical-overall-design.md](../architecture/canonical-overall-design.md).

## Identity and environment

- Work Package: WP-NARRATIVE-ORCHESTRATION-QUALIFICATION-01
- qualified code SHA: 4c79ea7ac412e18bbcb1c17096439e657ed0cdb3
- starting origin/main: e5d9a25b25fabd20aa49343c3f9ebe60fd78fa1c
- PR #25 merge SHA: e5d9a25b25fabd20aa49343c3f9ebe60fd78fa1c
- migration head: 20260821_0096_runtime_hardening
- migration status: ok=true, missing=[], extra=[]
- database: isolated local novel_forge_narrative_qualification_test
- PostgreSQL: Homebrew 16.14; pgvector 0.8.6
- Python: 3.12.13
- host: Darwin arm64
- provider used by the qualified slice: scripted_provider_v2
- real-provider credentials/profile: unavailable

No migration was added by this Work Package.

## Qualification slice

The PostgreSQL fixture uses three Arcs and a maximum active-Arc capacity of two:

- arc:truth: payoff-window Arc with two completion criteria accumulated over
  accepted Chapters 1 and 2;
- arc:obligation: linked to an overdue promise:late, fulfilled by typed
  Chapter 2 accepted payoff evidence;
- arc:countermove: dependency-blocked by arc:truth, despite being preferred by
  static ChapterGroup cadence.

Observed sequence:

1. Chapter 1 selects truth + obligation from initial accepted state and removes
   dependency-illegal countermove from static cadence.
2. Accepted Chapter 1 advances only truth from observed arc_evidence.
3. Chapter 2 sees truth in CRISIS, the obligation overdue, and countermove
   still blocked; it again selects truth + obligation.
4. Accepted Chapter 2 accumulates truth's second criterion and fulfills the
   unified Narrative Obligation from typed payoff evidence.
5. Chapter 3 excludes both completed Arcs, unblocks countermove, and selects
   only countermove.

Every Chapter persisted a qualified ChapterPlan → ChapterExecutionIntent v2 →
ChapterMemo v2 → Context chain. Intent bound the exact Plan AssetVersion/hash
and previous accepted StoryState/Canon boundary. Memo covered the exact
Mission Scene/Arc set. Context copied Mission expectations and fingerprints,
and the multi-Arc Chapters contained a shared causal multi-function event.
Neither Intent nor Memo acquired a story_plan_binding.

The Planning provider request persisted the selected structured Narrative
Intelligence in its task view, ExternalEffect and receipt lineage. The consumed
Planning Candidate and frozen Plan binding retained the KnowledgeCard identity.
This input was an upstream-governed card snapshot supplied by the qualification
fixture; separate MKAOS integration tests exercised Source evidence →
Candidate → Decision → Card and proved fixture-derived cards cannot activate
under production defaults.

## Defects exposed and repaired

- technical Planning retries froze Context by Attempt, allowing card selection
  to drift; Context is now frozen once per semantic Operation;
- a frozen card was not revalidated against revocation/governance drift before
  retry consumption;
- usage queries hid failed-attempt CONTEXT_FROZEN lineage;
- selected ArcPlan versions did not enter Chapter production preparation and
  Context under their semantic arc_plan role;
- ChapterOutcome declarations could fall back to broad Plan contributions
  instead of the exact Working Set;
- accepted obligations were not reevaluated at the next planning horizon, so a
  due obligation could fail to become overdue;
- a legal future dependency produced a premature replan checkpoint before its
  target window;
- Canon extraction had no unified obligation_changes provider contract, so Arc
  payoff evidence could not close the corresponding Narrative Obligation;
- Intent/Mission/Memo fingerprints and exact Scene/Arc coverage were generated
  but insufficiently revalidated at downstream Context consumption.

All repairs extend existing Planning, Book, Chapter, Context, Canon and MKAOS
Authorities. No parallel Scheduler, Runtime, Authority, Mission table or retry
engine was added.

## Exact-SHA commands and results

~~~text
NOVEL_FORGE_DATABASE_URL=postgresql:///novel_forge_narrative_qualification_test
PYTHONPATH=src pytest -q
  tests/integration/test_narrative_orchestration_qualification_postgres.py
  tests/integration/test_core_functional_loops_postgres.py::test_planning_retry_reuses_frozen_pack_after_measured_provider_result
→ 4 passed, 0 failed, 17.49s

NOVEL_FORGE_DATABASE_URL=postgresql:///novel_forge_narrative_qualification_test
PYTHONPATH=src pytest -q
  tests/integration/test_mkaos_authority_postgres.py::MkaosAuthorityPostgresTests::test_candidate_decision_card_and_deterministic_pack_are_separate
  tests/integration/test_mkaos_authority_postgres.py::MkaosAuthorityPostgresTests::test_raw_source_field_and_cross_project_lineage_fail_closed
  tests/integration/test_mkaos_authority_postgres.py::MkaosAuthorityPostgresTests::test_fixture_candidate_cannot_activate_with_production_defaults
→ 3 passed, 0 failed, 1.19s

PYTHONPATH=src pytest -q
  tests/unit/test_authority_production_preparation.py
  tests/unit/test_story_planning_runtime.py
  tests/unit/test_chapter_outcome_story_state.py
  tests/unit/test_chapter_outcome_longform_evidence.py
  tests/unit/test_chapter_authority_domain_handlers.py
  tests/unit/test_chapter_execution_artifacts.py
  tests/unit/test_chapter_provider_output_contracts.py
  tests/unit/test_stateful_canon_domain.py
  tests/unit/test_canon_semantic_quality_authority.py
  tests/unit/test_longform_narrative_contracts.py
  tests/unit/test_canonical_longform_projector.py
  tests/unit/test_mkaos_authority_domain.py
  tests/unit/test_source_intelligence_execution_contracts.py
  tests/unit/test_book_production_authority.py
→ 211 passed, 0 failed, 0.72s

git diff --name-only e5d9a25b25fabd20aa49343c3f9ebe60fd78fa1c..HEAD -- '*.py' |
  xargs ruff check
python -m compileall -q <directly changed module directories>
→ PASS
~~~

One preliminary baseline diagnostic of
test_book_input_resolver_freezes_active_authorities_and_planning_pack[NO_REPLAN]
failed because its older assertion expected an Agent work order/runtime binding
that the current Book path does not create. It was not used as qualification
evidence and was not weakened. One first static-check invocation passed a
newline-delimited filename list as one zsh scalar and failed with E902 File
name too long; the corrected xargs command above passed.

## Evidence classification

| Classification | Status | Boundary |
|---|---|---|
| CODE_IMPLEMENTED | true | Existing runtime defects repaired at qualified SHA. |
| POSTGRES_INTEGRATION_PROVEN | true | Three-Chapter accepted-reality slice plus retry/revocation and MKAOS Authority tests. |
| FIXTURE_PROVEN | true | Scripted planning/chapter provider protocol, explicitly labelled. |
| REAL_PROVIDER_PROVEN | false — BLOCKED_BY_ENVIRONMENT | No provider credentials, qualified profile or real-provider qualification switch. |
| LONGFORM_PROVEN | false | Three Chapters are not a long-form campaign. |
| PRODUCTION_QUALIFIED | false | No Production Admission campaign or release qualification. |

## Not run by scope

- full make test;
- full PostgreSQL integration suite;
- full Production Admission qualification;
- 30/100/300-Chapter or other long-form campaign;
- performance, load or multi-Book proof;
- large recovery campaign;
- automated publishing;
- real-provider Book campaign.

Remaining gaps are bounded real-provider Narrative Intelligence consumption,
larger accepted-reality recovery evidence, sustained long-form correctness and
quality, and production/multi-Book qualification.
