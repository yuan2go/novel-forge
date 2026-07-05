# Novel Forge Documentation

Updated: 2026-07-05
Baseline checked: branch `backup/v6-post-mkaos-industrialization-20260705`, commit `e4f700c`

This directory is the current documentation entrypoint for Novel Forge v6 / early Novel Operating System runtime.

Use code and tests as the source of truth. Older design files and phase reports remain useful as history, but they are not authoritative unless a current document links them as active evidence.

## Recommended Reading Order

1. [../CLAUDE.md](../CLAUDE.md) - project operating manual for Claude Code and coding agents.
2. [project-current-state.md](project-current-state.md) - current engineering and product state.
3. [architecture/overview.md](architecture/overview.md) - system architecture and data flow.
4. [architecture/module-map.md](architecture/module-map.md) - module boundaries and evidence paths.
5. [product/capability-map.md](product/capability-map.md) - Novel OS capability map and status.
6. [engineering/extension-guide.md](engineering/extension-guide.md) - how to add a capability without bypassing core contracts.
7. [quality/regression-tests.md](quality/regression-tests.md) - current test and validation map.
8. [roadmap/current-roadmap.md](roadmap/current-roadmap.md) - current P0/P1/P2/P3 roadmap.

## Current Docs

| Area | Current Entry | Purpose |
|---|---|---|
| Current state | [project-current-state.md](project-current-state.md) | Fact table for implemented, partial, missing, and risky capabilities |
| Architecture | [architecture/overview.md](architecture/overview.md) | Layering, runtime flow, Agent/workflow relationship |
| Modules | [architecture/module-map.md](architecture/module-map.md) | Module/API/UI/test evidence map |
| Product | [product/capability-map.md](product/capability-map.md) | Novel Operating System capability coverage |
| Engineering | [engineering/extension-guide.md](engineering/extension-guide.md) | Extension checklist for schema/service/API/UI/tests/docs |
| Testing | [quality/regression-tests.md](quality/regression-tests.md) | Regression suite and command map |
| Roadmap | [roadmap/current-roadmap.md](roadmap/current-roadmap.md) | Current implementation priorities |
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
