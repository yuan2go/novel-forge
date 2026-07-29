# Scoped Conversational Agent Architecture V1 Implementation Plan

> **For agentic workers:** Execute inline with the repository TDD discipline.
> Each task uses the existing public seams and preserves PostgreSQL Authority.

**Goal:** Build a recoverable, Authority-led, scope-frozen Agent collaboration
Saga whose every Agent turn uses the existing Production Execution Plane and
whose accepted result is committed as a versioned PostgreSQL Authority asset.

**Architecture:** Add a focused `agent_collaboration` domain containing immutable
contracts and deterministic transitions. Persist business state in normalized
PostgreSQL tables that reference the existing Authority Saga, Operation,
Attempt, and AssetVersion identities. Execute a turn only through
`DomainExecutionPort`; PEP remains unaware of novel deliberation semantics.

**Tech Stack:** Python 3.11+ dataclasses and `StrEnum`, psycopg 3, PostgreSQL,
stdlib `unittest`, existing Command Kernel and Production Execution modules.

## Global Constraints

- PostgreSQL Authority is the only production authority.
- Agent output is candidate-only; it cannot claim commit, activation, route, or
  successful Authority completion.
- `Agent Role != Model != Runtime`.
- No parallel Attempt, lease, fence, budget, receipt, or execution state machine.
- Every controlled Agent turn uses `DomainExecutionPort`.
- Scripted results remain `fixture_protocol_only=true`,
  `real_model_call=false`, and `production_verified=false`.
- Blocking conflicts and scope violations fail closed.

---

### Task 1: Immutable Domain Contracts And Scope

**Files:**

- Create: `src/novel_forge/modules/agent_collaboration/domain.py`
- Create: `src/novel_forge/modules/agent_collaboration/__init__.py`
- Test: `tests/unit/test_agent_collaboration_scope.py`
- Test: `tests/unit/test_agent_collaboration_domain.py`

**Interfaces:**

- Produce versioned `AgentDefinition`, `AgentCapability`,
  `AgentScopeContract`, `ScopeSnapshot`, `ParticipantSnapshot`,
  `AgentWorkOrder`, `AgentOutputEnvelope`, `AgentConversationMessage`,
  `AgentCollaborationSession`, `CandidateVersion`, `ConflictRecord`,
  `ScopeExpansionRequest`, `CollaborationDecision`, and `TerminationPolicy`.
- Produce `ScopePolicy.validate_output(snapshot, envelope)` and
  `CollaborationStateMachine.transition(session, target)`.

- [ ] Write failing public-interface tests for legal/illegal narrative scope,
  containment, read/proposal/authority/temporal/knowledge restrictions, and
  stable snapshot hash.
- [ ] Run:
  `.venv/bin/python -m unittest tests.unit.test_agent_collaboration_scope -v`
  and confirm missing-module failures.
- [ ] Implement frozen value objects, controlled enums, canonical hashes, and
  deterministic scope validation.
- [ ] Run scope tests and confirm all pass.
- [ ] Add failing tests for message targets, envelope validation, deterministic
  session transitions, termination limits, and immutable candidate lineage.
- [ ] Implement the minimum contracts and transition policy to pass.
- [ ] Run both domain test modules.

### Task 2: PostgreSQL Schema And Repository

**Files:**

- Create:
  `src/novel_forge/storage/migrations/versions/v20260728_0033_agent_collaboration_v1.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Create: `src/novel_forge/storage/agent_collaboration_repositories.py`
- Modify: `src/novel_forge/storage/authority_repositories.py`
- Test: `tests/unit/test_agent_collaboration_migration.py`
- Test: `tests/integration/test_agent_collaboration_postgres.py`

**Interfaces:**

- Produce `AgentCollaborationRepository` query/command methods for definitions,
  capabilities, snapshots, sessions, turns, work orders, envelopes, messages,
  candidates/parents, conflicts, expansion requests, decisions, commits, and
  recovery.
- Repository methods accept an existing cursor so Authority UoW owns commit.

- [ ] Write failing migration-shape tests for tables, foreign keys, checks,
  idempotency uniqueness, immutable candidate ancestry, and query indexes.
- [ ] Implement migration 0033 and register it in the chain.
- [ ] Run migration unit tests and the existing migration-chain unit tests.
- [ ] Write PostgreSQL tests for immutable snapshots/candidates, duplicate
  callback/output replay, concurrent turn uniqueness, stale fence rejection by
  PEP, decision replay, and queryable recovery.
- [ ] Implement focused repository methods with `ON CONFLICT` replay checks and
  row locks for session advancement.
- [ ] Run the PostgreSQL collaboration integration module.

### Task 3: Deterministic Application Service

**Files:**

- Create: `src/novel_forge/modules/agent_collaboration/application.py`
- Test: `tests/unit/test_agent_collaboration_application.py`
- Test: `tests/unit/test_agent_collaboration_candidate_graph.py`

**Interfaces:**

- Produce service methods:
  `create_collaboration_session`, `freeze_scope`, `assign_participants`,
  `submit_initial_proposal`, `schedule_next_turn`, `accept_agent_output`,
  `raise_challenge`, `create_candidate_revision`, `record_conflict`,
  `request_scope_expansion`, `evaluate_termination`,
  `request_authority_decision`, `apply_authority_decision`,
  `commit_accepted_candidate`, `recover_collaboration_session`, and
  `cancel_collaboration_session`.
- `schedule_next_turn` receives an existing Authority operation/attempt/fence
  binding and creates an `AgentWorkOrder`; it does not create an Attempt.
- `execute_turn` accepts only a `DomainExecutionPort`.

- [ ] Write a failing proposal→challenge→revision→evaluation state test through
  the public service.
- [ ] Implement deterministic state advancement and typed message persistence.
- [ ] Write failing graph tests for parent/merge ancestry, diffs, conflict links,
  idempotent output replay, and final source tracing.
- [ ] Implement append-only candidate graph behavior.
- [ ] Write failing termination tests for budget, turn/execution/round limits,
  required roles, blocking conflicts, human decisions, and escalation.
- [ ] Implement fail-closed Authority-led termination evaluation.
- [ ] Run application and graph tests.

### Task 4: PEP Semantic Closure

**Files:**

- Modify: `src/novel_forge/modules/agent_collaboration/application.py`
- Test: `tests/unit/test_agent_collaboration_pep.py`
- Test: `tests/integration/test_agent_collaboration_pep_postgres.py`
- Modify: `tests/architecture/test_repository_execution_boundaries.py`

**Interfaces:**

- `execute_turn(work_order, execution_port)` calls
  `execute_domain_candidate(capability="agent.workspace.execute", ...)`.
- Return a `TurnProcessingResult` with explicit backend, output, schema, scope,
  domain, message, candidate, decision, commit, and Attempt-completion layers.

- [ ] Write a failing test that a turn reaches a real
  `ProductionExecutionGateway` scripted backend and freezes RouteSnapshot.
- [ ] Implement the PEP-only call and evidence binding.
- [ ] Add tests for duplicate callback/output, repair-required malformed output,
  backend success/domain reject, post-domain/pre-commit recovery, post-commit
  replay, and stale fence.
- [ ] Add an architecture guard forbidding Provider/CLI/subprocess/HTTP imports
  from `agent_collaboration`.
- [ ] Run focused PEP, architecture, and PostgreSQL tests.

### Task 5: Book-Design Collaboration Fixture

**Files:**

- Create: `src/novel_forge/modules/agent_collaboration/fixtures.py`
- Test: `tests/integration/test_agent_collaboration_vertical_slice.py`

**Interfaces:**

- Produce `run_core_advantage_collaboration_fixture(...)`.
- Use Character Design Agent, Plot Architecture Agent, Reader Outcome Judge,
  and a minimal Book Design Authority stub.
- Use the actual work-order, PEP scripted backend, envelope validation,
  PostgreSQL repository, state machine, decision, and Authority AssetVersion
  commit paths.

- [ ] Write the failing happy-path vertical test:
  Proposal→Challenge→Revision→Evaluation→Decision→Commit.
- [ ] Implement fixture payloads without bypass branches.
- [ ] Assert v1→v2 lineage, structured Challenge, ConflictRecord, final source
  lineage, and fixture-only execution evidence.
- [ ] Write the failing ending-change test and implement scope violation /
  expansion-request behavior without changing the main candidate.
- [ ] Restart the application/repository between turns and assert recovery from
  PostgreSQL only.

### Task 6: Documentation And Acceptance

**Files:**

- Create:
  `docs/architecture/scoped-conversational-agent-architecture.md`
- Modify: `docs/architecture/production-execution-plane.md`
- Modify: `docs/project-current-state.md`
- Create: `docs/reports/agent-architecture-v1-implementation-report.md`

- [ ] Document Agent/Authority/Runtime/PEP boundaries, six-dimensional scope,
  session state, message protocol, candidate graph, conflicts, scope expansion,
  deliberation, recovery, idempotency, and future Book Design Authority.
- [ ] Record exact evidence levels:
  `architecture_defined`, `fixture_proven`, `integration_proven`,
  `real_runtime_proven`, and `production_verified`.
- [ ] Run focused unit and PostgreSQL suites.
- [ ] Run `make lint`, `make validate`, `make postgres-authority-test`, full
  Python discovery, and Web tests; record exact counts, skips, failures, and
  environment limitations without weakening tests.
- [ ] Run `git diff --check`, inspect the final diff, and verify all requested
  truth flags remain conservative.
