"use client";

import { Network, PackageCheck, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createContextBuildPlan, createContextBundle, loadContextData, type ContextAssetRow } from "./api";

export function ContextBuilderPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [contextAssets, setContextAssets] = useState<ContextAssetRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [buildPlanPath, setBuildPlanPath] = useState("");
  const [query, setQuery] = useState("人物 世界观 前文摘要 知识卡 伏笔 素材卡");
  const [topK, setTopK] = useState("8");
  const [tokenBudget, setTokenBudget] = useState("6000");
  const [backend, setBackend] = useState("auto");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const plans = contextAssets.filter((asset) => asset.type === "context_build_plan");
  const bundles = contextAssets.filter((asset) => asset.type === "context_bundle");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, contextRows, assetRows] = await loadContextData(nextProjectId);
    setProjects(projectRows);
    setContextAssets(contextRows);
    setAssets(assetRows);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setTargetPath((current) => current || assetRows[0]?.path || "");
    setBuildPlanPath((current) => current || contextRows.find((row) => row.type === "context_build_plan")?.path || "");
  }

  async function runAction(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action() as { path?: string };
      if (result?.path) setBuildPlanPath(result.path);
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
    <FeatureShell title="上下文构建器" subtitle="按项目检索人物、世界观、前文摘要、知识卡、伏笔和素材卡，生成可追溯 context bundle。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="Build Plan" value={String(plans.length)} />
        <Metric label="Bundle" value={String(bundles.length)} />
        <Metric label="候选资产" value={String(assets.length)} />
        <Metric label="默认后端" value={backend} />
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="构建计划" icon={<Search size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={targetPath} onChange={(event) => setTargetPath(event.target.value)}>
              <option value="">选择目标资产</option>
              {assets.map((asset) => <option value={asset.path} key={asset.path}>{asset.type}: {asset.title}</option>)}
            </select>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="query" />
            <input value={topK} onChange={(event) => setTopK(event.target.value)} placeholder="top k" />
            <input value={tokenBudget} onChange={(event) => setTokenBudget(event.target.value)} placeholder="token budget" />
            <select value={backend} onChange={(event) => setBackend(event.target.value)}>
              <option value="auto">auto</option>
              <option value="qdrant">qdrant</option>
              <option value="local">local</option>
            </select>
            <button className="primaryButton" disabled={busy || !targetPath} onClick={() => runAction(() => createContextBuildPlan(targetPath, query, Number(topK) || 8, Number(tokenBudget) || 6000, backend, selectedProject?.path), "上下文计划已创建")}>
              <Network size={18} />
              创建计划
            </button>
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="打包上下文" icon={<PackageCheck size={18} />} />
          <div className="formGrid">
            <select value={buildPlanPath} onChange={(event) => setBuildPlanPath(event.target.value)}>
              <option value="">选择 build plan</option>
              {plans.map((plan) => <option value={plan.path} key={plan.path}>{plan.title}</option>)}
            </select>
            <button className="primaryButton" disabled={busy || !buildPlanPath} onClick={() => runAction(() => createContextBundle(buildPlanPath, 12), "Context bundle 已创建")}>创建 Bundle</button>
          </div>
          <p className="previewText">Bundle 会记录 retrieved_context、top-k、query、ranker、backend 和 source asset ids。</p>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="上下文资产" icon={<Network size={18} />} />
        <DataTable
          emptyText="暂无上下文资产"
          columns={["类型", "标题", "Backend", "Ranker", "Token", "来源数", "状态", "路径"]}
          rows={contextAssets.map((asset) => [
            asset.type,
            asset.title,
            asset.retrieval_backend || "-",
            asset.ranker || "-",
            String(asset.token_estimate ?? "-"),
            String(asset.source_count ?? "-"),
            <span className={statusClass(asset.status || "")} key={`${asset.path}-status`}>{asset.status || "-"}</span>,
            <span className="pathText" key={asset.path}>{asset.path}</span>
          ])}
        />
      </section>
    </FeatureShell>
  );
}
