"use client";

import { GitPullRequest, Network, RefreshCw, ShieldCheck, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, NodeRunRow, ProjectRow, WorkflowRunRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createImpactReport, loadInvalidationData, refreshNovelKG, runNovelKGGate } from "./api";
import { compactJson, pathCell, selectedWorkspace } from "./helpers";

export function InvalidationMapPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [dirty, setDirty] = useState<Record<string, unknown>>({});
  const [nodeRuns, setNodeRuns] = useState<NodeRunRow[]>([]);
  const [workflowRuns, setWorkflowRuns] = useState<WorkflowRunRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [impactResult, setImpactResult] = useState<Record<string, unknown> | null>(null);
  const [refreshResult, setRefreshResult] = useState<Record<string, unknown> | null>(null);
  const [gateResult, setGateResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, reportRows, assetRows, dirtyResult, nodeRunRows, workflowRunRows] = await loadInvalidationData(nextProjectId);
    setProjects(projectRows);
    setReports(reportRows as Array<Record<string, unknown>>);
    setAssets(assetRows);
    setDirty(dirtyResult);
    setNodeRuns(nodeRunRows);
    setWorkflowRuns(workflowRunRows);
    const resolvedProject = nextProjectId || projectRows[0]?.project_id || "";
    setProjectId(resolvedProject);
    setTargetPath((current) => current || assetRows[0]?.path || "");
  }

  async function runAction(action: () => Promise<Record<string, unknown>>, message: string, setResult: (result: Record<string, unknown>) => void) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action();
      setResult(result);
      setNotice(message);
      await refresh(projectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const latestReport = reports[0];
  const impactedAssets = ((latestReport?.impacted_assets as Array<Record<string, unknown>> | undefined) || []);
  const impactEdges = ((latestReport?.impact_edges as Array<Record<string, unknown>> | undefined) || []);
  const invalidationRuns = nodeRuns.filter((run) => run.operation.includes("invalid") || run.operation.includes("impact"));
  const blockedRuns = workflowRuns.filter((run) => Boolean(run.blocked_node_id) || ["blocked", "failed", "paused"].includes(run.status));
  const dirtyReasons = ((dirty.reasons as Array<Record<string, unknown>> | undefined) || []);

  return (
    <FeatureShell title="Invalidation Map" subtitle="把上游资产变更、KG dirty、影响报告、下游失效和 workflow resume 证据放在同一张运营图里。" eyebrow="OS Runtime">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Impact Reports" value={String(reports.length)} />
        <Metric label="Impacted Assets" value={String(impactedAssets.length)} />
        <Metric label="KG Dirty" value={dirty.dirty ? "yes" : "no"} />
        <Metric label="Invalidation Runs" value={String(invalidationRuns.length)} />
        <Metric label="Blocked Runs" value={String(blockedRuns.length)} />
        <Metric label="Assets" value={String(assets.length)} />
      </section>

      <section className="panel">
        <PanelHeader title="Invalidation Controls" icon={<GitPullRequest size={18} />} />
        <div className="formGrid wide">
          <select value={projectId} onChange={(event) => refresh(event.target.value)}>
            <option value="">全局</option>
            {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
          </select>
          <select value={targetPath} onChange={(event) => setTargetPath(event.target.value)}>
            <option value="">选择变更资产</option>
            {assets.map((asset) => <option value={asset.path} key={asset.path}>{asset.type}: {asset.title}</option>)}
          </select>
          <button className="primaryButton" disabled={busy || !targetPath} onClick={() => runAction(() => createImpactReport(targetPath, projectId), "影响报告已创建", setImpactResult)}>
            <GitPullRequest size={16} />Change Impact
          </button>
          <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => refreshNovelKG(projectId, selectedWorkspace(projects, projectId), targetPath), "KG refresh/invalidation 已执行", setRefreshResult)}>
            <RefreshCw size={16} />KG Refresh
          </button>
          <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => runNovelKGGate(targetPath, projectId, selectedWorkspace(projects, projectId)), "KG gate 已执行", setGateResult)}>
            <ShieldCheck size={16} />KG Gate
          </button>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Impact Graph" icon={<Network size={18} />} />
          <div className="severityStrip">
            {Object.entries((latestReport?.severity_summary as Record<string, unknown> | undefined) || {}).map(([severity, count]) => (
              <span className={statusClass(severity)} key={severity}>{severity}: {String(count)}</span>
            ))}
          </div>
          <div className="assetGraphCanvas">
            {impactedAssets.slice(0, 30).map((asset) => (
              <div className={`graphNode ${String(asset.severity || "")}`} key={String(asset.path || asset.id || asset.title)}>
                <strong>{String(asset.title || asset.id || asset.path || "-")}</strong>
                <span>{String(asset.type || "-")}</span>
                <small>depth {String(asset.depth ?? "-")} · {String(asset.severity || "low")}</small>
              </div>
            ))}
            {!impactedAssets.length ? <p className="muted">生成影响报告后展示下游资产。</p> : null}
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="KG Dirty / Gate Evidence" icon={<ShieldCheck size={18} />} />
          <div className="summaryBand">
            <Metric label="Dirty" value={dirty.dirty ? "yes" : "no"} />
            <Metric label="Gate" value={String(gateResult?.status ?? "-")} />
            <Metric label="Refresh" value={String(refreshResult?.status ?? "-")} />
            <Metric label="Recommendation" value={String(gateResult?.recommendation ?? "-")} />
          </div>
          <DataTable
            emptyText="暂无 dirty reason"
            columns={["类型", "路径", "原因"]}
            rows={dirtyReasons.slice(0, 20).map((reason, index) => [
              String(reason.kind || reason.type || "-"),
              pathCell(String(reason.path || "-"), `dirty-${index}`),
              String(reason.reason || reason.message || "-")
            ])}
          />
          <pre className="jsonPreview">{JSON.stringify(gateResult || refreshResult || dirty, null, 2)}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Impact Edges" icon={<GitPullRequest size={18} />} />
          <DataTable
            emptyText="暂无影响边"
            columns={["Source", "Relation", "Target", "Depth"]}
            rows={impactEdges.slice(0, 60).map((edge, index) => [
              pathCell(String(edge.source || "-"), `edge-source-${index}`),
              String(edge.relation || "-"),
              pathCell(String(edge.target || "-"), `edge-target-${index}`),
              String(edge.depth ?? "-")
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Downstream Actions" icon={<Workflow size={18} />} />
          <DataTable
            emptyText="暂无建议动作"
            columns={["资产", "严重度", "建议"]}
            rows={impactedAssets.slice(0, 30).map((asset, index) => [
              pathCell(String(asset.path || asset.id || "-"), `asset-${index}`),
              <span className={statusClass(String(asset.severity || ""))} key={`severity-${index}`}>{String(asset.severity || "-")}</span>,
              String(asset.recommended_action || "-")
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Invalidation Node Runs" icon={<Workflow size={18} />} />
          <DataTable
            emptyText="暂无 invalidation node run"
            columns={["节点", "操作", "状态", "I/O", "错误", "路径"]}
            rows={invalidationRuns.slice(0, 50).map((run) => [
              `${run.node_type}/${run.node_id}`,
              run.operation,
              <span className={statusClass(run.status)} key={`${run.path}-status`}>{run.status}</span>,
              `${run.input_count} -> ${run.output_count}`,
              run.error || "-",
              pathCell(run.path, run.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Blocked / Resume Candidates" icon={<Workflow size={18} />} />
          <DataTable
            emptyText="暂无阻塞 workflow"
            columns={["Run", "状态", "Blocked", "Trace", "路径"]}
            rows={blockedRuns.slice(0, 40).map((run) => [
              run.run_id,
              <span className={statusClass(run.status)} key={`${run.path}-status`}>{run.status}</span>,
              run.blocked_node_id || "-",
              run.trace_id || "-",
              pathCell(run.path, run.path)
            ])}
          />
          <p className="previewText">Latest impact: {compactJson(impactResult || latestReport, 220)}</p>
        </div>
      </section>
    </FeatureShell>
  );
}
