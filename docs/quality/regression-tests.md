# Regression Tests

Updated: 2026-07-05
Baseline checked: branch `backup/v6-post-mkaos-industrialization-20260705`, commit `e4f700c`

Novel Forge keeps a dependency-light test core and optional industrial/browser checks. Run the smallest relevant verification for each change, then broaden when runtime, API, Agent, or publishing behavior changes.

## Primary Commands

```bash
make test
make lint
make validate
npm --prefix web/admin test
npm --prefix web/admin run lint
PYTHONPATH=src python3 -m novel_forge.cli --help
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_acceptance
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_long_chain_smoke
```

## Makefile Targets

| Command | Purpose | Notes |
|---|---|---|
| `make test` | Python unittest discovery plus web admin node tests | Default broad local check |
| `make lint` | Python compile check | No style formatter implied |
| `make validate` | Validate local workspace structure/assets | Uses `.local/workspace` by default |
| `make demo` | Run sample pipeline in `.local/demo-workspace` | Writes ignored runtime outputs |
| `make sync-skills-dry-run` | Preview root Skill to runtime Skill sync | Use before syncing |
| `make check-skills` | Fail if runtime Skills drift from source | Required for Skill changes |
| `make local-up` | Docker local stack and smoke | Requires Docker and free ports |
| `make local-smoke` | Smoke running local stack | Requires services |
| `make web-dev` | Next.js dev console | Requires Node deps |

## Test Coverage Map

| Area | Test Evidence | Current Coverage |
|---|---|---|
| CLI and local pipeline | `tests/unit/test_cli.py`, `tests/integration/test_pipeline.py`, `tests/integration/test_workflow_steps.py` | Good local coverage |
| Schemas/storage | `tests/unit/test_schemas.py`, `test_storage.py`, `test_storage_graph.py` | Good core coverage |
| Product API | `tests/unit/test_product_api.py`, `test_product_api_routes.py` | Good route/service coverage |
| Agent runtime | `test_agent_scheduler.py`, `test_agent_registry_scheduler_integration.py`, `test_agent_runtime_profiles.py`, `test_agent_center_v2.py` | First-slice coverage |
| Provider/runtime policy | `test_provider_runtime_guard.py`, `test_provider_hard_stop_proof.py`, `test_runtime_policy.py`, `test_runtime_ledger.py` | Active hardening coverage |
| Context/RAG | `test_context_builder_mkaos_flow.py`, `test_context_and_production_chain.py`, `test_pgvector_source_isolation.py` | Partial but meaningful |
| MKAOS | Many `test_mkaos_*.py`, MKAOS integration and acceptance tests | Broad coverage, still evolving |
| Canon/KG/continuity | `test_canon_graph*.py`, `test_novel_kg*.py`, long-chain integration tests | Partial long-form coverage |
| Review/revision/publishing | `test_review_issue.py`, `test_publishing_center.py`, `test_publish_feedback_loop.py`, publishing fixtures | Stronger than earlier, still needs more production-ready fixtures |
| Eval/quality | `test_evaluation_center_general.py`, `test_longform_quality_gate_e2e.py`, MKAOS quality tests | Partial production eval coverage |
| UI | `npm --prefix web/admin test`, optional Playwright smoke | Node tests exist; browser smoke may be skipped without browsers |
| Industrial services | `test_industrial_integration.py`, `test_online_backends_e2e.py`, Docker smoke targets | Optional, environment-dependent |

## When To Add Tests

Add tests when changing:

- schemas or asset validation;
- CLI/API contracts;
- workflow node execution or task state;
- Agent scheduler queue, lease, runner, gate, budget, retry, recovery, rollback, or dead-letter behavior;
- provider route resolution or model-call policy;
- Context Builder, RAG, Canon/KG, ReviewIssue, MKAOS, publishing, release package, or eval gates;
- broad exception handling or fallback policy;
- UI API contracts or visible operational evidence.

For large service splits, add characterization tests before refactoring. Keep tests at the behavior boundary rather than asserting private helper internals unless the helper is an intentional seam.

## Known Gaps

- Browser route smoke is optional and may be skipped when Playwright browsers are not installed.
- Production provider tests require explicit fixtures/secrets or safe mock-success fixtures that prove evidence shape without calling external APIs.
- Full long-novel generation is not a default regression test; current long-chain tests are smoke/pressure slices.
- Optional industrial services require Docker and ports; local unit tests should not depend on them.
- Some UI pages are console/reporting slices and need more end-to-end operator workflow tests.

## Docs-Only Changes

For docs-only updates, run at least:

```bash
git diff --check
rg -n "ARCHITECTURE.md|WORKFLOW.md|TESTING.md|Novel Forge V5|V5 structure" README.md CLAUDE.md docs Makefile
```

If docs changed command claims, verify the command exists in `Makefile`, `pyproject.toml`, `src/novel_forge/cli.py`, or `web/admin/package.json`.
