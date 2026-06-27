"use client";

import { GitPullRequest, Network } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createImpactReport, loadImpactData, type ChangeImpactRow } from "./api";

export function ChangeImpactPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [reports, setReports] = useState<ChangeImpactRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, reportRows, assetRows] = await loadImpactData(nextProjectId);
    setProjects(projectRows);
    setReports(reportRows);
    setAssets(assetRows);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setTargetPath((current) => current || assetRows[0]?.path || "");
  }

  async function runAction(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      await action();
      setNotice(message);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  return (
    <FeatureShell title="变更影响分析中心" subtitle="围绕长篇稳定性，分析设定、人物、伏笔、稿件变更会影响哪些资产和生产节点。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="报告" value={String(reports.length)} />
        <Metric label="资产候选" value={String(assets.length)} />
        <Metric label="高影响" value={String(reports.filter((row) => (row.impacted_count ?? 0) > 8).length)} />
        <Metric label="项目" value={projectId || "global"} code />
      </section>
      <section className="panel">
        <PanelHeader title="创建影响报告" icon={<Network size={18} />} />
        <div className="formGrid wide">
          <select value={projectId} onChange={(event) => refresh(event.target.value)}>
            <option value="">全局</option>
            {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
          </select>
          <select value={targetPath} onChange={(event) => setTargetPath(event.target.value)}>
            <option value="">选择目标资产</option>
            {assets.map((asset) => <option value={asset.path} key={asset.path}>{asset.type}: {asset.title}</option>)}
          </select>
          <button className="primaryButton" disabled={busy || !targetPath} onClick={() => runAction(() => createImpactReport(targetPath, projectId), "变更影响报告已创建")}>分析影响</button>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="影响报告" icon={<GitPullRequest size={18} />} />
        <DataTable
          emptyText="暂无影响报告"
          columns={["标题", "目标", "影响数", "建议", "状态", "路径"]}
          rows={reports.map((report) => [
            report.title,
            report.target_path || "-",
            String(report.impacted_count ?? 0),
            report.recommendation || "-",
            <span className={statusClass(report.status || "")} key={`${report.path}-status`}>{report.status || "-"}</span>,
            <span className="pathText" key={report.path}>{report.path}</span>
          ])}
        />
      </section>
    </FeatureShell>
  );
}
