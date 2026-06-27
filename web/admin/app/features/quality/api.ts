import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, ProjectRow } from "../../shared/types";

export function loadQualityData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=180` : "/assets?limit=160&rank=path")
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

export function createReleasePackage(draftPath: string, publishGatePath?: string, workspacePath?: string) {
  return postJson("/product/publishing/release-package", {
    draft_path: draftPath,
    workspace_path: workspacePath || null,
    publish_gate_path: publishGatePath || null,
    channel: "local",
    human_override: false
  });
}
