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

export function retryTask(row: { path?: string; run_id?: string; step?: string }, workspacePath?: string) {
  return postJson("/product/tasks/retry", {
    status_path: row.path || null,
    run_id: row.run_id || null,
    step: row.step || null,
    workspace_path: workspacePath || null,
    async_task: false
  });
}

export function retryDeadLetter(deadLetterPath: string) {
  return postJson("/product/tasks/dead-letters/retry", { dead_letter_path: deadLetterPath });
}
