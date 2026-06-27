"use client";

import { Archive, CalendarDays, CheckCircle2, FileSearch, Send, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createChapterAudit, createOriginalityReport, createPublishGate, createPublishingLog, createPublishingPlan, createReleasePackage, loadQualityData, preparePlatformRelease, type PublishingAdapterRow } from "./api";

export function QualityGatePage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [publishingAssets, setPublishingAssets] = useState<AssetRow[]>([]);
  const [publishingAdapters, setPublishingAdapters] = useState<PublishingAdapterRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [draftPath, setDraftPath] = useState("");
  const [chapterAuditPath, setChapterAuditPath] = useState("");
  const [publishGatePath, setPublishGatePath] = useState("");
  const [releasePackagePath, setReleasePackagePath] = useState("");
  const [publishingPlanPath, setPublishingPlanPath] = useState("");
  const [publishChannel, setPublishChannel] = useState("local");
  const [publishCadence, setPublishCadence] = useState("daily");
  const [publishStartDate, setPublishStartDate] = useState("");
  const [publishingLogStatus, setPublishingLogStatus] = useState("published");
  const [externalUrl, setExternalUrl] = useState("");
  const [adapterKey, setAdapterKey] = useState("manual_web");
  const [adapterDryRun, setAdapterDryRun] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const drafts = assets.filter((asset) => ["draft_chapter", "draft_version"].includes(asset.type));
  const qualityAssets = assets.filter((asset) => ["chapter_audit_report", "originality_report", "publish_gate_report", "release_package"].includes(asset.type));
  const audits = qualityAssets.filter((asset) => asset.type === "chapter_audit_report");
  const gates = qualityAssets.filter((asset) => asset.type === "publish_gate_report");
  const releasePackages = publishingAssets.filter((asset) => asset.type === "release_package");
  const publishingPlans = publishingAssets.filter((asset) => asset.type === "publishing_plan");
  const publishingLogs = publishingAssets.filter((asset) => asset.type === "publishing_log");
  const blockedPackages = releasePackages.filter((asset) => (asset.asset_status || asset.status) !== "ready");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows, publishingRows, adapterRows] = await loadQualityData(nextProjectId);
    setProjects(projectRows);
    setAssets(assetRows);
    setPublishingAssets(publishingRows);
    setPublishingAdapters(adapterRows);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setDraftPath((current) => current || assetRows.find((asset) => asset.type.includes("draft"))?.path || "");
    setChapterAuditPath((current) => current || assetRows.find((asset) => asset.type === "chapter_audit_report")?.path || "");
    setPublishGatePath((current) => current || assetRows.find((asset) => asset.type === "publish_gate_report")?.path || "");
    setReleasePackagePath((current) => current || publishingRows.find((asset) => asset.type === "release_package")?.path || "");
    setPublishingPlanPath((current) => current || publishingRows.find((asset) => asset.type === "publishing_plan")?.path || "");
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
        <Metric label="Release" value={String(releasePackages.length)} />
        <Metric label="发布计划" value={String(publishingPlans.length)} />
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
            <label className="selectWrap">
              <span>渠道</span>
              <input value={publishChannel} onChange={(event) => setPublishChannel(event.target.value)} />
            </label>
            <button className="primaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => createReleasePackage(draftPath, publishGatePath, selectedProject?.path, publishChannel), "Release package 已创建")}>打包发布</button>
          </div>
        </div>
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="发布计划" icon={<CheckCircle2 size={18} />} />
          <div className="formGrid wide">
            <select value={releasePackagePath} onChange={(event) => setReleasePackagePath(event.target.value)}>
              <option value="">选择 release package</option>
              {releasePackages.map((item) => <option value={item.path} key={item.path}>{item.title}</option>)}
            </select>
            <input placeholder="发布节奏 daily / weekly" value={publishCadence} onChange={(event) => setPublishCadence(event.target.value)} />
            <input placeholder="开始日期 YYYY-MM-DD" value={publishStartDate} onChange={(event) => setPublishStartDate(event.target.value)} />
            <button className="primaryButton" disabled={busy || !releasePackages.length} onClick={() => runAction(() => createPublishingPlan(releasePackages.slice(0, 20).map((item) => item.path), projectId, selectedProject?.path, publishChannel, publishCadence, publishStartDate), "发布计划已创建")}>生成发布计划</button>
            <select value={publishingPlanPath} onChange={(event) => setPublishingPlanPath(event.target.value)}>
              <option value="">选择 publishing plan</option>
              {publishingPlans.map((item) => <option value={item.path} key={item.path}>{item.title}</option>)}
            </select>
            <select value={publishingLogStatus} onChange={(event) => setPublishingLogStatus(event.target.value)}>
              <option value="published">published</option>
              <option value="scheduled">scheduled</option>
              <option value="failed">failed</option>
              <option value="rolled_back">rolled_back</option>
            </select>
            <input placeholder="外部发布链接，可空" value={externalUrl} onChange={(event) => setExternalUrl(event.target.value)} />
            <button className="secondaryButton" disabled={busy || !releasePackagePath} onClick={() => runAction(() => createPublishingLog(releasePackagePath, publishingPlanPath, publishChannel, publishingLogStatus, externalUrl), "发布日志已记录")}>记录发布</button>
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="发布日历" icon={<CalendarDays size={18} />} />
          <DataTable
            emptyText="暂无发布计划"
            columns={["计划", "下一发布", "队列", "平台", "门禁", "路径"]}
            rows={publishingPlans.map((asset) => [
              asset.title,
              asset.next_scheduled_at || "-",
              String(asset.chapter_queue_count ?? asset.calendar_count ?? 0),
              String(asset.platform_targets?.[0]?.channel ?? asset.channel ?? "-"),
              String(asset.gate_policy?.require_publish_gate_ready ? "required" : "-"),
              <span className="pathText" key={asset.path}>{asset.path}</span>
            ])}
          />
        </div>
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="发布版本库" icon={<Archive size={18} />} />
          <DataTable
            emptyText="暂无 release package"
            columns={["版本", "标题", "状态", "渠道", "草稿", "回滚"]}
            rows={releasePackages.map((asset) => [
              asset.release_version || asset.id || "-",
              asset.title,
              <span className={statusClass(asset.asset_status || asset.status || "")} key={`${asset.path}-status`}>{asset.asset_status || asset.status || "-"}</span>,
              asset.channel || "-",
              <span className="pathText" key={`${asset.path}-draft`}>{asset.draft_path || "-"}</span>,
              asset.rollback_available ? "available" : "package source"
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="平台规则与发布日志" icon={<Send size={18} />} />
          <div className="formGrid wide">
            <select value={adapterKey} onChange={(event) => setAdapterKey(event.target.value)}>
              {publishingAdapters.map((adapter) => <option value={adapter.key} key={adapter.key}>{adapter.label}</option>)}
            </select>
            <label className="checkboxLine">
              <input type="checkbox" checked={adapterDryRun} onChange={(event) => setAdapterDryRun(event.target.checked)} />
              dry-run
            </label>
            <button className="secondaryButton" disabled={busy || !releasePackagePath} onClick={() => runAction(() => preparePlatformRelease(releasePackagePath, publishingPlanPath, adapterKey, adapterDryRun, externalUrl), "平台发布 payload 已准备")}>准备平台发布</button>
          </div>
          <DataTable
            emptyText="暂无发布日志"
            columns={["日志状态", "渠道", "发布时间", "发布包", "链接", "回滚"]}
            rows={publishingLogs.map((asset) => [
              <span className={statusClass(asset.asset_status || asset.status || "")} key={`${asset.path}-status`}>{asset.asset_status || asset.status || "-"}</span>,
              asset.channel || "-",
              asset.published_at || asset.scheduled_at || "-",
              <span className="pathText" key={`${asset.path}-package`}>{asset.release_package_path || "-"}</span>,
              asset.external_url || "-",
              asset.rollback_available ? "available" : "-"
            ])}
          />
          <div className="publishingRuleList">
            {publishingAdapters.map((adapter) => (
              <div className="ruleCard" key={adapter.key}>
                <strong>{adapter.label}</strong>
                <span>{adapter.mode} / {adapter.external ? "external" : "local"} / {adapter.configured ? "configured" : "not configured"}</span>
                <small>{adapter.description}</small>
              </div>
            ))}
            {publishingAssets.filter((asset) => asset.platform_rules && Object.keys(asset.platform_rules).length).slice(0, 4).map((asset) => (
              <div className="ruleCard" key={`${asset.path}-rules`}>
                <strong>{asset.type}</strong>
                <span>{asset.channel || String(asset.platform_rules?.channel ?? "local")}</span>
                <small>{Object.entries(asset.platform_rules ?? {}).map(([key, value]) => `${key}: ${String(value)}`).join(" / ")}</small>
              </div>
            ))}
          </div>
        </div>
      </section>
      {blockedPackages.length ? <div className="warningLine">发布门禁提示：{blockedPackages.length} 个 release package 未 ready，发布计划会将其标记为 blocked。</div> : null}
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
