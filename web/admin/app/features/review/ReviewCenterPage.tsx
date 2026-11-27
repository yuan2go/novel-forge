"use client";

import { CheckCircle2, FileSearch, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { applyRevision, createRevisionPlan, loadReviewData, runReview } from "./api";

export function ReviewCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [draftPath, setDraftPath] = useState("");
  const [reviewPath, setReviewPath] = useState("");
  const [revisionPath, setRevisionPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const drafts = assets.filter((asset) => ["draft_chapter", "draft_version"].includes(asset.type));
  const reviews = assets.filter((asset) => ["review_report", "chapter_audit_report", "quality_score_report"].includes(asset.type));
  const revisions = assets.filter((asset) => ["revision_plan", "revision_report"].includes(asset.type));

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows] = await loadReviewData(nextProjectId);
    setProjects(projectRows);
    setAssets(assetRows);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setDraftPath((current) => current || assetRows.find((asset) => asset.type.includes("draft"))?.path || "");
    setReviewPath((current) => current || assetRows.find((asset) => asset.type === "review_report")?.path || "");
    setRevisionPath((current) => current || assetRows.find((asset) => asset.type === "revision_plan")?.path || "");
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
    <FeatureShell title="审稿 / 修订中心" subtitle="审稿报告、问题状态、修订计划、自动修订稿和修订后复审形成闭环。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="Draft" value={String(drafts.length)} />
        <Metric label="Review" value={String(reviews.length)} />
        <Metric label="Revision" value={String(revisions.length)} />
        <Metric label="Assets" value={String(assets.length)} />
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="审稿" icon={<CheckCircle2 size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={draftPath} onChange={(event) => setDraftPath(event.target.value)}>
              <option value="">选择稿件</option>
              {drafts.map((draft) => <option value={draft.path} key={draft.path}>{draft.title}</option>)}
            </select>
            <button className="primaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => runReview(draftPath, selectedProject?.path), "审稿已完成")}>运行审稿</button>
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="修订" icon={<RotateCcw size={18} />} />
          <div className="formGrid wide">
            <select value={reviewPath} onChange={(event) => setReviewPath(event.target.value)}>
              <option value="">选择 review</option>
              {reviews.map((review) => <option value={review.path} key={review.path}>{review.title}</option>)}
            </select>
            <button className="secondaryButton" disabled={busy || !reviewPath} onClick={() => runAction(() => createRevisionPlan(reviewPath, selectedProject?.path), "修订计划已创建")}>创建修订计划</button>
            <select value={revisionPath} onChange={(event) => setRevisionPath(event.target.value)}>
              <option value="">选择 revision</option>
              {revisions.map((revision) => <option value={revision.path} key={revision.path}>{revision.title}</option>)}
            </select>
            <button className="primaryButton" disabled={busy || !revisionPath} onClick={() => runAction(() => applyRevision(revisionPath, draftPath, selectedProject?.path), "修订已应用并复审")}>应用修订</button>
          </div>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="审稿与修订资产" icon={<FileSearch size={18} />} />
        <DataTable
          emptyText="暂无审稿资产"
          columns={["类型", "标题", "状态", "分数", "风险", "路径"]}
          rows={[...reviews, ...revisions].map((asset) => [
            asset.type,
            asset.title,
            <span className={statusClass(asset.asset_status || "")} key={`${asset.path}-status`}>{asset.asset_status || "-"}</span>,
            String(asset.score ?? "-"),
            asset.risk_level || "-",
            <span className="pathText" key={asset.path}>{asset.path}</span>
          ])}
        />
      </section>
    </FeatureShell>
  );
}
