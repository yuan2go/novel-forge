import { fetchJson, postJson } from "../../shared/api";
import type { ProjectRow } from "../../shared/types";

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
  references?: string[];
  asset?: Record<string, any>;
  asset_id?: string;
  asset_version_id?: string;
  lifecycle?: string;
  eligibility?: string;
  governance?: string;
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
  return fetchJson<MkaosRow[]>("/product/mkaos/assets?limit=500").then((rows) => {
    const byType = (types: string[]) => rows.filter((row) => types.includes(row.type));
    const sources = byType(["source_document", "source_chunk"]);
    const knowledge = byType(["knowledge_card_candidate", "knowledge_card"]);
    const bindings = byType(["knowledge_usage_binding"]);
    const rules = byType(["rule_card_candidate", "rule_card"]);
    const usageEvents = byType(["knowledge_usage_event"]);
    const risks = rows.filter((row) => row.risk_level && row.risk_level !== "clear");
    return {
      summary: {
        source_documents: sources.filter((row) => row.type === "source_document").length,
        knowledge_cards: knowledge.length,
        usage_bindings: bindings.length,
        usage_events: usageEvents.length,
        risk_items: risks.length
      },
      sources,
      knowledge,
      bindings,
      rules,
      usage_events: usageEvents,
      risks
    } satisfies MkaosOverview;
  });
}

export function loadMkaosProjects() {
  return fetchJson<ProjectRow[]>("/product/projects");
}

export function registerMkaosSource(body: {
  projectId: string;
  workspaceId: string;
  blobId: string;
  title: string;
  sourceKind: string;
  rightsAuthorization: "unknown" | "owned" | "licensed";
  licenseName: string;
  copyrightBoundary: string;
}) {
  return postJson("/product/source-governance/documents", {
    project_id: body.projectId,
    workspace_id: body.workspaceId,
    blob_id: body.blobId,
    title: body.title,
    source_kind: body.sourceKind,
    rights_authorization: body.rightsAuthorization,
    license_name: body.licenseName,
    copyright_boundary: body.copyrightBoundary,
    idempotency_key: `source-register:${body.projectId}:${body.blobId}`
  });
}

export function createKnowledgeCard(body: {
  projectId: string;
  workspaceId: string;
  executionAssetVersionId: string;
  conceptName: string;
  coreExplanation: string;
  discipline: string;
  sourceEvidence: Array<{
    sourceChunkAssetVersionId: string;
    chunkByteStart: number;
    chunkByteEnd: number;
    evidenceHash: string;
  }>;
}) {
  const seed = `${body.projectId}:${body.executionAssetVersionId}:${body.sourceEvidence.map((item) => `${item.sourceChunkAssetVersionId}:${item.chunkByteStart}:${item.chunkByteEnd}:${item.evidenceHash}`).join(",")}`;
  return postJson("/product/mkaos/knowledge-candidates", {
    project_id: body.projectId,
    workspace_id: body.workspaceId,
    execution_asset_version_id: body.executionAssetVersionId,
    candidate: {
      concept_name: body.conceptName,
      discipline: body.discipline || "general",
      abstract_principle: body.coreExplanation,
      constraints: ["Only the abstract mechanism may enter downstream context."],
      conflict_generators: ["Apply the mechanism through project-specific motives and consequences."],
      review_checks: ["Reject source-specific names, scenes, sentences and plot combinations."],
      copyright_boundaries: ["Mechanism and evidence identity only; no protected expression."]
    },
    evidence_spans: body.sourceEvidence.map((item) => ({
      source_chunk_asset_version_id: item.sourceChunkAssetVersionId,
      chunk_byte_start: item.chunkByteStart,
      chunk_byte_end: item.chunkByteEnd,
      evidence_hash: item.evidenceHash
    })),
    abstraction_policy_version: "anti-copy-abstraction:v1",
    idempotency_key: `mkaos-candidate:${seed}`
  });
}

export function approveKnowledgeCandidate(body: {
  projectId: string;
  workspaceId: string;
  candidateAssetVersionId: string;
  rationale: string;
}) {
  return postJson(`/product/mkaos/knowledge-candidates/${encodeURIComponent(body.candidateAssetVersionId)}/approve`, {
    project_id: body.projectId,
    workspace_id: body.workspaceId,
    policy_version: "mkaos-governance:v1",
    rationale: body.rationale,
    idempotency_key: `mkaos-approve:${body.projectId}:${body.candidateAssetVersionId}`
  });
}

export function loadAuthorityKnowledgeCards(projectId: string) {
  return fetchJson<MkaosRow[]>(`/product/mkaos/knowledge-cards?project_id=${encodeURIComponent(projectId)}`);
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

export function buildKnowledgePack(body: {
  projectId: string;
  workspaceId: string;
  targetAssetVersionId: string;
  knowledgeCardAssetVersionIds: string[];
}) {
  return postJson("/product/mkaos/knowledge-packs", {
    project_id: body.projectId,
    workspace_id: body.workspaceId,
    target_asset_version_id: body.targetAssetVersionId,
    selector_policy_version: "mkaos-explicit-selector:v1",
    selector_policy_hash: `sha256:${"1".repeat(64)}`,
    selections: body.knowledgeCardAssetVersionIds.map((assetVersionId) => ({
      knowledge_card_asset_version_id: assetVersionId,
      usage_role: "CONSTRAINT",
      frozen_weight: 1
    })),
    idempotency_key: `mkaos-pack:${body.projectId}:${body.targetAssetVersionId}:${body.knowledgeCardAssetVersionIds.join(",")}`
  });
}

export function loadPackPreview(projectId: string, packId: string) {
  return fetchJson<MkaosRow>(`/product/mkaos/knowledge-packs/${encodeURIComponent(packId)}?project_id=${encodeURIComponent(projectId)}`).then((row) => ({
    preview: JSON.stringify(row.content, null, 2),
    source_isolation: row.content?.source_policy ?? {}
  }));
}

export function loadPackDebug(projectId: string, packId: string) {
  return fetchJson<MkaosRow>(`/product/mkaos/knowledge-packs/${encodeURIComponent(packId)}?project_id=${encodeURIComponent(projectId)}`).then((row) => ({
    selected_items: row.content?.items ?? [],
    rejected_items: [],
    source_isolation_result: row.content?.source_policy ?? {},
    budget_usage: { estimated_tokens: 0 },
    blocking_risks: []
  }));
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

export function loadMkaosIngestionJob(jobId: string) {
  return fetchJson<MkaosRow>(`/product/mkaos/ingestion/jobs/${encodeURIComponent(jobId)}`);
}

export function resumeMkaosIngestionJob(jobId: string, force = false) {
  return postJson(`/product/mkaos/ingestion/jobs/${encodeURIComponent(jobId)}/resume`, {
    force,
    reason: "web-admin-resume"
  }).then(unwrapMkaos);
}

export function cancelMkaosIngestionJob(jobId: string, force = true) {
  return postJson(`/product/mkaos/ingestion/jobs/${encodeURIComponent(jobId)}/cancel`, {
    force,
    reason: "web-admin-cancel"
  }).then(unwrapMkaos);
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

export function createMkaosModelExtractionJob(body: { sourceType: string; inputSummary: string; providerMode?: string }) {
  return postJson("/product/mkaos/model-extraction/jobs", {
    source_type: body.sourceType,
    input_summary: body.inputSummary,
    provider_mode: body.providerMode || "disabled"
  }).then(unwrapMkaos);
}

export function loadMkaosModelExtractionJobs() {
  return fetchJson<MkaosRow[]>("/product/mkaos/model-extraction/jobs");
}

export function runMkaosModelExtractionJob(jobId: string) {
  return postJson(`/product/mkaos/model-extraction/jobs/${encodeURIComponent(jobId)}/run`, {
    provider_mode: "disabled"
  }).then(unwrapMkaos);
}

export function loadMkaosModelExtractionReviewQueue() {
  return fetchJson<MkaosRow[]>("/product/mkaos/model-extraction/review-queue");
}

export function approveMkaosModelExtractionCandidate(candidateId: string) {
  return postJson(`/product/mkaos/model-extraction/candidates/${encodeURIComponent(candidateId)}/approve`, {
    note: "approved-from-web-admin"
  }).then(unwrapMkaos);
}

export function rejectMkaosModelExtractionCandidate(candidateId: string) {
  return postJson(`/product/mkaos/model-extraction/candidates/${encodeURIComponent(candidateId)}/reject`, {
    reason: "rejected-from-web-admin"
  }).then(unwrapMkaos);
}

export function runMkaosModelExtractionBenchmark() {
  return postJson("/product/mkaos/model-extraction/benchmark/run", {
    provider_mode: "disabled"
  }).then(unwrapMkaos);
}

export function runMkaosModelExtractionRegression() {
  return postJson("/product/mkaos/model-extraction/regression/run", {
    provider_mode: "disabled"
  }).then(unwrapMkaos);
}

export function loadMkaosModelExtractionPrompts() {
  return fetchJson<MkaosRow[]>("/product/mkaos/model-extraction/prompts");
}

export function loadMkaosProductionGateReports() {
  return fetchJson<MkaosRow[]>("/product/mkaos/production-gate/reports");
}

export function loadMkaosProductionGateLatest() {
  return fetchJson<MkaosRow>("/product/mkaos/production-gate/latest");
}

export function runMkaosProductionGate(flow = "prose") {
  return postJson("/product/mkaos/production-gate/run", {
    flow,
    environment: "compat",
    target_asset: { id: "web-admin-gate-preview", type: "mkaos_preview", content: { summary: "safe preview" } },
    knowledge_pack: { id: "web-admin-pack-preview", type: "knowledge_pack", content: { pack_items: [{ knowledge_id: "preview", creative_principle: "abstract only" }] } }
  }).then(unwrapMkaos);
}

export function buildMkaosGateCoverage() {
  return postJson("/product/mkaos/production-gate/coverage", { persist: true }).then(unwrapMkaos);
}

export function loadMkaosGateCoverage() {
  return fetchJson<Record<string, any>>("/product/mkaos/production-gate/coverage");
}

export function buildMkaosLineageIndex() {
  return postJson("/product/mkaos/lineage/build-index", { persist: true }).then(unwrapMkaos);
}

export function loadMkaosLineageIndex() {
  return fetchJson<Record<string, any>>("/product/mkaos/lineage/index");
}

export function queryMkaosLineagePath(assetId: string) {
  return postJson("/product/mkaos/lineage/query-path", { source_asset_id: assetId, max_depth: 6 }).then(unwrapMkaos);
}

export function diffMkaosLineageIndexes() {
  return postJson("/product/mkaos/lineage/diff", { persist: true }).then(unwrapMkaos);
}

export function exportMkaosLineageGraph() {
  return postJson("/product/mkaos/lineage/export", { persist: true, limit: 120 }).then(unwrapMkaos);
}

export function analyzeMkaosAssetImpact(assetId: string) {
  return postJson("/product/mkaos/lineage/asset-impact", { asset_id: assetId }).then(unwrapMkaos);
}

export function attributeMkaosFeedback(assetId: string) {
  return postJson("/product/mkaos/lineage/feedback-to-knowledge", {
    feedback_id: "web-admin-feedback-preview",
    generated_asset_id: assetId,
    feedback_text: "节奏慢，设定太多"
  }).then(unwrapMkaos);
}

export function dryRunMkaosWeightGovernance(assetId?: string) {
  return postJson("/product/mkaos/lineage/weight-governance", {
    asset_id: assetId,
    dry_run: true
  }).then(unwrapMkaos);
}

export function applyMkaosWeightGovernance(assetId?: string) {
  return postJson("/product/mkaos/lineage/weight-governance", {
    asset_id: assetId,
    apply_updates: true,
    apply_policy: "explicit",
    environment: "compat",
    bypass_reason: "web-admin-explicit-weight-governance"
  }).then(unwrapMkaos);
}
