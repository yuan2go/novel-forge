import { fetchJson, postJson } from "../../shared/api";
import type { AgentEventRow, AgentRunRow, DeadLetter, ProjectRow, TaskCenter, TaskControl } from "../../shared/types";

export type RuntimeTraceTimeline = {
  spans: Array<Record<string, unknown>>;
  summary: Record<string, unknown>;
};

export type RuntimeCostDashboard = {
  path?: string;
  asset?: {
    content?: {
      summary?: Record<string, unknown>;
      snapshots?: Record<string, unknown>;
      recommendations?: string[];
    };
  };
};

export function loadTaskData(options: { projectId?: string; status?: string; taskType?: string; step?: string; offset?: number }) {
  const params = new URLSearchParams({ limit: "120", offset: String(options.offset ?? 0) });
  if (options.projectId) params.set("project_id", options.projectId);
  if (options.status) params.set("status", options.status);
  if (options.taskType) params.set("task_type", options.taskType);
  if (options.step) params.set("step", options.step);
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<TaskCenter>(`/product/tasks?${params.toString()}`),
    fetchJson<TaskControl>("/product/tasks/control"),
    fetchJson<DeadLetter[]>("/product/tasks/dead-letters?limit=80"),
    fetchJson<AgentRunRow[]>(options.projectId ? `/product/agents/runs?project_id=${encodeURIComponent(options.projectId)}&limit=80` : "/product/agents/runs?limit=80"),
    fetchJson<AgentEventRow[]>(options.projectId ? `/product/agents/events?project_id=${encodeURIComponent(options.projectId)}&limit=120` : "/product/agents/events?limit=120"),
    fetchJson<RuntimeTraceTimeline>(options.projectId ? `/product/runtime/trace-timeline?project_id=${encodeURIComponent(options.projectId)}&limit=120` : "/product/runtime/trace-timeline?limit=120"),
    fetchJson<RuntimeCostDashboard>(options.projectId ? `/product/runtime/cost-dashboard?project_id=${encodeURIComponent(options.projectId)}` : "/product/runtime/cost-dashboard")
  ]);
}

export function recoverAuthorityOperation(row: {
  operation_id?: string;
  id?: string;
  project_id?: string;
  version?: number;
}) {
  const operationId = row.operation_id || row.id;
  if (!operationId || !row.project_id || row.version === undefined) {
    throw new Error("Authority recovery requires operation, project, and version");
  }
  return postJson(`/product/tasks/${encodeURIComponent(operationId)}/recover`, {
    project_id: row.project_id,
    expected_version: row.version,
    idempotency_key: `task-recovery:${operationId}:${row.version}`,
    reason: "Task Center operator requested audited recovery"
  });
}

export function requeueAuthorityOutbox(row: DeadLetter) {
  if (!row.task_id || !row.project_id || row.attempt_count === undefined) {
    throw new Error("Outbox recovery requires outbox, project, and attempt count");
  }
  return postJson(`/product/tasks/outbox/${encodeURIComponent(row.task_id)}/requeue`, {
    project_id: row.project_id,
    expected_attempt_count: row.attempt_count,
    idempotency_key: `outbox-recovery:${row.task_id}:${row.attempt_count}`,
    reason: "Task Center operator approved a new outbox generation"
  });
}
