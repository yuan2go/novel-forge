import { fetchJson, postJson } from "../../shared/api";
import type { ProjectHealthReport, ProjectOperatingDashboard, ProjectRow } from "../../shared/types";

export function loadProjectsData() {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ProjectHealthReport>("/product/system/health"),
    fetchJson<ProjectOperatingDashboard>("/product/projects/operating-dashboard?limit=100")
  ]);
}

export function createProject(body: {
  title: string;
  seriesTitle?: string;
  bookNumber?: number;
}) {
  return postJson("/product/projects", {
    title: body.title,
    series_title: body.seriesTitle || null,
    book_number: body.bookNumber || null
  });
}

export function transitionProject(projectId: string, action: "archive" | "pause" | "restore") {
  return postJson(`/product/projects/${encodeURIComponent(projectId)}/${action}`, {});
}

export function duplicateProject(projectId: string, title?: string) {
  return postJson(`/product/projects/${encodeURIComponent(projectId)}/duplicate`, { title: title || null, copy_references: true });
}

export function repairProjectScope(projectId?: string) {
  return postJson("/product/projects/audit/scope", { project_id: projectId || null, repair: true });
}
