# Testing Strategy

## Canonical runner

Pytest is the canonical Python runner. It collects both pytest functions and the
retained `unittest.TestCase` suites. Architecture manifests require every
critical collection and listed critical module to collect at least one test.
File existence or zero-case unittest discovery is not evidence.

## Default gates

```bash
make test
make validate
make authority-test
npm --prefix web/admin test
make sync-skills-dry-run
make sync-skills
make check-skills
git diff --check
```

`make test` runs the complete Python suite with pytest and the Web tests.
`make validate` runs compile, Ruff boundaries/ratchet, architecture manifests,
architecture fitness, and Compose configuration checks.

## PostgreSQL and deployment gates

When Docker/PostgreSQL is available, also run:

```bash
make authority-postgres-test
make authority-query-plan-release
make authority-compose-config-check
make authority-smoke
```

The migration gate must replay all 73 registered migrations through
`20260806_0073_core_functional_loops`. The Compose smoke validates API readiness,
the eight-process Worker fleet, restart/recovery/fence behavior, Outbox evidence,
and clean drain. It remains fixture-only unless a real Provider was explicitly
configured and its evidence independently qualified.

## P0 Book vertical proofs

Book production tests must use the same composition builders as the Authority API
and Book Worker. A hand-built test-only Supervisor is not production evidence.

Required scenarios:

1. No-Replan: resolved Book admission, Planning, ChapterGroup/Plan, Chapter 1,
   acceptance, Reader/Recap, and Chapter 2 admission/execution.
2. Explicit Replan: replacement candidate and PlanChange proposal,
   `APPROVAL_PENDING`, restart-safe repeated ticks, Worker permission rejection,
   formal Authority API approval, plan activation, new input snapshot, Book
   resume, and Chapter 2 admission/execution.

The integration suite also covers retries, restart/resume, lease/fence rejection,
and UNKNOWN ExternalEffect reconciliation. Deterministic Provider output limits
these scenarios to fixture-backed PostgreSQL integration proof.

## P1 contract tests

Changes to converged boundaries must prove:

- Environment: only development/test/validation/production; controlled
  environments reject fixture composition.
- Provider: API and workers build through the common Provider factory/registry;
  missing controlled credentials fail closed.
- RuntimeJob: only governed Book/maintenance scheduling envelopes are accepted;
  business jobs remain Command Kernel Operations.
- Reachability: code/composition/deployment/Authority/Worker facts derive from
  real imports and Compose; `proof_sha` is current HEAD.
- Knowledge: optional packs do not block Preparation; a Capability-required
  missing `knowledge_pack` does block.
- Legacy: controlled production cannot import or silently fall back to listed
  compatibility surfaces.

## Provider qualification

Provider tests are layered:

```text
protocol fixture
→ adapter conformance
→ controlled route composition
→ credentialed qualification
→ Authority-bound real execution
```

Only the last two may support `real_provider_qualified` or
`real_provider_proven`, and only when evidence is current-SHA, non-fixture, and
persisted through the formal runtime. Default tests never call paid/network
providers.

## Web gate

```bash
npm --prefix web/admin test
npm --prefix web/admin run lint
npm --prefix web/admin run build
```

Browser/live-backend proof is separate and must be reported `NOT_VERIFIED` when
the browser or backend is unavailable.

## Reporting

Report the exact final SHA, command, collected/passed/failed/skipped counts, and
environment prerequisites. Use `NOT_VERIFIED` for unavailable external services,
credentials, GitHub Actions, or deployment conditions. Local success never
substitutes for Remote CI on the same SHA.
