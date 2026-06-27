import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, ProjectRow } from "../../shared/types";

export function loadQualityData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=180` : "/assets?limit=160&rank=path"),
    fetchJson<AssetRow[]>(projectId ? `/product/publishing/assets?project_id=${encodeURIComponent(projectId)}&limit=120` : "/product/publishing/assets?limit=120")
  ]);
}

export function createChapterAudit(draftPath: string, workspacePath?: string) {
  return postJson("/product/audits/chapter", { draft_path: draftPath, workspace_path: workspacePath || null });
}

export function createOriginalityReport(draftPath: string, workspacePath?: string) {
  return postJson("/product/audits/originality", { draft_path: draftPath, workspace_path: workspacePath || null });
}

export function createPublishGate(draftPath: string, chapterAuditPath?: string, workspacePath?: string) {
  return postJson("/product/publishing/gate", {
    draft_path: draftPath,
    workspace_path: workspacePath || null,
    chapter_audit_path: chapterAuditPath || null,
    human_override: false
  });
}

export function createReleasePackage(draftPath: string, publishGatePath?: string, workspacePath?: string, channel = "local") {
  return postJson("/product/publishing/release-package", {
    draft_path: draftPath,
    workspace_path: workspacePath || null,
    publish_gate_path: publishGatePath || null,
    channel,
    human_override: false
  });
}

export function createPublishingPlan(releasePackagePaths: string[], projectId?: string, workspacePath?: string, channel = "local", cadence = "daily", startDate = "") {
  return postJson("/product/publishing/plan", {
    release_package_paths: releasePackagePaths,
    project_id: projectId || null,
    workspace_path: workspacePath || null,
    channel,
    cadence,
    start_date: startDate
  });
}

export function createPublishingLog(releasePackagePath: string, publishingPlanPath?: string, channel = "local", status = "published", externalUrl = "") {
  return postJson("/product/publishing/log", {
    release_package_path: releasePackagePath,
    publishing_plan_path: publishingPlanPath || null,
    channel,
    status,
    external_url: externalUrl,
    rollback_note: "local publication record with rollback source package"
  });
}
