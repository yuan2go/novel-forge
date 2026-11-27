"use client";

import { FileSearch, RotateCcw, UploadCloud, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { BatchItem, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { loadBatchData, regenerateBatchHandoff, retryBatchItem, runBatchDeconstruct, voidBatchHandoff } from "./api";

export function BatchProcessingPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [items, setItems] = useState<BatchItem[]>([]);
  const [projectId, setProjectId] = useState("");
  const [inputPath, setInputPath] = useState("");
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState("claude_code");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const failed = items.filter((item) => item.status === "failed");
  const waiting = items.filter((item) => item.status === "waiting_handoff" || item.handoff_status === "waiting_handoff");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, itemRows] = await loadBatchData(nextProjectId);
    setProjects(projectRows);
    setItems(itemRows);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
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
    <FeatureShell title="批量拆书处理中心" subtitle="批量导入本地文件，支持自动拆解和 Claude Code handoff 模式，并提供 item 级失败恢复。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="Items" value={String(items.length)} />
        <Metric label="失败" value={String(failed.length)} />
        <Metric label="等待 Handoff" value={String(waiting.length)} />
        <Metric label="模式" value={mode} />
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="批量导入" icon={<UploadCloud size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <input value={inputPath} onChange={(event) => setInputPath(event.target.value)} placeholder="本地文件或目录路径" />
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="批处理标题" />
            <select value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="claude_code">Claude Code 解析模式</option>
              <option value="auto">自动流水线</option>
            </select>
            <button className="primaryButton" disabled={busy || !inputPath.trim()} onClick={() => runAction(() => runBatchDeconstruct(inputPath, title, selectedProject?.path, mode), "批处理任务已提交")}>提交</button>
          </div>
          <p className="previewText">Claude Code 模式会在自动清洗后为 item 生成 handoff，并停在 waiting_handoff 等待人工完成输出绑定。</p>
        </div>
        <div className="panel">
          <PanelHeader title="恢复入口" icon={<RotateCcw size={18} />} />
          <DataTable
            emptyText="暂无失败 item"
            columns={["状态", "来源", "错误", "操作"]}
            rows={failed.slice(0, 8).map((item) => [
              item.status,
              item.source_name || item.source_path,
              item.error_message || "-",
              <button className="secondaryButton tableButton" disabled={busy} key={item.path} onClick={() => runAction(() => retryBatchItem(item.path, selectedProject?.path), "item 已重试")}>重试</button>
            ])}
          />
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="Batch Items" icon={<FileSearch size={18} />} />
        <DataTable
          emptyText="暂无 batch item"
          columns={["状态", "模式", "源文件", "Handoff", "重试", "更新时间", "操作"]}
          rows={items.map((item) => [
            <span className={statusClass(item.status)} key={`${item.path}-status`}>{item.status}</span>,
            item.analysis_mode || "-",
            item.source_name || item.source_path,
            item.handoff_path ? <span className="pathText" key={`${item.path}-handoff`}>{item.handoff_path}</span> : "-",
            String(item.retry_count ?? 0),
            item.updated_at || "-",
            <div className="studioActions" key={`${item.path}-actions`}>
              <button className="secondaryButton tableButton" disabled={busy} onClick={() => runAction(() => retryBatchItem(item.path, selectedProject?.path), "item 已重试")}>重试</button>
              <button className="secondaryButton tableButton" disabled={busy} onClick={() => runAction(() => regenerateBatchHandoff(item.path, selectedProject?.path), "handoff 已重建")}><Workflow size={15} />重建</button>
              <button className="secondaryButton tableButton dangerButton" disabled={busy} onClick={() => runAction(() => voidBatchHandoff(item.path, selectedProject?.path), "handoff 已作废")}>作废</button>
            </div>
          ])}
        />
      </section>
    </FeatureShell>
  );
}
