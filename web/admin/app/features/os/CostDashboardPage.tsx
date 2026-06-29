"use client";

import { BarChart3, CreditCard, Database, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createCostSnapshot, loadCostDashboardData, type CostLedgerRow, type RuntimeCostDashboard } from "./api";
import { compactJson, formatMoney, pathCell, selectedWorkspace } from "./helpers";

const sourceTypes = ["", "model_call_log", "agent_run", "workflow_run", "gate_result", "manual"];

export function CostDashboardPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [dashboard, setDashboard] = useState<RuntimeCostDashboard | null>(null);
  const [ledgers, setLedgers] = useState<CostLedgerRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [scope, setScope] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [chapter, setChapter] = useState("");
  const [snapshotResult, setSnapshotResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId, nextScope = scope, nextSourceType = sourceType) {
    setBusy(true);
    setError("");
    try {
      const [projectRows, costDashboard, ledgerRows, assetRows] = await loadCostDashboardData(nextProjectId, nextScope, nextSourceType);
      setProjects(projectRows);
      setDashboard(costDashboard);
      setLedgers(ledgerRows);
      setAssets(assetRows);
      setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function persistSnapshot() {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const parsedChapter = chapter.trim() ? Number(chapter.trim()) : undefined;
      const result = await createCostSnapshot(projectId, selectedWorkspace(projects, projectId), Number.isFinite(parsedChapter) ? parsedChapter : undefined);
      setSnapshotResult(result);
      setNotice("成本快照已持久化");
      await refresh(projectId, scope, sourceType);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const content = dashboard?.asset?.content || {};
  const summary = content.summary || {};
  const snapshots = content.snapshots || {};
  const projectSnapshot = (snapshots.project as Record<string, unknown> | undefined) || {};
  const agentSnapshot = (snapshots.agent as Record<string, unknown> | undefined) || {};
  const chapterSnapshot = (snapshots.chapter as Record<string, unknown> | undefined) || {};
  const recommendations = content.recommendations || [];
  const modelCallAssets = assets.filter((asset) => asset.type === "model_call_log");
  const budgetPolicies = assets.filter((asset) => asset.type === "budget_policy");
  const costAlerts = assets.filter((asset) => asset.type === "cost_alert");
  const byProvider = asRows(projectSnapshot.by_provider);
  const byModel = asRows(projectSnapshot.by_model);
  const byOperation = asRows(projectSnapshot.by_operation);
  const scopes = useMemo(() => Array.from(new Set(ledgers.map((ledger) => ledger.scope).filter(Boolean))).slice(0, 80), [ledgers]);
  const currency = String(summary.currency || projectSnapshot.currency || "USD");

  return (
    <FeatureShell title="Cost Dashboard" subtitle="从估算字段升级到 model_call_log、cost_ledger、budget_policy、成本快照和质量成本比的运营看板。" eyebrow="OS Runtime">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Total Cost" value={formatMoney(summary.total_cost, currency)} />
        <Metric label="Ledger" value={String(summary.ledger_count ?? ledgers.length)} />
        <Metric label="Model Calls" value={String(summary.model_call_count ?? modelCallAssets.length)} />
        <Metric label="Avg Quality" value={String(summary.average_quality_score ?? 0)} />
        <Metric label="Cost / Quality" value={String(summary.cost_per_quality_point ?? 0)} />
        <Metric label="Alerts" value={String(costAlerts.length)} />
      </section>

      <section className="panel">
        <PanelHeader title="Cost Controls" icon={<CreditCard size={18} />} />
        <div className="formGrid wide">
          <select value={projectId} onChange={(event) => { setProjectId(event.target.value); refresh(event.target.value, scope, sourceType).catch(() => undefined); }}>
            <option value="">全局</option>
            {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
          </select>
          <input value={scope} onChange={(event) => setScope(event.target.value)} placeholder="ledger scope，可留空" list="ledger-scope-list" />
          <datalist id="ledger-scope-list">
            {scopes.map((item) => <option value={item} key={item} />)}
          </datalist>
          <select value={sourceType} onChange={(event) => { setSourceType(event.target.value); refresh(projectId, scope, event.target.value).catch(() => undefined); }}>
            {sourceTypes.map((item) => <option value={item} key={item}>{item || "全部 source_type"}</option>)}
          </select>
          <input value={chapter} onChange={(event) => setChapter(event.target.value)} placeholder="chapter，可选" />
          <button className="primaryButton" disabled={busy} onClick={() => refresh()}><BarChart3 size={16} />刷新</button>
          <button className="secondaryButton" disabled={busy} onClick={persistSnapshot}><Save size={16} />持久化快照</button>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Provider / Model Cost" icon={<BarChart3 size={18} />} />
          <DataTable
            emptyText="暂无 provider 成本"
            columns={["Provider", "成本", "Ledger", "Model Calls"]}
            rows={byProvider.slice(0, 20).map((row) => [
              String(row.provider || row.name || row.key || "-"),
              formatMoney(row.total_cost, currency),
              String(row.ledger_count ?? 0),
              String(row.model_call_count ?? row.model_calls ?? 0)
            ])}
          />
          <DataTable
            emptyText="暂无 model 成本"
            columns={["Model", "成本", "Ledger", "Model Calls"]}
            rows={byModel.slice(0, 20).map((row) => [
              String(row.model || row.name || row.key || "-"),
              formatMoney(row.total_cost, currency),
              String(row.ledger_count ?? 0),
              String(row.model_call_count ?? row.model_calls ?? 0)
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Budget / Alerts" icon={<CreditCard size={18} />} />
          <div className="summaryBand">
            <Metric label="Policies" value={String(budgetPolicies.length)} />
            <Metric label="Alerts" value={String(costAlerts.length)} />
            <Metric label="Project Snapshot" value={String(snapshots.project_cost_snapshot_path || "-")} />
            <Metric label="Agent Snapshot" value={String(snapshots.agent_cost_snapshot_path || "-")} />
          </div>
          <DataTable
            emptyText="暂无成本建议"
            columns={["建议"]}
            rows={recommendations.map((item) => [item])}
          />
          <pre className="jsonPreview">{JSON.stringify(snapshotResult || {}, null, 2)}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Operation Cost" icon={<Database size={18} />} />
          <DataTable
            emptyText="暂无 operation 成本"
            columns={["Operation", "成本", "Ledger", "Model Calls"]}
            rows={byOperation.slice(0, 40).map((row) => [
              String(row.operation || row.name || row.key || "-"),
              formatMoney(row.total_cost, currency),
              String(row.ledger_count ?? 0),
              String(row.model_call_count ?? row.model_calls ?? 0)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Agent / Chapter Snapshot" icon={<BarChart3 size={18} />} />
          <DataTable
            emptyText="暂无 Agent 成本"
            columns={["Agent", "成本", "Ledger", "Model Calls"]}
            rows={asRows(agentSnapshot.by_agent).slice(0, 20).map((row) => [
              String(row.agent || "-"),
              formatMoney(row.total_cost, currency),
              String(row.ledger_count ?? 0),
              String(row.model_calls ?? 0)
            ])}
          />
          <DataTable
            emptyText="暂无章节成本"
            columns={["Chapter", "成本", "Ledger"]}
            rows={asRows(chapterSnapshot.by_chapter).slice(0, 20).map((row) => [
              String(row.chapter || "-"),
              formatMoney(row.total_cost, currency),
              String(row.ledger_count ?? 0)
            ])}
          />
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Cost Ledger" icon={<Database size={18} />} />
        <DataTable
          emptyText="暂无 cost ledger"
          columns={["时间", "Scope", "Amount", "Source", "Provider/Model", "Trace", "路径"]}
          rows={ledgers.slice(0, 160).map((ledger) => [
            ledger.created_at || "-",
            ledger.scope || "-",
            formatMoney(ledger.amount, ledger.currency),
            `${ledger.source_type || "-"} · ${ledger.source_id || "-"}`,
            `${String(ledger.metadata?.provider || "-")} / ${String(ledger.metadata?.model || "-")}`,
            compactJson(ledger.trace, 80),
            pathCell(ledger.path, ledger.path)
          ])}
        />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Model Call Assets" icon={<Database size={18} />} />
          <DataTable
            emptyText="暂无 model_call_log 资产"
            columns={["标题", "状态", "风险", "路径"]}
            rows={modelCallAssets.slice(0, 60).map((asset) => [
              asset.title,
              <span className={statusClass(asset.status || asset.asset_status || "")} key={`${asset.path}-status`}>{asset.status || asset.asset_status || "-"}</span>,
              asset.risk_level || "-",
              pathCell(asset.path, asset.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Budget Policy / Alert Assets" icon={<CreditCard size={18} />} />
          <DataTable
            emptyText="暂无预算或告警资产"
            columns={["类型", "标题", "状态", "路径"]}
            rows={[...budgetPolicies, ...costAlerts].slice(0, 60).map((asset) => [
              asset.type,
              asset.title,
              <span className={statusClass(asset.status || asset.asset_status || "")} key={`${asset.path}-status`}>{asset.status || asset.asset_status || "-"}</span>,
              pathCell(asset.path, asset.path)
            ])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}

function asRows(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) {
    return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
  }
  if (value && typeof value === "object") {
    return Object.values(value as Record<string, unknown>).filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
  }
  return [];
}
