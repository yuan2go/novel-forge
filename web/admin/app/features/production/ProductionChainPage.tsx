"use client";

import { GitPullRequest, PenLine, RotateCcw, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  createChapterPlanVersion,
  createDraftVersion,
  createGenerationRun,
  createOutlineVersion,
  loadProductionData,
  resumeChapterProduction,
  startChapterProduction,
  type ChapterProductionRun,
  type ProductionVersionRow
} from "./api";

export function ProductionChainPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [versions, setVersions] = useState<ProductionVersionRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [chapterRuns, setChapterRuns] = useState<ChapterProductionRun[]>([]);
  const [projectId, setProjectId] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [outlinePath, setOutlinePath] = useState("");
  const [chapterPlanPath, setChapterPlanPath] = useState("");
  const [selectedRunPath, setSelectedRunPath] = useState("");
  const [fromStep, setFromStep] = useState("next_chapter_plan");
  const [runTo, setRunTo] = useState("next_chapter_plan");
  const [chapter, setChapter] = useState(1);
  const [contextBundlePath, setContextBundlePath] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [provider, setProvider] = useState("local-rules");
  const [model, setModel] = useState("local-rules");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId) {
    const projectChanged = nextProjectId !== projectId;
    const [projectRows, versionRows, assetRows, runRows] = await loadProductionData(nextProjectId);
    setProjects(projectRows);
    setVersions(versionRows);
    setAssets(assetRows);
    setChapterRuns(runRows);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setSelectedPath((current) => projectChanged ? assetRows[0]?.path || "" : current || assetRows[0]?.path || "");
    setOutlinePath((current) => projectChanged ? assetRows.find((asset) => asset.type === "outline")?.path || "" : current || assetRows.find((asset) => asset.type === "outline")?.path || "");
    setChapterPlanPath((current) => projectChanged ? assetRows.find((asset) => asset.type === "chapter_plan")?.path || "" : current || assetRows.find((asset) => asset.type === "chapter_plan")?.path || "");
    setContextBundlePath((current) => projectChanged ? assetRows.find((asset) => asset.type === "context_bundle")?.path || "" : current || assetRows.find((asset) => asset.type === "context_bundle")?.path || "");
    setSelectedRunPath((current) => projectChanged ? runRows[0]?.path || "" : current || runRows[0]?.path || "");
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

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const selectedRun = chapterRuns.find((run) => run.path === selectedRunPath) || chapterRuns[0];
  const outlineAssets = assets.filter((asset) => asset.type === "outline");
  const chapterPlanAssets = assets.filter((asset) => asset.type === "chapter_plan");

  return (
    <FeatureShell title="版本化生产链" subtitle="大纲、细纲、上下文、生成记录和稿件版本形成可追溯链条。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="版本资产" value={String(versions.length)} />
        <Metric label="Outline" value={String(versions.filter((row) => row.type === "outline_version").length)} />
        <Metric label="ChapterPlan" value={String(versions.filter((row) => row.type === "chapter_plan_version").length)} />
        <Metric label="GenerationRun" value={String(versions.filter((row) => row.type === "generation_run").length)} />
        <Metric label="章节总线" value={String(chapterRuns.length)} />
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="章节生产总线" icon={<Workflow size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={outlinePath} onChange={(event) => setOutlinePath(event.target.value)}>
              <option value="">选择 outline</option>
              {outlineAssets.map((asset) => <option value={asset.path} key={asset.path}>{asset.title}</option>)}
            </select>
            <select value={chapterPlanPath} onChange={(event) => setChapterPlanPath(event.target.value)}>
              <option value="">自动生成 chapter plan</option>
              {chapterPlanAssets.map((asset) => <option value={asset.path} key={asset.path}>{asset.title}</option>)}
            </select>
            <input type="number" min={1} value={chapter} onChange={(event) => setChapter(Number(event.target.value || 1))} />
            <select value={runTo} onChange={(event) => setRunTo(event.target.value)}>
              {CHAPTER_BUS_STEPS.map((step) => <option value={step.key} key={step.key}>{step.label}</option>)}
            </select>
            <button
              className="primaryButton"
              disabled={busy || !outlinePath || !selectedProject?.path}
              onClick={() => runAction(
                () => startChapterProduction(outlinePath, chapterPlanPath, selectedProject?.path || "", chapter, runTo),
                "章节生产总线已推进"
              )}
            >
              <Workflow size={18} />
              启动总线
            </button>
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="失败恢复" icon={<RotateCcw size={18} />} />
          <div className="formGrid wide">
            <select value={selectedRunPath} onChange={(event) => setSelectedRunPath(event.target.value)}>
              <option value="">选择 run</option>
              {chapterRuns.map((run) => <option value={run.path} key={run.path}>Ch{run.chapter} {run.status}: {run.current_step}</option>)}
            </select>
            <select value={fromStep} onChange={(event) => setFromStep(event.target.value)}>
              {CHAPTER_BUS_STEPS.map((step) => <option value={step.key} key={step.key}>{step.label}</option>)}
            </select>
            <select value={runTo} onChange={(event) => setRunTo(event.target.value)}>
              {CHAPTER_BUS_STEPS.map((step) => <option value={step.key} key={step.key}>{step.label}</option>)}
            </select>
            <button
              className="secondaryButton"
              disabled={busy || !selectedRunPath}
              onClick={() => runAction(() => resumeChapterProduction(selectedRunPath, fromStep, runTo), "章节生产总线已恢复")}
            >
              <RotateCcw size={18} />
              从步骤恢复
            </button>
          </div>
          {selectedRun?.recovery_instruction ? <div className="errorLine">{selectedRun.recovery_instruction}</div> : null}
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="总线状态" icon={<Workflow size={18} />} />
        <div className="productionSteps">
          {(selectedRun?.steps || []).map((step) => (
            <div className={`productionStep ${step.status === "completed" ? "ok" : step.status === "failed" ? "warn" : "muted"}`} key={step.step}>
              <span>{step.label || step.step}</span>
              <strong>{step.status}</strong>
              <small>{step.output_paths?.[0] || step.error || `attempts ${step.attempts ?? 0}`}</small>
            </div>
          ))}
          {!selectedRun ? <div className="emptyCell">暂无章节生产总线运行</div> : null}
        </div>
        <DataTable
          emptyText="暂无章节生产运行"
          columns={["章节", "状态", "当前步骤", "完成", "最终稿", "下一章细纲", "路径"]}
          rows={chapterRuns.map((run) => [
            String(run.chapter),
            <span className={statusClass(run.status || "")} key={`${run.path}-status`}>{run.status}</span>,
            run.current_step,
            `${run.completed_steps}/${run.total_steps}`,
            run.final_draft_path || "-",
            run.next_chapter_plan_path || "-",
            <button className="linkButton" key={run.path} onClick={() => setSelectedRunPath(run.path)}>{run.path}</button>
          ])}
        />
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="版本操作" icon={<GitPullRequest size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={selectedPath} onChange={(event) => setSelectedPath(event.target.value)}>
              <option value="">选择资产</option>
              {assets.map((asset) => <option value={asset.path} key={asset.path}>{asset.type}: {asset.title}</option>)}
            </select>
            <button className="secondaryButton" disabled={busy || !selectedPath} onClick={() => runAction(() => createOutlineVersion(selectedPath), "大纲版本已创建")}>大纲版本</button>
            <button className="secondaryButton" disabled={busy || !selectedPath} onClick={() => runAction(() => createChapterPlanVersion(selectedPath), "细纲版本已创建")}>细纲版本</button>
            <button className="secondaryButton" disabled={busy || !selectedPath} onClick={() => runAction(() => createDraftVersion(selectedPath), "稿件版本已创建")}>稿件版本</button>
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="生成记录" icon={<PenLine size={18} />} />
          <div className="formGrid wide">
            <input value={contextBundlePath} onChange={(event) => setContextBundlePath(event.target.value)} placeholder="context bundle path" />
            <input value={outputPath} onChange={(event) => setOutputPath(event.target.value)} placeholder="output path optional" />
            <input value={provider} onChange={(event) => setProvider(event.target.value)} placeholder="provider" />
            <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="model" />
            <button className="primaryButton" disabled={busy || !selectedPath || !contextBundlePath} onClick={() => runAction(() => createGenerationRun(selectedPath, contextBundlePath, outputPath, provider, model), "生成记录已创建")}>
              <Workflow size={18} />
              记录生成
            </button>
          </div>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="生产版本资产" icon={<GitPullRequest size={18} />} />
        <DataTable
          emptyText="暂无生产版本"
          columns={["类型", "标题", "版本", "状态", "输入", "上下文", "输出", "路径"]}
          rows={versions.map((row) => [
            row.type,
            row.title,
            String(row.version_index ?? "-"),
            <span className={statusClass(row.status || "")} key={`${row.path}-status`}>{row.status || "-"}</span>,
            row.source_path || "-",
            row.context_bundle_path || "-",
            row.output_path || "-",
            <span className="pathText" key={row.path}>{row.path}</span>
          ])}
        />
      </section>
    </FeatureShell>
  );
}

const CHAPTER_BUS_STEPS = [
  { key: "outline_checkpoint", label: "大纲检查点" },
  { key: "chapter_plan", label: "章节细纲" },
  { key: "context_bundle", label: "上下文包" },
  { key: "draft_v0", label: "草稿 v0" },
  { key: "review", label: "审稿" },
  { key: "revision_plan", label: "修订计划" },
  { key: "final_draft", label: "最终稿" },
  { key: "next_chapter_plan", label: "下一章细纲" }
];
