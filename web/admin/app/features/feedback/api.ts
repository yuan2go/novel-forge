import { fetchJson, postJson } from "../../shared/api";
import type { FeedbackAssetRow, ProjectRow } from "../../shared/types";

export function loadFeedbackData(projectId?: string) {
  const assets = projectId
    ? `/product/feedback/assets?project_id=${encodeURIComponent(projectId)}&limit=160`
    : "/product/feedback/assets?limit=160";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<FeedbackAssetRow[]>(assets)
  ]);
}

export function importFeedbackBatch(inputPath: string, workspacePath?: string) {
  return postJson("/product/feedback/import-batch", {
    input_path: inputPath,
    workspace_path: workspacePath || null,
    source_label: "reader feedback",
    platform: "local"
  });
}

export function createSentimentReport(feedbackPaths: string[], projectId?: string, workspacePath?: string) {
  return postJson("/product/feedback/sentiment-report", {
    feedback_paths: feedbackPaths,
    project_id: projectId || null,
    workspace_path: workspacePath || null
  });
}

export function createFeedbackInsight(inputPath?: string) {
  return postJson("/product/feedback/insight", { input_path: inputPath || null });
}

export function applyFeedbackStrategy(reportPath: string, workspacePath?: string) {
  return postJson("/product/feedback/apply-strategy", {
    report_path: reportPath,
    workspace_path: workspacePath || null
  });
}
