# Canon Graph / Permission Center / Agent Center v2 Report

## Scope

This pass deepens three Novel OS governance surfaces without replacing the existing local-first runtime:

- Canon Graph v1 governance: graph diff, conflict propagation, canon change approval, impacted chapter location.
- Permission Center: agent/tool/source/publish/bypass policy evaluation, human approval gate, audit-bound decisions.
- Agent Center v2: multi-agent DAG asset, full operation coverage, provider hard-stop dashboard, rollback rehearsal, dead-letter repair.

## Canon Graph v1

Implemented in `src/novel_forge/modules/canon_graph/service.py`.

New APIs:

- `POST /product/canon-graph/diff`
- `POST /product/canon-graph/propagate-conflicts`
- `POST /product/canon-graph/impact-chapters`
- `POST /product/canon-graph/approvals`
- `POST /product/canon-graph/approvals/{approval_id}/resolve`

Assets:

- `canon_graph_diff_report`
- `canon_conflict_propagation_report`
- `canon_change_approval`
- existing strict `canon_patch` on approval resolution

Design notes:

- Diff uses semantic node keys, not volatile source asset ids.
- Impact location scans chapter plans, drafts, review reports, publish gates, release packages, and longform recap reports without exposing raw source text.
- Approval is fail-closed: proposed canon changes remain `pending` until resolved by a human actor.
- Approval and resolution write audit events with a non-empty `trace_id`.

## Permission Center

Implemented in `src/novel_forge/modules/permission_center/` and `src/novel_forge/api/routers/permission_center.py`.

New APIs:

- `GET /product/permission-center/snapshot`
- `GET /product/permission-center/policies`
- `POST /product/permission-center/policies`
- `POST /product/permission-center/evaluate`
- `POST /product/permission-center/human-gates`
- `POST /product/permission-center/human-gates/{gate_id}/resolve`

Assets:

- `permission_policy`
- `permission_decision`
- `human_approval_gate`
- `audit_log`

Policy coverage:

- `agent`
- `tool`
- `source`
- `publish`
- `bypass`

Production behavior:

- Production and bypass requests fail closed when no active policy matches.
- Policies can require human approval.
- Approved human gates unlock matching future evaluations.
- Every policy creation, gate creation/resolution, and permission evaluation writes audit evidence.

## Agent Center v2

Implemented in `src/novel_forge/modules/agent_scheduler/service.py` and existing Agent Dispatch UI.

New APIs:

- `GET /product/agents/operation-coverage`
- `GET /product/agents/hard-stop-dashboard`
- `POST /product/agents/dag`
- `POST /product/agents/rollback-rehearsal`
- `POST /product/agents/dead-letter-repair`

Assets:

- `agent_dag`
- `agent_rollback_rehearsal`
- `agent_dead_letter_repair`

UI:

- `/agent-dispatch` now includes Agent Center v2 control, hard-stop summary, full operation coverage, rollback rehearsal, and dead-letter repair controls.
- `/permission-center` exposes policy, human gate, and decision state.

## Tests

Added:

- `tests/unit/test_canon_graph_v1_governance.py`
- `tests/unit/test_permission_center.py`
- `tests/unit/test_agent_center_v2.py`

Validated:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_canon_graph_v1_governance tests.unit.test_permission_center tests.unit.test_agent_center_v2
```

## Remaining Risk

- Canon graph semantic reasoning is deterministic and graph-based; full semantic inference still needs opt-in model judge or richer event extraction.
- Permission Center is local-first policy/governance, not SaaS RBAC or organization permissions.
- Agent DAG execution still reuses existing scheduler and queue; this pass adds DAG assets and coverage visibility, not a second scheduler.
