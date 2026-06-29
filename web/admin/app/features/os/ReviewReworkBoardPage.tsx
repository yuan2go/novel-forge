"use client";

import { CheckCircle2, FileText, RotateCcw, Send, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetDetail, AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  applyRevision,
  createPublishGate,
  createRevisionPlan,
  loadAssetDetail,
  loadReviewReworkData,
  runReview,
  runReviewReworkLoop,
  updateReviewIssue,
  type RuntimeCostDashboard,
  type RuntimeTraceTimeline
} from "./api";
import { assetOptions, compactJson, detailContent, parseIndexList, pathCell, selectedWorkspace } from "./helpers";

export function ReviewReworkBoardPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [traceTimeline, setTraceTimeline] = useState<RuntimeTraceTimeline | null>(null);
  const [costDashboard, setCostDashboard] = useState<RuntimeCostDashboard | null>(null);
  const [projectId, setProjectId] = useState("");
  const [draftPath, setDraftPath] = useState("");
  const [reviewPath, setReviewPath] = useState("");
  const [revisionPath, setRevisionPath] = useState("");
  const [contextBundlePath, setContextBundlePath] = useState("");
  const [issueIndexes, setIssueIndexes] = useState("");
  const [reviewDetail, setReviewDetail] = useState<AssetDetail | null>(null);
  const [actionResult, setActionResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows, traceData, costData] = await loadReviewReworkData(nextProjectId);
    setProjects(projectRows);
    setAssets(assetRows);
    setTraceTimeline(traceData);
    setCostDashboard(costData);
    const resolvedProject = nextProjectId || projectRows[0]?.project_id || "";
    setProjectId(resolvedProject);
    setDraftPath((current) => current || assetRows.find((asset) => ["draft_chapter", "draft_version"].includes(asset.type))?.path || "");
    setReviewPath((current) => current || assetRows.find((asset) => asset.type === "review_report")?.path || "");
    setRevisionPath((current) => current || assetRows.find((asset) => ["revision_plan", "revision_task"].includes(asset.type))?.path || "");
    setContextBundlePath((current) => current || assetRows.find((asset) => asset.type === "context_bundle")?.path || "");
  }

  async function loadReview(path = reviewPath) {
    if (!path) {
      setReviewDetail(null);
      return;
    }
    try {
      setReviewDetail(await loadAssetDetail(path));
    } catch {
      setReviewDetail(null);
    }
  }

  async function runAction(action: () => Promise<Record<string, unknown>>, message: string, reloadDetail = true) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action();
      setActionResult(result);
      setNotice(message);
      await refresh(projectId);
      if (reloadDetail) await loadReview(reviewPath);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  useEffect(() => {
    loadReview().catch(() => undefined);
  }, [reviewPath]);

  const workspacePath = selectedWorkspace(projects, projectId);
  const drafts = assetOptions(assets, ["draft_chapter", "draft_version"]);
  const reviews = assetOptions(assets, ["review_report", "chapter_audit_report", "quality_score_report"]);
  const revisions = assetOptions(assets, ["revision_plan", "revision_task", "editor_patch", "draft_diff_report"]);
  const contextBundles = assetOptions(assets, ["context_bundle"]);
  const publishGates = assetOptions(assets, ["publish_gate_report", "release_package"]);
  const content = detailContent(reviewDetail);
  const issues = useMemo(() => extractIssues(content), [content]);
  const openIssues = issues.filter((issue) => !["resolved", "accepted", "waived"].includes(String(issue.status || "")));
  const traceSpans = traceTimeline?.summary?.span_count ?? 0;
  const costSummary = costDashboard?.asset?.content?.summary || {};

  return (
    <FeatureShell title="Review Rework Board" subtitle="打通 review_issue -> revision_task -> editor_patch -> apply patch -> draft_version -> re-review -> publish gate 的返工闭环。" eyebrow="OS Runtime">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Drafts" value={String(drafts.length)} />
        <Metric label="Reviews" value={String(reviews.length)} />
        <Metric label="Open Issues" value={String(openIssues.length)} />
        <Metric label="Revisions" value={String(revisions.length)} />
        <Metric label="Publish Gates" value={String(publishGates.length)} />
        <Metric label="Trace Spans" value={String(traceSpans)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Review Inputs" icon={<FileText size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={draftPath} onChange={(event) => setDraftPath(event.target.value)}>
              <option value="">选择 Draft</option>
              {drafts.map((draft) => <option value={draft.path} key={draft.path}>{draft.type}: {draft.title}</option>)}
            </select>
            <select value={reviewPath} onChange={(event) => setReviewPath(event.target.value)}>
              <option value="">选择 Review</option>
              {reviews.map((review) => <option value={review.path} key={review.path}>{review.type}: {review.title}</option>)}
            </select>
            <select value={contextBundlePath} onChange={(event) => setContextBundlePath(event.target.value)}>
              <option value="">选择 Context Bundle，可选</option>
              {contextBundles.map((bundle) => <option value={bundle.path} key={bundle.path}>{bundle.title}</option>)}
            </select>
            <input value={issueIndexes} onChange={(event) => setIssueIndexes(event.target.value)} placeholder="issue indexes，例如 0,2,4；留空处理全部" />
            <button className="primaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => runReview(draftPath, workspacePath), "审稿已生成")}>
              <CheckCircle2 size={16} />Run Review
            </button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="Rework Controls" icon={<RotateCcw size={18} />} />
          <div className="formGrid">
            <select value={revisionPath} onChange={(event) => setRevisionPath(event.target.value)}>
              <option value="">选择 Revision / Patch</option>
              {revisions.map((revision) => <option value={revision.path} key={revision.path}>{revision.type}: {revision.title}</option>)}
            </select>
            <button className="secondaryButton" disabled={busy || !reviewPath} onClick={() => runAction(() => createRevisionPlan(reviewPath, workspacePath), "revision_plan 已创建")}>
              <FileText size={16} />Create Plan
            </button>
            <button className="primaryButton" disabled={busy || !reviewPath} onClick={() => runAction(() => runReviewReworkLoop({
              review_path: reviewPath,
              draft_path: draftPath,
              issue_indexes: parseIndexList(issueIndexes),
              context_bundle_path: contextBundlePath,
              workspace_path: workspacePath
            }), "review_rework_loop 已完成")}>
              <RotateCcw size={16} />Rework Loop
            </button>
            <button className="secondaryButton" disabled={busy || !revisionPath} onClick={() => runAction(() => applyRevision(revisionPath, draftPath, workspacePath), "修订已应用并复审")}>
              <CheckCircle2 size={16} />Apply + Re-review
            </button>
            <button className="primaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => createPublishGate(draftPath, workspacePath), "publish gate 已运行", false)}>
              <Send size={16} />Publish Gate
            </button>
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Review Issues" icon={<ShieldCheck size={18} />} />
        <DataTable
          emptyText="暂无 review issue"
          columns={["Index", "严重度", "状态", "问题", "建议", "操作"]}
          rows={issues.slice(0, 80).map((issue) => [
            String(issue.index),
            <span className={statusClass(String(issue.severity || issue.risk || ""))} key={`severity-${issue.index}`}>{String(issue.severity || issue.risk || "-")}</span>,
            <span className={statusClass(String(issue.status || ""))} key={`status-${issue.index}`}>{String(issue.status || "-")}</span>,
            String(issue.message || issue.issue || issue.title || "-"),
            String(issue.recommendation || issue.suggestion || "-"),
            <div className="actionRow compact" key={`actions-${issue.index}`}>
              <button className="secondaryButton" disabled={busy || !reviewPath} onClick={() => runAction(() => updateReviewIssue(reviewPath, Number(issue.index), "resolved", "resolved from Review Rework Board"), "issue 已标记 resolved")}>Resolved</button>
              <button className="secondaryButton" disabled={busy || !reviewPath} onClick={() => runAction(() => updateReviewIssue(reviewPath, Number(issue.index), "needs_revision", "sent to rework from Review Rework Board"), "issue 已标记 needs_revision")}>Rework</button>
            </div>
          ])}
        />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Revision / Patch Assets" icon={<RotateCcw size={18} />} />
          <DataTable
            emptyText="暂无 revision 资产"
            columns={["类型", "标题", "状态", "分数/风险", "路径"]}
            rows={revisions.slice(0, 80).map((asset) => [
              asset.type,
              asset.title,
              <span className={statusClass(asset.status || asset.asset_status || "")} key={`${asset.path}-status`}>{asset.status || asset.asset_status || "-"}</span>,
              `${String(asset.score ?? "-")} / ${asset.risk_level || "-"}`,
              pathCell(asset.path, asset.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Publish Gate Evidence" icon={<Send size={18} />} />
          <div className="summaryBand">
            <Metric label="Cost" value={String(costSummary.total_cost ?? 0)} />
            <Metric label="Model Calls" value={String(costSummary.model_call_count ?? 0)} />
            <Metric label="Quality" value={String(costSummary.average_quality_score ?? 0)} />
            <Metric label="Last Action" value={String(actionResult?.status || actionResult?.path || "-")} />
          </div>
          <DataTable
            emptyText="暂无 publish gate"
            columns={["类型", "标题", "状态", "风险", "路径"]}
            rows={publishGates.slice(0, 40).map((asset) => [
              asset.type,
              asset.title,
              <span className={statusClass(asset.status || asset.asset_status || "")} key={`${asset.path}-status`}>{asset.status || asset.asset_status || "-"}</span>,
              asset.risk_level || "-",
              pathCell(asset.path, asset.path)
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Review Detail" icon={<FileText size={18} />} />
          <pre className="jsonPreview">{JSON.stringify(content, null, 2)}</pre>
        </div>
        <div className="panel">
          <PanelHeader title="Action Result" icon={<CheckCircle2 size={18} />} />
          <pre className="jsonPreview">{compactJson(actionResult, 2000)}</pre>
        </div>
      </section>
    </FeatureShell>
  );
}

function extractIssues(content: Record<string, unknown>): Array<Record<string, unknown> & { index: number }> {
  const candidates = [
    content.issues,
    content.review_issues,
    content.findings,
    content.revision_tasks,
    content.blockers,
    content.warnings
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      return candidate
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
        .map((item, index) => ({ ...item, index: Number(item.index ?? item.issue_index ?? index) }));
    }
  }
  const checks = content.checks;
  if (checks && typeof checks === "object") {
    return Object.entries(checks as Record<string, unknown>).map(([key, value], index) => ({
      index,
      title: key,
      status: value,
      message: `${key}: ${String(value)}`
    }));
  }
  return [];
}
