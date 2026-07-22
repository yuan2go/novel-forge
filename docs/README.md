# Autonomous Novel OS Documentation

Updated: 2026-07-22
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`, commit `c638927`

This directory is the current documentation entrypoint for Autonomous Novel OS on the `novel-forge` codebase. The repository/package/CLI remain Novel Forge v6 until an explicit rename migration is approved.

Current engineering priority: v1 single-book production closure.

Use code and tests as the source of truth. Older design files and phase reports remain useful as history, but they are not authoritative unless a current document links them as active evidence.

## Autonomous Novel OS Blueprint Control

The active product target is defined by the blueprint files and the current control reports:

- [blueprint/autonomous-novel-os-full-blueprint.md](blueprint/autonomous-novel-os-full-blueprint.md) - full functional blueprint.
- [blueprint/novel-os-project-blueprint.md](blueprint/novel-os-project-blueprint.md) - project blueprint and phase plan.
- [architecture/production-execution-plane.md](architecture/production-execution-plane.md) - Claude Code orchestration, Codex CLI execution, model profiles, routing, workspace transactions, recovery, evaluation, and multi-book expansion target architecture.
- [design/hierarchical-story-planning-and-production-authority.md](design/hierarchical-story-planning-and-production-authority.md) - Book Authority、Volume/Arc/Chapter Group Authority、真实 Chapter Saga 委托、滚动规划与分层重规划目标设计。
- [reports/novel-os-final-blueprint-gap-analysis.md](reports/novel-os-final-blueprint-gap-analysis.md) - evidence-first final-blueprint requirement traceability and maturity audit.
- [plans/novel-os-final-blueprint-completion-plan.md](plans/novel-os-final-blueprint-completion-plan.md) - target architecture, migration, phased delivery, and acceptance plan.
- [reports/blueprint-gap-audit.md](reports/blueprint-gap-audit.md) - current gap audit against the blueprint.
- [reports/module-maturity-matrix.md](reports/module-maturity-matrix.md) - M0-M5 module maturity matrix.
- [reports/data-model-gap-matrix.md](reports/data-model-gap-matrix.md) - data model gap matrix.
- [reports/v1-v7-roadmap.md](reports/v1-v7-roadmap.md) - engineering roadmap aligned to v1-v7 phases.
- [reports/next-production-slices.md](reports/next-production-slices.md) - ordered implementation slices, starting with v1.

## V7 Content Intelligence Update

The active branch adds the first V7 Content Intelligence Foundation on top of the existing Novel OS runtime. Verified implementation paths now include:

- Genre OS: `src/novel_forge/modules/genre_os/`, `/product/genre/*`, `tests/unit/test_genre_os.py`
- Style OS: `src/novel_forge/modules/style_os/`, `/product/style/*`, `tests/unit/test_style_os.py`
- Canon Graph 2.0 plugins: `src/novel_forge/modules/canon_graph/service.py`, `tests/unit/test_canon_graph_plugins.py`
- Quality Eval 2.0: `src/novel_forge/modules/quality_eval/`, `/product/quality/*`, `tests/unit/test_quality_eval_v2.py`
- Long-chain Proof Center: `src/novel_forge/modules/long_chain_proof/`, `/product/long-chain-proof/*`, integration 50-chapter pressure fixture
- Publishing/Feedback Adapter 2.0: `src/novel_forge/modules/publishing_feedback_adapters/`, `/product/publishing-adapters/*`, `/product/feedback-adapters/*`
- Web Admin consoles: Genre, Style, Canon Graph 2.0, Quality Eval 2.0, Long-chain Proof, Publishing Feedback 2.0, and Agent Operation Coverage routes.

Current report: [reports/v7-content-intelligence-foundation-report.md](reports/v7-content-intelligence-foundation-report.md).
Risk closure addendum: [reports/v7-content-intelligence-risk-closure-report.md](reports/v7-content-intelligence-risk-closure-report.md).

## Recommended Reading Order

1. [../CLAUDE.md](../CLAUDE.md) - project operating manual for Claude Code and coding agents.
2. [project-current-state.md](project-current-state.md) - current engineering and product state.
3. [architecture/overview.md](architecture/overview.md) - system architecture and data flow.
4. [architecture/production-execution-plane.md](architecture/production-execution-plane.md) - current target production execution architecture and migration plan.
5. [architecture/module-map.md](architecture/module-map.md) - module boundaries and evidence paths.
6. [design/hierarchical-story-planning-and-production-authority.md](design/hierarchical-story-planning-and-production-authority.md) - current single-book hierarchical planning and production target.
7. [product/capability-map.md](product/capability-map.md) - Novel OS capability map and status.
8. [engineering/extension-guide.md](engineering/extension-guide.md) - how to add a capability without bypassing core contracts.
9. [quality/regression-tests.md](quality/regression-tests.md) - current test and validation map.
10. [roadmap/current-roadmap.md](roadmap/current-roadmap.md) - current P0/P1/P2/P3 roadmap.

## Current Docs

| Area | Current Entry | Purpose |
|---|---|---|
| Current state | [project-current-state.md](project-current-state.md) | Fact table for implemented, partial, missing, and risky capabilities |
| Architecture | [architecture/overview.md](architecture/overview.md) | Layering, runtime flow, Agent/workflow relationship |
| Production execution | [architecture/production-execution-plane.md](architecture/production-execution-plane.md) | Claude Code orchestration, Codex CLI backend, high/xhigh model profiles, routing, recovery, workspace, evaluation, and phased migration |
| Hierarchical story production | [design/hierarchical-story-planning-and-production-authority.md](design/hierarchical-story-planning-and-production-authority.md) | Book/Volume/Arc/ChapterGroup/Chapter Authority、真实子 Saga 委托、滚动规划、计划影响传播和分阶段验收设计 |
| Modules | [architecture/module-map.md](architecture/module-map.md) | Module/API/UI/test evidence map |
| Product | [product/capability-map.md](product/capability-map.md) | Novel Operating System capability coverage |
| Engineering | [engineering/extension-guide.md](engineering/extension-guide.md) | Extension checklist for schema/service/API/UI/tests/docs |
| Testing | [quality/regression-tests.md](quality/regression-tests.md) | Regression suite and command map |
| Roadmap | [roadmap/current-roadmap.md](roadmap/current-roadmap.md) | Current implementation priorities |
| Final blueprint gap | [reports/novel-os-final-blueprint-gap-analysis.md](reports/novel-os-final-blueprint-gap-analysis.md) | Evidence-first 135-requirement traceability, gaps, and weighted maturity score |
| Final blueprint plan | [plans/novel-os-final-blueprint-completion-plan.md](plans/novel-os-final-blueprint-completion-plan.md) | Target architecture, phased dependencies, migrations, tests, and acceptance gates |
| Blueprint gap | [reports/blueprint-gap-audit.md](reports/blueprint-gap-audit.md) | Autonomous Novel OS gap audit and v1 blockers |
| Module maturity | [reports/module-maturity-matrix.md](reports/module-maturity-matrix.md) | M0-M5 module maturity matrix |
| Data model gap | [reports/data-model-gap-matrix.md](reports/data-model-gap-matrix.md) | Blueprint data model coverage |
| v1-v7 roadmap | [reports/v1-v7-roadmap.md](reports/v1-v7-roadmap.md) | Phase roadmap from single-book closure to platform feedback |
| Next slices | [reports/next-production-slices.md](reports/next-production-slices.md) | Ordered production-grade implementation slices |
| V7 report | [reports/v7-content-intelligence-foundation-report.md](reports/v7-content-intelligence-foundation-report.md) | Verified V7 content intelligence foundation changes |
| V7 risk closure | [reports/v7-content-intelligence-risk-closure-report.md](reports/v7-content-intelligence-risk-closure-report.md) | Provider judge, provider long-chain proof, platform API adapter, and UI artifact workflow closure |
| Audit | [reports/docs-audit-current-state.md](reports/docs-audit-current-state.md) | Documentation drift audit |
| Final state report | [reports/current-engineering-state.md](reports/current-engineering-state.md) | Result of the current docs audit pass |

## Historical And Design References

The following directories are valuable but should be treated as historical or design material unless refreshed by the current docs above:

- `docs/00-product/` through `docs/09-skills/`: earlier product, architecture, workflow, schema, module, operations, audit, roadmap, and skill docs. Some remain useful, but several contain v5 wording.
- `docs/design/`: design proposals and requirements. These describe intent, not necessarily complete implementation.
- `docs/new/`: v6/v7 design and implementation planning material. Treat as historical planning unless code evidence confirms it.
- `docs/reports/`: execution reports, proof reports, audits, and prior state summaries. Multiple files use words like "current" or "final"; prefer the current docs index first.
- `docs/08-roadmap/v5-*`: v5 roadmap and test history. Keep for lineage, not current roadmap.
- `docs/archive/`: archive index and future deprecation notes.

Do not delete historical docs during ordinary cleanup. Mark them historical, link them from this index, or move only with explicit migration intent.

## Claude Code Usage

When Claude Code enters the project:

1. Read `CLAUDE.md`.
2. Read this file.
3. Read `docs/project-current-state.md`.
4. Inspect relevant code and tests before making claims.
5. Update this docs index when adding or replacing durable docs.

If current code contradicts an older report, code wins. Document the conflict in `docs/reports/docs-audit-current-state.md` or a relevant report instead of silently copying old claims.
