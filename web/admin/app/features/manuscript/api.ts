import { fetchJson, postJson } from "../../shared/api";
import type { DraftEditorState, DraftSaveResult, DraftWorkbench, ExportResult, ManuscriptWorkbench, ProjectOption } from "./types";

export function listProjects() {
  return fetchJson<ProjectOption[]>("/product/projects");
}

export function loadDraftWorkbench(projectId?: string) {
  const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return fetchJson<DraftWorkbench>(`/product/drafts${params}`);
}

export function loadDraftEditor(path: string) {
  return fetchJson<DraftEditorState>(`/product/drafts/editor?path=${encodeURIComponent(path)}`);
}

export function loadManuscriptWorkbench(options: { projectId?: string; draftPath?: string; limit?: number }) {
  const params = new URLSearchParams({ limit: String(options.limit ?? 120) });
  if (options.projectId) params.set("project_id", options.projectId);
  if (options.draftPath) params.set("draft_path", options.draftPath);
  return fetchJson<ManuscriptWorkbench>(`/product/manuscript/workbench?${params.toString()}`);
}

export function saveDraftEdit(body: { draft_path: string; title: string; text: string; workspace_path?: string }) {
  return postJson("/product/drafts/save", {
    draft_path: body.draft_path,
    title: body.title,
    text: body.text,
    status: "edited",
    workspace_path: body.workspace_path || null
  }) as Promise<DraftSaveResult>;
}

export function exportDraft(draftPath: string, format: string) {
  return postJson("/product/drafts/export", { draft_path: draftPath, format }) as Promise<ExportResult>;
}
