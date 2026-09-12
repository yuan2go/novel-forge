Baseline: a1661483d68a3282b5a07f66ab7740c4b2a1f697. Local uncommitted engineering changes; no commits or external Provider calls performed by this subtask. Exact tested source/file hashes and native artifact hashes are in verified-code-and-artifacts.json.

Commands run from /Users/yuan/projects/novel-forge-first-novel-pilot:

```sh
PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/unit/test_creation_pilot.py tests/unit/test_creation_export.py
PYTHONPATH=src:. NOVEL_FORGE_DATABASE_URL=REDACTED_CREDENTIAL_CONNECTION_URL NOVEL_FORGE_GROUP_PILOT_EVIDENCE_DIR=/Users/yuan/projects/novel-forge-first-novel-pilot-evidence-20260912-a1661483/development/group-pilot .venv/bin/python -m pytest -q 'tests/integration/test_core_functional_loops_postgres.py::test_open_book_runs_foundation_search_and_snapshot_vertical_in_postgres[long_novel_pilot]' 'tests/integration/test_core_functional_loops_postgres.py::test_open_book_runs_foundation_search_and_snapshot_vertical_in_postgres[operator_plan_change]'
PYTHONPATH=src:. .venv/bin/ruff check scripts/creation_pilot.py scripts/prepare_knowledge_closure.py scripts/run_creation_synthesis.py scripts/run_world_production_smoke.py src/novel_forge/modules/book_authority/queries.py src/novel_forge/api/routers/book_authority.py tests/unit/test_creation_pilot.py tests/unit/test_creation_export.py tests/integration/operator_plan_change_support.py tests/integration/test_core_functional_loops_postgres.py
git diff --check
```

Results: 54 unit PASS; 2 PostgreSQL PASS in 277.30 seconds; Ruff and diff checks PASS. The native tests use migrated isolated PostgreSQL and existing command/Pack/ExternalEffect/Book Acceptance/ChapterGroup paths with explicit SCRIPTED_PROVIDER fixtures. They do not prove real Provider execution, narrative quality, full-book completion, or creative benefit.

Both native runs retain the first three accepted state/outcome versions across a real future PlanChange proposal/decision/activation/resume sequence, preserve identical input snapshot on repeated resume, accept exactly six chapters, do not create a seventh Chapter request, close both Groups, query them through the public API, reject a foreign-project query/API request, verify pagination, and compare native exports to exact accepted prose and normalized plan lineage. The long run keeps target 180 and pauses after accepted 6; the bounded run retains target 6. The exact independent run paths are indexed in verified-code-and-artifacts.json.

Confirmed defects and minimal reproductions:

- blind-red.log: Arc cardinality incorrectly stood for Group executions. Two real Groups sharing an Arc were rejected; one Group with two Arcs could pass. Native Group ranges, immutable plan/hash, child request/delegation, committed acceptance/outcome/Canon/StoryState, and normalized ChapterPlan source lineage now establish coverage.
- pilot-red.log: stopping immediately at the accepted target left the final Group unclosed. The runner reconciles/closes the accepted Group before a successful stop.
- cursor-crossing-red.log: a frozen intervention inside a Group could dispatch beyond its boundary; an incomplete Group at pilot cursor could return success. Scope/cursor conflicts now pause and block without further Chapter dispatch or accepted-history changes.
- partial-export-red.log: a complete six-chapter manuscript could conceal incomplete native evidence export. Blind export now requires successful creation cursor and COMPLETE asset/workspace export receipts without errors.
- treatment-red.log: ALLOW_ONLY policy alone incorrectly implied a valid comparison treatment. Native knowledge-runtime-usage.json records verified actual creative request delivery. Accepted knowledge review is checked against exact accepted text/hash/literal location, retaining fixture/model evidence classes. No delivery or claim-only results remain exportable for blind reading but are TREATMENT_NOT_ESTABLISHED and CREATIVE_BENEFIT_NOT_EVALUABLE; even positive evidence never sets human approval or proves benefit.
- shared-parent-red.log: independent Group IDs cannot conceal a shared parent Volume. Cross-arm Group/Volume/Arc plan versions are rejected.
- custom-freeze-red.log: --input-dir was unavailable. Custom input directories now freeze explicit existing files and rights declarations; synthetic rights are generated only for the built-in synthetic sample source.

Other diagnostic runs are retained separately: native-long-pg.log correctly rejected a six-Volume fixture under the existing 48-call Opening topology budget. The approved test direction changed to three Volumes over 180 chapters, retaining all production budget limits. native-long-pg-2.log was an infrastructure invocation error using the wrong environment variable/port. native-long-pg-3.log was intentionally interrupted after confirming the fixture had not configured three-chapter Groups; the fixture now calls the same native policy authority as creation runner. native-long-pg-4.log exposed an incorrect exporter comparison between Planning candidate and normalized ChapterPlan IDs; it now verifies the actual candidate -> imported frozen input -> normalized ChapterPlan -> accepted Outcome chain. No historical evidence or assertions were edited to manufacture PASS.

Native paths:

```text
GET /product/production/book-authority/runs/{book_run_id}/chapter-groups?offset=0&limit=100
creation.json: pilot_stop_after_chapter = 6
creation.json: profiles.production_profile.content.target_chapter_count = 180
formation.json: target_chapters = 180
```

```sh
PYTHONPATH=src:. .venv/bin/python scripts/prepare_knowledge_closure.py prepare --input-dir config/production/first-novel-pilot --output /absolute/new/freeze-directory --target-book-id DECLARED_TREATMENT_BOOK_ID
PYTHONPATH=src:. .venv/bin/python scripts/run_creation_synthesis.py --brief config/production/first-novel-pilot/brief.json --policy config/production/first-novel-pilot/creation.json --formation-policy config/production/first-novel-pilot/formation.json --project-id PROJECT_ID --book-id BOOK_ID --root /absolute/runtime-root --run-key UNIQUE_RUN_KEY --evidence-dir /absolute/new/preview-directory
PYTHONPATH=src:. .venv/bin/python scripts/prepare_knowledge_closure.py blind /absolute/treatment-export /absolute/control-export --output /absolute/new/blind-directory
```

The preview command omits --execute and returns CONFIGURATION_VALIDATED_NO_PROVIDER_CALL, target 180, pilot cursor 6, real Provider NOT_RUN. The parent task owns authorization, real Source inputs, actual account execution, repository manifests/docs and final integrated gates.

Additional confirmed pre-execution configuration defect: both CLI runners constructed IndustrialSettings manually and dropped explicit Minio endpoint, credentials and buckets. runner-settings-minio-red.log reproduces both using dummy settings. Both now call IndustrialSettings.from_env(values, root=args.root). Command `PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/unit/test_creation_runner_settings.py tests/unit/test_creation_pilot.py tests/unit/test_creation_export.py` passes 56 tests. No Minio or Provider call was performed; the test stops before constructing execution composition. The existing 2-PG drive/export validation remains applicable to unchanged functions; this final CLI-only correction is covered by the focused unit main-entry test. The combined, non-overwriting final index is final-code-and-artifacts.json.
