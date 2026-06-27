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

export function runBenchmarkBatch(taskPaths: string[], candidates: Array<{ provider: string; model_name: string }>, workspacePath?: string) {
  return postJson("/product/evaluation/benchmark-batch", {
    task_paths: taskPaths,
    candidates,
    workspace_path: workspacePath || null
  });
}

export function createRoutingPolicy(comparisonPaths: string[], workspacePath?: string) {
  return postJson("/product/evaluation/routing-policy", {
    comparison_paths: comparisonPaths,
    status: "active",
    workspace_path: workspacePath || null
  });
}

export function createPromptVersion(promptId: string, version: string, taskType: string, template: string) {
  return postJson("/product/evaluation/prompt-version", {
    prompt_id: promptId,
    version,
    task_type: taskType,
    template,
    status: "active"
  });
}

export function createPromptRegression(promptId: string, baselineVersion: string, candidateVersion: string, benchmarkRuns: string[]) {
  return postJson("/product/evaluation/prompt-regression", {
    prompt_id: promptId,
    baseline_version: baselineVersion,
    candidate_version: candidateVersion,
    benchmark_runs: benchmarkRuns
  });
}
