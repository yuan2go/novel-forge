# Scoped Conversational Agent Architecture V1 — Code Fact Audit

Date: 2026-07-28

## Scope And Baseline

- Branch: `feat/v7-content-intelligence-and-longform-proof`
- Initial HEAD: `8613f743ca039f4ed13513e7eee51478df10487a`
- Pull result: already up to date with
  `origin/feat/v7-content-intelligence-and-longform-proof`
- Initial worktree: clean
- Initial full test command: `make test`
- Initial full-test result: Python stopped the Make target after 1108 tests:
  2 failures, 32 PostgreSQL connection errors caused by the restricted sandbox,
  9 skipped. The Web suite was not reached by the Make target.
- Initial non-skippable PostgreSQL Authority baseline:
  `make postgres-authority-test` passed 105/105 tests in 44.393 seconds.
- Pre-existing non-PostgreSQL failures:
  `test_model_effect_profile_versions_and_requires_each_model_capability`
  expects `model.review` in a definition that currently contains only
  `model.rereview`; `test_tool_gateway_invokes_remote_mcp_http_jsonrpc_tools`
  observed a restricted-network failure instead of the fixture HTTP success.

## Evidence Index

| Area | Code fact | Evidence |
|---|---|---|
| Agent role/runtime profile | Agent roles and permissions are mutable dictionary constants, not versioned production definitions. | `src/novel_forge/agents/runtime.py`: `AGENT_RUNTIME_PROFILES`, `agent_runtime_profile`, `enforce_agent_action` |
| Local Agent contract | `ensure_agent_contract` creates a local JSON `agent_contract` asset with a 0.1.0 contract version. | `src/novel_forge/modules/agent_runs/service.py`: `ensure_agent_contract`; `src/novel_forge/schemas/assets.py`: `AgentContract` |
| Agent capability asset | An `AgentCapability` asset class exists but has no collaboration-domain semantics or PostgreSQL authority table. | `src/novel_forge/schemas/assets.py`: `AgentCapability` |
| Agent Workspace | Workspace execution has a frozen read/write/tool/command/network/Git/cost contract and a qualified backend. | `src/novel_forge/modules/production_execution/agent_workspace_backend.py`: `AgentWorkspaceExecutionContract`, `AgentWorkspaceExecutionBackend` |
| Candidate-only output | Agent Workspace output forbids commit/activation/route claims and enforces `proposed_only`. | `src/novel_forge/modules/production_execution/agent_execution.py`: `AgentWorkspaceResultCandidate`; `agent_workspace_backend.py`: `_validate_candidate` |
| Existing messages | A local-file message bus stores free-form payloads, inbox/outbox assets, and a replayed trace. It is not a business Saga and is not PostgreSQL authority. | `src/novel_forge/modules/agent_messages/service.py`: `send_agent_message`, `acknowledge_agent_message`, `replay_agent_messages`, `create_agent_conversation_trace` |
| Existing scope | PEP has a transport-facing `TargetScope`, but no frozen narrative/read/proposal/authority/temporal/knowledge collaboration contract. | `src/novel_forge/modules/production_execution/contracts.py`: `TargetScope` |
| Domain execution seam | Business code sends a `DomainExecutionCommand` through `DomainExecutionPort`; controlled environments reject the legacy direct-adapter path. | `src/novel_forge/modules/production_execution/domain_execution.py`: `DomainExecutionPort`, `GatewayDomainExecutionPort`, `execute_domain_candidate` |
| PEP connection | `GatewayDomainExecutionPort` submits an existing Authority-bound `ExecutionRequest` to `ProductionExecutionGateway`, reconciles it, and returns only a candidate plus evidence. | `src/novel_forge/modules/production_execution/domain_execution.py`: `GatewayDomainExecutionPort.execute`; `src/novel_forge/modules/production_execution/gateway.py`: `ProductionExecutionGateway` |
| Attempt/fence authority | PEP verifies, but does not own, the existing Authority Attempt and fence. | `src/novel_forge/modules/production_execution/gateway.py`: `AttemptFenceVerifier`, `AdmissionController`; `src/novel_forge/modules/production_execution/postgres.py`: `PostgresAttemptFenceVerifier` |
| Saga authority | The existing PostgreSQL `authority_saga` and `authority_saga_step` tables bind the root and child Authority Operations; coordinator leases have fencing. | migration `v20260713_0018_operation_graph_completion`; migration `v20260716_0021_saga_coordination`; `storage/operation_graph_repositories.py`: `OperationGraphRepository` |
| Operation/Attempt authority | PostgreSQL `authority_operation`, `authority_attempt`, and `authority_lease_acquisition` are the execution state authority. | migration `v20260712_0007_postgres_command_kernel_authority`; `modules/command_kernel/attempt_runtime.py` |
| Asset authority | Formal output uses versioned `authority_asset` / `authority_asset_version`; active versions are unique and command handlers own activation. | migration `v20260712_0007_postgres_command_kernel_authority`; `modules/command_kernel/asset_runtime.py` |
| Architecture boundary tests | Repository guards reject business-domain imports in PEP, direct controlled provider/model execution, backend asset commit, and a parallel execution-attempt authority. | `tests/architecture/test_repository_execution_boundaries.py`; `tests/architecture/test_production_execution_gateway_boundaries.py` |

## Required Questions

### 1. Agent Definition, Runtime, And Workspace

`AGENT_RUNTIME_PROFILES` is the current role/permission catalog. A per-project
local `agent_contract` is synthesized by `ensure_agent_contract`. The actual
bounded workspace runtime is `AgentWorkspaceExecutionContract` plus
`AgentWorkspaceExecutionBackend`. These three concepts are currently adjacent
but not a versioned `AgentDefinition` aggregate. The implementation must add a
PostgreSQL-backed definition/capability contract while preserving runtime
routing as a separate PEP concern.

### 2. Candidate Or `proposed_only`

The PEP Agent Workspace slice is candidate-only. Both
`AgentWorkspaceResultCandidate.__post_init__` and
`AgentWorkspaceExecutionBackend._validate_candidate` reject commit, activation,
provider, model, backend, route, and reasoning claims. Workspace manifests must
set `proposed_only=true`. This is reusable and must remain intact.

Local Agent role profiles still list direct business asset write types. Those
profiles are operator/runtime compatibility policy, not proof that every legacy
local workflow is candidate-only. Collaboration V1 must therefore accept only
an `AgentOutputEnvelope` and never invoke those local write helpers.

### 3. Session, Message, Conversation, Or Collaboration

There is a local `agent_messages` feature with `conversation_id`, free-form
payload, inbox/outbox, acknowledge, replay, and trace assets. There is no
frozen participant/scope session, typed deliberation protocol, candidate graph,
conflict record, scope expansion, Authority decision, or collaboration Saga.
The local feature is a compatibility message projection, not production
collaboration authority.

### 4. Existing Scope

PEP `TargetScope` freezes transport routing identity such as book, volume, arc,
chapter group, chapter, and asset version IDs. Agent Workspace freezes
filesystem read/write boundaries. There is no single domain contract covering
Narrative, Asset Read, Proposal, Authority, Temporal, and Knowledge Visibility
scope. A collaboration-specific immutable `ScopeSnapshot` is missing.

### 5. DomainExecutionPort To ProductionExecutionGateway

`execute_domain_candidate` builds a governed `DomainExecutionCommand`.
`GatewayDomainExecutionPort.execute` selects a pre-frozen `ExecutionRequest` by
capability, calls `gateway.submit`, then `gateway.reconcile`, requires normalized
output/validation/usage/cost evidence, and returns `DomainExecutionCandidate`.
It does not materialize domain assets.

### 6. Does Every Agent Execution Pass PEP?

The production Agent Workspace capability does. Controlled environments fail
closed when `execute_domain_candidate` lacks a `GatewayDomainExecutionPort`.
The repository architecture tests also block direct model/provider paths.
Legacy local `agent_runs` and `agent_messages` are not themselves model
execution and are not a production Collaboration Saga. Collaboration V1 must
use the existing port and must not call Provider SDK, CLI, subprocess, HTTP, or
Agent Workspace runners directly.

### 7. Direct Formal-Asset Writes

PEP backends do not activate or commit assets; architecture tests enforce that.
Legacy local role profiles and local workflow services can write local JSON
assets, so they cannot be treated as production authority. Formal collaboration
commit must use the existing PostgreSQL Authority AssetVersion path, with a
Collaboration Decision and blocking-conflict check.

### 8. In-Memory Conversation State

`agent_messages` reconstructs from local files rather than only memory, but it
is still outside PostgreSQL production authority. PEP composition contains
in-memory test stores and a Chapter gateway session cache; those are runtime
composition aids and not formal business state. Collaboration recovery must
load session, turn, messages, candidates, conflicts, decisions, and work-order
bindings from PostgreSQL.

### 9. Reusing Saga, Operation, And Attempt

Use one `authority_saga` for a Collaboration Session root. Each Agent turn is a
child `authority_operation`/`authority_attempt` and a registered saga step.
PEP receives that Attempt and fence through `ExecutionRequest`. Collaboration
tables reference those identities but do not create a second attempt table or
second execution state machine. Session state remains a separate deterministic
business aggregate state.

### 10. Reuse, Correction, And Migration

Reuse:

- Authority Operation/Saga/Attempt/Lease/Fence and command-kernel idempotency;
- Authority AssetVersion and immutable activation path;
- `DomainExecutionPort`, `GatewayDomainExecutionPort`, RouteSnapshot and PEP
  evidence contracts;
- candidate-only Agent Workspace validation;
- scripted fixture backend, clearly marked fixture-only.

Correct:

- replace scattered role constants as the collaboration source of truth with
  versioned AgentDefinition and AgentCapability rows;
- add a real six-dimensional `ScopeSnapshot`;
- separate transport success, schema/scope validation, domain acceptance,
  message acceptance, candidate creation, Authority decision, commit, and
  Attempt completion.

Migrate:

- keep `agent_messages` as compatibility/operator messaging, but forbid it as
  the persistence implementation of `AgentCollaborationSession`;
- new collaboration callers use the PostgreSQL application service and typed
  message protocol;
- no destructive migration of old local messages is part of V1.

## Design Decision

Three approaches were evaluated:

1. Extend the local Agent message bus. Rejected because it would make local
   files a second production authority and still lack frozen scope/participants.
2. Put deliberation state into PEP. Rejected because it would teach the generic
   execution plane novel-business semantics.
3. Add a PostgreSQL Agent Collaboration domain over existing
   Operation/Saga/Attempt and call PEP only through `DomainExecutionPort`.
   Selected because it preserves all required authority and runtime boundaries.

## Audit Judgment

| Requirement | Judgment | Reason |
|---|---|---|
| Candidate-only Agent runtime | MATCH | Existing PEP Agent Workspace guards are strong. |
| Unified production execution | MATCH for governed execution, PARTIAL for legacy local features | Controlled model execution is PEP-only; local messages are not collaboration execution. |
| Versioned AgentDefinition/Capability | PARTIAL | Local asset/classes exist but required versioned PostgreSQL contracts do not. |
| Frozen collaboration scope | MISSING | PEP target/workspace scopes are insufficient. |
| Typed collaboration protocol | MISSING | Existing payload is free-form. |
| Candidate graph/conflict/decision | MISSING | No production aggregates exist. |
| Recoverable collaboration Saga | MISSING | Existing Saga infrastructure is reusable but unbound to collaboration. |
| PostgreSQL Authority commit | EXTRA_VALID foundation | Authority AssetVersion commands already provide the correct boundary. |
