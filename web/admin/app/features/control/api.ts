import { fetchJson, postJson } from "../../shared/api";
import type { AgentRunRow, BatchItem, DeadLetter, HandoffRow, NodeRunRow, ProjectHealthReport, ProjectRow, TaskCenter, TaskControl, WorkflowDefinitionRow, WorkflowRunRow } from "../../shared/types";

export function loadProductionControlData(projectId?: string) {
  const projectQuery = projectId ? `project_id=${encodeURIComponent(projectId)}&` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<TaskCenter>(`/product/tasks?${projectQuery}limit=120`),
    fetchJson<TaskControl>("/product/tasks/control"),
    fetchJson<DeadLetter[]>("/product/tasks/dead-letters?limit=80"),
    fetchJson<BatchItem[]>(`/product/batch/items?${projectQuery}limit=120`),
    fetchJson<HandoffRow[]>(`/product/handoffs?${projectQuery}limit=120`),
    fetchJson<NodeRunRow[]>(`/product/workflow/node-runs?${projectQuery}limit=120`),
    fetchJson<WorkflowDefinitionRow[]>("/product/workflow/definitions?limit=120"),
    fetchJson<WorkflowRunRow[]>(`/product/workflow/runs?${projectQuery}limit=120`),
    fetchJson<AgentRunRow[]>(`/product/agents/runs?${projectQuery}limit=120`),
    fetchJson<ProjectHealthReport>(projectId ? `/product/system/health?project_id=${encodeURIComponent(projectId)}` : "/product/system/health")
  ]);
}

export function runAgentBoundaryAudit(applyRuntimeGuard = true) {
  return postJson(`/product/agents/boundary-audit?apply_runtime_guard=${applyRuntimeGuard ? "true" : "false"}`, {}) as Promise<{ path: string; asset: { content?: Record<string, unknown> } }>;
}

export function runWorkflowSchedulerTick(projectId?: string) {
  return postJson("/product/workflow/scheduler/tick", {
    project_id: projectId || null,
    limit: 20,
    max_nodes_per_resume: 5,
    dry_run: false,
    async_task: false,
    iterations: 1,
    interval_seconds: 0,
    apply_invalidation: true,
    stop_when_idle: true,
    lease_ttl_seconds: 300
  }) as Promise<Record<string, unknown>>;
}

export function enqueueWorkflowSchedulerLoop(projectId?: string) {
  return postJson("/product/workflow/scheduler/tick", {
    project_id: projectId || null,
    limit: 20,
    max_nodes_per_resume: 5,
    dry_run: false,
    async_task: true,
    iterations: 5,
    interval_seconds: 5,
    apply_invalidation: true,
    stop_when_idle: true,
    lease_ttl_seconds: 300
  }) as Promise<Record<string, unknown>>;
}

export function executeWorkflow(payload: {
  workflow_path_or_id: string;
  input_assets?: string[];
  max_nodes?: number;
  execute_agents?: boolean;
  workspace_path?: string;
}) {
  return postJson("/product/workflow/execute", {
    workflow_path_or_id: payload.workflow_path_or_id,
    input_assets: payload.input_assets || [],
    max_nodes: payload.max_nodes || null,
    dispatch_agents: true,
    execute_agents: Boolean(payload.execute_agents),
    apply_invalidation: true,
    workspace_path: payload.workspace_path || null
  }) as Promise<Record<string, unknown>>;
}

export function resumeWorkflow(payload: {
  workflow_run_path_or_id: string;
  resume_node_id?: string;
  output_assets?: string[];
  token_used?: number;
  cost_estimate?: number;
}) {
  return postJson("/product/workflow/resume", {
    workflow_run_path_or_id: payload.workflow_run_path_or_id,
    resume_node_id: payload.resume_node_id || null,
    output_assets: payload.output_assets || [],
    token_used: payload.token_used || 0,
    cost_estimate: payload.cost_estimate || 0,
    checkpoint: { status: "ui_resume", source: "workflow_console" },
    evidence: { resumed_by: "workflow_console" },
    max_nodes: 5,
    apply_invalidation: true,
    archive_previous: true
  }) as Promise<Record<string, unknown>>;
}
