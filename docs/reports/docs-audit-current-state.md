# Docs Audit Current State

Updated: 2026-07-05
Baseline checked: branch `backup/v6-post-mkaos-industrialization-20260705`, commit `e4f700c`

This audit compares the documentation tree against current code, tests, commands, routes, and skills. Current code is the source of truth. Historical docs are preserved, but they are no longer the default entrypoint for current implementation state.

## Summary

| Finding | Evidence | Action Taken |
|---|---|---|
| No docs root index existed before this pass | `rg --files docs -g '*.md'` found many docs but no `docs/README.md` | Added `docs/README.md` as the current docs entrypoint |
| README linked missing root docs | `README.md` linked `ARCHITECTURE.md`, `WORKFLOW.md`, `TESTING.md`; these root files were not present | Updated README to link current docs under `docs/` |
| Makefile help still said V5 | `Makefile` target help printed "validate V5 structure" | Updated help text to Novel Forge workspace |
| Historical v5 docs still use active-sounding language | `docs/08-roadmap/v5-*`, `docs/07-audits/*`, older architecture/workflow docs | Marked historical in `docs/README.md` and `docs/archive/README.md` |
| Multiple reports use "current" or "final" | `docs/reports/*current*`, `*final*`, phase reports | Added `docs/reports/current-engineering-state.md` as the current report for this pass |
| Current code has v6 runtime metadata | `pyproject.toml`, `src/novel_forge/api/app.py` | New docs describe v6 and no longer rely on old V5 runtime wording |

## Documentation Inventory

Status legend:

- Current: maintained entrypoint or current-state doc created/updated in this pass.
- Active reference: still useful but should be checked against code.
- Historical/design: preserved for lineage; not authoritative for current state.
- Report/history: proof, audit, or execution report; use as evidence only for that pass.

### Current Entrypoints

| Path | Topic | Status | Action |
|---|---|---|---|
| `docs/README.md` | Documentation index | Current | Added |
| `docs/project-current-state.md` | Current project fact table | Current | Added |
| `docs/architecture/overview.md` | Current architecture overview | Current | Added |
| `docs/architecture/module-map.md` | Current module map | Current | Added |
| `docs/product/capability-map.md` | Novel OS capability status | Current | Added |
| `docs/engineering/extension-guide.md` | Extension guide | Current | Added |
| `docs/quality/regression-tests.md` | Regression test guide | Current | Added |
| `docs/roadmap/current-roadmap.md` | Current roadmap | Current | Added |
| `docs/archive/README.md` | Archive usage notes | Current | Added |
| `docs/reports/docs-audit-current-state.md` | This audit | Current | Added |
| `docs/reports/current-engineering-state.md` | Current engineering report | Current | Added after verification |

### Existing Product, Architecture, Workflow, Schema, Module, Testing, Operations, Skill Docs

| Path | Topic | Status | Recommended Action |
|---|---|---|---|
| `docs/00-product/copyright-and-compliance.md` | Compliance | Active reference | Keep; refresh if policy changes |
| `docs/00-product/novel-operating-system.md` | Product target | Active reference/design | Keep; do not treat all target claims as implemented |
| `docs/00-product/product-vision.md` | Product vision | Historical/design | Keep |
| `docs/01-architecture/current-implementation.md` | Earlier implementation map | Active reference with drift risk | Prefer new current state docs |
| `docs/01-architecture/data-flow.md` | Earlier data flow | Active reference | Prefer current architecture overview first |
| `docs/01-architecture/industrial-stack.md` | Industrial stack | Active reference | Keep; validate commands against Compose |
| `docs/01-architecture/module-map.md` | Earlier module map | Active reference with drift risk | Prefer `docs/architecture/module-map.md` |
| `docs/01-architecture/skills-system.md` | Skill architecture | Active reference with V5 wording | Refresh later or mark historical inline |
| `docs/01-architecture/system-architecture.md` | Earlier architecture | Active reference with drift risk | Prefer current overview |
| `docs/02-workflows/main-pipeline.md` | Main pipeline | Active reference | Validate before using as current truth |
| `docs/02-workflows/model-collaboration.md` | Model collaboration | Active reference | Validate provider policy details |
| `docs/02-workflows/skill-usage.md` | Skill usage | Active reference with V5 wording | Refresh later |
| `docs/03-schemas/schema-index.md` | Schema index | Active reference | Validate against `schemas/assets.py` |
| `docs/04-modules/module-index.md` | Module index | Active reference with V5 wording | Prefer current module map |
| `docs/05-testing/testing-strategy.md` | Testing strategy | Active reference | Prefer current regression test guide |
| `docs/06-operations/cli-usage.md` | CLI usage | Active reference | Validate examples against `cli.py` |
| `docs/07-audits/deprecated-designs.md` | Deprecated designs | Historical | Keep |
| `docs/07-audits/reusable-assets.md` | Reusable old assets | Historical | Keep |
| `docs/07-audits/v4-source-review.md` | V4 review | Historical | Keep |
| `docs/07-audits/v5-rebuild-plan.md` | V5 rebuild | Historical | Keep |
| `docs/09-skills/README.md` | Skills index | Active reference | Keep |
| `docs/09-skills/agent-skill-map.md` | Agent-to-Skill map | Active reference | Keep aligned with Agent roles |
| `docs/09-skills/external-resource-intake.md` | External Skill/resource intake | Active reference | Keep |
| `docs/09-skills/github-knowledge-sources.md` | Skill/source research | Historical/reference | Keep |
| `docs/09-skills/runtime-sync.md` | Runtime Skill sync | Active reference | Keep |
| `docs/09-skills/usage-policy.md` | Skill policy | Active reference | Keep |

### Roadmap And Historical Planning

| Path | Topic | Status | Recommended Action |
|---|---|---|---|
| `docs/08-roadmap/novel-os-remaining-closure-plan.md` | Prior Novel OS closure plan | Active reference/report | Compare to current roadmap |
| `docs/08-roadmap/novel-os-remaining-closure-plan1.md` | Duplicate/variant closure plan | Historical/duplicate | Merge only if refreshed |
| `docs/08-roadmap/v5-final-acceptance.md` | V5 acceptance | Historical | Keep |
| `docs/08-roadmap/v5-open-issues.md` | V5 issues | Historical | Keep |
| `docs/08-roadmap/v5-optimization-plan.md` | V5 optimization | Historical | Keep |
| `docs/08-roadmap/v5-phase-report.md` | V5 phase report | Historical | Keep |
| `docs/08-roadmap/v5-progress-log.md` | V5 progress | Historical | Keep |
| `docs/08-roadmap/v5-roadmap.md` | V5 roadmap | Historical | Keep |
| `docs/08-roadmap/v5-strategic-risk-plan.md` | V5 risks | Historical | Keep |
| `docs/08-roadmap/v5-task-pool.md` | V5 tasks | Historical | Keep |
| `docs/08-roadmap/v5-test-log.md` | V5 tests | Historical | Keep |

### Design And Imported Planning Docs

These are design or planning references. Keep them, but do not use them as current implementation truth without code evidence.

| Path | Topic | Status |
|---|---|---|
| `docs/design/agent-center-design.md` | Agent center design | Historical/design |
| `docs/design/context-builder-design.md` | Context Builder design | Historical/design |
| `docs/design/editor-in-chief-console-design.md` | Editor-in-chief console design | Historical/design |
| `docs/design/longform-recap-agent-design.md` | Longform recap design | Historical/design |
| `docs/design/loop-engineering-kernel-design.md` | Loop kernel design | Historical/design |
| `docs/design/mkaos-ingestion-creative-extraction-requirements.md` | MKAOS requirements | Historical/design |
| `docs/design/mkaos-knowledge-graph-learning-design.md` | MKAOS graph learning | Historical/design |
| `docs/design/mkaos-selector-and-canon-conflict-design.md` | Selector/canon design | Historical/design |
| `docs/design/novel-os-ui-console-design.md` | UI console design | Historical/design |
| `docs/design/novel-os-v6-industrialization-design.md` | v6 industrialization design | Historical/design |
| `docs/design/os-envelope-design.md` | OS envelope design | Historical/design |
| `docs/design/p1-canon-agent-loop-provider-ui-governance-design.md` | P1 governance design | Historical/design |
| `docs/design/platform-strategy-os-design.md` | Platform strategy design | Historical/design |
| `docs/design/publish-feedback-loop-design.md` | Publish/feedback design | Historical/design |
| `docs/design/review-issue-system-design.md` | ReviewIssue design | Historical/design |
| `docs/new/deep-research-report.md` | Imported research report | Historical/design |
| `docs/new/implementation/agent-industrialization-design.md` | Agent industrialization | Historical/design |
| `docs/new/implementation/agent-scheduler-design.md` | Scheduler design | Historical/design |
| `docs/new/implementation/ui-inventory.md` | UI inventory | Historical/reference |
| `docs/new/implementation/v6-v7-gap-analysis.md` | v6/v7 gap analysis | Historical/design |
| `docs/new/implementation/v6-v7-implementation-plan.md` | v6/v7 implementation plan | Historical/design |
| `docs/new/novel-forge-v6-1-literary-analysis-design-for-codex.md` | Literary analysis design | Historical/design |
| `docs/new/novel-forge-v6-complete-design-with-literary-analysis.md` | Complete design import | Historical/design |
| `docs/new/novel-forge-v6-gap-design-for-codex.md` | Gap design import | Historical/design |

### Standalone Docs

| Path | Topic | Status | Recommended Action |
|---|---|---|---|
| `docs/adr/0001-stdlib-unittest-first.md` | Test/dependency ADR | Active reference | Keep |
| `docs/ai/skill-adoption/anthropic-skills-inventory.md` | Skill adoption inventory | Historical/reference | Keep |
| `docs/ai/skill-adoption/custom-skill-backlog.md` | Skill backlog | Historical/reference | Keep |
| `docs/ai/skill-adoption/final-report.md` | Skill adoption final report | Historical/report | Keep |
| `docs/ai/skill-adoption/history-question-profile.md` | Skill research profile | Historical/reference | Keep |
| `docs/ai/skill-adoption/install-log.md` | Skill install log | Historical/report | Keep |
| `docs/ai/skill-adoption/project-profile.md` | Project profile for Skill adoption | Historical/reference; path drift found | Refresh later |
| `docs/ai/skill-adoption/skill-selection-matrix.md` | Skill selection | Historical/reference | Keep |
| `docs/ai/skill-adoption/trigger-test-cases.md` | Skill trigger tests | Historical/reference | Keep |
| `docs/auto-implementation-plan.md` | Auto implementation plan | Historical/design | Keep |
| `docs/deep-research-report.md` | Research report | Historical/design, v5 wording | Keep |
| `docs/implementation-summary.md` | Prior implementation summary | Historical/report | Keep |
| `docs/mkaos-agent-api-protocol.md` | MKAOS API protocol | Active reference | Validate before editing API |
| `docs/mkaos-database-schema.md` | MKAOS DB schema | Active reference | Validate against code/migrations |
| `docs/mkaos-p0-implementation-plan.md` | MKAOS P0 plan | Historical/report | Keep |
| `docs/multidisciplinary-knowledge-asset-os.md` | MKAOS product concept | Active reference/design | Keep |
| `docs/novel-os-final-optimization-blueprint.md` | Prior optimization blueprint | Historical/design | Keep |
| `docs/novel-os-optimization-plan.md` | Prior optimization plan | Historical/report | Keep |
| `docs/prompts/claude-code-novel-os-v6-long-task-prompts.md` | Prompt archive | Historical/reference | Keep |
| `docs/skills-audit-report.md` | Skill audit | Active reference | Refresh when Skills change |

### Reports

`docs/reports/` contains audit reports, phase reports, proof reports, and prior final/current summaries. Treat all reports as report/history unless explicitly referenced by a current doc.

High-value active reference reports:

- `docs/reports/novel-os-full-codebase-map.md`
- `docs/reports/novel-os-functional-inventory.md`
- `docs/reports/novel-os-agent-audit-report.md`
- `docs/reports/novel-os-agent-optimization-plan.md`
- `docs/reports/novel-os-architecture-audit.md`
- `docs/reports/novel-os-code-quality-audit.md`
- `docs/reports/novel-os-data-model-audit.md`
- `docs/reports/novel-os-performance-reliability-audit.md`
- `docs/reports/novel-os-distance-to-operating-system.md`
- `docs/reports/novel-os-temporary-solutions-register.md`
- `docs/reports/novel-os-optimization-execution-log.md`
- `docs/reports/provider-hard-stop-proof.md`
- `docs/reports/production-fail-closed-hardening-report.md`

Older or phase-specific reports remain useful as evidence of previous work, not as current truth:

- `docs/reports/phase-*`
- `docs/reports/v6-*`
- `docs/reports/mkaos-*`
- `docs/reports/*proof.md`
- `docs/reports/*report.md`
- `docs/reports/*summary.md`

## Conflict List

| Conflict | Document Position | Old Claim | Current Code Fact | Correction |
|---|---|---|---|---|
| Missing root docs | `README.md` Key Docs | Links to `ARCHITECTURE.md`, `WORKFLOW.md`, `TESTING.md` | No root files found by `rg --files`; current docs live under `docs/` | README now links `docs/README.md`, architecture, module map, tests, roadmap |
| CLI command path | `README.md` Quick Start/Core Commands | Uses `./novel-forge` | No root executable was found in scan; console script exists in `pyproject.toml` after install | README now uses `PYTHONPATH=src python3 -m novel_forge.cli`; notes installed `novel-forge` script |
| V5 Makefile wording | `Makefile` help | `validate V5 structure` | Runtime package/API are v6 | Updated text to Novel Forge workspace |
| V5 wording in active docs | `docs/02-workflows/skill-usage.md`, `docs/01-architecture/skills-system.md`, `docs/04-modules/module-index.md` | Describes V5 pipeline as current | Current runtime is v6, with newer OS modules and tests | Marked as active reference with drift risk; prefer current docs |
| V5 roadmaps appear current | `docs/08-roadmap/v5-*` | Contains done/pending V5 state | Many v6 features now exist and current roadmap differs | Classified as historical |
| Multiple final/current reports | `docs/reports/*current*`, `*final*` | Competing current/final status | Current state must be based on code scan | Added current engineering report for this pass |
| Design docs may overclaim | `docs/design/`, `docs/new/` | Target architecture and features | Code has many slices but not every design feature is complete | Classified as design/historical unless code evidence confirms |
| Old docs mention missing root workflow/testing docs | `docs/ai/skill-adoption/project-profile.md` | References `WORKFLOW.md` and `TESTING.md` | No root docs found | Marked for later refresh |

## Proposed Documentation Architecture

```text
docs/
  README.md
  project-current-state.md
  architecture/
    overview.md
    module-map.md
  product/
    capability-map.md
  engineering/
    extension-guide.md
  quality/
    regression-tests.md
  roadmap/
    current-roadmap.md
  reports/
    docs-audit-current-state.md
    current-engineering-state.md
  archive/
    README.md
```

Existing historical directories remain in place:

- `00-product` to `09-skills`;
- `design`;
- `new`;
- `reports`;
- `ai`;
- `prompts`;
- older standalone docs.

## Recommendations

1. Keep `docs/README.md` and `docs/project-current-state.md` as the first docs Claude Code reads.
2. Refresh old `docs/01-architecture/*`, `docs/02-workflows/*`, and `docs/04-modules/*` only when they are needed; do not mass-edit historical files without a migration task.
3. For future docs, always include date, baseline commit/branch, status language, and evidence paths.
4. Do not use "final" or "current" in report names unless the report is linked from the current docs index.
5. Update `docs/roadmap/current-roadmap.md` when P0/P1 status changes.
