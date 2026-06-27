"use client";

import { CheckCircle2, FileSearch, Send, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createChapterAudit, createOriginalityReport, createPublishGate, createReleasePackage, loadQualityData } from "./api";

export function QualityGatePage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [draftPath, setDraftPath] = useState("");
  const [chapterAuditPath, setChapterAuditPath] = useState("");
  const [publishGatePath, setPublishGatePath] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const drafts = assets.filter((asset) => ["draft_chapter", "draft_version"].includes(asset.type));
  const qualityAssets = assets.filter((asset) => ["chapter_audit_report", "originality_report", "publish_gate_report", "release_package"].includes(asset.type));
  const audits = qualityAssets.filter((asset) => asset.type === "chapter_audit_report");
  const gates = qualityAssets.filter((asset) => asset.type === "publish_gate_report");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows] = await loadQualityData(nextProjectId);
    setProjects(projectRows);
    setAssets(assetRows);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setDraftPath((current) => current || assetRows.find((asset) => asset.type.includes("draft"))?.path || "");
    setChapterAuditPath((current) => current || assetRows.find((asset) => asset.type === "chapter_audit_report")?.path || "");
    setPublishGatePath((current) => current || assetRows.find((asset) => asset.type === "publish_gate_report")?.path || "");
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
    <FeatureShell title="质量与发布门禁" subtitle="章节审稿、原创性保护、发布前门禁和 release package 在同一质量闭环内执行。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="Quality Assets" value={String(qualityAssets.length)} />
        <Metric label="Chapter Audit" value={String(audits.length)} />
        <Metric label="Publish Gate" value={String(gates.length)} />
        <Metric label="Release" value={String(qualityAssets.filter((asset) => asset.type === "release_package").length)} />
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="质量检查" icon={<ShieldCheck size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={draftPath} onChange={(event) => setDraftPath(event.target.value)}>
              <option value="">选择稿件</option>
              {drafts.map((draft) => <option value={draft.path} key={draft.path}>{draft.title}</option>)}
            </select>
            <button className="primaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => createChapterAudit(draftPath, selectedProject?.path), "章节审稿报告已创建")}>章节审稿</button>
            <button className="secondaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => createOriginalityReport(draftPath, selectedProject?.path), "原创性报告已创建")}>原创性检查</button>
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="发布门禁" icon={<Send size={18} />} />
          <div className="formGrid wide">
            <select value={chapterAuditPath} onChange={(event) => setChapterAuditPath(event.target.value)}>
              <option value="">选择 chapter audit</option>
              {audits.map((audit) => <option value={audit.path} key={audit.path}>{audit.title}</option>)}
            </select>
            <button className="secondaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => createPublishGate(draftPath, chapterAuditPath, selectedProject?.path), "发布门禁报告已创建")}>发布门禁</button>
            <select value={publishGatePath} onChange={(event) => setPublishGatePath(event.target.value)}>
              <option value="">选择 publish gate</option>
              {gates.map((gate) => <option value={gate.path} key={gate.path}>{gate.title}</option>)}
            </select>
            <button className="primaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => createReleasePackage(draftPath, publishGatePath, selectedProject?.path), "Release package 已创建")}>打包发布</button>
          </div>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="质量资产" icon={<FileSearch size={18} />} />
        <DataTable
          emptyText="暂无质量资产"
          columns={["类型", "标题", "状态", "分数", "风险", "路径"]}
          rows={qualityAssets.map((asset) => [
            asset.type,
            asset.title,
            <span className={statusClass(asset.asset_status || asset.risk_level || "")} key={`${asset.path}-status`}>{asset.asset_status || "-"}</span>,
            String(asset.score ?? "-"),
            asset.risk_level || "-",
            <span className="pathText" key={asset.path}>{asset.path}</span>
          ])}
        />
      </section>
    </FeatureShell>
  );
}
