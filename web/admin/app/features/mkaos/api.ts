import { fetchJson, postJson } from "../../shared/api";

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
  });
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
  });
}

export function patchKnowledge(id: string, body: Record<string, unknown>) {
  return fetchJson(`/product/mkaos/knowledge/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
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
  });
}

export function patchUsageBinding(id: string, body: Record<string, unknown>) {
  return fetchJson(`/product/mkaos/usage-bindings/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

export function buildKnowledgePack(flow: string, goal: string) {
  return postJson("/product/mkaos/packs/build", {
    flow,
    current_goal: goal,
    genre: "历史",
    platform: "local",
    chapter_id: flow === "outline" ? "" : "1"
  });
}

export function loadPackPreview(packId: string) {
  return fetchJson<{ preview: string; source_isolation: Record<string, unknown> }>(`/product/mkaos/packs/${encodeURIComponent(packId)}/prompt-preview`);
}

export function runMinimalAcceptance() {
  return postJson("/product/mkaos/acceptance/minimal", {});
}
