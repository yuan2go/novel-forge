"use client";

import { Database, Edit3, Library, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetDetail, AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createCreativeAsset, loadAssetDetail, loadAssetsData, saveAssetContent, type CreativeLibrary } from "./api";

const assetTypes = [
  "genre_market_profile",
  "material_card",
  "knowledge_card",
  "continuity_bible",
  "style_profile",
  "quality_standard_profile",
  "writing_template",
  "craft_template",
  "review_rule_pack"
];

export function AssetsCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [libraries, setLibraries] = useState<CreativeLibrary[]>([]);
  const [projectId, setProjectId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [detail, setDetail] = useState<AssetDetail | null>(null);
  const [draftContent, setDraftContent] = useState("{}");
  const [newType, setNewType] = useState(assetTypes[0]);
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const byType = useMemo(() => {
    return assets.reduce<Record<string, number>>((counts, asset) => {
      counts[asset.type] = (counts[asset.type] ?? 0) + 1;
      return counts;
    }, {});
  }, [assets]);

  async function refresh(nextProjectId = projectId, nextKeyword = keyword) {
    const [projectRows, assetRows, libraryRows] = await loadAssetsData(nextProjectId, nextKeyword);
    const selected = nextProjectId || projectRows[0]?.project_id || "";
    setProjects(projectRows);
    setProjectId(selected);
    setAssets(assetRows);
    setLibraries(libraryRows);
    setSelectedPath((current) => current || assetRows[0]?.path || "");
  }

  async function selectAsset(path: string) {
    setSelectedPath(path);
    setError("");
    try {
      const nextDetail = await loadAssetDetail(path);
      setDetail(nextDetail);
      setDraftContent(JSON.stringify(nextDetail.asset.content ?? {}, null, 2));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
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

  useEffect(() => {
    if (selectedPath) {
      selectAsset(selectedPath);
    }
  }, [selectedPath]);

  return (
    <FeatureShell title="创作资产工作台" subtitle="题材库、素材库、知识库、设定书、文风、写作模板和精品标准统一进入 schema-backed 资产工作台。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="资产总数" value={String(assets.length)} />
        <Metric label="知识卡" value={String(byType.knowledge_card ?? 0)} />
        <Metric label="素材卡" value={String(byType.material_card ?? 0)} />
        <Metric label="标准/文风" value={String((byType.quality_standard_profile ?? 0) + (byType.style_profile ?? 0))} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="筛选与创建" icon={<Search size={18} />} />
          <div className="formGrid">
            <label className="selectWrap">
              <span>项目</span>
              <select value={projectId} onChange={(event) => refresh(event.target.value)}>
                <option value="">全局</option>
                {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
              </select>
            </label>
            <label className="selectWrap">
              <span>关键词</span>
              <input value={keyword} onChange={(event) => setKeyword(event.target.value)} onBlur={() => refresh(projectId, keyword)} />
            </label>
            <button className="secondaryButton" onClick={() => refresh(projectId, keyword)} disabled={busy}>搜索</button>
          </div>
          <div className="formGrid">
            <select value={newType} onChange={(event) => setNewType(event.target.value)}>
              {assetTypes.map((type) => <option value={type} key={type}>{type}</option>)}
            </select>
            <input placeholder="资产标题" value={newTitle} onChange={(event) => setNewTitle(event.target.value)} />
            <button className="primaryButton" disabled={busy || !newTitle.trim()} onClick={() => runAction(() => createCreativeAsset(newType, newTitle.trim(), projectId, selectedProject?.path), "资产已创建")}>创建</button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="资产库分布" icon={<Library size={18} />} />
          <DataTable
            emptyText="暂无资产库"
            columns={["资产库", "类型", "数量"]}
            rows={libraries.map((library) => [
              library.title,
              library.asset_types.join(", "),
              String(library.assets.length)
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="资产列表" icon={<Database size={18} />} />
          <DataTable
            emptyText="暂无资产"
            columns={["类型", "标题", "状态", "风险", "路径"]}
            rows={assets.map((asset) => [
              asset.type,
              <button className="linkButton" key={asset.path} onClick={() => setSelectedPath(asset.path)}>{asset.title || asset.id}</button>,
              <span className={statusClass(asset.asset_status || "")} key={`${asset.path}-status`}>{asset.asset_status || "-"}</span>,
              asset.risk_level || "-",
              <span className="pathText" key={`${asset.path}-path`}>{asset.path}</span>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="深度编辑" icon={<Edit3 size={18} />} />
          {detail ? (
            <>
              <div className="summaryBand">
                <Metric label="类型" value={detail.summary.type} />
                <Metric label="标题" value={detail.summary.title || detail.summary.id} />
                <Metric label="风险" value={detail.summary.risk_level || "-"} />
              </div>
              <textarea value={draftContent} onChange={(event) => setDraftContent(event.target.value)} rows={18} />
              <button
                className="primaryButton"
                disabled={busy}
                onClick={() => runAction(() => saveAssetContent(detail.path, JSON.parse(draftContent) as Record<string, unknown>), "资产内容已保存")}
              >
                保存内容
              </button>
            </>
          ) : (
            <p className="muted">选择资产后可编辑 schema content。</p>
          )}
        </div>
      </section>
    </FeatureShell>
  );
}
