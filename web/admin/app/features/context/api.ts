import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";

export type ContextAssetRow = FeatureAssetRow & {
  target_asset_id?: string;
  target_asset_type?: string;
  target_path?: string;
  retrieval_backend?: string;
  ranker?: string;
  context_profile?: string;
  token_estimate?: number;
  source_count?: number;
  candidate_count?: number;
  candidate_assets?: ContextCandidate[];
  selected_assets?: ContextCandidate[];
  manual_selection?: Record<string, unknown>;
  stale_context_warnings?: Array<{ path?: string; reason?: string }>;
  actual_context?: string;
  context_budget_score?: { score?: number; status?: string; recommendation?: string; usage_ratio?: number };
};

export type ContextCandidate = {
  asset_id?: string;
  path: string;
  type?: string;
  title?: string;
  score?: number;
  ranker?: string;
  token_estimate?: number;
  summary?: string;
  categories?: string[];
};

export type ContextBundleDiff = {
  path?: string;
  recommendation: string;
  added_asset_paths: string[];
  removed_asset_paths: string[];
  shared_asset_paths: string[];
  token_delta: number;
  budget_status_change: { from?: string; to?: string };
};

export function loadContextData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ContextAssetRow[]>(projectId ? `/product/context/assets?project_id=${encodeURIComponent(projectId)}&limit=160` : "/product/context/assets?limit=160"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=160` : "/assets?limit=120&rank=path")
  ]);
}

export function createContextBuildPlan(targetPath: string, query: string, topK: number, tokenBudget: number, backend: string, contextProfile: string, workspacePath?: string) {
  return postJson("/product/context/build-plan", {
    target_path: targetPath,
    query,
    top_k: topK,
    token_budget: tokenBudget,
    backend,
    context_profile: contextProfile,
    workspace_path: workspacePath || null
  });
}

export function createContextBundle(
  buildPlanPath: string,
  maxItems: number,
  selectedAssetPaths: string[] = [],
  disabledAssetPaths: string[] = [],
  priorityAssetPaths: string[] = [],
  finalConfirmed = false
) {
  return postJson("/product/context/bundle", {
    build_plan_path: buildPlanPath,
    max_items: maxItems,
    selected_asset_paths: selectedAssetPaths,
    disabled_asset_paths: disabledAssetPaths,
    priority_asset_paths: priorityAssetPaths,
    final_confirmed: finalConfirmed
  });
}

export function diffContextBundles(leftPath: string, rightPath: string): Promise<ContextBundleDiff> {
  return postJson("/product/context/diff", {
    left_path: leftPath,
    right_path: rightPath,
    persist: true
  }) as Promise<ContextBundleDiff>;
}
