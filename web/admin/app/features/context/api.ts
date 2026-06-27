import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";

export type ContextAssetRow = FeatureAssetRow & {
  target_asset_id?: string;
  target_asset_type?: string;
  target_path?: string;
  retrieval_backend?: string;
  ranker?: string;
  token_estimate?: number;
  source_count?: number;
  candidate_count?: number;
};

export function loadContextData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ContextAssetRow[]>(projectId ? `/product/context/assets?project_id=${encodeURIComponent(projectId)}&limit=160` : "/product/context/assets?limit=160"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=160` : "/assets?limit=120&rank=path")
  ]);
}

export function createContextBuildPlan(targetPath: string, query: string, topK: number, tokenBudget: number, backend: string, workspacePath?: string) {
  return postJson("/product/context/build-plan", {
    target_path: targetPath,
    query,
    top_k: topK,
    token_budget: tokenBudget,
    backend,
    workspace_path: workspacePath || null
  });
}

export function createContextBundle(buildPlanPath: string, maxItems: number) {
  return postJson("/product/context/bundle", {
    build_plan_path: buildPlanPath,
    max_items: maxItems
  });
}
