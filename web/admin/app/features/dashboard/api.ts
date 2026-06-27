import { fetchJson } from "../../shared/api";
import type { Health, ProjectHealthReport, ProjectRow, TaskCenter } from "../../shared/types";

export function loadDashboardData() {
  return Promise.all([
    fetchJson<Health>("/health"),
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<TaskCenter>("/product/tasks?limit=80"),
    fetchJson<ProjectHealthReport>("/product/system/health")
  ]);
}
