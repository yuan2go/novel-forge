"use client";

import { FileSearch, Layers3, Workflow } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { convertAnalysis, createAnalysisHandoff, loadAnalysisData, runAnalysis, type AnalysisReportRow } from "./api";

const analysisTypes = [
  ["web_fiction_business", "网文商业结构"],
  ["published_fiction", "出版小说技法"],
  ["classic_literary", "经典名著深度"]
];

export function AnalysisCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [reports, setReports] = useState<AnalysisReportRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [reportPath, setReportPath] = useState("");
  const [analysisType, setAnalysisType] = useState("web_fiction_business");
  const [targets, setTargets] = useState("writing_template, material_card, review_rule_pack");
  const [humanApproved, setHumanApproved] = useState(false);
  const [approvalNote, setApprovalNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const sourceCandidates = useMemo(() => assets.filter((asset) => ["source_document", "cleaned_text", "draft_chapter", "decomposition_report"].includes(asset.type)).slice(0, 80), [assets]);
  const selectedReport = reports.find((report) => report.path === reportPath) || reports[0];
  const rubricRows = Object.entries(selectedReport?.semantic_depth?.rubric_scores ?? {});

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows, reportRows] = await loadAnalysisData(nextProjectId);
    const selected = nextProjectId || projectRows[0]?.project_id || "";
    setProjects(projectRows);
    setProjectId(selected);
    setAssets(assetRows);
    setReports(reportRows);
    setSourcePath((current) => current || assetRows[0]?.path || "");
    setReportPath((current) => current || reportRows[0]?.path || "");
  }

  async function runAction(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await action();
      setNotice(message);
      await refresh();
      return result;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  return (
    <FeatureShell title="分析拆解中心" subtitle="网文商业结构、出版技法、经典名著深度拆解，以及拆解报告到可复用资产的转换。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="分析报告" value={String(reports.length)} />
        <Metric label="网文拆解" value={String(reports.filter((row) => row.type === "web_fiction_business_analysis_report").length)} />
        <Metric label="出版/名著" value={String(reports.filter((row) => row.type.includes("published") || row.type.includes("classic")).length)} />
        <Metric label="转换报告" value={String(reports.filter((row) => row.type === "analysis_conversion_report").length)} />
        <Metric label="语义均分" value={String(averageScore(reports))} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="语义深度评分" icon={<FileSearch size={18} />} />
          <div className="summaryBand">
            <Metric label="总分" value={String(selectedReport?.semantic_depth?.overall_score ?? "-")} />
            <Metric label="Provider" value={selectedReport?.provider_review?.provider || "-"} />
            <Metric label="Model" value={selectedReport?.provider_review?.model || "-"} />
            <Metric label="可视化" value={selectedReport?.visualization?.kind || "-"} />
          </div>
          <DataTable
            emptyText="选择一个报告查看 rubric"
            columns={["维度", "分数", "权重", "建议"]}
            rows={rubricRows.map(([dimension, value]) => [
              dimension,
              String(value.score ?? "-"),
              String(value.weight ?? "-"),
              value.recommendation || "-"
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="模式可视化" icon={<Layers3 size={18} />} />
          <div className="analysisPanelGrid">
            {(selectedReport?.mode_specific_panels || []).map((panel) => (
              <div className="decisionCard" key={panel.title}>
                <span>{panel.title}</span>
                <strong>{panel.score}</strong>
                <small>{panel.recommendation || panel.visual_kind || "-"}</small>
              </div>
            ))}
          </div>
          <div className="tagCloud">
            {(selectedReport?.provider_review?.patterns || []).slice(0, 8).map((pattern) => <span key={pattern}>{pattern}</span>)}
          </div>
          <p className="previewText">{selectedReport?.provider_review?.summary || selectedReport?.summary || "暂无 provider-backed 语义摘要"}</p>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="运行拆解" icon={<Layers3 size={18} />} />
          <div className="formGrid">
            <label className="selectWrap">
              <span>项目</span>
              <select value={projectId} onChange={(event) => refresh(event.target.value)}>
                <option value="">全局</option>
                {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
              </select>
            </label>
            <label className="selectWrap">
              <span>模式</span>
              <select value={analysisType} onChange={(event) => setAnalysisType(event.target.value)}>
                {analysisTypes.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
              </select>
            </label>
            <button className="primaryButton" disabled={busy || !sourcePath} onClick={() => runAction(() => runAnalysis(sourcePath, analysisType, selectedProject?.path), "拆解完成")}>运行</button>
            <button className="secondaryButton" disabled={busy || !sourcePath} onClick={() => runAction(() => createAnalysisHandoff(sourcePath, analysisType, selectedProject?.path), "Handoff 已生成")}>Claude Code</button>
          </div>
          <label className="selectWrap">
            <span>输入资产</span>
            <select value={sourcePath} onChange={(event) => setSourcePath(event.target.value)}>
              <option value="">选择输入</option>
              {sourceCandidates.map((asset) => <option value={asset.path} key={asset.path}>{asset.type}: {asset.title || asset.path}</option>)}
            </select>
          </label>
        </div>

        <div className="panel">
          <PanelHeader title="资产转换器" icon={<Workflow size={18} />} />
          <label className="selectWrap">
            <span>拆解报告</span>
            <select value={reportPath} onChange={(event) => setReportPath(event.target.value)}>
              <option value="">选择报告</option>
              {reports.map((report) => <option value={report.path} key={report.path}>{report.type}: {report.title}</option>)}
            </select>
          </label>
          <input value={targets} onChange={(event) => setTargets(event.target.value)} aria-label="targets" />
          <label className="checkboxLine">
            <input type="checkbox" checked={humanApproved} onChange={(event) => setHumanApproved(event.target.checked)} />
            人工确认抽象边界，可进入后续生产资产候选
          </label>
          <input value={approvalNote} onChange={(event) => setApprovalNote(event.target.value)} placeholder="审核备注" />
          <button className="primaryButton" disabled={busy || !reportPath} onClick={() => runAction(() => convertAnalysis(reportPath, targets.split(",").map((item) => item.trim()).filter(Boolean), selectedProject?.path, humanApproved, approvalNote), "转换完成")}>转换为资产</button>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="拆解报告" icon={<FileSearch size={18} />} />
        <DataTable
          emptyText="暂无报告"
          columns={["类型", "标题", "状态", "风险", "路径"]}
          rows={reports.map((report) => [
            report.type,
            report.title,
            <span className={statusClass(report.status || "")} key={report.path}>{report.status || "-"}</span>,
            `${report.risk_level || "-"} / ${report.semantic_depth?.overall_score ?? "-"}`,
            report.path
          ])}
        />
      </section>
    </FeatureShell>
  );
}

function averageScore(reports: AnalysisReportRow[]) {
  const scores = reports.map((report) => Number(report.semantic_depth?.overall_score ?? 0)).filter(Boolean);
  if (!scores.length) return "-";
  return Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length);
}
