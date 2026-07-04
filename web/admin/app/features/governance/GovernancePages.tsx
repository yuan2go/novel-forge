"use client";

import { BarChart3, CheckCircle2, Database, FileSearch, ListChecks, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  createPermissionPolicy,
  createAnalyticsSnapshot,
  evaluatePermission,
  exportAuditPackage,
  loadAgentRegistry,
  loadAnalyticsDashboard,
  loadAuditLog,
  loadPermissionCenter,
  loadRetrievalStatus,
  rebuildDirtyIndex,
  syncAgentRegistry,
  syncAnalytics,
  verifyPgvector,
  type GovernanceRow
} from "./api";

export function AgentRegistryPage() {
  const [entries, setEntries] = useState<GovernanceRow[]>([]);
  const [coverage, setCoverage] = useState<Record<string, unknown>>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const [entryRows, coverageReport] = await loadAgentRegistry();
    setEntries(entryRows);
    setCoverage(coverageReport);
  }

  async function runSync() {
    setNotice("");
    setError("");
    try {
      await syncAgentRegistry();
      setNotice("Agent Registry 已从 runtime profile 同步。");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const stateCounts = asRecord(coverage.states);
  return (
    <FeatureShell title="Agent Registry" subtitle="统一 Agent 元数据、生命周期、调度资格、operation coverage 和评测绑定。" eyebrow="OS Governance">
      <Notice notice={notice} error={error} />
      <section className="summaryBand manuscriptSummary">
        <Metric label="Entries" value={String(coverage.entry_count ?? entries.length)} />
        <Metric label="Runtime Profiles" value={String(coverage.runtime_profile_count ?? 0)} />
        <Metric label="Active" value={String(stateCounts.active ?? 0)} />
        <Metric label="Draft" value={String(stateCounts.draft ?? 0)} />
        <Metric label="Policy" value={String(coverage.scheduler_policy || "active only")} />
      </section>
      <section className="panel">
        <PanelHeader title="Registry Operations" icon={<ListChecks size={18} />} />
        <div className="studioActions">
          <button className="primaryButton" onClick={runSync}><CheckCircle2 size={16} />Sync Runtime Profiles</button>
          <button className="secondaryButton" onClick={() => refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Refresh</button>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="Agent Coverage" icon={<ShieldCheck size={18} />} />
        <DataTable
          emptyText="暂无 Agent Registry entry"
          columns={["Agent", "State", "Schedulable", "Operations", "Eval", "Path"]}
          rows={entries.map((entry) => {
            const content = asRecord(entry.content);
            return [
              String(content.display_name || content.agent_id || entry.id || "-"),
              <span className={statusClass(String(content.lifecycle_state || ""))} key={`${entry.path}-state`}>{String(content.lifecycle_state || "-")}</span>,
              String(content.scheduler_enabled ? "yes" : "no"),
              String(asArray(content.operation_coverage).length),
              String(asArray(content.evaluation_bindings).length),
              <span className="pathText" key={`${entry.path}-path`}>{entry.path || "-"}</span>
            ];
          })}
        />
      </section>
    </FeatureShell>
  );
}

export function AuditLogPage() {
  const [events, setEvents] = useState<GovernanceRow[]>([]);
  const [trail, setTrail] = useState<Record<string, unknown>>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const [eventRows, trailReport] = await loadAuditLog();
    setEvents(eventRows);
    setTrail(trailReport);
  }

  async function runExport() {
    setNotice("");
    setError("");
    try {
      const latestTrace = String(asRecord(events[0]?.content).trace_id || "");
      await exportAuditPackage(latestTrace);
      setNotice("Audit export package 已生成，raw source text 已移除。");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  return (
    <FeatureShell title="Audit Log" subtitle="按 project_id / trace_id 还原 Agent、Gate、Model、Evaluation、Publish 和 Rollback 证据链。" eyebrow="OS Governance">
      <Notice notice={notice} error={error} />
      <section className="summaryBand manuscriptSummary">
        <Metric label="Events" value={String(trail.event_count ?? events.length)} />
        <Metric label="Trail" value={String(trail.status || "-")} />
        <Metric label="Evidence" value={String(asArray(trail.evidence_refs).length)} />
        <Metric label="Blocked" value={events.some((event) => asRecord(event.content).blocking) ? "yes" : "no"} />
      </section>
      <section className="panel">
        <PanelHeader title="Audit Operations" icon={<FileSearch size={18} />} />
        <div className="studioActions">
          <button className="primaryButton" onClick={runExport}><CheckCircle2 size={16} />Export Latest Trail</button>
          <button className="secondaryButton" onClick={() => refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Refresh</button>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="Recent Audit Events" icon={<ListChecks size={18} />} />
        <DataTable
          emptyText="暂无 audit event"
          columns={["Type", "Action", "Actor", "Status", "Trace", "Path"]}
          rows={events.map((event) => {
            const content = asRecord(event.content);
            return [
              String(content.event_type || "-"),
              String(content.action || "-"),
              String(content.actor_id || content.actor_type || "-"),
              <span className={statusClass(String(content.status || ""))} key={`${event.path}-status`}>{String(content.status || "-")}</span>,
              String(content.trace_id || "-"),
              <span className="pathText" key={`${event.path}-path`}>{event.path || "-"}</span>
            ];
          })}
        />
      </section>
    </FeatureShell>
  );
}

export function PermissionCenterPage() {
  const [snapshot, setSnapshot] = useState<Record<string, unknown>>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    setSnapshot(await loadPermissionCenter());
  }

  async function run(action: () => Promise<unknown>, message: string) {
    setNotice("");
    setError("");
    try {
      await action();
      setNotice(message);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const summary = asRecord(snapshot.summary);
  const policies = asArray(snapshot.policies).map(asRecord);
  const gates = asArray(snapshot.human_approval_gates).map(asRecord);
  const decisions = asArray(snapshot.decisions).map(asRecord);
  return (
    <FeatureShell title="Permission Center" subtitle="agent/tool/source/publish/bypass 权限、human approval gate 和 audit 强绑定。" eyebrow="OS Governance">
      <Notice notice={notice} error={error} />
      <section className="summaryBand manuscriptSummary">
        <Metric label="Status" value={String(snapshot.status || "-")} />
        <Metric label="Policies" value={String(summary.policy_count ?? policies.length)} />
        <Metric label="Pending Gates" value={String(summary.pending_gate_count ?? 0)} />
        <Metric label="Decisions" value={String(summary.decision_count ?? decisions.length)} />
        <Metric label="Audit Required" value={summary.audit_required === false ? "no" : "yes"} />
      </section>
      <section className="panel">
        <PanelHeader title="Permission Operations" icon={<ShieldCheck size={18} />} />
        <div className="studioActions">
          <button
            className="primaryButton"
            onClick={() => run(() => createPermissionPolicy({
              scope: "publish",
              subject_type: "agent",
              subject_id: "publishing-agent",
              resource_type: "release_package",
              resource_id: "*",
              actions: ["release"],
              environment: "production",
              requires_human_approval: true,
              reason: "production publish requires editor approval"
            }), "Publish permission policy 已创建。")}
          >
            <CheckCircle2 size={16} />Create Publish Policy
          </button>
          <button
            className="secondaryButton"
            onClick={() => run(() => evaluatePermission({
              scope: "publish",
              action: "release",
              subject_type: "agent",
              subject_id: "publishing-agent",
              resource_type: "release_package",
              resource_id: "release-ui",
              environment: "production"
            }), "Production publish permission 已评估。")}
          >
            Evaluate Publish
          </button>
          <button className="secondaryButton" onClick={() => refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Refresh</button>
        </div>
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Policies" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 permission policy"
            columns={["Scope", "Subject", "Resource", "Actions", "Approval", "Path"]}
            rows={policies.slice(0, 80).map((row) => {
              const content = asRecord(row.content);
              return [
                String(content.scope || "-"),
                `${String(content.subject_type || "*")} / ${String(content.subject_id || "*")}`,
                `${String(content.resource_type || "*")} / ${String(content.resource_id || "*")}`,
                String(asArray(content.actions).join(", ") || "-"),
                String(content.requires_human_approval ? "required" : "no"),
                <span className="pathText" key={`${String(row.path)}-policy-path`}>{String(row.path || "-")}</span>
              ];
            })}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Human Approval Gates" icon={<ShieldCheck size={18} />} />
          <DataTable
            emptyText="暂无 human approval gate"
            columns={["Scope", "Action", "状态", "Reason", "Path"]}
            rows={gates.slice(0, 80).map((row) => {
              const content = asRecord(row.content);
              return [
                String(content.scope || "-"),
                String(content.action || "-"),
                <span className={statusClass(String(content.status || ""))} key={`${String(row.path)}-gate-status`}>{String(content.status || "-")}</span>,
                String(content.reason || "-"),
                <span className="pathText" key={`${String(row.path)}-gate-path`}>{String(row.path || "-")}</span>
              ];
            })}
          />
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="Recent Decisions" icon={<FileSearch size={18} />} />
        <DataTable
          emptyText="暂无 permission decision"
          columns={["Scope", "Action", "状态", "Reason", "Path"]}
          rows={decisions.slice(0, 80).map((row) => {
            const content = asRecord(row.content);
            return [
              String(content.scope || "-"),
              String(content.action || "-"),
              <span className={statusClass(String(content.status || ""))} key={`${String(row.path)}-decision-status`}>{String(content.status || "-")}</span>,
              String(content.reason || "-"),
              <span className="pathText" key={`${String(row.path)}-decision-path`}>{String(row.path || "-")}</span>
            ];
          })}
        />
      </section>
    </FeatureShell>
  );
}

export function RetrievalStatusPage() {
  const [capabilities, setCapabilities] = useState<Record<string, unknown>>({});
  const [operations, setOperations] = useState<Record<string, unknown>>({});
  const [comparison, setComparison] = useState<Record<string, unknown>>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const [capabilityReport, operationsPlan, comparisonReport] = await loadRetrievalStatus();
    setCapabilities(capabilityReport);
    setOperations(operationsPlan);
    setComparison(comparisonReport);
  }

  async function run(action: () => Promise<unknown>, message: string) {
    setNotice("");
    setError("");
    try {
      await action();
      setNotice(message);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const sourceIsolation = asRecord(capabilities.source_isolation);
  const opsContent = asRecord(operations.content);
  return (
    <FeatureShell title="Retrieval / pgvector" subtitle="PostgreSQL + pgvector PoC、source isolation、dirty index rebuild 和 Qdrant 对比。" eyebrow="OS Governance">
      <Notice notice={notice} error={error} />
      <section className="summaryBand manuscriptSummary">
        <Metric label="Status" value={String(capabilities.status || "-")} />
        <Metric label="Online" value={String(capabilities.online_enabled ? "yes" : "no")} />
        <Metric label="Local Chunks" value={String(capabilities.local_projection_chunk_count ?? 0)} />
        <Metric label="Raw Text" value={sourceIsolation.raw_source_text_for_generation === false ? "blocked" : "check"} />
        <Metric label="Qdrant" value={String(asRecord(comparison.qdrant).role || "optional")} />
      </section>
      <section className="panel">
        <PanelHeader title="Retrieval Operations" icon={<Database size={18} />} />
        <div className="studioActions">
          <button className="primaryButton" onClick={() => run(verifyPgvector, "pgvector migration verification 已完成。")}><CheckCircle2 size={16} />Verify</button>
          <button className="secondaryButton" onClick={() => run(rebuildDirtyIndex, "dirty index rebuild plan 已生成。")}>Rebuild Dirty Index</button>
          <button className="secondaryButton" onClick={() => refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Refresh</button>
        </div>
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Migration Steps" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 operations plan"
            columns={["Step", "Blocking", "Command"]}
            rows={asArray(asRecord(opsContent).migration_steps).map((item) => {
              const row = asRecord(item);
              return [String(row.step || "-"), String(row.blocking ? "yes" : "no"), String(row.command || "-")];
            })}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Source Isolation" icon={<ShieldCheck size={18} />} />
          <DataTable
            columns={["Policy", "Value"]}
            rows={Object.entries(sourceIsolation).map(([key, value]) => [key, Array.isArray(value) ? value.join(", ") : String(value)])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}

export function AnalyticsDashboardPage() {
  const [capabilities, setCapabilities] = useState<Record<string, unknown>>({});
  const [quality, setQuality] = useState<Record<string, unknown>>({});
  const [agent, setAgent] = useState<Record<string, unknown>>({});
  const [evaluation, setEvaluation] = useState<Record<string, unknown>>({});
  const [cost, setCost] = useState<Record<string, unknown>>({});
  const [feedback, setFeedback] = useState<Record<string, unknown>>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const [capabilityReport, qualityReport, agentReport, evaluationReport, costReport, feedbackReport] = await loadAnalyticsDashboard();
    setCapabilities(capabilityReport);
    setQuality(qualityReport);
    setAgent(agentReport);
    setEvaluation(evaluationReport);
    setCost(costReport);
    setFeedback(feedbackReport);
  }

  async function run(action: () => Promise<unknown>, message: string) {
    setNotice("");
    setError("");
    try {
      await action();
      setNotice(message);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const metricRows = useMemo(() => [
    ["Quality Avg", String(quality.average ?? 0)],
    ["Evaluation Avg", String(evaluation.average_score ?? 0)],
    ["Agent Failure Rate", String(agent.failure_rate ?? 0)],
    ["Total Cost", String(cost.total_cost ?? 0)],
    ["Feedback Events", String(feedback.event_count ?? 0)]
  ], [agent, cost, evaluation, feedback, quality]);

  return (
    <FeatureShell title="Analytics Dashboard" subtitle="ClickHouse optional OLAP 层的离线统计投影、同步任务和治理指标。" eyebrow="OS Governance">
      <Notice notice={notice} error={error} />
      <section className="summaryBand manuscriptSummary">
        <Metric label="Mode" value={String(capabilities.default_mode || "offline_snapshot")} />
        <Metric label="Online" value={String(capabilities.online_enabled ? "yes" : "no")} />
        <Metric label="Events" value={String(capabilities.local_event_count ?? 0)} />
        <Metric label="Status" value={String(capabilities.status || "-")} />
        <Metric label="Business Writeback" value={capabilities.business_writeback === false ? "no" : "check"} />
      </section>
      <section className="panel">
        <PanelHeader title="Analytics Operations" icon={<BarChart3 size={18} />} />
        <div className="studioActions">
          <button className="primaryButton" onClick={() => run(syncAnalytics, "Analytics events 已从 LocalStorage 投影。")}><CheckCircle2 size={16} />Sync Offline</button>
          <button className="secondaryButton" onClick={() => run(createAnalyticsSnapshot, "Dashboard snapshot 已生成。")}>Create Snapshot</button>
          <button className="secondaryButton" onClick={() => refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Refresh</button>
        </div>
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Governance Metrics" icon={<BarChart3 size={18} />} />
          <DataTable columns={["Metric", "Value"]} rows={metricRows} />
        </div>
        <div className="panel">
          <PanelHeader title="Agent Status" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 agent metrics"
            columns={["Status", "Count"]}
            rows={Object.entries(asRecord(agent.by_status)).map(([status, count]) => [status, String(count)])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}

function Notice({ notice, error }: { notice: string; error: string }) {
  return (
    <>
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
    </>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
