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

export function createOperationalSnapshot(feedbackPaths: string[], projectId?: string, workspacePath?: string) {
  return postJson("/product/feedback/operational-snapshot", {
    feedback_paths: feedbackPaths,
    project_id: projectId || null,
    workspace_path: workspacePath || null
  });
}

export function runPublishFeedbackLoop(payload: {
  feedbackPaths: string[];
  projectId?: string;
  workspacePath?: string;
  releasePackagePath?: string;
}) {
  return postJson("/product/feedback/publish-loop", {
    feedback_paths: payload.feedbackPaths,
    project_id: payload.projectId || null,
    workspace_path: payload.workspacePath || null,
    release_package_path: payload.releasePackagePath || null,
    apply_mkaos_weight_update: true,
    require_human_gate: true
  });
}

export function createReaderSimulation(payload: {
  draftPath?: string;
  chapterText?: string;
  projectId?: string;
  workspacePath?: string;
  platform?: string;
  chapter?: number;
}) {
  return postJson("/product/feedback/reader-simulation", {
    draft_path: payload.draftPath || null,
    chapter_text: payload.chapterText || null,
    project_id: payload.projectId || null,
    workspace_path: payload.workspacePath || null,
    platform: payload.platform || "qidian",
    chapter: payload.chapter || null
  });
}

export function runRealFeedbackBackflow(payload: {
  metrics: Record<string, unknown>;
  projectId?: string;
  workspacePath?: string;
  platform?: string;
  releasePackagePath?: string;
}) {
  return postJson("/product/feedback/real-backflow", {
    metrics: payload.metrics,
    project_id: payload.projectId || null,
    workspace_path: payload.workspacePath || null,
    platform: payload.platform || "qidian",
    release_package_path: payload.releasePackagePath || null,
    apply_mkaos_weight_update: true
  });
}
