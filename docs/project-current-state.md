# Project Current State

Updated: 2026-08-11

Novel Forge has one PostgreSQL-backed Book production composition shared by the
Authority API and Book Worker. Current vertical evidence uses deterministic
Providers. Real Provider, sustained long-form, and production deployment remain
unproven.

```text
canonical_book_runtime=true
api_worker_composition_shared=true
postgresql_authority=true
explicit_replan_approval_gate=true
capability_pack_compilable=true
runtime_environment_unified=true
provider_composition_shared=true
runtime_job_boundary_enforced=true
production_reachability_derived=true
knowledge_pack_capability_optional=true
fixture_only=true
real_provider_qualified=false
real_provider_proven=false
longform_proven=false
production_verified=false
```

## Current runtime facts

| Area | Code/runtime fact | Evidence ceiling |
|---|---|---|
| Book | API and Worker share `BookProductionComposition` | two-chapter PostgreSQL fixture proof |
| Replan | Worker creates candidate/proposal, waits for formal approval, then resumes automatically | explicit approval fixture proof |
| Chapter | Command Kernel owns Operation, Saga, Attempt, Lease, Fence, ExternalEffect, validation, commit, retry and recovery | PostgreSQL integration/fault injection |
| Provider | one Factory/Registry composition feeds the shared Production Execution Gateway | composition/conformance; no current real call |
| Environment | development/test are local; validation/production are controlled | unit and architecture checks |
| RuntimeJob | Book ticks and maintenance scans only | contract and PostgreSQL integration |
| Knowledge | `knowledge_pack` is optional unless the Capability Pack/stage requires it | Preparation and Capability Pack tests |
| Reachability | derived from imports, production entry manifest, console scripts, and Compose | static architecture reachability only |
| Readiness | API dependencies and complete Worker freshness are distinct; proof flags remain explicit | Compose fixture smoke |

## Canonical Book path

```text
Authority API admission
→ Planning candidate / activation
→ Book input snapshot
→ ChapterGroup / ChapterPlan
→ Chapter Operation / Attempt / ExternalEffect
→ acceptance / checkpoint / Reader Outcome / Recap
→ no-replan next chapter

or

→ Replan candidate / PlanChange proposal
→ APPROVAL_PENDING
→ Authority approval
→ Plan activation / input snapshot update / Book resume
→ next chapter
```

## Current limits

- Scripted Provider fixtures do not prove credentials, model quality, real usage
  or cost receipts, or Provider-specific timeout/query/cancel behavior.
- There is no sustained real long-form or multi-book proof.
- Public authentication, production secrets, backup/PITR, capacity/SLO, and a
  real deployment remain unverified.
- Legacy LocalStorage, Celery/product API, generic workflow/loop, production
  kernel, agent scheduler, and context services remain isolated compatibility or
  migration surfaces. They are not canonical production paths.
- GitHub Actions execution is external evidence. A local pass cannot substitute
  for a remote run on the same SHA.

Historical reports are navigation material only. Current code, migrations, and
exact-HEAD evidence take precedence.
