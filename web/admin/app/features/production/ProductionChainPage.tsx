"use client";

import { GitPullRequest, PenLine, RotateCcw, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  createCanonPatch,
  createChapterPlanVersion,
  createDraftVersion,
  createGenerationRun,
  createLongFormMacroPlan,
  createOutlineVersion,
  cancelChapterProduction,
  loadProductionData,
  pauseChapterProduction,
  recoverChapterProduction,
  resumeChapterProduction,
  startChapterProduction,
  type ChapterProductionRun,
  type LongFormMacroPlanRow,
  type ProductionVersionRow
} from "./api";

export function ProductionChainPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [versions, setVersions] = useState<ProductionVersionRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [chapterRuns, setChapterRuns] = useState<ChapterProductionRun[]>([]);
  const [macroPlans, setMacroPlans] = useState<LongFormMacroPlanRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [outlinePath, setOutlinePath] = useState("");
  const [chapterPlanPath, setChapterPlanPath] = useState("");
  const [selectedRunPath, setSelectedRunPath] = useState("");
  const [fromStep, setFromStep] = useState("next_chapter_plan");
  const [runTo, setRunTo] = useState("next_chapter_plan");
  const [asyncTask, setAsyncTask] = useState(false);
  const [generatorMode, setGeneratorMode] = useState("strict_bus");
  const [preflightRequired, setPreflightRequired] = useState(true);
  const [chapter, setChapter] = useState(1);
  const [contextBundlePath, setContextBundlePath] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [provider, setProvider] = useState("local-rules");
  const [model, setModel] = useState("local-rules");
  const [targetWordCount, setTargetWordCount] = useState(1000000);
  const [volumeCount, setVolumeCount] = useState(5);
  const [chaptersPerVolume, setChaptersPerVolume] = useState(80);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId) {
    const projectChanged = nextProjectId !== projectId;
    const [projectRows, versionRows, assetRows, runRows, macroRows] = await loadProductionData(nextProjectId);
    setProjects(projectRows);
    setVersions(versionRows);
    setAssets(assetRows);
    setChapterRuns(runRows);
    setMacroPlans(macroRows);
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
        <Metric label="宏观规划" value={String(macroPlans.length)} />
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="百万字宏观规划" icon={<GitPullRequest size={18} />} />
          <div className="formGrid wide">
            <input type="number" min={100000} step={10000} value={targetWordCount} onChange={(event) => setTargetWordCount(Number(event.target.value || 1000000))} />
            <input type="number" min={1} value={volumeCount} onChange={(event) => setVolumeCount(Number(event.target.value || 5))} />
            <input type="number" min={10} value={chaptersPerVolume} onChange={(event) => setChaptersPerVolume(Number(event.target.value || 80))} />
            <button
              className="primaryButton"
              disabled={busy || !selectedProject?.path}
              onClick={() => runAction(
                () => createLongFormMacroPlan(selectedProject?.path || "", outlinePath || selectedProject?.path || "", targetWordCount, volumeCount, chaptersPerVolume),
                "长篇宏观规划已生成"
              )}
            >
              <GitPullRequest size={18} />
              生成宏观规划
            </button>
          </div>
          <DataTable
            emptyText="暂无宏观规划"
            columns={["标题", "字数", "卷数", "主线", "支线", "Gate", "路径"]}
            rows={macroPlans.map((row) => [
              row.title,
              String(row.target_word_count ?? "-"),
              String(row.volume_count ?? "-"),
              String(row.mainline_count ?? "-"),
              String(row.subplot_count ?? "-"),
              String(row.gate_count ?? "-"),
              <span className="pathText" key={row.path}>{row.path}</span>
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Final Draft 后 Canon 更新" icon={<Workflow size={18} />} />
          <p className="previewText">从最终稿抽取事件、人物状态、地点移动、伏笔推进，生成等待人工确认的 canon patch。</p>
          <div className="formGrid wide">
            <select value={selectedRunPath} onChange={(event) => setSelectedRunPath(event.target.value)}>
              <option value="">选择章节 run</option>
              {chapterRuns.map((run) => <option value={run.path} key={run.path}>Ch{run.chapter} {run.status}: {run.final_draft_path || run.current_step}</option>)}
            </select>
            <input value={selectedRun?.final_draft_path || ""} readOnly placeholder="final draft path" />
            <button
              className="secondaryButton"
              disabled={busy || !selectedRun?.final_draft_path}
              onClick={() => runAction(() => createCanonPatch(selectedRun?.final_draft_path || "", selectedProject?.path), "Canon patch 已生成，等待人工确认")}
            >
              <Workflow size={18} />
              生成 Canon Patch
            </button>
          </div>
        </div>
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
            <select value={generatorMode} onChange={(event) => setGeneratorMode(event.target.value)}>
              <option value="strict_bus">严格章节工厂</option>
              <option value="draft_only">只到草稿</option>
              <option value="review_gate">审稿门禁</option>
            </select>
            <label className="checkboxLine">
              <input type="checkbox" checked={asyncTask} onChange={(event) => setAsyncTask(event.target.checked)} />
              Celery 异步
            </label>
            <label className="checkboxLine">
              <input type="checkbox" checked={preflightRequired} onChange={(event) => setPreflightRequired(event.target.checked)} />
              强制 preflight
            </label>
            <button
              className="primaryButton"
              disabled={busy || !outlinePath || !selectedProject?.path || !preflightRequired}
              onClick={() => runAction(
                () => startChapterProduction(outlinePath, chapterPlanPath, selectedProject?.path || "", chapter, runToForMode(generatorMode, runTo), asyncTask),
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
              onClick={() => runAction(() => resumeChapterProduction(selectedRunPath, fromStep, runTo, true, asyncTask), "章节生产总线已恢复")}
            >
              <RotateCcw size={18} />
              从步骤恢复
            </button>
            <button className="secondaryButton" disabled={busy || !selectedRunPath} onClick={() => runAction(() => recoverChapterProduction(selectedRunPath, runTo, asyncTask), "失败步骤已恢复")}>失败恢复</button>
            <button className="secondaryButton" disabled={busy || !selectedRunPath} onClick={() => runAction(() => pauseChapterProduction(selectedRunPath), "章节生产已暂停")}>暂停</button>
            <button className="dangerButton" disabled={busy || !selectedRunPath} onClick={() => runAction(() => cancelChapterProduction(selectedRunPath), "章节生产已取消")}>取消</button>
          </div>
          {selectedRun?.recovery_instruction ? <div className="errorLine">{selectedRun.recovery_instruction}</div> : null}
        </div>
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="章节队列" icon={<Workflow size={18} />} />
          <DataTable
            emptyText="暂无章节队列"
            columns={["章节", "状态", "执行", "Preflight", "Celery", "失败恢复"]}
            rows={chapterRuns.map((run) => [
              `Ch${run.chapter}`,
              <span className={statusClass(run.status || "")} key={`${run.path}-queue-status`}>{run.status}</span>,
              run.execution_mode || "sync",
              run.stability_preflight_path ? "ready" : "missing",
              run.celery_task_id || "-",
              <button className="linkButton" key={`${run.path}-recover`} onClick={() => { setSelectedRunPath(run.path); setFromStep(run.current_step || "outline_checkpoint"); }}>{run.current_step}</button>
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Preflight Checklist" icon={<GitPullRequest size={18} />} />
          <div className="checklistGrid">
            {CHAPTER_BUS_STEPS.slice(0, 6).map((step) => {
              const state = selectedRun?.steps?.find((item) => item.step === step.key);
              return (
                <div className={`checkItem ${state?.status === "completed" ? "ok" : state?.status === "failed" ? "warn" : ""}`} key={step.key}>
                  <strong>{step.label}</strong>
                  <span>{state?.status || "planned"}</span>
                  <small>{state?.output_paths?.[0] || state?.error || "等待执行"}</small>
                </div>
              );
            })}
          </div>
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
      <section className="panel">
        <PanelHeader title="进度历史" icon={<Workflow size={18} />} />
        <DataTable
          emptyText="暂无 timeline"
          columns={["时间", "步骤", "状态", "输出", "错误"]}
          rows={(selectedRun?.timeline || []).slice(-40).reverse().map((event, index) => [
            String(event.recorded_at || "-"),
            String(event.label || event.step || "-"),
            <span className={statusClass(String(event.status || ""))} key={`timeline-${index}`}>{String(event.status || "-")}</span>,
            Array.isArray(event.output_paths) ? event.output_paths.join(", ") : "-",
            String(event.error || "-")
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

function runToForMode(mode: string, fallback: string) {
  if (mode === "draft_only") return "draft_v0";
  if (mode === "review_gate") return "review";
  return fallback;
}
