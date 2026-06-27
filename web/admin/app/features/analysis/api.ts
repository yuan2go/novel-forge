import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";

export function loadAnalysisData(projectId?: string) {
  const projectQuery = projectId ? `?project_id=${encodeURIComponent(projectId)}&limit=120` : "?limit=120";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=120` : "/assets?limit=80&rank=path"),
    fetchJson<FeatureAssetRow[]>(`/product/analysis/reports${projectQuery}`)
  ]);
}

export function runAnalysis(sourcePath: string, analysisType: string, workspacePath?: string) {
  return postJson("/product/analysis/run", {
    source_path: sourcePath,
    analysis_type: analysisType,
    workspace_path: workspacePath || null
  });
}

export function convertAnalysis(reportPath: string, targets: string[], workspacePath?: string) {
  return postJson("/product/analysis/convert", {
    report_path: reportPath,
    targets,
    reuse_scope: "project",
    workspace_path: workspacePath || null
  });
}

export function createAnalysisHandoff(inputPath: string, analysisType: string, workspacePath?: string) {
  return postJson("/product/analysis/handoff", {
    input_path: inputPath,
    analysis_type: analysisType,
    workspace_path: workspacePath || null,
    purpose: "manual Claude Code / Codex analysis from V6 feature page"
  });
}
