import { fetchJson, postJson } from "../../shared/api";
import type { BatchItem, ProjectRow } from "../../shared/types";

export function loadBatchData(projectId?: string) {
  const projectQuery = projectId ? `project_id=${encodeURIComponent(projectId)}&` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<BatchItem[]>(`/product/batch/items?${projectQuery}limit=180`)
  ]);
}

export function runBatchDeconstruct(inputPath: string, title: string, workspacePath?: string, analysisMode = "claude_code") {
  return postJson("/product/batch/deconstruct", {
    input_path: inputPath,
    title: title || null,
    rights_authorization: "operator_confirmed_local_use",
    license_name: "local",
    copyright_note: "Local operator confirmed rights boundary before import.",
    source_url: "",
    allow_downstream_generation: false,
    workspace_path: workspacePath || null,
    analysis_mode: analysisMode,
    async_task: true
  });
}

export function retryBatchItem(itemPath: string, workspacePath?: string) {
  return postJson("/product/batch/items/retry", { item_path: itemPath, workspace_path: workspacePath || null });
}

export function regenerateBatchHandoff(itemPath: string, workspacePath?: string) {
  return postJson("/product/batch/items/handoff/regenerate", {
    item_path: itemPath,
    workspace_path: workspacePath || null,
    reason: "operator requested from batch workbench"
  });
}

export function voidBatchHandoff(itemPath: string, workspacePath?: string) {
  return postJson("/product/batch/items/handoff/void", {
    item_path: itemPath,
    workspace_path: workspacePath || null,
    reason: "operator voided from batch workbench"
  });
}
