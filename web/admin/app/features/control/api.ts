import { fetchJson } from "../../shared/api";
import type { AgentRunRow, BatchItem, DeadLetter, HandoffRow, NodeRunRow, ProjectHealthReport, ProjectRow, TaskCenter, TaskControl } from "../../shared/types";

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
    fetchJson<AgentRunRow[]>(`/product/agents/runs?${projectQuery}limit=120`),
    fetchJson<ProjectHealthReport>(projectId ? `/product/system/health?project_id=${encodeURIComponent(projectId)}` : "/product/system/health")
  ]);
}
