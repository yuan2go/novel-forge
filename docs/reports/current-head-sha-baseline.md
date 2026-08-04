# Current HEAD SHA Evidence Model

This file is a stable source-tree contract, not a snapshot of the latest GitHub
Actions run. It deliberately does not record a commit SHA, remote run id,
artifact digest, timestamped test count, or remote conclusion.

## Three evidence layers

| Layer | Authority | Persistence | Binding |
|---|---|---|---|
| Architecture Contract | `architecture/manifests/postgresql-authority-contract.json` | Git | reviewed requirements and minimum thresholds; never a mutable source-tree hash |
| Implementation Tree Identity | `novel_forge.tools.implementation_tree_identity` | recomputed locally and in CI | canonical SHA-256 over semantic inputs only |
| Run Evidence | Core OS CI artifacts | GitHub Actions | exact tested `GITHUB_SHA`, artifact content hash, job result and environment |

The implementation identity includes `src/**`, `tests/**`, `scripts/**`,
`architecture/manifests/**`, `.github/workflows/**`, Compose definitions,
Dockerfiles, `Makefile`, and `pyproject.toml`. Reports, generated output, CI ids,
temporary files, logs, build output, and other self-referential evidence are
excluded by an explicit code-level selection contract and unit tests.

## Candidate schema facts

| Fact | Value |
|---|---|
| Migration head | `20260804_0063_worker_fleet_operational_governance` |
| Migration count | 63 |
| Migration registry | 59 source types: 18 `DOMAIN_NATIVE`, 41 `ARCHIVAL_NATIVE` |
| Default backend | PostgreSQL Authority, fail closed |
| Legacy default reachability | forbidden |
| Worker runtime groups | Chapter, Content, Source, MKAOS, Book, Outbox, Maintenance |

## Final-SHA qualification flow

```text
code + stable contract commit
  -> push candidate SHA
  -> run all Core OS CI required jobs on that SHA
  -> emit SHA-bound Coverage, tests, migrations, Compose, query plan,
     Worker Fleet, Docker digest and environment artifacts
  -> fail-closed release-qualification artifact validates all classes
  -> annotated qualification tag points to that same green SHA
  -> no evidence-only source commit after the tag
```

The authoritative remote status is therefore the Actions run and annotated tag,
not this report. A later source commit automatically requires a new run and can
never inherit the preceding tag's proof.

## Evidence boundary

Fixture-based unit, PostgreSQL integration, Compose recovery, core domain
migration and Worker Fleet claims are eligible only after their exact-SHA jobs
pass. The following remain false regardless of a green backend qualification:

- real Provider proof;
- real long-form or multi-book proof;
- production verification;
- backup/PITR exercise proof;
- autonomous Book Loop proof.
