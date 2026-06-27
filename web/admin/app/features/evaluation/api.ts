import { fetchJson, postJson } from "../../shared/api";
import type { AssetRow, FeatureAssetRow, ProjectRow } from "../../shared/types";

export function loadEvaluationData(projectId?: string) {
  const assets = projectId
    ? `/product/evaluation/assets?project_id=${encodeURIComponent(projectId)}&limit=160`
    : "/product/evaluation/assets?limit=160";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<FeatureAssetRow[]>(assets),
    fetchJson<AssetRow[]>(projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=120` : "/assets?limit=80&rank=path")
  ]);
}

export function createModelProfile(provider: string, modelName: string, taskTypes: string[]) {
  return postJson("/product/evaluation/model-profile", {
    provider,
    model_name: modelName,
    task_types: taskTypes,
    status: "active"
  });
}

export function createBenchmarkTask(taskType: string, inputAssets: string[], workspacePath?: string) {
  return postJson("/product/evaluation/benchmark-task", {
    task_type: taskType,
    input_assets: inputAssets,
    expected_output_type: "draft_chapter",
    prompt_template: "Evaluate this task with project context, quality standard, and originality boundary.",
    workspace_path: workspacePath || null
  });
}

export function runBenchmark(taskPath: string, provider: string, modelName: string) {
  return postJson("/product/evaluation/benchmark-run", {
    task_path: taskPath,
    provider,
    model_name: modelName
  });
}

export function compareRuns(runPaths: string[], taskType: string, workspacePath?: string) {
  return postJson("/product/evaluation/compare", {
    run_paths: runPaths,
    task_type: taskType,
    workspace_path: workspacePath || null
  });
}
