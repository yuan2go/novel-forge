import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, ProjectRow } from "../../shared/types";

export type NovelKGNode = {
  id: string;
  kind: string;
  entity_type?: string;
  name: string;
  aliases?: string[];
  confidence?: number;
  source_path?: string;
  source_asset_type?: string;
  evidence_spans?: Array<{ snippet?: string; source_path?: string; field_path?: string }>;
};

export type NovelKGRelation = {
  id: string;
  relation_type: string;
  source: string;
  target: string;
  confidence?: number;
};

export type NovelKGGraph = {
  ontology_version: string;
  ontology_schema_version?: string;
  summary?: { counts?: Record<string, number>; confidence?: Record<string, number> };
  entities: NovelKGNode[];
  events: NovelKGNode[];
  rules: NovelKGNode[];
  timelines: NovelKGNode[];
  foreshadowing: NovelKGNode[];
  factions: NovelKGNode[];
  locations: NovelKGNode[];
  props: NovelKGNode[];
  power_scales: NovelKGNode[];
  review_rules: NovelKGNode[];
  templates: NovelKGNode[];
  relations: NovelKGRelation[];
};

export type NovelKGConflictResult = {
  conflicts: Array<Record<string, unknown>>;
  count: number;
  blocking_count: number;
  recommendation: string;
};

export function loadNovelKGData(projectId?: string) {
  const projectQuery = projectId ? `project_id=${encodeURIComponent(projectId)}&` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<NovelKGGraph>(`/product/novel-kg/graph?${projectQuery}limit=1200`),
    fetchJson<NovelKGConflictResult>(`/product/novel-kg/conflicts?${projectQuery}limit=120`),
    fetchJson<Record<string, unknown>>(`/product/novel-kg/dirty?${projectQuery}`),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=160` : "/assets?limit=160&rank=path")
  ]);
}

export function createNovelKGSnapshot(projectId?: string, workspacePath?: string) {
  return postJson("/product/novel-kg/snapshot", {
    project_id: projectId || null,
    workspace_path: workspacePath || null,
    limit: 2000,
    include_content_snapshot: false
  }) as Promise<Record<string, unknown>>;
}

export function refreshNovelKG(projectId?: string, workspacePath?: string, changedAssetPath?: string) {
  return postJson("/product/novel-kg/refresh", {
    project_id: projectId || null,
    workspace_path: workspacePath || null,
    changed_asset_path: changedAssetPath || null,
    apply_invalidation: Boolean(changedAssetPath)
  }) as Promise<Record<string, unknown>>;
}

export function runNovelKGGate(targetPath?: string, projectId?: string, workspacePath?: string) {
  return postJson("/product/novel-kg/gate", {
    target_path: targetPath || null,
    project_id: projectId || null,
    workspace_path: workspacePath || null
  }) as Promise<Record<string, unknown>>;
}

export function loadNovelKGPath(source: string, target: string, projectId?: string) {
  const params = new URLSearchParams({ source, target, max_depth: "5", limit: "20" });
  if (projectId) params.set("project_id", projectId);
  return fetchJson<Record<string, unknown>>(`/product/novel-kg/paths?${params.toString()}`);
}

export function loadNovelKGImpact(node: string, projectId?: string) {
  const params = new URLSearchParams({ node, max_depth: "3", direction: "both", limit: "120" });
  if (projectId) params.set("project_id", projectId);
  return fetchJson<Record<string, unknown>>(`/product/novel-kg/impact?${params.toString()}`);
}

export function loadNovelKGCypher(q: string, kind?: string) {
  const params = new URLSearchParams({ q, limit: "80" });
  if (kind) params.set("kind", kind);
  return fetchJson<Record<string, unknown>>(`/product/novel-kg/cypher?${params.toString()}`);
}
