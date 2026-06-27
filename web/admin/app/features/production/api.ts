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
  next_chapter_plan_path: string;
  steps?: ChapterProductionStep[];
  timeline?: Array<Record<string, unknown>>;
  outputs?: Record<string, string>;
  recovery_instruction?: string;
};

export function loadProductionData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ProductionVersionRow[]>(projectId ? `/product/production/versions?project_id=${encodeURIComponent(projectId)}&limit=160` : "/product/production/versions?limit=160"),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=160` : "/assets?limit=120&rank=path"),
    fetchJson<ChapterProductionRun[]>(projectId ? `/product/production/chapter-runs?project_id=${encodeURIComponent(projectId)}&limit=80` : "/product/production/chapter-runs?limit=80")
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

export function startChapterProduction(outlinePath: string, chapterPlanPath: string, workspacePath: string, chapter: number, runTo: string) {
  return postJson("/product/production/chapter-run/start", {
    outline_path: outlinePath,
    chapter_plan_path: chapterPlanPath || null,
    workspace_path: workspacePath || null,
    chapter,
    run_to: runTo
  });
}

export function resumeChapterProduction(runPath: string, fromStep: string, runTo: string, force = false) {
  return postJson("/product/production/chapter-run/resume", {
    run_path: runPath,
    from_step: fromStep || null,
    run_to: runTo || null,
    force
  });
}
