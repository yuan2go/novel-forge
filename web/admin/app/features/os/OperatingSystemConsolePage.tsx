"use client";

import { Activity, BarChart3, BookOpenCheck, CheckCircle2, GitPullRequest, ListChecks, Network, Route, ShieldCheck, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow, TaskControl, WorkflowDefinitionRow, WorkflowRunRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  applyRollback,
  coordinateRollback,
  loadAgentDispatchData,
  loadCostDashboardData,
  loadInvalidationData,
  loadProviderHardStopEvidence,
  loadRuntimePolicyEnforcement,
  loadRuntimePolicyLegacyAudit,
  loadRuntimePolicySurfaceCoverage,
  loadTraceTimelineData,
  loadWorkflowRuntimeData,
  previewRollback,
  verifyRollbackResult,
  type RuntimeCostDashboard,
  type RuntimeTraceTimeline
} from "./api";
import { formatMoney } from "./helpers";

const consoleLinks = [
  { href: "/workflow-runtime", label: "Workflow Runtime Console", icon: <Workflow size={18} />, description: "DAG、ready queue、processor contract、execute/resume/control。" },
  { href: "/agent-dispatch", label: "Agent Dispatch Center", icon: <Activity size={18} />, description: "dispatch queue、lease、operation contract、retry/recover。" },
  { href: "/novel-kg", label: "Novel KG Workbench", icon: <Network size={18} />, description: "实体、关系、时间线、伏笔、冲突和强门禁。" },
  { href: "/trace-timeline", label: "Trace Timeline", icon: <Route size={18} />, description: "workflow/node/agent/model/gate/cost span 全链路。" },
  { href: "/cost-dashboard", label: "Cost Dashboard", icon: <BarChart3 size={18} />, description: "ledger、model call、预算、质量成本比。" },
  { href: "/invalidation", label: "Invalidation Map", icon: <GitPullRequest size={18} />, description: "变更影响、KG dirty、下游失效和恢复入口。" },
  { href: "/review-rework", label: "Review Rework Board", icon: <ShieldCheck size={18} />, description: "review issue -> revision task -> patch -> re-review -> publish gate。" },
  { href: "/longform-stability", label: "Longform Stability", icon: <BookOpenCheck size={18} />, description: "canon、chapter state、arc、motif、villain 和 OS acceptance。" }
];

export function OperatingSystemConsolePage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [taskControl, setTaskControl] = useState<TaskControl | null>(null);
  const [workflowDefinitions, setWorkflowDefinitions] = useState<WorkflowDefinitionRow[]>([]);
  const [workflowRuns, setWorkflowRuns] = useState<WorkflowRunRow[]>([]);
  const [agentScheduler, setAgentScheduler] = useState<Record<string, unknown>>({});
  const [agentQueue, setAgentQueue] = useState<Array<Record<string, unknown>>>([]);
  const [traceTimeline, setTraceTimeline] = useState<RuntimeTraceTimeline | null>(null);
  const [costDashboard, setCostDashboard] = useState<RuntimeCostDashboard | null>(null);
  const [impactReports, setImpactReports] = useState<Array<Record<string, unknown>>>([]);
  const [dirty, setDirty] = useState<Record<string, unknown>>({});
  const [policyReport, setPolicyReport] = useState<Record<string, unknown>>({});
  const [legacyAudit, setLegacyAudit] = useState<Record<string, unknown>>({});
  const [surfaceCoverage, setSurfaceCoverage] = useState<Record<string, unknown>>({});
  const [providerHardStop, setProviderHardStop] = useState<Record<string, unknown>>({});
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [rollbackVerify, setRollbackVerify] = useState<Record<string, unknown> | null>(null);
  const [rollbackCoordination, setRollbackCoordination] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");

  async function refresh() {
    const [workflowData, agentData, traceData, costData, invalidationData, policyData, legacyAuditData, surfaceData, hardStopData] = await Promise.all([
      loadWorkflowRuntimeData(),
      loadAgentDispatchData(),
      loadTraceTimelineData(),
      loadCostDashboardData(),
      loadInvalidationData(),
      loadRuntimePolicyEnforcement(),
      loadRuntimePolicyLegacyAudit(),
      loadRuntimePolicySurfaceCoverage(),
      loadProviderHardStopEvidence()
    ]);
    setProjects(workflowData[0]);
    setTaskControl(workflowData[1]);
    setWorkflowDefinitions(workflowData[2]);
    setWorkflowRuns(workflowData[3]);
    setAgentScheduler(agentData[3]);
    setAgentQueue(agentData[4]);
    setTraceTimeline(traceData[1]);
    setCostDashboard(costData[1]);
    setAssets(costData[3]);
    setImpactReports(invalidationData[1]);
    setDirty(invalidationData[3]);
    setPolicyReport(policyData);
    setLegacyAudit(legacyAuditData);
    setSurfaceCoverage(surfaceData);
    setProviderHardStop(hardStopData);
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const costSummary = costDashboard?.asset?.content?.summary || {};
  const schedulerLease = (agentScheduler.lease as Record<string, unknown> | undefined) || {};
  const policySummary = (policyReport.summary as Record<string, unknown> | undefined) || {};
  const legacySummary = (legacyAudit.summary as Record<string, unknown> | undefined) || {};
  const surfaceSummary = (surfaceCoverage.summary as Record<string, unknown> | undefined) || {};
  const hardStopSummary = (providerHardStop.summary as Record<string, unknown> | undefined) || {};
  const legacyEntrypoints = (legacyAudit.entrypoints as Array<Record<string, unknown>> | undefined) || [];
  const surfaceRows = (surfaceCoverage.surface_matrix as Array<Record<string, unknown>> | undefined) || [];
  const hardStopRows = (providerHardStop.provider_gates as Array<Record<string, unknown>> | undefined) || [];
  const uncoveredOperations = (policyReport.uncovered_operations as string[] | undefined) || [];
  const policyOperations = (policyReport.operations as Array<Record<string, unknown>> | undefined) || [];
  const rollbackRows = assets.filter((asset) => ["operation_transaction", "rollback_plan", "rollback_result"].includes(asset.type));
  const rollbackTransactionPaths = rollbackRows.filter((asset) => asset.type === "operation_transaction").map((asset) => asset.path);
  const queued = agentQueue.filter((item) => ["queued", "claimed", "retry_scheduled"].includes(String(item.status || ""))).length;
  const blockedRuns = workflowRuns.filter((run) => Boolean(run.blocked_node_id) || ["blocked", "waiting_human", "failed"].includes(run.status));

  return (
    <FeatureShell title="Novel Operating System Console" subtitle="Workflow、Agent、KG、Trace、Cost、Invalidation、Rework 的统一运行入口。" eyebrow="OS Runtime">
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Projects" value={String(projects.length)} />
        <Metric label="Workflow Runs" value={String(workflowRuns.length)} />
        <Metric label="Agent Queue" value={String(queued)} />
        <Metric label="Trace Spans" value={String(traceTimeline?.summary?.span_count ?? 0)} />
        <Metric label="Cost" value={formatMoney(costSummary.total_cost, String(costSummary.currency || "USD"))} />
        <Metric label="KG Dirty" value={dirty.dirty ? "yes" : "no"} />
        <Metric label="Policy Gaps" value={String(policySummary.uncovered_operation_count ?? uncoveredOperations.length)} />
        <Metric label="Bypass Audit" value={String(legacySummary.review_required_count ?? 0)} />
        <Metric label="Surface" value={String(surfaceCoverage.status || "-")} />
        <Metric label="Hard Stops" value={String(hardStopSummary.covered_hard_stop_dimension_count ?? 0)} />
      </section>

      <section className="osConsoleGrid">
        {consoleLinks.map((link) => (
          <a className="decisionCard osConsoleLink" href={link.href} key={link.href}>
            <span className="badge muted">{link.icon}{link.label}</span>
            <strong>{link.description}</strong>
          </a>
        ))}
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Runtime Health" icon={<CheckCircle2 size={18} />} />
          <div className="summaryBand">
            <Metric label="Worker" value={taskControl?.celery.healthy ? "healthy" : "offline"} />
            <Metric label="Scheduler" value={String(taskControl?.scheduler?.status ?? "missing")} />
            <Metric label="Agent Lease" value={String(schedulerLease.status ?? "missing")} />
            <Metric label="Definitions" value={String(workflowDefinitions.length)} />
          </div>
          <DataTable
            emptyText="暂无阻塞 workflow"
            columns={["Run", "状态", "Blocked Node", "Trace", "路径"]}
            rows={blockedRuns.slice(0, 10).map((run) => [
              run.run_id,
              <span className={statusClass(run.status)} key={`${run.path}-status`}>{run.status}</span>,
              run.blocked_node_id || "-",
              run.trace_id || "-",
              <span className="pathText" key={run.path}>{run.path}</span>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="OS Evidence" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无运行证据"
            columns={["能力", "证据", "入口"]}
            rows={[
              ["Workflow Executor", `${workflowDefinitions.length} definitions / ${workflowRuns.length} runs`, <a className="linkButton" href="/workflow-runtime" key="workflow">打开</a>],
              ["Agent Scheduler", `${agentQueue.length} queue items / lease ${String(schedulerLease.status ?? "-")}`, <a className="linkButton" href="/agent-dispatch" key="agent">打开</a>],
              ["Trace Timeline", `${String(traceTimeline?.summary?.span_count ?? 0)} spans`, <a className="linkButton" href="/trace-timeline" key="trace">打开</a>],
              ["Cost Ledger", `${String(costSummary.ledger_count ?? 0)} ledgers / ${String(costSummary.model_call_count ?? 0)} model calls`, <a className="linkButton" href="/cost-dashboard" key="cost">打开</a>],
              ["Invalidation", `${impactReports.length} reports / dirty ${dirty.dirty ? "yes" : "no"}`, <a className="linkButton" href="/invalidation" key="invalidation">打开</a>],
              ["Runtime Policy", `${String(policySummary.covered_operation_count ?? 0)} covered / ${String(policySummary.operation_count ?? 0)} operations`, <span className={uncoveredOperations.length ? "badge warn" : "badge ok"} key="policy">{uncoveredOperations.length ? "gaps" : "covered"}</span>]
            ]}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="OS Surface Coverage" icon={<ShieldCheck size={18} />} />
          <div className="summaryBand">
            <Metric label="Status" value={String(surfaceCoverage.status || "-")} />
            <Metric label="Score" value={String(surfaceSummary.score ?? surfaceCoverage.score ?? 0)} />
            <Metric label="Strict Blockers" value={String(surfaceSummary.strict_blocker_count ?? 0)} />
          </div>
          <DataTable
            emptyText="暂无 surface coverage 矩阵"
            columns={["Path", "Type", "Envelope", "Trace", "Cost", "Gate", "Status"]}
            rows={surfaceRows.slice(0, 28).map((row) => [
              String(row.path || row.operation || "-"),
              String(row.type || "-"),
              String(row.has_os_envelope ?? "-"),
              String(row.has_trace ?? "-"),
              String(row.has_cost_ledger ?? "-"),
              String(row.has_publishing_gate ?? "-"),
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-surface-status`}>{String(row.status || "-")}</span>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Provider Hard-stop Evidence" icon={<ListChecks size={18} />} />
          <div className="summaryBand">
            <Metric label="Status" value={String(providerHardStop.status || "-")} />
            <Metric label="Dimensions" value={String(hardStopSummary.covered_hard_stop_dimension_count ?? 0)} />
            <Metric label="Failures" value={String(hardStopSummary.failed_model_call_count ?? 0)} />
          </div>
          <DataTable
            emptyText="暂无 provider hard-stop gate"
            columns={["Gate", "Status", "Dimension", "Message"]}
            rows={hardStopRows.slice(0, 28).map((row) => [
              String(row.gate_kind || "provider_runtime_guard"),
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-provider-status`}>{String(row.status || "-")}</span>,
              Array.isArray(row.observed_dimensions) ? row.observed_dimensions.join(", ") : Array.isArray(row.hard_stop_dimensions) ? row.hard_stop_dimensions.join(", ") : String(row.hard_stop_dimension || "-"),
              String(row.message || "-")
            ])}
          />
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Runtime Policy Coverage" icon={<ShieldCheck size={18} />} />
        <DataTable
          emptyText="暂无 runtime policy operation"
          columns={["Operation", "状态", "Model Calls", "Cost Ledger", "KG Context", "问题"]}
          rows={policyOperations.slice(0, 24).map((row) => [
            String(row.operation || "-"),
            <span className={statusClass(String(row.status || ""))} key={`${String(row.operation)}-status`}>{String(row.status || "-")}</span>,
            String(row.model_call_count ?? 0),
            String(row.cost_ledger_count ?? 0),
            row.requires_kg_context ? "required" : "-",
            Array.isArray(row.issues) && row.issues.length ? row.issues.join("; ") : "-"
          ])}
        />
      </section>

      <section className="panel">
        <PanelHeader title="Legacy Runtime Entrypoint Audit" icon={<Route size={18} />} />
        <DataTable
          emptyText="暂无旧入口审计结果"
          columns={["路径", "状态", "模型调用痕迹", "覆盖证据", "建议"]}
          rows={legacyEntrypoints.slice(0, 24).map((row) => [
            <span className="pathText" key={`${String(row.path)}-path`}>{String(row.path || "-")}</span>,
            <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-status`}>{String(row.status || "-")}</span>,
            Array.isArray(row.matched_calls) ? row.matched_calls.join(", ") : "-",
            Array.isArray(row.coverage_markers) && row.coverage_markers.length ? row.coverage_markers.join(", ") : "-",
            String(row.recommendation || "-")
          ])}
        />
      </section>

      <section className="panel">
        <PanelHeader title="Rollback Operations" icon={<GitPullRequest size={18} />} />
        <div className="summaryBand">
          <Metric label="Rollback Assets" value={String(rollbackRows.length)} />
          <Metric label="Transactions" value={String(rollbackTransactionPaths.length)} />
          <Metric label="Last Verify" value={String((rollbackVerify?.verification as Record<string, unknown> | undefined)?.status ?? "-")} />
          <Metric label="Coordination" value={String((rollbackCoordination?.verification as Record<string, unknown> | undefined)?.status ?? "-")} />
        </div>
        <div className="formGrid wide">
          <button className="secondaryButton" disabled={!rollbackTransactionPaths.length} onClick={() => coordinateRollback(rollbackTransactionPaths, "physical_restore", false).then(setRollbackCoordination).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Coordinate Preview</button>
          <button className="secondaryButton dangerButton" disabled={!rollbackTransactionPaths.length} onClick={() => coordinateRollback(rollbackTransactionPaths, "physical_restore", true).then((result) => { setRollbackCoordination(result); refresh().catch(() => undefined); }).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Coordinate Apply</button>
        </div>
        <DataTable
          emptyText="暂无 rollback transaction / result"
          columns={["类型", "标题", "状态", "路径", "验证"]}
          rows={rollbackRows.slice(0, 20).map((asset) => [
            asset.type,
            asset.title,
            <span className={statusClass(String(asset.status || asset.asset_status || ""))} key={`${asset.path}-status`}>{String(asset.status || asset.asset_status || "-")}</span>,
            <span className="pathText" key={`${asset.path}-path`}>{asset.path}</span>,
            asset.type === "operation_transaction" ? <button className="secondaryButton" key={`${asset.path}-preview`} onClick={() => previewRollback(asset.path).then(() => refresh()).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Preview</button>
              : asset.type === "rollback_plan" ? <button className="secondaryButton" key={`${asset.path}-apply`} onClick={() => applyRollback(asset.path).then(() => refresh()).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Apply</button>
              : asset.type === "rollback_result" ? <button className="secondaryButton" key={`${asset.path}-verify`} onClick={() => verifyRollbackResult(asset.path).then(setRollbackVerify).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>Verify</button> : "-"
          ])}
        />
        <pre className="jsonPreview">{JSON.stringify(rollbackCoordination || {}, null, 2)}</pre>
      </section>
    </FeatureShell>
  );
}
