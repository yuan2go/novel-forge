# Novel Forge Documentation

This directory contains current reference documents and historical engineering
records. Current code and exact-HEAD evidence always outrank prose.

## Canonical current documents

| Fact area | Document |
|---|---|
| Current status and evidence ceiling | [`project-current-state.md`](project-current-state.md) |
| Current module and runtime architecture | [`01-architecture/current-implementation.md`](01-architecture/current-implementation.md) |
| Canonical Book workflow | [`../WORKFLOW.md`](../WORKFLOW.md) |
| Provider / execution architecture | [`architecture/unified-production-execution-plane.md`](architecture/unified-production-execution-plane.md) |
| Testing | [`05-testing/testing-strategy.md`](05-testing/testing-strategy.md) |
| Operations | [`06-operations/authority-compose-runbook.md`](06-operations/authority-compose-runbook.md) |
| Roadmap | [`roadmap/current-roadmap.md`](roadmap/current-roadmap.md) |
| ADRs | [`adr/`](adr/) |

The code-derived production reachability manifest is available with:

```bash
PYTHONPATH=src python -m novel_forge.tools.production_reachability
```

It derives `code_exists`, `composed`, `deployed`, `runtime_reachable`,
`authority_backed`, `worker_backed`, `proof_level`, and `proof_sha` from tracked
production entries, imports, console scripts, and `compose.yml`.

## Documentation authority order

```text
current code and migrations
→ current-SHA runtime/test evidence
→ accepted ADRs
→ canonical current documents above
→ design references
→ historical audits, reports, plans, blueprints, prompts
```

Documents under `reports/`, `superpowers/`, `plans/`, `deliverables/`,
`architecture-closure/`, and most `blueprint/` paths retain engineering lineage.
They describe their original baseline and are not Current Truth unless a
canonical current document links them for a specific invariant.

## Maintenance rules

- Update current documents only after the code and verification change.
- Bind test/proof claims to a full commit SHA.
- Do not promote fixture evidence to real-provider, long-form, or production
  evidence.
- Keep PostgreSQL as the only production state authority.
- Do not document a module, table, interface, route, or class as production
  reachable without composition/deployment evidence.
- Keep phase delivery notes historical instead of repeatedly rewriting them as
  current state.
