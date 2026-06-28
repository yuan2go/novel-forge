import { fetchJson, postJson } from "../../shared/api";
import type { FeatureAssetRow, ProjectHealthReport, ProjectOperatingDashboard, ProjectRow } from "../../shared/types";

export type ProjectWizardLibrary = {
  key: string;
  title: string;
  title_zh?: string;
  asset_types: string[];
  assets: FeatureAssetRow[];
};

export function loadProjectsData() {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ProjectHealthReport>("/product/system/health"),
    fetchJson<ProjectWizardLibrary[]>("/product/libraries/creative?limit_per_library=100"),
    fetchJson<ProjectOperatingDashboard>("/product/projects/operating-dashboard?limit=100")
  ]);
}

export function createProject(body: {
  title: string;
  seriesTitle?: string;
  bookNumber?: number;
  platformProfilePath?: string;
  genreMarketProfilePath?: string;
  qualityStandardProfilePath?: string;
  styleProfilePath?: string;
  continuityBiblePath?: string;
}) {
  return postJson("/product/projects", {
    title: body.title,
    series_title: body.seriesTitle || null,
    book_number: body.bookNumber || null,
    platform_profile_path: body.platformProfilePath || null,
    genre_market_profile_path: body.genreMarketProfilePath || null,
    quality_standard_profile_path: body.qualityStandardProfilePath || null,
    style_profile_path: body.styleProfilePath || null,
    continuity_bible_path: body.continuityBiblePath || null
  });
}

export function transitionProject(projectId: string, action: "archive" | "pause" | "restore") {
  return postJson(`/product/projects/${encodeURIComponent(projectId)}/${action}`, {});
}

export function duplicateProject(projectId: string, title?: string) {
  return postJson(`/product/projects/${encodeURIComponent(projectId)}/duplicate`, { title: title || null, copy_references: true });
}

export function repairProjectScope(projectId?: string) {
  return postJson("/product/projects/audit/scope", { project_id: projectId || null, repair: true });
}
