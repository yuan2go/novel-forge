"use client";

import { BarChart3, BrainCircuit, FlaskConical, GitCompare } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { compareRuns, createBenchmarkFromGenerationRun, createBenchmarkTask, createModelProfile, createPromptRegression, createPromptVersion, createRoutingPolicy, loadEvaluationData, runBenchmark, runBenchmarkBatch } from "./api";

const taskTypes = ["outline_generation", "chapter_plan", "draft_chapter", "review", "originality", "style_review"];

export function EvaluationCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<FeatureAssetRow[]>([]);
  const [inputAssets, setInputAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [provider, setProvider] = useState("mock");
  const [modelName, setModelName] = useState("mock-model");
  const [taskType, setTaskType] = useState("draft_chapter");
  const [selectedInput, setSelectedInput] = useState("");
  const [taskPath, setTaskPath] = useState("");
  const [runPaths, setRunPaths] = useState("");
  const [candidateText, setCandidateText] = useState("mock/mock-model");
  const [promptId, setPromptId] = useState("draft_chapter_prompt");
  const [promptVersion, setPromptVersion] = useState("v1");
  const [candidateVersion, setCandidateVersion] = useState("v2");
  const [promptTemplate, setPromptTemplate] = useState("Return schema-valid JSON for this Novel Forge task.");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const grouped = useMemo(() => {
    return assets.reduce<Record<string, FeatureAssetRow[]>>((groups, asset) => {
      groups[asset.type] = [...(groups[asset.type] ?? []), asset];
      return groups;
    }, {});
  }, [assets]);
  const totalEstimatedCost = assets
    .filter((asset) => asset.type === "model_benchmark_run")
    .reduce((sum, asset) => sum + Number((asset as FeatureAssetRow & { cost_estimate?: { cost?: number } }).cost_estimate?.cost ?? 0), 0);
  const activeRoutes = grouped.model_routing_policy?.flatMap((asset) => Object.entries((asset as FeatureAssetRow & { task_routes?: Record<string, { provider?: string; model_name?: string; overall?: number }> }).task_routes ?? {}).map(([task, route]) => ({ task, ...route, path: asset.path }))) ?? [];

  async function refresh(nextProjectId = projectId) {
    const [projectRows, evaluationAssets, sourceAssets] = await loadEvaluationData(nextProjectId);
    setProjects(projectRows);
    setAssets(evaluationAssets);
    setInputAssets(sourceAssets);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setSelectedInput((current) => current || sourceAssets[0]?.path || "");
    setTaskPath((current) => current || evaluationAssets.find((asset) => asset.type === "model_benchmark_task")?.path || "");
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
    <FeatureShell title="模型评测中心" subtitle="模型 Profile、评测集、Benchmark Run、A/B 对比和 Prompt Regression 的工程化入口。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="模型 Profile" value={String(grouped.model_profile?.length ?? 0)} />
        <Metric label="评测任务" value={String(grouped.model_benchmark_task?.length ?? 0)} />
        <Metric label="Benchmark Run" value={String(grouped.model_benchmark_run?.length ?? 0)} />
        <Metric label="对比报告" value={String(grouped.model_comparison_report?.length ?? 0)} />
        <Metric label="路由策略" value={String(grouped.model_routing_policy?.length ?? 0)} />
        <Metric label="估算成本" value={totalEstimatedCost.toFixed(4)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="模型与评测任务" icon={<BrainCircuit size={18} />} />
          <div className="formGrid">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <input value={provider} onChange={(event) => setProvider(event.target.value)} />
            <input value={modelName} onChange={(event) => setModelName(event.target.value)} />
            <select value={taskType} onChange={(event) => setTaskType(event.target.value)}>
              {taskTypes.map((type) => <option value={type} key={type}>{type}</option>)}
            </select>
          </div>
          <div className="studioActions">
            <button className="primaryButton" disabled={busy} onClick={() => runAction(() => createModelProfile(provider, modelName, [taskType]), "模型 Profile 已创建")}>保存模型</button>
            <button className="secondaryButton" disabled={busy || !selectedInput} onClick={() => runAction(() => createBenchmarkTask(taskType, [selectedInput], selectedProject?.path), "评测任务已创建")}>创建评测任务</button>
            <button className="secondaryButton" disabled={busy || !selectedInput.includes("runs/")} onClick={() => runAction(() => createBenchmarkFromGenerationRun(selectedInput, taskType), "生产链评测任务已创建")}>从 Generation Run 建任务</button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="运行与对比" icon={<FlaskConical size={18} />} />
          <label className="selectWrap">
            <span>输入资产</span>
            <select value={selectedInput} onChange={(event) => setSelectedInput(event.target.value)}>
              <option value="">选择输入资产</option>
              {inputAssets.map((asset) => <option value={asset.path} key={asset.path}>{asset.type}: {asset.title}</option>)}
            </select>
          </label>
          <input placeholder="benchmark task path" value={taskPath} onChange={(event) => setTaskPath(event.target.value)} />
          <input placeholder="run paths, comma separated" value={runPaths} onChange={(event) => setRunPaths(event.target.value)} />
          <input placeholder="candidates: provider/model, one per comma" value={candidateText} onChange={(event) => setCandidateText(event.target.value)} />
          <div className="studioActions">
            <button className="primaryButton" disabled={busy || !taskPath} onClick={() => runAction(() => runBenchmark(taskPath, provider, modelName), "Benchmark 已运行")}>运行</button>
            <button className="secondaryButton" disabled={busy || !taskPath} onClick={() => runAction(() => runBenchmarkBatch([taskPath], parseCandidates(candidateText), selectedProject?.path), "批量 Benchmark 已运行")}>批量跑分</button>
            <button className="secondaryButton" disabled={busy || !runPaths.trim()} onClick={() => runAction(() => compareRuns(runPaths.split(",").map((item) => item.trim()).filter(Boolean), taskType, selectedProject?.path), "对比报告已生成")}>A/B 对比</button>
            <button className="secondaryButton" disabled={busy || !(grouped.model_comparison_report?.length)} onClick={() => runAction(() => createRoutingPolicy((grouped.model_comparison_report || []).slice(0, 8).map((asset) => asset.path), selectedProject?.path), "模型路由策略已生效")}>生成路由策略</button>
          </div>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="真实 Provider 批量评测" icon={<FlaskConical size={18} />} />
          <p className="previewText">候选格式：provider/model。非 mock provider 会走本地环境变量和 model adapter，未配置时 fail-closed 并在 run 中记录错误。</p>
          <DataTable
            emptyText="暂无 benchmark run"
            columns={["Provider", "Model", "任务", "状态", "分数", "成本", "延迟"]}
            rows={(grouped.model_benchmark_run || []).slice(0, 20).map((asset) => [
              (asset as FeatureAssetRow & { provider?: string }).provider || "-",
              (asset as FeatureAssetRow & { model_name?: string }).model_name || "-",
              (asset as FeatureAssetRow & { task_type?: string }).task_type || "-",
              <span className={statusClass(asset.status || "")} key={`${asset.path}-eval-status`}>{asset.status || "-"}</span>,
              String(asset.score ?? "-"),
              `$${Number((asset as FeatureAssetRow & { cost_estimate?: { cost?: number } }).cost_estimate?.cost ?? 0).toFixed(4)}`,
              String((asset as FeatureAssetRow & { latency_ms?: number }).latency_ms ?? "-")
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="路由生效回归" icon={<GitCompare size={18} />} />
          <DataTable
            emptyText="暂无模型路由策略"
            columns={["任务", "Provider", "Model", "分数", "策略"]}
            rows={activeRoutes.map((route) => [
              route.task,
              route.provider || "-",
              route.model_name || "-",
              String(route.overall ?? "-"),
              <span className="pathText" key={`${route.path}-${route.task}`}>{route.path}</span>
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="评测集管理" icon={<FlaskConical size={18} />} />
          <p className="previewText">model_benchmark_task 是当前评测集单元；批量跑分会对同一任务运行多个 provider/model，并生成 comparison。</p>
          <DataTable
            emptyText="暂无评测任务"
            columns={["任务", "标题", "状态", "路径"]}
            rows={(grouped.model_benchmark_task || []).map((asset) => [
              (asset as FeatureAssetRow & { task_type?: string }).task_type || asset.type,
              asset.title,
              <span className={statusClass(asset.status || "active")} key={`${asset.path}-status`}>{asset.status || "active"}</span>,
              <button className="linkButton" key={asset.path} onClick={() => setTaskPath(asset.path)}>{asset.path}</button>
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Prompt Regression" icon={<GitCompare size={18} />} />
          <div className="formGrid wide">
            <input value={promptId} onChange={(event) => setPromptId(event.target.value)} placeholder="prompt id" />
            <input value={promptVersion} onChange={(event) => setPromptVersion(event.target.value)} placeholder="baseline version" />
            <input value={candidateVersion} onChange={(event) => setCandidateVersion(event.target.value)} placeholder="candidate version" />
            <textarea value={promptTemplate} onChange={(event) => setPromptTemplate(event.target.value)} rows={4} />
            <button className="secondaryButton" disabled={busy || !promptId || !promptVersion} onClick={() => runAction(() => createPromptVersion(promptId, promptVersion, taskType, promptTemplate), "Prompt 版本已保存")}>保存 Prompt</button>
            <button
              className="primaryButton"
              disabled={busy || !promptId || !runPaths.trim()}
              onClick={() => runAction(() => createPromptRegression(promptId, promptVersion, candidateVersion, runPaths.split(",").map((item) => item.trim()).filter(Boolean)), "Prompt 回归报告已生成")}
            >
              回归评测
            </button>
          </div>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="评测资产" icon={<BarChart3 size={18} />} />
          <DataTable
            emptyText="暂无评测资产"
            columns={["类型", "标题", "状态", "分数", "路径"]}
            rows={assets.map((asset) => [
              asset.type,
              asset.title,
              <span className={statusClass(asset.status || "")} key={asset.path}>{asset.status || "-"}</span>,
              `${String(asset.score ?? "-")}${(asset as FeatureAssetRow & { cost_estimate?: { cost?: number } }).cost_estimate ? ` / $${Number((asset as FeatureAssetRow & { cost_estimate?: { cost?: number } }).cost_estimate?.cost ?? 0).toFixed(4)}` : ""}`,
              <span className="pathText" key={`${asset.path}-path`}>{asset.path}</span>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="结果分组" icon={<GitCompare size={18} />} />
          <DataTable
            columns={["资产类型", "数量"]}
            rows={Object.entries(grouped).map(([type, rows]) => [type, String(rows.length)])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}

function parseCandidates(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const [provider, modelName] = item.split("/");
      return { provider: provider || "mock", model_name: modelName || "mock-model" };
    });
}
