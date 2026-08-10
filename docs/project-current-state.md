# Project Current State

Updated: 2026-08-10

The codebase now has one PostgreSQL-backed Book production composition shared by
the Authority API and Book Worker. P0 convergence is proven with deterministic
providers, PostgreSQL integration, and the default Compose topology. Real
Provider, sustained long-form, and production deployment evidence remain absent.

```text
status=P0_PRODUCTION_RUNTIME_CONVERGED_FIXTURE_PROVEN
canonical_book_runtime=true
api_worker_composition_shared=true
postgresql_authority=true
capability_pack_compilable=true
required_worker_fleet_readiness_proven=true
two_chapter_no_replan_proven=true
two_chapter_explicit_replan_approval_proven=true
fixture_only=true
real_provider_qualified=false
real_provider_proven=false
longform_proven=false
production_verified=false
```

## Canonical runtime

`build_book_production_composition` is the Book production composition root. It
constructs `BookProductionComposition` from the existing Book, Planning,
ChapterGroup, Production Preparation, Followup, PlanChange, input resolver, and
Replan components. Both the Authority API and Book Worker require this graph at
startup; missing dependencies fail closed.

For `RESOLVED_AUTHORITY_INPUT`, the durable path is:

```text
Authority API admission
→ Story Planning candidate and activation
→ Book input snapshot
→ ChapterGroup and ChapterPlan
→ Chapter Authority Operation/Saga/Attempt/ExternalEffect
→ acceptance
→ Narrative Checkpoint and Ending Reachability
→ Reader Outcome
→ cadence Recap, or Authority-requested Recap when Ending Reachability is at risk
→ no-replan next chapter, or Replan candidate and PlanChange proposal
→ APPROVAL_PENDING
→ formal Authority approval command/API
→ PlanChange activation and new input snapshot
→ Book resume and next chapter
```

The Worker may generate a Replan candidate and proposal but cannot approve it:
its principal has `book.authority.execute`, not the separate
`book.authority.approve_replan` permission. `APPROVAL_PENDING` is a durable
normal wait state. Approval replay and the subsequent activation/resume path
are idempotent and restart-safe.

## Authority and recovery facts

| Area | Current code/runtime fact | Evidence ceiling |
|---|---|---|
| PostgreSQL | sole production state authority; production-like paths fail closed without it | migration and PostgreSQL integration |
| Book composition | API and Worker share `BookProductionComposition` | two-chapter PostgreSQL fixture proof |
| Replan | candidate/proposal automatic; approval explicit; activation/resume automatic after approval | formal API approval fixture proof |
| Chapter execution | Command Kernel owns Operation, Saga, Attempt, Lease, Fence, ExternalEffect, receipt, result, and recovery | PostgreSQL integration and fault injection |
| Capability Pack | shipped Chapter Pack compiles against real operation/capability/artifact catalogs; controlled environments also require activation | local and Compose compilation; no real-provider activation proof |
| Readiness | separates `api_ready` from complete required Worker fleet `runtime_ready` and explicit evidence flags | eight-worker Compose health proof |
| Compose | PostgreSQL, MinIO, migration, API, and eight required Worker kinds; restart, lease recovery, stale-fence rejection, and drain | fixture fault-injection proof |

## Current limits

- All current vertical proofs use deterministic fixture providers. They do not
  prove prose quality, credentials, usage/cost receipts from a real Provider, or
  Provider-specific timeout/query/cancel behavior.
- No sustained real long-form or multi-book run has been performed.
- Public authentication, production secrets, backup/PITR, load/capacity/SLO,
  and real publishing behavior remain unverified.
- Explicit legacy compatibility code still exists for migration and local
  compatibility use; it is not the canonical production path.
- Final-SHA remote CI is not evidence until the pushed Draft PR checks complete.

Historical reports describe their own SHA and are navigation material only.
Current code, current migrations, and exact-HEAD test evidence take precedence.
