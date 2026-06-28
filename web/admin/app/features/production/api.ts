import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";

export type ProductionVersionRow = FeatureAssetRow & {
  version_index?: number | string;
  source_path?: string;
  context_bundle_path?: string;
  output_path?: string;
};

export type ChapterProductionStep = {
  step: string;
  label: string;
  status: string;
  attempts?: number;
  input_paths?: string[];
  output_paths?: string[];
  error?: string;
  started_at?: string;
  finished_at?: string;
  task_status_paths?: string[];
};

export type ChapterProductionRun = FeatureAssetRow & {
  run_id: string;
  chapter: number | string;
  current_step: string;
  completed_steps: number;
  total_steps: number;
  final_draft_path: string;
  stability_preflight_path?: string;
  execution_mode?: string;
  celery_task_id?: string;
  pause_requested?: boolean;
  cancel_requested?: boolean;
  next_chapter_plan_path: string;
  steps?: ChapterProductionStep[];
  timeline?: Array<Record<string, unknown>>;
  outputs?: Record<string, string>;
  recovery_instruction?: string;
};

export type LongFormMacroPlanRow = FeatureAssetRow & {
  target_word_count?: number;
  volume_count?: number;
  mainline_count?: number;
  subplot_count?: number;
  gate_count?: number;
};

export function loadProductionData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ProductionVersionRow[]>(projectId ? `/product/production/versions?project_id=${encodeURIComponent(projectId)}&limit=160` : "/product/production/versions?limit=160"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=160` : "/assets?limit=120&rank=path"),
    fetchJson<ChapterProductionRun[]>(projectId ? `/product/production/chapter-runs?project_id=${encodeURIComponent(projectId)}&limit=80` : "/product/production/chapter-runs?limit=80"),
    fetchJson<LongFormMacroPlanRow[]>(projectId ? `/product/production/macro-plans?project_id=${encodeURIComponent(projectId)}&limit=80` : "/product/production/macro-plans?limit=80")
  ]);
}

export function createOutlineVersion(outlinePath: string) {
  return postJson("/product/production/outline-version", { outline_path: outlinePath, change_summary: "version from production workbench", status: "active" });
}

export function createChapterPlanVersion(chapterPlanPath: string) {
  return postJson("/product/production/chapter-plan-version", { chapter_plan_path: chapterPlanPath, change_summary: "version from production workbench", status: "active" });
}

export function createDraftVersion(draftPath: string) {
  return postJson("/product/production/draft-version", { draft_path: draftPath, change_summary: "version from production workbench", status: "active" });
}

export function createGenerationRun(inputPath: string, contextBundlePath: string, outputPath: string, provider: string, model: string) {
  return postJson("/product/production/generation-run", {
    input_path: inputPath,
    context_bundle_path: contextBundlePath,
    output_path: outputPath || null,
    provider,
    model,
    prompt_version: "prompt-v1",
    status: "succeeded"
  });
}

export function startChapterProduction(outlinePath: string, chapterPlanPath: string, workspacePath: string, chapter: number, runTo: string, asyncTask = false) {
  return postJson("/product/production/chapter-run/start", {
    outline_path: outlinePath,
    chapter_plan_path: chapterPlanPath || null,
    workspace_path: workspacePath || null,
    chapter,
    run_to: runTo,
    async_task: asyncTask
  });
}

export function resumeChapterProduction(runPath: string, fromStep: string, runTo: string, force = false, asyncTask = false) {
  return postJson("/product/production/chapter-run/resume", {
    run_path: runPath,
    from_step: fromStep || null,
    run_to: runTo || null,
    force,
    async_task: asyncTask
  });
}

export function pauseChapterProduction(runPath: string, reason = "paused from chapter factory") {
  return postJson("/product/production/chapter-run/pause", { run_path: runPath, reason });
}

export function cancelChapterProduction(runPath: string, reason = "cancelled from chapter factory") {
  return postJson("/product/production/chapter-run/cancel", { run_path: runPath, reason, terminate: true, signal: "SIGTERM" });
}

export function recoverChapterProduction(runPath: string, runTo: string, asyncTask = false) {
  return postJson("/product/production/chapter-run/recover", { run_path: runPath, run_to: runTo || null, force: true, async_task: asyncTask });
}

export function createLongFormMacroPlan(workspacePath: string, sourcePath: string, targetWordCount: number, volumeCount: number, chaptersPerVolume: number) {
  return postJson("/product/production/macro-plan", {
    workspace_path: workspacePath || null,
    source_path: sourcePath || null,
    target_word_count: targetWordCount,
    volume_count: volumeCount,
    chapters_per_volume: chaptersPerVolume
  });
}

export function createCanonPatch(draftPath: string, workspacePath?: string) {
  return postJson("/product/continuity/canon-patch", {
    draft_path: draftPath,
    workspace_path: workspacePath || null
  });
}
