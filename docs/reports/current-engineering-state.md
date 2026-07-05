# Current Engineering State

Updated: 2026-07-05
Baseline checked: branch `backup/v6-post-mkaos-industrialization-20260705`, commit `e4f700c`

This report records the result of the documentation audit and context cleanup pass. It is the current report for this pass; older "current" or "final" reports remain historical unless refreshed.

## 1. Completed Work

Updated or added current documentation:

- `CLAUDE.md` rewritten as a long-lived Claude Code operating manual.
- `README.md` corrected to use current docs links and source-checkout CLI invocation.
- `docs/README.md` added as the docs entrypoint.
- `docs/project-current-state.md` added with a current capability fact table.
- `docs/architecture/overview.md` added with runtime layers and data flow.
- `docs/architecture/module-map.md` added with module/API/UI/test evidence paths.
- `docs/product/capability-map.md` added with Novel OS capability status.
- `docs/engineering/extension-guide.md` added with capability extension workflow.
- `docs/quality/regression-tests.md` added with regression commands and coverage map.
- `docs/roadmap/current-roadmap.md` added with current P0/P1/P2/P3 roadmap.
- `docs/archive/README.md` added to explain archive/historical docs policy.
- `docs/reports/docs-audit-current-state.md` added with drift conflicts and documentation architecture.
- `docs/reports/current-engineering-state.md` added as this pass report.
- `Makefile` help text updated from V5 wording to Novel Forge workspace wording.

No historical docs were deleted.

## 2. Current Engineering Conclusion

Novel Forge v6 currently has:

- a runnable local-first Python CLI and schema-backed JSON asset pipeline;
- FastAPI product API and many product/OS/MKAOS routers;
- a Next.js admin console with broad operational route coverage;
- root project Skills with generated Claude runtime copies;
- MKAOS ingestion, quality, lineage, graph, pack, and gate slices;
- Context Builder, local/vector retrieval, optional Qdrant/pgvector slices;
- ReviewIssue, editor/revision, publish gate, release package, evaluation, runtime ledger, provider guard, Agent registry/scheduler, and workflow node slices;
- broad unit/integration/acceptance tests, including Novel OS, long-chain, MKAOS, provider guard, and publishing tests.

The system is not yet a complete autonomous Novel Operating System product. Key gaps remain:

- universal provider/model-call hard-stop coverage across every production path;
- complete Agent operation coverage for all target Agent roles;
- deeper UI workflows beyond route/report existence;
- production-grade rollback and environment policy;
- full publishing/platform adapter operations;
- fully proven full-novel autonomous long-chain production.

The biggest documentation risk before this pass was that older v5 docs, design imports, and prior "final/current" reports could be mistaken for current code truth. The new docs hierarchy now makes current entrypoints explicit.

## 3. Priority Recommendations

### P0

- Keep hardening provider runtime evidence and production fail-closed behavior.
- Finish publish/release gate positive and negative end-to-end fixtures.
- Expand Agent operation coverage for Platform Compliance, Training, publishing, evaluation, and long-form roles.
- Keep Context Builder, MKAOS, Canon/KG, ReviewIssue, and publishing gates unified.
- Make local-vs-production environment policy explicit and enforced.

### P1

- Continue splitting large services with characterization tests first.
- Continue broad-exception governance in workflow nodes, audit/publishing, MKAOS, scheduler, and product API.
- Expose provider approval, gate, trace, cost, rollback, and recovery evidence in operator UI.
- Refresh older architecture/workflow/module docs only when needed.

### P2

- Productize Eval Center so model quality/cost evidence affects routing and release gates.
- Strengthen long-form continuity tests and UI workflows.
- Deepen reader feedback backflow into traceable planning/revision suggestions.
- Improve publishing calendar/platform adapter workflows.

### P3

- Move toward production database-first mode with explicit local fallback policy.
- Build multi-provider benchmarking/routing from verified eval results.
- Turn report-heavy UI routes into executable operator workflows.
- Add full long-novel production acceptance after runtime P0/P1 gaps close.

## 4. Claude Code Usage

Next Claude Code session should read in this order:

1. `CLAUDE.md`
2. `docs/README.md`
3. `docs/project-current-state.md`
4. `docs/architecture/module-map.md`
5. relevant code and tests for the task

Do not start from `docs/reports/` or `docs/new/` unless the task is explicitly historical research. Those files are useful evidence, not default truth.

When changing architecture, runtime behavior, API, UI, schemas, Skills, or roadmap:

- update the relevant current docs;
- include evidence paths;
- label partial/design-only capabilities honestly;
- do not delete historical docs without a deliberate archive migration.

## 5. Verification Results

Verification commands from this pass:

| Command | Result | Notes |
|---|---|---|
| `rg --files docs -g '*.md' \| sort` | Passed | Used to inventory docs |
| `rg -n "ARCHITECTURE\\.md\|WORKFLOW\\.md\|TESTING\\.md\|V5 structure\|Novel Forge V5\|version=\\\"5\\.0\\.0\\\"\|v5\|V5" ...` | Passed with intentional findings | Current README/CLAUDE are corrected; remaining hits in the current-doc scan are audit/test-guide references to historical conflicts |
| `git diff --check` | Passed | No whitespace errors |
| `PYTHONPATH=src python3 -m novel_forge.cli --help` | Passed | CLI reports Novel Forge v6 / Novel OS command surface |
| `make lint` | Passed | `compileall -q src tests` passed |
| Markdown link check over current docs | Passed | Checked 23 current entrypoint/report files |
| `make validate` | Failed due local runtime state | `.local/workspace/data/runs/*` contains existing run assets without `project_id/workspace_path`; not caused by docs edits |
| `PYTHONPATH=src python3 -m novel_forge.cli validate --root /private/tmp/novel-forge-docs-validate` | Passed | Clean isolated workspace validates |

Full `make test` was not rerun in this docs-only pass. A full suite should be run before merging with the unrelated code changes already present in the working tree.
