import { fetchJson, postJson } from "../../shared/api";
import type { AssetDetail, GitHubSource, HandoffAcceptance, HandoffOutputValidation, HandoffRow, ProjectRow } from "../../shared/types";

export function loadHandoffData(projectId?: string) {
  const projectQuery = projectId ? `project_id=${encodeURIComponent(projectId)}&` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<HandoffRow[]>(`/product/handoffs?${projectQuery}limit=160`),
    fetchJson<GitHubSource[]>("/product/sources/github")
  ]);
}

export function loadHandoffDetail(path: string) {
  return fetchJson<AssetDetail>(`/product/assets/detail?path=${encodeURIComponent(path)}`);
}

export function loadHandoffAcceptance(path: string) {
  return fetchJson<HandoffAcceptance>(`/product/handoffs/acceptance?handoff_path=${encodeURIComponent(path)}`);
}

export function createDeconstructHandoff(inputPath: string, genre: string, targetReader: string, purpose: string, workspacePath?: string) {
  return postJson("/product/handoffs/deconstruct", {
    input_path: inputPath,
    genre,
    target_reader: targetReader,
    purpose,
    workspace_path: workspacePath || null
  });
}

export function createKnowledgeHandoff(inputPath: string, discipline: string, credibility: string, scope: string, projectContext: string, workspacePath?: string) {
  return postJson("/product/handoffs/knowledge", {
    input_path: inputPath,
    discipline,
    credibility,
    scope,
    project_context: projectContext,
    workspace_path: workspacePath || null
  });
}

export function createGitHubKnowledgeHandoff(repoRefs: string[], discipline: string, credibility: string, scope: string, projectContext: string, workspacePath?: string) {
  return postJson("/product/handoffs/github-knowledge", {
    repo_refs: repoRefs,
    discipline,
    credibility,
    scope,
    project_context: projectContext,
    workspace_path: workspacePath || null
  });
}

export function validateHandoffOutput(handoffPath: string, outputPath: string, workspacePath?: string): Promise<HandoffOutputValidation> {
  return postJson("/product/handoffs/validate-output", {
    handoff_path: handoffPath,
    output_path: outputPath,
    workspace_path: workspacePath || null,
    mark_completed: false
  }) as Promise<HandoffOutputValidation>;
}

export function bindHandoffOutput(handoffPath: string, outputPath: string, workspacePath?: string) {
  return postJson("/product/handoffs/bind-output", {
    handoff_path: handoffPath,
    output_path: outputPath,
    workspace_path: workspacePath || null,
    mark_completed: true,
    auto_continue_batch: true,
    semantic_review: true
  });
}

export function updateAcceptance(handoffPath: string, checkIndex: number, status: string, note?: string) {
  return fetchJson<HandoffAcceptance>("/product/handoffs/acceptance", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ handoff_path: handoffPath, check_index: checkIndex, status, note: note || null })
  });
}

export function failHandoff(handoffPath: string, reason: string) {
  return postJson("/product/handoffs/fail", { handoff_path: handoffPath, reason });
}

export function retryHandoff(handoffPath: string, workspacePath?: string) {
  return postJson("/product/handoffs/retry", {
    handoff_path: handoffPath,
    reason: "operator requested retry from feature workbench",
    workspace_path: workspacePath || null
  });
}
