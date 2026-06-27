import { fetchJson, postJson } from "../../shared/api";
import type { AssetDetail, AssetGraph, AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";

export type CreativeLibrary = {
  key: string;
  title: string;
  description: string;
  asset_types: string[];
  assets: FeatureAssetRow[];
};

export function loadAssetsData(projectId?: string, keyword?: string) {
  const assetParams = new URLSearchParams({ limit: "160", rank: keyword ? "relevance" : "path" });
  if (keyword) assetParams.set("keyword", keyword);
  const projectAssets = projectId
    ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=160`
    : `/assets?${assetParams.toString()}`;
  const creative = projectId
    ? `/product/libraries/creative?project_id=${encodeURIComponent(projectId)}&limit_per_library=30`
    : "/product/libraries/creative?limit_per_library=30";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<AssetRow[]>(projectAssets),
    fetchJson<CreativeLibrary[]>(creative)
  ]);
}

export function loadAssetDetail(path: string) {
  return fetchJson<AssetDetail>(`/product/assets/detail?path=${encodeURIComponent(path)}`);
}

export function loadAssetGraph(path: string, depth = 2) {
  return fetchJson<AssetGraph>(`/product/assets/graph?path=${encodeURIComponent(path)}&depth=${depth}`);
}

export function createCreativeAsset(assetType: string, title: string, projectId?: string, workspacePath?: string) {
  return postJson("/product/creative-assets", {
    asset_type: assetType,
    title,
    project_id: projectId || null,
    workspace_path: workspacePath || null,
    scope: projectId ? "project" : "global"
  });
}

export function saveAssetContent(path: string, content: Record<string, unknown>) {
  return fetchJson<AssetDetail>("/product/assets/content", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content })
  });
}
