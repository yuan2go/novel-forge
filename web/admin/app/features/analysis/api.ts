import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";

export type AnalysisReportRow = FeatureAssetRow & {
  semantic_depth?: {
    overall_score?: number;
    rubric_scores?: Record<string, { score?: number; weight?: number; evidence?: string[]; recommendation?: string }>;
    provider_status?: string;
    evidence?: string[];
  };
  provider_review?: {
    provider?: string;
    model?: string;
    status?: string;
    summary?: string;
    patterns?: string[];
  };
  visualization?: {
    kind?: string;
    score_points?: Array<{ label: string; score: number; weight?: number }>;
    timeline?: Array<Record<string, unknown>>;
    nodes?: Array<Record<string, unknown>>;
    edges?: Array<Record<string, unknown>>;
    diagnostics?: Record<string, unknown>;
  };
  mode_specific_panels?: Array<{ title: string; score: number; visual_kind?: string; recommendation?: string }>;
};

export function loadAnalysisData(projectId?: string) {
  const projectQuery = projectId ? `?project_id=${encodeURIComponent(projectId)}&limit=120` : "?limit=120";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=120` : "/assets?limit=80&rank=path"),
    fetchJson<AnalysisReportRow[]>(`/product/analysis/reports${projectQuery}`)
  ]);
}

export function runAnalysis(sourcePath: string, analysisType: string, workspacePath?: string) {
  return postJson("/product/analysis/run", {
    source_path: sourcePath,
    analysis_type: analysisType,
    workspace_path: workspacePath || null
  });
}

export function convertAnalysis(reportPath: string, targets: string[], workspacePath?: string, humanApproved = false, approvalNote = "") {
  return postJson("/product/analysis/convert", {
    report_path: reportPath,
    targets,
    reuse_scope: "project",
    human_approved: humanApproved,
    approval_note: approvalNote,
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
