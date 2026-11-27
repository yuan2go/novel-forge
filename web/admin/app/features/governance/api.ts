import { fetchJson, postJson } from "../../shared/api";

export type GovernanceRow = Record<string, unknown> & {
  path?: string;
  id?: string;
  title?: string;
  type?: string;
  content?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export function loadAgentRegistry() {
  return Promise.all([
    fetchJson<GovernanceRow[]>("/product/agent-registry/entries?limit=500"),
    fetchJson<Record<string, unknown>>("/product/agent-registry/coverage")
  ]);
}

export function syncAgentRegistry() {
  return postJson("/product/agent-registry/sync-runtime-profiles", { default_state: "active" });
}

export function loadAuditLog() {
  return Promise.all([
    fetchJson<GovernanceRow[]>("/product/audit-log/events?limit=200"),
    fetchJson<Record<string, unknown>>("/product/audit-log/trail?limit=200")
  ]);
}

export function exportAuditPackage(traceId = "") {
  return postJson("/product/audit-log/export-package", { trace_id: traceId, limit: 200 });
}

export function loadRetrievalStatus() {
  return Promise.all([
    fetchJson<Record<string, unknown>>("/product/os/retrieval/pgvector-capabilities"),
    fetchJson<Record<string, unknown>>("/product/os/retrieval/pgvector-operations-plan"),
    fetchJson<Record<string, unknown>>("/product/os/retrieval/pgvector-qdrant-comparison")
  ]);
}

export function verifyPgvector() {
  return postJson("/product/os/retrieval/pgvector-verify", { dry_run: true });
}

export function rebuildDirtyIndex() {
  return postJson("/product/os/retrieval/rebuild-dirty-index", { dry_run: true });
}

export function loadAnalyticsDashboard() {
  return Promise.all([
    fetchJson<Record<string, unknown>>("/product/analytics/capabilities"),
    fetchJson<Record<string, unknown>>("/product/analytics/quality-trends"),
    fetchJson<Record<string, unknown>>("/product/analytics/agent-metrics"),
    fetchJson<Record<string, unknown>>("/product/analytics/evaluation-metrics"),
    fetchJson<Record<string, unknown>>("/product/analytics/cost-metrics"),
    fetchJson<Record<string, unknown>>("/product/analytics/feedback-metrics")
  ]);
}

export function syncAnalytics() {
  return postJson("/product/analytics/sync", { online: false, limit: 2000 });
}

export function createAnalyticsSnapshot() {
  return postJson("/product/analytics/dashboard-snapshot", {});
}

export function loadPermissionCenter() {
  return fetchJson<Record<string, unknown>>("/product/permission-center/snapshot?limit=300");
}

export function createPermissionPolicy(payload: Record<string, unknown>) {
  return postJson("/product/permission-center/policies", payload);
}

export function evaluatePermission(payload: Record<string, unknown>) {
  return postJson("/product/permission-center/evaluate", payload);
}
