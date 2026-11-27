"use client";

import { BrainCircuit, DatabaseZap, Settings2, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { FeatureAssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createPromptVersion, createSettingsProfile, loadSettingsData, type PostgresStrict, type SystemHealth } from "./api";

export function SettingsCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [settingsAssets, setSettingsAssets] = useState<FeatureAssetRow[]>([]);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [postgres, setPostgres] = useState<PostgresStrict | null>(null);
  const [projectId, setProjectId] = useState("");
  const [provider, setProvider] = useState("mock");
  const [model, setModel] = useState("mock-model");
  const [profileTitle, setProfileTitle] = useState("Local Production Profile");
  const [promptId, setPromptId] = useState("draft.chapter");
  const [promptVersion, setPromptVersion] = useState("v1");
  const [promptTemplate, setPromptTemplate] = useState("Write with project context, continuity bible, style profile, and quality standard.");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows, healthStatus, postgresStatus] = await loadSettingsData(nextProjectId);
    setProjects(projectRows);
    setSettingsAssets(assetRows);
    setHealth(healthStatus);
    setPostgres(postgresStatus);
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
    <FeatureShell title="设置中心" subtitle="模型配置、Prompt 版本、平台规则、审稿规则、存储配置和严格本地生产模式统一管理。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="模型 Provider" value={String(Object.keys(health?.model_providers ?? {}).length)} />
        <Metric label="Postgres Strict" value={postgres?.strict ? "on" : "off"} />
        <Metric label="Postgres Ready" value={postgres?.ready ? "ready" : "not ready"} />
        <Metric label="配置资产" value={String(settingsAssets.length)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="运行配置 Profile" icon={<Settings2 size={18} />} />
          <div className="formGrid">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <input value={profileTitle} onChange={(event) => setProfileTitle(event.target.value)} />
            <input value={provider} onChange={(event) => setProvider(event.target.value)} />
            <input value={model} onChange={(event) => setModel(event.target.value)} />
            <button className="primaryButton" disabled={busy || !profileTitle.trim()} onClick={() => runAction(() => createSettingsProfile({ title: profileTitle, workspacePath: selectedProject?.path, provider, model, strict: true }), "设置 Profile 已创建")}>保存 Profile</button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="Prompt 版本" icon={<BrainCircuit size={18} />} />
          <div className="formGrid">
            <input value={promptId} onChange={(event) => setPromptId(event.target.value)} />
            <input value={promptVersion} onChange={(event) => setPromptVersion(event.target.value)} />
            <input value="draft_chapter" readOnly />
          </div>
          <textarea value={promptTemplate} onChange={(event) => setPromptTemplate(event.target.value)} rows={6} />
          <button className="primaryButton" disabled={busy || !promptId.trim()} onClick={() => runAction(() => createPromptVersion(promptId, promptVersion, "draft_chapter", promptTemplate), "Prompt 版本已创建")}>保存 Prompt</button>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="服务状态" icon={<DatabaseZap size={18} />} />
          <DataTable
            columns={["服务", "状态"]}
            rows={Object.entries(health?.configured_services ?? {}).map(([service, ok]) => [
              service,
              <span className={statusClass(ok ? "ready" : "failed")} key={service}>{ok ? "ready" : "missing"}</span>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="配置资产" icon={<SlidersHorizontal size={18} />} />
          <DataTable
            emptyText="暂无配置资产"
            columns={["类型", "标题", "状态", "路径"]}
            rows={settingsAssets.map((asset) => [
              asset.type,
              asset.title,
              <span className={statusClass(asset.status || "")} key={asset.path}>{asset.status || "-"}</span>,
              <span className="pathText" key={`${asset.path}-path`}>{asset.path}</span>
            ])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}
