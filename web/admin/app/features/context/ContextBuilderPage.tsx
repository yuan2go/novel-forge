"use client";

import { Network, PackageCheck, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createContextBuildPlan, createContextBundle, diffContextBundles, loadContextData, type ContextAssetRow, type ContextBundleDiff } from "./api";

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
  const [contextProfile, setContextProfile] = useState("chapter_generation");
  const [diffLeftPath, setDiffLeftPath] = useState("");
  const [diffRightPath, setDiffRightPath] = useState("");
  const [bundleDiff, setBundleDiff] = useState<ContextBundleDiff | null>(null);
  const [disabledPaths, setDisabledPaths] = useState<string[]>([]);
  const [priorityText, setPriorityText] = useState("");
  const [finalConfirmed, setFinalConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const plans = contextAssets.filter((asset) => asset.type === "context_build_plan");
  const bundles = contextAssets.filter((asset) => asset.type === "context_bundle");
  const selectedPlan = plans.find((plan) => plan.path === buildPlanPath);
  const selectedBundle = bundles[0];
  const candidates = selectedPlan?.candidate_assets || [];

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
        <Metric label="预算评分" value={String(selectedBundle?.context_budget_score?.score ?? "-")} />
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
            <select value={contextProfile} onChange={(event) => setContextProfile(event.target.value)}>
              <option value="chapter_generation">章节生成</option>
              <option value="review">审稿</option>
              <option value="revision">修订</option>
              <option value="analysis_conversion">分析转换</option>
            </select>
            <button className="primaryButton" disabled={busy || !targetPath} onClick={() => runAction(() => createContextBuildPlan(targetPath, query, Number(topK) || 8, Number(tokenBudget) || 6000, backend, contextProfile, selectedProject?.path), "上下文计划已创建")}>
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
            <input value={priorityText} onChange={(event) => setPriorityText(event.target.value)} placeholder="优先级路径，逗号分隔" />
            <label className="checkboxLine">
              <input type="checkbox" checked={finalConfirmed} onChange={(event) => setFinalConfirmed(event.target.checked)} />
              发送前最终确认
            </label>
            <button
              className="primaryButton"
              disabled={busy || !buildPlanPath}
              onClick={() => runAction(
                () => createContextBundle(buildPlanPath, 12, candidates.map((candidate) => candidate.path).filter((path) => !disabledPaths.includes(path)), disabledPaths, priorityText.split(",").map((item) => item.trim()).filter(Boolean), finalConfirmed),
                "Context bundle 已创建"
              )}
            >
              创建 Bundle
            </button>
          </div>
          <p className="previewText">Bundle 会记录 retrieved_context、top-k、query、ranker、backend 和 source asset ids。</p>
        </div>
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="人工精调来源" icon={<Network size={18} />} />
          <DataTable
            emptyText="先创建 build plan 后显示候选来源"
            columns={["启用", "类型", "标题", "分数", "Token", "路径"]}
            rows={candidates.slice(0, 24).map((candidate) => [
              <input
                type="checkbox"
                checked={!disabledPaths.includes(candidate.path)}
                onChange={(event) => setDisabledPaths((current) => event.target.checked ? current.filter((path) => path !== candidate.path) : [...new Set([...current, candidate.path])])}
                key={`${candidate.path}-enabled`}
              />,
              candidate.type || "-",
              candidate.title || "-",
              String(candidate.score ?? "-"),
              String(candidate.token_estimate ?? "-"),
              <button className="linkButton" key={candidate.path} onClick={() => setPriorityText((current) => [candidate.path, ...current.split(",").map((item) => item.trim()).filter(Boolean)].join(", "))}>{candidate.path}</button>
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="发送前上下文确认" icon={<PackageCheck size={18} />} />
          <div className="summaryBand">
            <Metric label="已选来源" value={String(selectedBundle?.selected_assets?.length ?? 0)} />
            <Metric label="Token" value={String(selectedBundle?.token_estimate ?? "-")} />
            <Metric label="状态" value={selectedBundle?.context_budget_score?.status || "-"} />
          </div>
          {(selectedBundle?.stale_context_warnings || []).slice(0, 8).map((warning) => <div className="warningLine" key={`${warning.path}-${warning.reason}`}>{warning.path}: {warning.reason}</div>)}
          <textarea className="contextPreview" readOnly value={selectedBundle?.actual_context || "暂无最终上下文。创建 Bundle 后在这里确认实际发送内容。"} rows={12} />
        </div>
        <div className="panel">
          <PanelHeader title="上下文版本比较" icon={<Network size={18} />} />
          <div className="formGrid">
            <select value={diffLeftPath} onChange={(event) => setDiffLeftPath(event.target.value)}>
              <option value="">旧 Bundle</option>
              {bundles.map((bundle) => <option value={bundle.path} key={`left-${bundle.path}`}>{bundle.title}</option>)}
            </select>
            <select value={diffRightPath} onChange={(event) => setDiffRightPath(event.target.value)}>
              <option value="">新 Bundle</option>
              {bundles.map((bundle) => <option value={bundle.path} key={`right-${bundle.path}`}>{bundle.title}</option>)}
            </select>
            <button
              className="secondaryButton"
              disabled={busy || !diffLeftPath || !diffRightPath}
              onClick={() => runAction(async () => setBundleDiff(await diffContextBundles(diffLeftPath, diffRightPath)), "上下文差异报告已生成")}
            >
              对比
            </button>
          </div>
          <div className="summaryBand">
            <Metric label="建议" value={bundleDiff?.recommendation || "-"} />
            <Metric label="新增" value={String(bundleDiff?.added_asset_paths.length ?? 0)} />
            <Metric label="移除" value={String(bundleDiff?.removed_asset_paths.length ?? 0)} />
            <Metric label="Token Δ" value={String(bundleDiff?.token_delta ?? "-")} />
          </div>
          <p className="previewText">{bundleDiff ? `预算状态：${bundleDiff.budget_status_change.from || "-"} -> ${bundleDiff.budget_status_change.to || "-"}` : "用于确认本次发送上下文与上一版的变化。"}</p>
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
