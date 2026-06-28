import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";

export type EditorArtifactRow = FeatureAssetRow & {
  target_draft_path?: string;
  operations?: Array<Record<string, unknown>>;
  summary?: Record<string, unknown>;
};

export type DraftEditorState = {
  path: string;
  id: string;
  title: string;
  chapter?: number | string;
  text: string;
  version_index?: number;
  root_draft_id?: string;
  status?: string;
  updated_at?: string;
};

export function loadEditorData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<EditorArtifactRow[]>(projectId ? `/product/editor/artifacts?project_id=${encodeURIComponent(projectId)}&limit=160` : "/product/editor/artifacts?limit=160"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=160` : "/assets?limit=120&rank=path")
  ]);
}

export function createEditorPatch(draftPath: string, instructions: string, workspacePath?: string) {
  return postJson("/product/editor/patch", {
    draft_path: draftPath,
    instructions,
    operations: [],
    workspace_path: workspacePath || null
  });
}

export function applyEditorPatch(patchPath: string, operationIds: string[] = []) {
  return postJson("/product/editor/apply", {
    patch_path: patchPath,
    apply: true,
    change_summary: operationIds.length ? "selected editor patch operations applied from editor workbench" : "applied from editor workbench",
    operation_ids: operationIds
  });
}

export function createDraftDiffReport(basePath: string, targetPath: string) {
  return postJson("/product/editor/diff-report", { base_path: basePath, target_path: targetPath });
}

export function loadDraftEditor(path: string) {
  return fetchJson<DraftEditorState>(`/product/drafts/editor?path=${encodeURIComponent(path)}`);
}
