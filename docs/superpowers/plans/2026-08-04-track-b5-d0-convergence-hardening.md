# Track B.5, D0 Authority, and Track C Convergence Implementation Plan

> Date: 2026-08-04  
> Branch: `feat/v7-content-intelligence-and-longform-proof`  
> Baseline SHA: `921d681635e0ce408024cf8335ca516971241660`

## Objective

Remove the mixed synchronous-worker semantics from Project and BookDesign,
prove transaction-command atomicity with named crash points, harden architecture
and database scope boundaries, persist the D0 qualification protocol through the
Authority runtime, repair the Admin production dependency advisories, and record
the existing BookDesign/StoryDesign/Planning convergence decision. C1 is not
started unless every user-specified gate has current-SHA evidence.

## Evidence already established

- `ProjectAuthorityApplication.execute()` admits and then performs an inline
  Attempt/Lease execution although its definitions use `execution_mode=worker`.
- `BookDesignAuthorityApplication.execute()` declares
  `transaction_command`, but also creates Attempt/Lease state and commits its
  business transaction before `submit_attempt_result()`.
- Both applications can commit business state and Outbox before an exception or
  process loss leaves the Operation non-terminal, and the exception path can
  then mark the Attempt failed.
- `authority-worker` and `maintenance-worker` only scan deadlines and publish
  health; they do not claim these Operations or invoke their domain handlers.
- `admit_command_in_uow()` already exists, so the kernel can be extended without
  duplicating admission or idempotency rules in domain applications.
- Migration 0051 gives `authority_asset_version.schema_version` a legacy default
  and its Book/Asset relationship tables do not prove composite scope integrity.
- Migration 0039 already models Arc as an orthogonal plan contract: Arc may have
  no parent, and containment relations exclude Arc.
- The current D0 runner is an in-memory protocol harness. Its stdout report is
  not PostgreSQL/Object Store Authority evidence and its one live path cannot
  prove the A-F scenario set.

## Commit 1 — Atomic transaction-command runtime

### Red tests

- Add PostgreSQL crash-window tests for Project create and Book/BookDesign
  propose/decide/activate.
- Inject these exact checkpoints:
  `before_admission`, `after_admission`, `after_domain_validation`,
  `after_asset_version_insert`, `after_business_projection_update`,
  `after_outbox_insert`, `before_operation_completion`, and
  `after_operation_completion_before_response`.
- Before changing production code, reproduce the existing business-committed /
  Operation-not-succeeded window by forcing failure at the old result-submit
  boundary.
- Assert Operation, Attempt, AssetVersion, Book, Candidate, Decision,
  Activation, Outbox, StateEvent, and Audit counts.

### Kernel implementation

- Add a versioned transaction-command result table in migration 0052.
- Add repository methods that persist the command result and transition
  `ADMITTED -> SUCCEEDED` inside the caller's UoW.
- Allow only transaction-classified definitions to use the direct terminal
  transition. Keep durable jobs and external effects on Attempt/Lease paths.
- Add `execute_transaction_command()` around `admit_command_in_uow()` with an
  explicit checkpoint hook. The hook is test-only injection plumbing; normal
  runtime uses a no-op.
- On duplicate same-digest admission, read and return the committed result
  without re-running the domain handler. Different digests continue to fail.
- Commit the UoW before the response-loss checkpoint so a retry proves replay.

### Domain conversion

- Convert Project and Book/BookDesign to the transaction helper.
- Move input-asset resolution, domain validation, AssetVersion/business
  projection, event/audit/outbox, result storage, and Operation completion into
  that UoW.
- Remove Attempt, Lease, Fence, READY/RUNNING, inline worker simulation, and
  failure submission from these applications.
- Change Project definitions to `execution_mode=transactional` and add
  `policy.execution_classification=transaction_command`.
- Record transaction commands as non-recoverable in-flight because no partial
  state can survive rollback; distinguish this from durable-job recovery.

### Verification

- Run focused unit and PostgreSQL integration tests after the red-to-green
  change.
- Run duplicate same/different digest, response loss, and concurrent replay
  tests.
- Commit as `fix: make transaction command completion atomic` and
  `test: add command crash-window and recovery proofs` if separation remains
  reviewable; otherwise keep code and its proof in one atomic commit.

## Commit 2 — Architecture fitness hardening

- Replace the single `**/domain.py` scan with an explicit domain-layer policy
  covering every `modules/<domain>` package and its `domain`, `contracts`,
  `validators`, and `policies` files.
- Deny FastAPI/router, concrete storage repositories, provider SDKs,
  `requests/httpx`, subprocess, Celery, and LocalStorage imports in domain-layer
  files.
- Add an AST provider-direct-call scan. Permit SDK imports and Responses API
  calls only in provider-control / production-execution adapters and explicit
  composition roots; tests and fixtures are outside production roots.
- Add cross-domain concrete Repository rules for Planning→StoryState,
  Context→Planning, Quality→Chapter, and Book Coordinator→domain repositories.
- Expand production roots to routers, provider control/qualification,
  composition roots, storage repositories, worker dispatch, outbox publisher,
  and reconciliation.
- Enrich production entry manifest rows with definition factory and dispatch
  semantics. Dynamically compare manifest classification, definition
  `execution_mode`, policy classification, and static Attempt/Lease usage.
- Fail a transaction command that imports attempt runtime, a worker operation
  whose API calls its handler inline, or an external effect path that lacks the
  Receipt/external-effect boundary.
- Add focused architecture tests, then run the full architecture suite.
- Commit as `refactor: harden architecture fitness boundaries`.

## Commit 3 — Migration 0052 scope and schema integrity

- Mark 0052 `FORWARD_ONLY`; provide executable preflight queries and a
  documented forward-fix procedure. Do not add a fake downgrade.
- Backfill all pre-0051 asset rows to explicit `legacy-unversioned.v1`, validate
  the format/not-null invariant, then drop the default.
- Make `AuthorityAssetWriteCommand.schema_version` required and update every
  production call site to supply a domain schema version. Legacy import paths
  use the explicit legacy version.
- Add reusable composite uniqueness for Project/Workspace, Book scope, and
  AssetVersion→Project identity where safe.
- Add deferrable constraint triggers for Book, BookDesign candidate,
  dependency, decision, activation, supersession, evidence, story plan binding,
  active plan, and dependency edge scope checks.
- Add Project and Book foreign keys to planning tables after a preflight that
  rejects unresolvable legacy rows. Do not delete or silently rewrite data.
- Test clean install, 0051→0052 upgrade, explicit schema omission, cross-project,
  cross-workspace, cross-book, transaction rollback, and preflight failures.
- Add backup/PITR and restore rehearsal prerequisites to operations docs.
- Commit as `fix: enforce asset schema and scope integrity`.

## Commit 4 — D0 Authority-integrated qualification

### Contracts and persistence

- Extend D0 gate names with restart recovery and retain fixture-vs-real evidence
  separation.
- Add migration 0053 for qualification run/scenario projections, route snapshot,
  versioned provider price, late-result evidence, and query indexes.
- Register `d0.provider_qualification` as a durable job. API/CLI admission returns
  READY; the integration worker owns Attempt/Lease execution.
- Persist each A-F scenario, ExternalEffect identity, provider request ID,
  receipt, raw/normalized usage, price version, calculated cost, capability,
  timeout, SDK retry, and reconciliation state.
- Store request and response bodies through the configured Object Store and keep
  only content hashes/object refs in PostgreSQL.
- Materialize the final typed D0 report as a PostgreSQL AssetVersion and expose a
  read-only query projection. Compute gates from persisted evidence only.

### Scenario execution

- D0-A: authenticated background/basic request and receipt/usage/object evidence.
- D0-B: background create, persisted response ID, retrieve to terminal after a
  fresh worker instance.
- D0-C: cancel or already-completed receipt with replay-safe identity.
- D0-D: controlled before-send timeout→retryable and after-send timeout→UNKNOWN;
  UNKNOWN can only query/reconcile, never blind resend.
- D0-E: terminal-decision preservation plus explicit late-result evidence and
  intervention/policy disposition.
- D0-F: restart with existing ExternalEffect/response ID, query without creating
  another provider request, and terminal receipt commit.
- Configure OpenAI SDK with `max_retries=0`, explicit timeout, background mode,
  and secret reference resolution only at the composition root.
- Add optional `provider-openai` dependency with a tested bounded SDK range.
- Add a versioned price table; never interpret provider `0/not_provided` as cost
  proof.

### Verification and blocked semantics

- Run contract/unit, PostgreSQL, Object Store, duplicate receipt, UNKNOWN/late
  result, and worker restart tests with a scripted adapter.
- If credentials/model are absent, run no network request, persist a
  `BLOCKED_MISSING_CREDENTIALS` qualification decision, and keep all real gates
  false.
- If credentials exist, run A-F individually and report every real scenario.
- Commit as `feat: persist D0 provider qualification through authority runtime`.

## Commit 5 — Admin production advisory repair

- Capture `npm audit --omit=dev` dependency paths.
- Apply the smallest compatible Next/PostCSS/Sharp updates or scoped overrides;
  never use `npm audit fix --force`.
- Add Playwright as a development dependency and a deterministic local smoke
  test that starts the production server on a test port and checks an existing
  health/landing route.
- Run unit tests, TypeScript, production build, production audit, and Playwright.
- Commit package and lockfile changes as
  `fix: resolve admin production dependency advisories`.

## Commit 6 — Track C convergence and formal plan commit

- Audit BookDesign, StoryDesign, Content Authority, hierarchical planning,
  Book Authority, plan binding/active plan, horizon, and cursor call paths.
- Create ADR 0002: BookDesign is the sole active whole-book design root;
  StoryDesign retains generator/candidate/validation/repair/qualification/
  approval lifecycle; Content Authority is a deterministic content handler,
  not a workflow engine.
- Retain the existing option-two Arc semantics: Book→Volume→ChapterGroup→Chapter
  containment; Arc is an orthogonal narrative track connected by dependency or
  contribution edges.
- Replace `bind_active_contract()` reuse of an old StoryDesign Operation ID with
  a dedicated expected-version Plan Binding transaction command, decision,
  audit, and outbox. Reuse existing planning tables/module; create no new Plan
  Authority.
- Add scope and independent-operation tests for formal binding/activation.
- Commit code separately if needed, then documentation as
  `docs: publish Track B.5 and Track C convergence evidence`.

## Final validation and gate decision

- Run compile/import/CLI, architecture, unit, acceptance, PostgreSQL Authority,
  integration, Admin test/type/build/audit/Playwright, Docker config/build, and
  all manifest checks on one final SHA.
- Record command/result/pass/fail/error/skip/environment/SHA without carrying
  evidence across SHAs.
- Update the required current-state, engineering-state, architecture closure,
  roadmap, and regression-test documents plus the three requested reports.
- Distinguish persistent-state restart, in-flight command recovery, and atomic
  transaction-command evidence.
- Do not start C1 when real-provider credentials or any other gate remains false.

