# Agent Industrialization Design

This design upgrades Novel Forge Agents from prompt roles into persisted, permission-bound, observable local production entities.

It preserves the AGENTS.md boundary: reference works are used for abstract structural learning, not copying.

## Current Agent Baseline

Current files:

- `AGENTS.md`
- `docs/09-skills/agent-skill-map.md`
- `src/novel_forge/agents/runtime.py`
- `src/novel_forge/modules/agent_runs/service.py`
- `src/novel_forge/modules/handoff/service.py`
- `src/novel_forge/api/routers/agents.py`
- `src/novel_forge/api/services/product.py` handoff validation/binding functions

Current agent classes:

- Chief Editor Agent
- Engineering Agent
- Draft Agent
- Review Agent
- Knowledge Agent
- Material Agent
- Quality Agent

Current runtime support:

- permission profile
- tool allowlist
- allowed write types
- skill-to-agent mapping
- boundary contract text
- `validate_tool_allowed()`
- `validate_write_type_allowed()`
- `enforce_agent_action()`
- handoff output type enforcement during binding
- persisted `agent_contract`
- persisted `agent_run`
- persisted `agent_event`
- persisted `agent_checkpoint`
- persisted `agent_budget`
- persisted `agent_gate`
- persisted `agent_metric`
- persisted `agent_failure_report`
- `/product/agents/runs`
- `/product/agents/events`
- `/product/agents/contracts`
- `/product/agents/runs/status`
- Claude Code/Codex handoff creates `waiting_human` Agent runs and synchronizes success/failure/retry status

Current gap:

- Permission allowlists are not consistently enforced in every worker/model/service boundary.
- Agent rollback policy is not yet implemented as one-click rollback operations.
- SLA/timeout/rate-limit enforcement is not yet uniform across Celery and local execution.
- Agent metrics exist as schema but are not yet aggregated into scorecards or model routing.
- Production Control shows Agent runs, but a deeper Agent Center timeline and gate-detail view is still needed.

## Target Agent Set

V6/V7 should support these Agent types:

```text
chief_editor
planner
knowledge
material
analysis
style
standard
worldbuilding
character
outline
chapter_plan
context_builder
draft
ai_editor
review
originality
publishing
feedback
model_evaluation
quality
engineering
```

Display names:

- Chief Editor Agent
- Planner Agent
- Knowledge Agent
- Material Agent
- Analysis Agent
- Style Agent
- Standard Agent
- Worldbuilding Agent
- Character Agent
- Outline Agent
- Chapter Plan Agent
- Context Builder Agent
- Draft Agent
- AI Editor Agent
- Review Agent
- Originality Agent
- Publishing Agent
- Feedback Agent
- Model Evaluation Agent
- Quality Agent
- Engineering Agent

## Unified State Machine

All Agent runs must use this state machine:

```text
planned
prepared
running
waiting_human
verifying
succeeded
needs_revision
failed
dead_letter
recovered
cancelled
```

Rules:

- `planned` means the contract exists but inputs are not prepared.
- `prepared` means inputs, permission profile, model route, output type, and budget have been checked.
- `running` means a worker, handoff, model adapter, or local service is executing.
- `waiting_human` is required for manual Claude Code/Codex handoff or high-risk gates.
- `verifying` means schema, permission, source boundary, originality, and acceptance checks are running.
- `succeeded` requires validated output assets.
- `needs_revision` means output passed schema but failed quality/human gate.
- `failed` means recoverable error.
- `dead_letter` means retry exhausted or missing preconditions.
- `recovered` means a failed/dead-letter run resumed successfully.
- `cancelled` means human or system cancellation.

## New Asset Types

### `agent_contract`

Purpose: immutable or versioned contract for a class of Agent operation.

Required content fields:

```json
{
  "agent_type": "draft",
  "operation": "generate_chapter",
  "input_types": ["chapter_plan", "context_bundle"],
  "output_types": ["draft_chapter", "generation_run"],
  "required_permissions": {
    "permission_profile": "draft_generation_from_approved_context",
    "allowed_tools": ["read_asset", "call_model_adapter", "write_draft_chapter", "run_validation"],
    "allowed_write_types": ["draft_chapter", "generation_run", "task_status"]
  },
  "validation": {
    "schema_required": true,
    "project_scope_required": true,
    "source_boundary_required": true,
    "human_gate_required": false
  },
  "budget_policy": {
    "max_tokens": 12000,
    "max_cost": 1.5,
    "max_retries": 2,
    "timeout_seconds": 1800
  },
  "rollback_policy": {
    "strategy": "keep_previous_version",
    "revertible_outputs": true
  }
}
```

### `agent_run`

Purpose: runtime instance of an Agent operation.

Required content fields:

```json
{
  "agent_type": "draft",
  "operation": "generate_chapter",
  "status": "running",
  "input_assets": ["data/chapter_plans/...json", "data/contexts/...json"],
  "output_assets": [],
  "contract_id": "agent_contract_draft_generate_chapter",
  "permissions": {},
  "model_provider": "openai-compatible",
  "model_name": "qwen3-32b",
  "prompt_version": "draft-v3",
  "token_budget": 12000,
  "token_used": 0,
  "cost_estimate": 0.0,
  "started_at": "2026-06-26T00:00:00Z",
  "finished_at": "",
  "error": "",
  "checkpoint_id": "",
  "evidence": {
    "context_bundle_id": "",
    "source_asset_ids": [],
    "validation_status": "pending"
  },
  "human_gate": {
    "required": false,
    "status": "not_required"
  },
  "retry_count": 0
}
```

### `agent_checkpoint`

Purpose: resumable state for long work.

Required content fields:

```json
{
  "agent_run_id": "...",
  "step": "context_built",
  "status": "completed",
  "input_snapshot": {},
  "partial_outputs": [],
  "resume_instruction": "resume from generation step",
  "created_at": "..."
}
```

### `agent_event`

Purpose: append-only event log.

Required content fields:

```json
{
  "agent_run_id": "...",
  "event_type": "status_changed",
  "from_status": "running",
  "to_status": "verifying",
  "message": "model output received; running schema validation",
  "severity": "info",
  "created_at": "..."
}
```

### `agent_budget`

Purpose: budget and rate control evidence.

Required content fields:

```json
{
  "agent_run_id": "...",
  "token_budget": 12000,
  "token_used": 8820,
  "cost_limit": 1.5,
  "cost_estimate": 0.82,
  "time_limit_seconds": 1800,
  "elapsed_seconds": 312
}
```

### `agent_gate`

Purpose: human or automated gate.

Required content fields:

```json
{
  "agent_run_id": "...",
  "gate_type": "human|schema|source_boundary|originality|quality",
  "status": "open|passed|failed|waived",
  "criteria": [],
  "decision": "",
  "decision_reason": "",
  "decided_at": ""
}
```

### `agent_metric`

Purpose: evaluation and observability metrics.

Required content fields:

```json
{
  "agent_run_id": "...",
  "quality_score": 86.5,
  "latency_seconds": 12.3,
  "retry_count": 0,
  "validation_error_count": 0,
  "human_gate_latency_seconds": 0,
  "model_failure": false
}
```

### `agent_failure_report`

Purpose: recoverability and dead-letter evidence.

Required content fields:

```json
{
  "agent_run_id": "...",
  "failure_type": "schema_validation|permission_denied|model_error|timeout|source_boundary|quality_gate",
  "error_message": "...",
  "failed_step": "...",
  "recoverable": true,
  "recovery_instruction": "...",
  "dead_letter_path": ""
}
```

## Permission Profiles

Permission profiles remain local runtime boundaries, not SaaS user roles.

Each profile must include:

- `permission_profile`
- `allowed_tools`
- `allowed_read_types`
- `allowed_write_types`
- `allowed_output_dirs`
- `forbidden_tools`
- `requires_human_gate_for`
- `source_policy`

Example:

```json
{
  "agent_type": "analysis",
  "permission_profile": "reference_to_abstract_analysis_only",
  "allowed_tools": [
    "read_asset",
    "read_skill",
    "call_model_adapter",
    "write_analysis_report",
    "write_conversion_report",
    "run_validation"
  ],
  "allowed_read_types": ["source_document", "cleaned_text", "source_policy"],
  "allowed_write_types": [
    "common_novel_analysis_report",
    "web_fiction_business_analysis_report",
    "published_fiction_analysis_report",
    "classic_literary_analysis_report",
    "analysis_conversion_report"
  ],
  "forbidden_tools": ["write_draft_chapter"],
  "requires_human_gate_for": ["high_copyright_risk", "manual_handoff"],
  "source_policy": "abstract_only_no_protected_expression"
}
```

## Tool Control

Tool control must be enforced in these places:

1. Handoff output binding.
2. Worker task execution.
3. Model adapter calls.
4. Asset write operations that identify an Agent run.
5. Analysis-to-asset conversion.
6. Draft/review/revision generation.

Minimum implementation path:

- Keep existing `enforce_agent_action()` as the policy primitive.
- Add `agent_run_id` and `agent_type` to operation metadata.
- Add a shared `AgentExecutionContext`.
- Require any service that writes assets on behalf of an Agent to call `enforce_agent_action()` before writing.

## Observability

All Agent runs should emit events for:

- contract loaded
- inputs resolved
- permission checked
- queue submitted
- model call started
- model call completed
- output parsed
- schema validation started
- schema validation failed/passed
- project scope validation failed/passed
- source boundary check failed/passed
- human gate opened/closed
- output written
- retry scheduled
- dead-lettered
- recovered
- cancelled

Task center should show:

- latest state per Agent run
- full event timeline
- failed/dead-letter runs
- human gates waiting
- run duration and retry count

Production control should aggregate:

- current Agent bottlenecks
- quality gate failures
- model failure rate
- queue pressure
- budget usage

## Human Gates

Human gates are required when:

- source policy is high risk or unclear
- analysis output is derived from protected reference text and will be converted to reusable assets
- originality report is high risk
- publish gate fails any critical dimension
- an Agent attempts to write outside allowed output types
- Claude Code/Codex manual handoff is required

Gate status:

```text
open -> accepted | rejected | waived
```

Rejected gates should move the Agent run to `needs_revision` or `failed`, not silently continue.

## Rollback and Recovery

Every Agent run should have a rollback strategy:

- `no_write`: dry run or report only.
- `keep_previous_version`: write new asset version without deleting prior asset.
- `revert_asset`: restore last backup for a specific asset.
- `supersede_output`: mark output superseded and create replacement.
- `manual_recovery`: require a human recovery instruction.

Recovery flow:

```text
failed/dead_letter
  -> failure_report
  -> recovery_instruction
  -> retry from checkpoint
  -> recovered or dead_letter
```

## API Design

Future router: `src/novel_forge/api/routers/agents.py`

Suggested endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/product/agents/contracts` | List available contracts |
| `POST` | `/product/agents/contracts` | Create/update local contract |
| `GET` | `/product/agents/runs` | List Agent runs with filters |
| `POST` | `/product/agents/runs` | Create Agent run |
| `GET` | `/product/agents/runs/{run_id}` | Get run details |
| `GET` | `/product/agents/runs/{run_id}/events` | Full event timeline |
| `POST` | `/product/agents/runs/{run_id}/retry` | Retry from failure/checkpoint |
| `POST` | `/product/agents/runs/{run_id}/cancel` | Cancel run |
| `GET` | `/product/agents/gates` | List open gates |
| `PATCH` | `/product/agents/gates/{gate_id}` | Accept/reject/waive gate |
| `GET` | `/product/agents/metrics` | Agent metrics by project/type/time |

## UI Design

Agent visibility should appear in:

- Production Control Center: active pipeline Agents and blockers.
- Task Center: latest status plus full timeline.
- Handoff Center: manual Claude Code/Codex runs.
- Model Evaluation Center: Agent quality/cost/failure comparisons.
- Project Health: waiting gates, failed Agents, dead-letter count, SLA breaches.

## Testing Strategy

Unit tests:

- `tests/unit/test_agent_contracts.py`
- `tests/unit/test_agent_run_lifecycle.py`
- `tests/unit/test_agent_permissions.py`
- `tests/unit/test_agent_checkpoints.py`
- `tests/unit/test_agent_gates.py`

Integration tests:

- `tests/integration/test_agent_handoff_lifecycle.py`
- `tests/integration/test_agent_draft_run.py`
- `tests/integration/test_agent_failure_recovery.py`
- `tests/integration/test_agent_permission_denied.py`

Acceptance checks:

- Agent cannot write an output type outside `allowed_write_types`.
- Agent cannot use a tool outside `allowed_tools`.
- Failed schema validation creates `agent_failure_report`.
- Human gate blocks publish or downstream generation.
- Retry resumes from checkpoint when possible.
- Agent output records input assets, output assets, model, prompt version, token budget, and validation status.

## Implementation Order

1. Add schema types and content validation.
2. Add storage directory mapping, likely `data/agents`.
3. Add `AgentExecutionContext` and event writer.
4. Wrap existing handoff binding with `agent_run` creation and event logging.
5. Wrap draft/review/revision service calls.
6. Add task center aggregation.
7. Add Agent Center/Production Control UI panels.
8. Add model evaluation metrics integration.

## Non-Goals

- No SaaS RBAC.
- No user/team permission model.
- No external autonomous tool execution without explicit local configuration.
- No protected-text copying.
- No concrete author imitation.
