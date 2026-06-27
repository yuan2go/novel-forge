import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";

export type ChangeImpactRow = FeatureAssetRow & {
  target_path?: string;
  target_asset_type?: string;
  impacted_count?: number;
  impacted_assets?: Array<{ id?: string; path?: string; type?: string; title?: string; severity?: string; depth?: number; recommended_action?: string }>;
  impact_edges?: Array<{ source?: string; target?: string; relation?: string; depth?: number }>;
  recommendation?: string;
  severity_summary?: Record<string, number>;
};

export function loadImpactData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ChangeImpactRow[]>(projectId ? `/product/impact/reports?project_id=${encodeURIComponent(projectId)}&limit=160` : "/product/impact/reports?limit=160"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=160` : "/assets?limit=120&rank=path")
  ]);
}

export function createImpactReport(targetPath: string, projectId?: string) {
  return postJson("/product/impact/report", {
    target_path: targetPath,
    max_depth: 4,
    project_id: projectId || null
  });
}
