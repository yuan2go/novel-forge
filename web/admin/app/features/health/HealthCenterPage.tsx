"use client";

import { Activity, Archive, Database, RefreshCw, RotateCcw, Search, UploadCloud, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { BackupRow, FeatureAssetRow, MinioStatus, ModuleCompletionReport, ProjectHealthReport, ProjectRow, QdrantSearchResult } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { archiveEvents, createBackup, loadHealthData, qdrantSearch, rebuildQdrantIndex, restoreBackup, runFailureDrill, runLongChainAcceptance, syncMinio } from "./api";

export function HealthCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [report, setReport] = useState<ProjectHealthReport | null>(null);
  const [backups, setBackups] = useState<BackupRow[]>([]);
  const [minioStatus, setMinioStatus] = useState<MinioStatus | null>(null);
  const [operationReports, setOperationReports] = useState<FeatureAssetRow[]>([]);
  const [moduleCompletion, setModuleCompletion] = useState<ModuleCompletionReport | null>(null);
  const [qdrantResult, setQdrantResult] = useState<QdrantSearchResult | null>(null);
  const [projectId, setProjectId] = useState("");
  const [restorePath, setRestorePath] = useState("");
  const [qdrantQuery, setQdrantQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, healthReport, backupRows, objectStatus, opsRows, completionReport] = await loadHealthData(nextProjectId);
    setProjects(projectRows);
    setReport(healthReport);
    setBackups(backupRows);
    setMinioStatus(objectStatus);
    setOperationReports(opsRows);
    setModuleCompletion(completionReport);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
  }

  async function runAction(action: () => Promise<unknown>, message: string, refreshAfter = true) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      await action();
      setNotice(message);
      if (refreshAfter) await refresh();
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
    <FeatureShell title="健康检查中心" subtitle="Postgres、Celery、Qdrant、MinIO、项目隔离、备份恢复和事件归档统一检查。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="范围问题" value={String(report?.summary.scope_issue_count ?? 0)} />
        <Metric label="失败任务" value={String(report?.summary.failed_task_count ?? 0)} />
        <Metric label="待处理 Handoff" value={String(report?.summary.pending_handoff_count ?? 0)} />
        <Metric label="资产" value={String(report?.summary.asset_count ?? 0)} />
        <Metric label="演练报告" value={String(operationReports.length)} />
        <Metric label="模块完成度" value={`${moduleCompletion?.summary.average_completion ?? 0}%`} />
      </section>

      <section className="panel">
        <PanelHeader title="项目健康" icon={<Activity size={18} />} />
        <div className="formGrid">
          <select value={projectId} onChange={(event) => refresh(event.target.value)}>
            <option value="">全局</option>
            {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
          </select>
          <button className="secondaryButton" disabled={busy} onClick={() => refresh()}>
            <RefreshCw size={18} />
            刷新
          </button>
        </div>
        <div className="serviceGrid">
          <article className="serviceCard">
            <div className="serviceTitle"><Database size={17} /><span>PostgreSQL</span></div>
            <span className={report?.postgres.ready ? "badge ok" : report?.postgres.strict ? "badge warn" : "badge muted"}>{report?.postgres.ready ? "ready" : report?.postgres.strict ? "blocked" : "relaxed"}</span>
          </article>
          <article className="serviceCard">
            <div className="serviceTitle"><Workflow size={17} /><span>Celery</span></div>
            <span className={report?.celery.healthy ? "badge ok" : "badge muted"}>{report?.celery.healthy ? "healthy" : "offline"}</span>
          </article>
          <article className="serviceCard">
            <div className="serviceTitle"><Search size={17} /><span>Embedding / Qdrant</span></div>
            <span className={report?.embedding.ok ? "badge ok" : "badge warn"}>{report?.embedding.ok ? (report.embedding.model ?? "ready") : (report?.embedding.missing_env_vars?.join(", ") || report?.embedding.error || "not ready")}</span>
            <button className="secondaryButton tableButton" disabled={busy} onClick={() => runAction(rebuildQdrantIndex, "Qdrant 索引已重建")}>重建索引</button>
          </article>
          <article className="serviceCard">
            <div className="serviceTitle"><UploadCloud size={17} /><span>MinIO</span></div>
            <span className={minioStatus?.available ? "badge ok" : minioStatus?.configured ? "badge warn" : "badge muted"}>{minioStatus?.available ? minioStatus.bucket : minioStatus?.configured ? "offline" : "not checked"}</span>
            <button className="secondaryButton tableButton" disabled={busy} onClick={() => runAction(syncMinio, "MinIO 已同步")}>同步</button>
          </article>
        </div>
        <div className="formGrid wide">
          <input value={qdrantQuery} onChange={(event) => setQdrantQuery(event.target.value)} placeholder="向量检索查询" />
          <button className="secondaryButton" disabled={busy || !qdrantQuery.trim()} onClick={() => runAction(async () => setQdrantResult(await qdrantSearch(qdrantQuery, projectId)), "检索完成", false)}>
            <Search size={18} />
            检索
          </button>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="V6/V7 模块完成度" icon={<Activity size={18} />} />
        <section className="summaryBand manuscriptSummary compactBand">
          <Metric label="模块数" value={String(moduleCompletion?.summary.module_count ?? 0)} />
          <Metric label="完整闭环" value={String(moduleCompletion?.summary.completed_count ?? 0)} />
          <Metric label="部分闭环" value={String(moduleCompletion?.summary.partial_count ?? 0)} />
          <Metric label="阻塞项" value={String(moduleCompletion?.summary.blocking_count ?? 0)} />
        </section>
        <DataTable
          emptyText="暂无模块完成度报告"
          columns={["模块", "状态", "完成度", "代码证据", "运行资产", "剩余缺口", "验收判断"]}
          rows={(moduleCompletion?.modules ?? []).map((module) => [
            module.name,
            <span className={statusClass(module.status)} key={`${module.key}-status`}>{module.status}</span>,
            `${module.completion_percent}%`,
            `${module.code_score}%`,
            `${module.runtime_asset_score}%`,
            module.remaining.slice(0, 2).join(" / ") || "-",
            module.acceptance
          ])}
        />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="故障演练 / 长链路验收" icon={<Workflow size={18} />} />
          <div className="studioActions">
            <button className="primaryButton" disabled={busy} onClick={() => runAction(runFailureDrill, "本地故障演练报告已生成")}>故障演练</button>
            <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => runLongChainAcceptance(projectId, 10), "10 章长链路验收已生成")}>10章验收</button>
            <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => runLongChainAcceptance(projectId, 50), "50 章长链路验收已生成")}>50章验收</button>
          </div>
          <DataTable
            emptyText="暂无运维报告"
            columns={["类型", "标题", "状态", "建议", "路径"]}
            rows={operationReports.map((row) => [
              row.type,
              row.title,
              <span className={row.status === "failed" || row.status === "block" ? "badge warn" : row.status === "passed" || row.status === "pass" ? "badge ok" : "badge muted"} key={`${row.path}-status`}>{row.status || "-"}</span>,
              row.recommendation || row.summary || "-",
              <span className="pathText" key={row.path}>{row.path}</span>
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="向量命中" icon={<Search size={18} />} />
          <DataTable
            emptyText="暂无检索结果"
            columns={["排名", "分数", "标题", "解释", "资产"]}
            rows={(qdrantResult?.results ?? []).map((hit) => [
              String(hit.rank),
              String(hit.score ?? ""),
              hit.title || hit.path,
              hit.explanation?.reason || "",
              <span className="pathText" key={hit.path}>{hit.path}</span>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="最近失败" icon={<Activity size={18} />} />
          <DataTable
            emptyText="无失败"
            columns={["类型", "步骤", "状态", "资产"]}
            rows={(report?.recent_failures ?? []).map((task) => [
              task.task_type,
              task.step,
              <span className={task.status === "failed" ? "badge warn" : "badge muted"} key={`health-${task.path}`}>{task.status}</span>,
              <span className="pathText" key={task.path}>{task.path}</span>
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="本地备份 / 恢复" icon={<Archive size={18} />} />
          <div className="formGrid wide">
            <button className="primaryButton" disabled={busy} onClick={() => runAction(createBackup, "本地备份已创建")}>
              <Archive size={18} />
              创建备份
            </button>
            <input value={restorePath} onChange={(event) => setRestorePath(event.target.value)} placeholder="data/backups/local-prod/...zip" />
            <button className="secondaryButton dangerButton" disabled={busy || !restorePath.trim()} onClick={() => runAction(() => restoreBackup(restorePath), "本地备份已恢复")}>
              <RotateCcw size={18} />
              恢复
            </button>
            <button className="secondaryButton" disabled={busy} onClick={() => runAction(archiveEvents, "旧事件已归档")}>
              <Archive size={18} />
              归档旧事件
            </button>
          </div>
          <DataTable
            emptyText="暂无备份"
            columns={["时间", "大小", "路径"]}
            rows={backups.map((backup) => [backup.created_at, String(backup.size_bytes), <button className="linkButton" onClick={() => setRestorePath(backup.path)} key={backup.path}>{backup.path}</button>])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="MinIO 对象" icon={<UploadCloud size={18} />} />
          <DataTable
            emptyText="暂无对象状态"
            columns={["分类", "状态", "大小", "对象", "资产"]}
            rows={(minioStatus?.objects ?? []).map((object) => [
              object.category,
              <span className={object.exists ? "badge ok" : "badge muted"} key={`exists-${object.path}`}>{object.exists ? "synced" : "local"}</span>,
              String(object.size || ""),
              <span className="pathText" key={`object-${object.path}`}>{object.object_name}</span>,
              <span className="pathText" key={object.path}>{object.path}</span>
            ])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}
