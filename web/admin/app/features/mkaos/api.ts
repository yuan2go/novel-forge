import { fetchJson, postJson } from "../../shared/api";

function unwrapMkaos<T = any>(payload: T): T {
  if (payload && typeof payload === "object" && (payload as any).success === true && "data" in (payload as any)) {
    return (payload as any).data as T;
  }
  return payload;
}

export type MkaosRow = {
  path: string;
  id: string;
  type: string;
  title: string;
  source?: string;
  status?: string;
  risk_level?: string;
  content: Record<string, any>;
  metadata: Record<string, any>;
  asset?: Record<string, any>;
};

export type MkaosOverview = {
  summary: Record<string, number>;
  sources: MkaosRow[];
  knowledge: MkaosRow[];
  bindings: MkaosRow[];
  rules: MkaosRow[];
  usage_events: MkaosRow[];
  risks: MkaosRow[];
};

export function loadMkaosOverview() {
  return fetchJson<MkaosOverview>("/product/mkaos/overview");
}

export function importMkaosSource(title: string, text: string) {
  return postJson("/product/mkaos/sources", {
    title,
    text,
    source_kind: "manual_note",
    rights: {
      authorization: "unknown",
      copyright_boundary: "operator supplied MKAOS source for abstract knowledge extraction",
      allow_downstream_generation: false
    }
  }).then(unwrapMkaos);
}

export function createKnowledgeCard(body: {
  conceptName: string;
  coreExplanation: string;
  discipline: string;
  sourceChunkIds: string[];
}) {
  return postJson("/product/mkaos/knowledge", {
    concept_name: body.conceptName,
    core_explanation: body.coreExplanation,
    discipline: body.discipline || "general",
    knowledge_type: "conflict_mechanism",
    source_chunk_ids: body.sourceChunkIds,
    confidence: 0.75,
    source_reliability: 0.7
  }).then(unwrapMkaos);
}

export function patchKnowledge(id: string, body: Record<string, unknown>) {
  return fetchJson(`/product/mkaos/knowledge/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(unwrapMkaos);
}

export function createUsageBinding(knowledgeId: string, body: {
  flow: string;
  usageType: string;
  inputRole: string;
  outputForm: string;
  constraintText: string;
}) {
  return postJson(`/product/mkaos/knowledge/${encodeURIComponent(knowledgeId)}/usage-bindings`, {
    flow: body.flow,
    usage_type: body.usageType,
    input_role: body.inputRole,
    output_form: body.outputForm,
    constraint_text: body.constraintText,
    priority: body.flow === "prose" ? 30 : 10
  }).then(unwrapMkaos);
}

export function patchUsageBinding(id: string, body: Record<string, unknown>) {
  return fetchJson(`/product/mkaos/usage-bindings/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(unwrapMkaos);
}

export function buildKnowledgePack(flow: string, goal: string) {
  return postJson("/product/mkaos/packs/build", {
    flow,
    current_goal: goal,
    genre: "历史",
    platform: "local",
    chapter_id: flow === "outline" ? "" : "1"
  }).then(unwrapMkaos);
}

export function loadPackPreview(packId: string) {
  return fetchJson<{ preview: string; source_isolation: Record<string, unknown> }>(`/product/mkaos/packs/${encodeURIComponent(packId)}/prompt-preview`);
}

export function loadPackDebug(packId: string) {
  return fetchJson<Record<string, any>>(`/product/mkaos/packs/${encodeURIComponent(packId)}/debug`);
}

export function buildKnowledgeGraph() {
  return postJson("/product/mkaos/knowledge-graph/build", { persist: true }).then(unwrapMkaos);
}

export function buildKnowledgeGraphExplorer() {
  return postJson("/product/mkaos/knowledge-graph/explorer", { persist: true, max_nodes: 80, max_frames: 32 }).then(unwrapMkaos);
}

export function queryLineage(knowledgeId: string) {
  return postJson("/product/mkaos/lineage/query", { knowledge_id: knowledgeId }).then(unwrapMkaos);
}

export function loadMutations(assetId?: string) {
  const query = assetId ? `?asset_id=${encodeURIComponent(assetId)}` : "";
  return fetchJson<MkaosRow[]>(`/product/mkaos/mutations${query}`);
}

export function runRegressionSuite() {
  return postJson("/product/mkaos/regression/run", { create_default_fixtures: true }).then(unwrapMkaos);
}

export function runMinimalAcceptance() {
  return postJson("/product/mkaos/acceptance/minimal", {}).then(unwrapMkaos);
}

export function runKnowledgeAssetOsAcceptance() {
  return postJson("/product/mkaos/acceptance/knowledge-asset-os", {}).then(unwrapMkaos);
}

export function runKnowledgeEvolution() {
  return postJson("/product/mkaos/evolution/run", {
    persist_graph: true,
    create_approval_requests: true,
    apply_updates: false,
    apply_rule_updates: false,
    apply_template_updates: false,
    apply_elimination: false
  }).then(unwrapMkaos);
}

export function createMkaosRepository(body: { name: string; localPath: string; sourceUri?: string; sourceType?: string }) {
  return postJson("/product/mkaos/ingestion/repositories", {
    name: body.name,
    local_path: body.localPath,
    source_uri: body.sourceUri || body.localPath,
    source_type: body.sourceType || "professional_book",
    source_kind: body.localPath ? "local_folder" : "github_repo",
    rights: {
      copyright_boundary: "evidence_only",
      allow_downstream_generation: false,
      raw_text_allowed_for_prose: false
    }
  }).then(unwrapMkaos);
}

export function loadMkaosRepositories() {
  return fetchJson<MkaosRow[]>("/product/mkaos/ingestion/repositories");
}

export function scanMkaosRepository(repositoryId: string) {
  return postJson(`/product/mkaos/ingestion/repositories/${encodeURIComponent(repositoryId)}/scan`, {}).then(unwrapMkaos);
}

export function importMkaosRepository(repositoryId: string) {
  return postJson(`/product/mkaos/ingestion/repositories/${encodeURIComponent(repositoryId)}/import`, {}).then(unwrapMkaos);
}

export function loadMkaosIngestionJobs() {
  return fetchJson<MkaosRow[]>("/product/mkaos/ingestion/jobs");
}

export function loadMkaosBooks() {
  return fetchJson<MkaosRow[]>("/product/mkaos/books");
}

export function loadMkaosBookChapters(bookId: string) {
  return fetchJson<MkaosRow[]>(`/product/mkaos/books/${encodeURIComponent(bookId)}/chapters`);
}

export function loadMkaosParallelPairs() {
  return fetchJson<MkaosRow[]>("/product/mkaos/parallel-pairs");
}

export function runMkaosExtractionJob(body: { sourceType: string; bookId?: string; text?: string }) {
  return postJson("/product/mkaos/extraction/jobs", {
    source_type: body.sourceType,
    book_id: body.bookId,
    text: body.text,
    bypass_reason: "web-admin-local-ingestion"
  }).then(unwrapMkaos);
}

export function convertMkaosCreativeAssets(knowledgeIds: string[], dryRun = true) {
  return postJson("/product/mkaos/convert/creative-assets", {
    knowledge_ids: knowledgeIds,
    dry_run: dryRun
  }).then(unwrapMkaos);
}

export function evaluateMkaosExtraction() {
  return postJson("/product/mkaos/quality/evaluate-extraction", {}).then(unwrapMkaos);
}

export function checkMkaosLeakage(candidateText: string, sourceText: string) {
  return postJson("/product/mkaos/quality/check-leakage", {
    candidate_text: candidateText,
    source_text: sourceText
  }).then(unwrapMkaos);
}

export function gateMkaosKnowledgePack(knowledgePack: Record<string, any>) {
  return postJson("/product/mkaos/quality/gate-knowledge-pack", {
    knowledge_pack: knowledgePack,
    flow: "prose"
  }).then(unwrapMkaos);
}
