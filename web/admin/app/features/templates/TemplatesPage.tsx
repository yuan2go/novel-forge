"use client";

import { Library, PenLine, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { createCreativeAsset, loadAssetsData } from "../assets/api";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";

const templateTypes = ["writing_template", "craft_template", "review_rule_pack"];

export function TemplatesPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [newType, setNewType] = useState(templateTypes[0]);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const templates = assets.filter((asset) => templateTypes.includes(asset.type));

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows] = await loadAssetsData(nextProjectId);
    setProjects(projectRows);
    setAssets(assetRows);
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
    <FeatureShell title="写作模板中心" subtitle="维护冲突模板、节奏模板、钩子模板、修辞模板和审稿规则包，并作为生产与审稿稳定输入。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="模板总数" value={String(templates.length)} />
        <Metric label="写作模板" value={String(templates.filter((row) => row.type === "writing_template").length)} />
        <Metric label="技法模板" value={String(templates.filter((row) => row.type === "craft_template").length)} />
        <Metric label="审稿规则" value={String(templates.filter((row) => row.type === "review_rule_pack").length)} />
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="创建模板" icon={<PenLine size={18} />} />
          <div className="formGrid">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={newType} onChange={(event) => setNewType(event.target.value)}>
              {templateTypes.map((type) => <option value={type} key={type}>{type}</option>)}
            </select>
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="模板标题" />
            <button className="primaryButton" disabled={busy || !title.trim()} onClick={() => runAction(() => createCreativeAsset(newType, title, projectId, selectedProject?.path), "模板已创建")}>
              <Save size={18} />
              创建
            </button>
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="模板使用边界" icon={<Library size={18} />} />
          <ul className="plainList">
            <li>模板只能沉淀抽象结构、节奏、冲突、钩子和审稿维度。</li>
            <li>不得保存受保护作品的原文、具体角色配置或可识别桥段。</li>
            <li>正文生成和审稿都应引用模板资产路径，便于复盘和回滚。</li>
          </ul>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="模板资产" icon={<Library size={18} />} />
        <DataTable
          emptyText="暂无模板"
          columns={["类型", "标题", "状态", "风险", "路径"]}
          rows={templates.map((asset) => [
            asset.type,
            asset.title,
            <span className={statusClass(asset.asset_status || "")} key={`${asset.path}-status`}>{asset.asset_status || "-"}</span>,
            asset.risk_level || "-",
            <span className="pathText" key={asset.path}>{asset.path}</span>
          ])}
        />
      </section>
    </FeatureShell>
  );
}
