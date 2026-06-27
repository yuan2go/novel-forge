"use client";

import { BarChart3, BrainCircuit, FlaskConical, GitCompare } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { compareRuns, createBenchmarkTask, createModelProfile, loadEvaluationData, runBenchmark } from "./api";

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
          <div className="studioActions">
            <button className="primaryButton" disabled={busy || !taskPath} onClick={() => runAction(() => runBenchmark(taskPath, provider, modelName), "Benchmark 已运行")}>运行</button>
            <button className="secondaryButton" disabled={busy || !runPaths.trim()} onClick={() => runAction(() => compareRuns(runPaths.split(",").map((item) => item.trim()).filter(Boolean), taskType, selectedProject?.path), "对比报告已生成")}>A/B 对比</button>
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
              String(asset.score ?? "-"),
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
