import { fetchJson, postJson } from "../../shared/api";
import type { AgentRunRow, MetricSnapshotRow, ProjectHealthReport, ProjectRow, TaskCenter } from "../../shared/types";

export function loadStatisticsData(projectId?: string) {
  const projectQuery = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<MetricSnapshotRow[]>(`/product/metrics/snapshots${projectQuery ? `${projectQuery}&limit=120` : "?limit=120"}`),
    fetchJson<TaskCenter>(`/product/tasks${projectQuery ? `${projectQuery}&limit=80` : "?limit=80"}`),
    fetchJson<AgentRunRow[]>(`/product/agents/runs${projectQuery ? `${projectQuery}&limit=120` : "?limit=120"}`),
    fetchJson<ProjectHealthReport>(projectId ? `/product/system/health?project_id=${encodeURIComponent(projectId)}` : "/product/system/health")
  ]);
}

export function createMetricSnapshot(projectId?: string, workspacePath?: string) {
  return postJson("/product/metrics/snapshot", {
    project_id: projectId || null,
    workspace_path: workspacePath || null
  });
}
