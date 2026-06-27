import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, ProjectRow } from "../../shared/types";

export function loadReviewData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=180` : "/assets?limit=160&rank=path")
  ]);
}

export function runReview(draftPath: string, workspacePath?: string) {
  return postJson("/product/reviews/run", {
    draft_path: draftPath,
    workspace_path: workspacePath || null,
    comparison: false,
    update_workspace: true
  });
}

export function createRevisionPlan(reviewPath: string, workspacePath?: string) {
  return postJson("/product/revisions/plan", { review_path: reviewPath, workspace_path: workspacePath || null });
}

export function applyRevision(revisionPath: string, draftPath?: string, workspacePath?: string) {
  return postJson("/product/revisions/apply", {
    revision_path: revisionPath,
    draft_path: draftPath || null,
    workspace_path: workspacePath || null,
    confirmed: true,
    review_after: true
  });
}
