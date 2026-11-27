import { fetchJson } from "../../shared/api";
import type { Health, ProjectHealthReport, ProjectOperatingDashboard, ProjectRow, TaskCenter } from "../../shared/types";

export function loadDashboardData() {
  return Promise.all([
    fetchJson<Health>("/health"),
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ProjectOperatingDashboard>("/product/projects/operating-dashboard?limit=12"),
    fetchJson<TaskCenter>("/product/tasks?limit=80"),
    fetchJson<ProjectHealthReport>("/product/system/health")
  ]);
}
