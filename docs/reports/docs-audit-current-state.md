# Docs Audit Current State

Updated: 2026-08-01  
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`  
Audited code HEAD: `aa991b53039cdf2e4e7911d4483052b9a6a752a1`

This document records the 2026-08-01 documentation rebaseline. It replaces the 2026-07-05 V6 documentation audit as the current docs-audit entrypoint.

Detailed code audit: [`2026-08-01-code-audit-and-documentation-rebaseline.md`](2026-08-01-code-audit-and-documentation-rebaseline.md).

## 1. Audit Objective

The documentation tree contained many historically valid but competing “current”, “final”, “complete” and “proof” reports. Several reports mixed:

- target design;
- code presence;
- deterministic fixture results;
- historical test results;
- real Provider or production readiness.

The rebaseline establishes one current documentation path and makes evidence limits explicit.

## 2. Updated Current Documents

| Path | 2026-08-01 action | Current purpose |
|---|---|---|
| `docs/README.md` | Rewritten | current documentation index and authority order |
| `docs/project-current-state.md` | Rewritten | implementation fact table and current flags |
| `docs/architecture/module-map.md` | Rewritten | Authority/Legacy architecture and module boundaries |
| `docs/product/capability-map.md` | Rewritten | evidence-based capability maturity |
| `docs/quality/regression-tests.md` | Rewritten | static, PostgreSQL, Provider, long-form and multi-book verification gates |
| `docs/roadmap/current-roadmap.md` | Rewritten | dependency-ordered P0-P8 roadmap |
| `docs/reports/current-engineering-state.md` | Rewritten | concise current engineering verdict |
| `docs/reports/current-engineering-progress-feature-docs.md` | Rewritten | current feature-progress summary |
| `docs/reports/2026-08-01-code-audit-and-documentation-rebaseline.md` | Added | detailed code audit and documentation rebaseline |
| `docs/reports/docs-audit-current-state.md` | Rewritten | this documentation audit record |

Historical documents were not deleted.

## 3. Current Documentation Authority Order

When documents disagree:

```text
current code and migrations
→ current-SHA runtime/test evidence
→ docs/project-current-state.md
→ current engineering/audit reports
→ active architecture/design/implementation plans
→ blueprints
→ historical reports
```

Blueprints describe target capability. Design docs describe intended contracts. Reports describe a specific pass. None of them replace code and current-SHA execution evidence.

## 4. Major Drift Corrected

### 4.1 Historical test results presented near current state

Older documents listed successful test counts from earlier commits. The new current docs state that the 2026-08-01 remote audit did not execute tests and that historical results apply only to their original SHA.

### 4.2 Fixture proof mixed with production proof

The new docs consistently separate:

```text
fixture/protocol proof
real Provider proof
long-form proof
multi-book proof
platform proof
production proof
```

Current flags remain false where real evidence is absent.

### 4.3 Authority and Legacy runtime ambiguity

The new docs state that the repository still contains two runtime surfaces and that default development/Compose behavior remains Legacy-oriented. PostgreSQL Authority is the target production runtime, but its default deployment topology is not closed.

### 4.4 Whole-book coordination overstated as autonomy

Book Authority is now documented as a persistent coordinator that delegates and accepts Chapters. It is not described as a complete whole-book autonomous supervisor because an external caller still supplies frozen ChapterPlan and production inputs.

### 4.5 Provider controls overstated as real Provider validation

Provider v2 registry, route, query/cancel/callback and OpenAI transport seams are documented as implemented protocol foundations. They are not described as real Provider or real cost proof.

### 4.6 UI/module presence overstated as business completion

The capability map now requires end-to-end Authority, recovery, evidence, operator workflow and real external proof where applicable. A class, schema, route, page or fixture alone does not mark a capability complete.

### 4.7 Current HEAD integrity not reflected in docs

The current docs now record that some newly referenced Authority modules, workers, migrations and tests could not be resolved from the same exact HEAD through the repository content interface.

Until local checkout verification:

```text
head_integrity_verified=false
current_head_build_verified=false
```

## 5. Current Flag Vocabulary

Use stable machine-readable flags in current reports:

```text
architecture_defined
head_integrity_verified
current_head_build_verified
command_kernel_proven
postgres_authority_fixture_proven
single_chapter_fixture_proven
single_chapter_real_provider_proven
real_provider_proven
real_usage_proven
real_cost_proven
quality_judge_calibrated
reader_outcome_behavior_calibrated
longform_proven
multi_book_proven
platform_publish_proven
production_verified
```

A true flag must link to a current-SHA evidence report with acceptance criteria.

## 6. Status Vocabulary

Use:

- `Implemented` — substantial code path exists;
- `Fixture-proven` — deterministic/mock integration proves protocol behavior;
- `Partial` — important path exists but the business loop is incomplete;
- `Design/Foundation` — schema, migration, contract or first slice exists;
- `Unproven` — real-world proof is absent;
- `Blocked` — repository, deployment or dependency condition prevents a valid completion claim;
- `NOT_EXECUTED` — test or external proof was not run;
- `BLOCKED_PRECONDITION` — run did not start because a declared gate was missing.

Do not use “complete”, “production-ready” or “final” without explicit acceptance evidence.

## 7. Current File Classification

### Current entrypoints

- `docs/README.md`
- `docs/project-current-state.md`
- `docs/architecture/module-map.md`
- `docs/product/capability-map.md`
- `docs/quality/regression-tests.md`
- `docs/roadmap/current-roadmap.md`
- `docs/reports/current-engineering-state.md`
- `docs/reports/current-engineering-progress-feature-docs.md`
- `docs/reports/2026-08-01-code-audit-and-documentation-rebaseline.md`
- `docs/reports/docs-audit-current-state.md`

### Active target/design references

- `docs/blueprint/*`
- `docs/architecture/production-execution-plane.md`
- `docs/architecture/scoped-conversational-agent-architecture.md`
- `docs/design/hierarchical-story-planning-and-production-authority.md`
- `docs/design/book-design-authority-and-longform-closed-loop.md`
- `docs/plans/book-design-authority-implementation-plan.md`
- `docs/plans/novel-os-final-blueprint-completion-plan.md`

These are active design inputs, not implementation proof.

### Historical evidence

Unless explicitly refreshed and linked from `docs/README.md`, treat as historical:

- V5/V6/V7 phase reports;
- old “current/final/complete/proof” reports;
- imported research/design documents;
- earlier module maps and progress logs;
- test reports bound to previous commits.

## 8. Required Metadata For New Current Docs

Every current-state, architecture, test or proof document must include:

```text
updated date
branch
full commit SHA
scope
code facts
runtime verification results
NOT_EXECUTED/BLOCKED_PRECONDITION status
explicit proof flags
evidence paths
remaining gaps
replacement/current-entry links
```

## 9. Required Documentation Updates By Change Type

| Change | Required current docs |
|---|---|
| Authority state machine or migration | current state, module map, regression guide, audit/proof report |
| New production capability | capability map, module map, roadmap, focused acceptance report |
| Provider/backend change | current state, regression guide, Provider proof report |
| Whole-book/long-form change | project current state, capability map, roadmap, staged long-form report |
| Deployment change | current engineering state, regression guide, operations/readiness report |
| Security/auth change | capability map, regression guide, threat/security report |
| Capability maturity promotion | current state, capability map, current engineering report and linked evidence |

## 10. Documentation Non-goals

- Do not mass-delete historical reports.
- Do not rewrite blueprints to match current limitations; preserve the target.
- Do not hide failed or unexecuted verification.
- Do not copy test counts without commit binding.
- Do not mark documentation cleanup itself as product capability completion.

## 11. Next Docs Action

After P0 repository-integrity and full current-SHA validation complete:

1. add a HEAD-bound verification report;
2. update current flags and maturity only from that report;
3. record exact failure/skip counts;
4. update Authority deployment/readiness documentation;
5. archive or clearly mark any newly superseded “current” report.
