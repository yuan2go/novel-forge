import { fetchJson, postJson } from "../../shared/api";
import type {
  AgentEventRow,
  AgentRunRow,
  AssetDetail,
  AssetRow,
  NodeRunRow,
  ProjectRow,
  TaskControl,
  WorkflowDefinitionRow,
  WorkflowRunRow
} from "../../shared/types";
import type { ChangeImpactRow } from "../impact/api";

export type RuntimeTraceTimeline = {
  spans: Array<Record<string, unknown>>;
  summary: Record<string, unknown>;
};

export type CostLedgerRow = {
  path: string;
  ledger_id: string;
  scope: string;
  amount: number;
  currency: string;
  source_type: string;
  source_id: string;
  metadata?: Record<string, unknown>;
  project_id?: string;
  workspace_path?: string;
  created_at?: string;
  trace?: Record<string, unknown>;
};

export type RuntimeCostDashboard = {
  path?: string;
  asset?: {
    content?: {
      summary?: Record<string, unknown>;
      snapshots?: Record<string, unknown>;
      quality?: Record<string, unknown>;
      recommendations?: string[];
    };
  };
};

export type AgentOperationContracts = {
  contracts: Array<Record<string, unknown>>;
};

export type AgentCenterSnapshot = {
  status?: string;
  agent_center_version?: string;
  summary?: Record<string, unknown>;
  health_score?: number;
  readiness_checks?: Array<Record<string, unknown>>;
  run_graph?: Record<string, unknown>;
  agent_tasks?: Array<Record<string, unknown>>;
  loop_runs?: Array<Record<string, unknown>>;
  context_bundles?: Array<Record<string, unknown>>;
  review_issues?: Array<Record<string, unknown>>;
  revision_tasks?: Array<Record<string, unknown>>;
  handoffs?: Array<Record<string, unknown>>;
  runtime_links?: Record<string, unknown>;
  gate_timeline?: Array<Record<string, unknown>>;
  checkpoints?: Array<Record<string, unknown>>;
  budget_burn?: Record<string, unknown>;
  retry_controls?: Array<Record<string, unknown>>;
  dead_letter_queue?: Array<Record<string, unknown>>;
  rollback_preview?: Array<Record<string, unknown>>;
  sla_duration?: Array<Record<string, unknown>>;
  evidence_drawer?: Array<Record<string, unknown>>;
  operation_coverage?: Array<Record<string, unknown>>;
  operation_coverage_full?: Record<string, unknown>;
  hard_stop_dashboard?: Record<string, unknown>;
  rollback_rehearsals?: Array<Record<string, unknown>>;
  dead_letter_repairs?: Array<Record<string, unknown>>;
  agent_dags?: Array<Record<string, unknown>>;
  recommendations?: string[];
};

export type LongformStabilityDashboard = {
  project_id: string;
  workspace_path: string;
  summary: Record<string, unknown>;
  counts_by_type: Record<string, number>;
  chapters: Array<Record<string, unknown>>;
  latest_assets: Record<string, Record<string, unknown>>;
  arc_visualization: {
    arc_id?: string;
    title?: string;
    chapter_range?: string;
    nodes: Array<Record<string, unknown>>;
    edges: Array<Record<string, unknown>>;
    lanes: Array<Record<string, unknown>>;
  };
  gate_history: Array<Record<string, unknown>>;
  revision_tasks: Array<Record<string, unknown>>;
  acceptance: {
    status: string;
    summary: Record<string, unknown>;
    checks: Array<Record<string, unknown>>;
    recommendations?: string[];
    gate_result_path?: string;
  };
  created_at: string;
};

export type EditorChiefSnapshot = {
  status: string;
  generated_at: string;
  project: Record<string, unknown>;
  executive_decision: Record<string, unknown>;
  overall_health: Record<string, unknown>;
  arc_progress: Record<string, unknown>;
  character_drift: Record<string, unknown>;
  foreshadowing: Record<string, unknown>;
  recent_fatigue: Record<string, unknown>;
  next_10_chapter_strategy: Record<string, unknown>;
  blocking_repair_queue: Record<string, unknown>;
  publish_and_platform_fit: Record<string, unknown>;
  governance_loop?: Record<string, unknown>;
  control_links: Record<string, string>;
  evidence: Record<string, unknown>;
};

export type LongformControlAssetPayload = {
  asset_type: "canon_database" | "arc_plan" | "foreshadowing_graph" | "character_state_ledger" | "villain_operation_plan";
  title?: string;
  project_id?: string;
  workspace_path?: string;
  content?: Record<string, unknown>;
};

export function projectAssetPath(projectId?: string, limit = 220) {
  return projectId ? `/product/projects/${encodeURIComponent(projectId)}/assets?limit=${limit}` : `/assets?limit=${limit}&rank=path`;
}

export function loadWorkflowRuntimeData(projectId?: string) {
  const projectQuery = projectId ? `project_id=${encodeURIComponent(projectId)}&` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<TaskControl>("/product/tasks/control"),
    fetchJson<WorkflowDefinitionRow[]>("/product/workflow/definitions?limit=200"),
    fetchJson<WorkflowRunRow[]>(`/product/workflow/runs?${projectQuery}limit=200`),
    fetchJson<NodeRunRow[]>(`/product/workflow/node-runs?${projectQuery}limit=200`)
  ]);
}

export function loadWorkflowRuntimeConsole(payload: {
  workflow_path_or_id?: string;
  workflow_run_path_or_id?: string;
  input_assets?: string[];
}) {
  const params = new URLSearchParams();
  if (payload.workflow_path_or_id) params.set("workflow_path_or_id", payload.workflow_path_or_id);
  if (payload.workflow_run_path_or_id) params.set("workflow_run_path_or_id", payload.workflow_run_path_or_id);
  for (const path of payload.input_assets || []) params.append("input_assets", path);
  return fetchJson<Record<string, unknown>>(`/product/workflow/runtime-console?${params.toString()}`);
}

export function executeWorkflow(payload: { workflow_path_or_id: string; input_assets?: string[]; max_nodes?: number; execute_agents?: boolean; workspace_path?: string }) {
  return postJson("/product/workflow/execute", {
    workflow_path_or_id: payload.workflow_path_or_id,
    input_assets: payload.input_assets || [],
    max_nodes: payload.max_nodes ?? 8,
    dispatch_agents: true,
    execute_agents: Boolean(payload.execute_agents),
    apply_invalidation: true,
    workspace_path: payload.workspace_path || null
  }) as Promise<Record<string, unknown>>;
}

export function resumeWorkflow(payload: {
  workflow_run_path_or_id: string;
  resume_node_id?: string;
  output_assets?: string[];
  token_used?: number;
  cost_estimate?: number;
}) {
  return postJson("/product/workflow/resume", {
    workflow_run_path_or_id: payload.workflow_run_path_or_id,
    resume_node_id: payload.resume_node_id || null,
    output_assets: payload.output_assets || [],
    token_used: payload.token_used || 0,
    cost_estimate: payload.cost_estimate || 0,
    checkpoint: { status: "ui_resume", source: "os_workflow_runtime_console" },
    evidence: { resumed_by: "os_workflow_runtime_console" },
    max_nodes: 8,
    apply_invalidation: true,
    archive_previous: true
  }) as Promise<Record<string, unknown>>;
}

export function controlWorkflowRun(payload: {
  workflow_run_path_or_id: string;
  action: "pause" | "retry" | "cancel" | "resume";
  resume_node_id?: string;
  output_assets?: string[];
}) {
  return postJson("/product/workflow/runs/control", {
    workflow_run_path_or_id: payload.workflow_run_path_or_id,
    action: payload.action,
    reason: `os workflow console ${payload.action}`,
    resume_node_id: payload.resume_node_id || null,
    output_assets: payload.output_assets || [],
    checkpoint: { status: `ui_${payload.action}`, source: "os_workflow_runtime_console" },
    evidence: { controlled_by: "os_workflow_runtime_console" },
    max_nodes: 8,
    apply_invalidation: true,
    archive_previous: true
  }) as Promise<Record<string, unknown>>;
}

export function runWorkflowSchedulerTick(projectId?: string, iterations = 1) {
  return postJson("/product/workflow/scheduler/tick", {
    project_id: projectId || null,
    limit: 30,
    max_nodes_per_resume: 8,
    dry_run: false,
    async_task: false,
    iterations,
    interval_seconds: iterations > 1 ? 5 : 0,
    apply_invalidation: true,
    stop_when_idle: true,
    lease_ttl_seconds: 300
  }) as Promise<Record<string, unknown>>;
}

export function loadAgentDispatchData(projectId?: string, status?: string) {
  const projectQuery = projectId ? `project_id=${encodeURIComponent(projectId)}&` : "";
  const statusQuery = status ? `status=${encodeURIComponent(status)}&` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<AgentRunRow[]>(`/product/agents/runs?${projectQuery}limit=200`),
    fetchJson<AgentEventRow[]>(`/product/agents/events?${projectQuery}limit=240`),
    fetchJson<Record<string, unknown>>("/product/agents/scheduler/status"),
    fetchJson<Array<Record<string, unknown>>>(`/product/agents/scheduler/queue?${projectQuery}${statusQuery}limit=200`),
    fetchJson<AgentOperationContracts>("/product/agents/operation-contracts")
  ]);
}

export function loadAgentCenterSnapshot(projectId?: string) {
  const params = new URLSearchParams({ limit: "300" });
  if (projectId) params.set("project_id", projectId);
  return fetchJson<AgentCenterSnapshot>(`/product/agents/center?${params.toString()}`);
}

export function loadAgentOperationCoverage(projectId?: string) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  return fetchJson<Record<string, unknown>>(`/product/agents/operation-coverage?${params.toString()}`);
}

export function loadAgentHardStopDashboard(projectId?: string, workspacePath?: string) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (workspacePath) params.set("workspace_path", workspacePath);
  return fetchJson<Record<string, unknown>>(`/product/agents/hard-stop-dashboard?${params.toString()}`);
}

export function loadEditorChiefSnapshot(projectId?: string, workspacePath?: string) {
  const params = new URLSearchParams({ limit: "700" });
  if (projectId) params.set("project_id", projectId);
  if (workspacePath) params.set("workspace_path", workspacePath);
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<EditorChiefSnapshot>(`/product/editor-chief/snapshot?${params.toString()}`)
  ]);
}

export function runAgentSchedulerTick(projectId?: string, iterations = 1) {
  return postJson("/product/agents/scheduler/tick", {
    project_id: projectId || null,
    limit: 30,
    dry_run: false,
    iterations,
    interval_seconds: iterations > 1 ? 5 : 0,
    stop_when_idle: true,
    lease_ttl_seconds: 300,
    retry_delay_seconds: 0
  }) as Promise<Record<string, unknown>>;
}

export function recoverAgentDispatch(queuePath: string) {
  return postJson("/product/agents/recover", {
    queue_path: queuePath,
    reason: "os agent dispatch center recovery"
  }) as Promise<Record<string, unknown>>;
}

export function repairDeadLetterDispatch(queuePath: string) {
  return postJson("/product/agents/dead-letter-repair", {
    queue_path: queuePath,
    reason: "os agent center v2 dead letter repair"
  }) as Promise<Record<string, unknown>>;
}

export function rehearseAgentRollback(queuePath: string) {
  return postJson("/product/agents/rollback-rehearsal", {
    queue_path: queuePath
  }) as Promise<Record<string, unknown>>;
}

export function createAgentDag(projectId?: string) {
  return postJson("/product/agents/dag", {
    project_id: projectId || "",
    name: "review -> revision -> publish gate",
    nodes: [
      { id: "draft", operation: "draft" },
      { id: "review", operation: "review", depends_on: ["draft"] },
      { id: "revision", operation: "revise", depends_on: ["review"] },
      { id: "publish_gate", operation: "create-publish-gate-report", depends_on: ["revision"] }
    ]
  }) as Promise<Record<string, unknown>>;
}

export function dispatchAgentRun(payload: {
  agent_run_path: string;
  workflow_run_id?: string;
  workflow_run_path?: string;
  workflow_node_id?: string;
  expected_output_assets?: string[];
  max_attempts?: number;
  priority?: number;
}) {
  return postJson("/product/agents/dispatch", {
    agent_run_path: payload.agent_run_path,
    workflow_run_id: payload.workflow_run_id || "",
    workflow_run_path: payload.workflow_run_path || "",
    workflow_node_id: payload.workflow_node_id || "",
    expected_output_assets: payload.expected_output_assets || [],
    max_attempts: payload.max_attempts ?? 3,
    priority: payload.priority ?? 100
  }) as Promise<Record<string, unknown>>;
}

export function dispatchAgentTaskFromIssue(issueRef: string, priority = 40) {
  return postJson("/product/agents/tasks/from-issue", {
    issue_ref: issueRef,
    agent_type: "review",
    operation: "fix_review_issue",
    token_budget: 1200,
    priority
  }) as Promise<Record<string, unknown>>;
}

export function loadTraceTimelineData(projectId?: string, traceId?: string) {
  const params = new URLSearchParams({ limit: "500" });
  if (projectId) params.set("project_id", projectId);
  if (traceId) params.set("trace_id", traceId);
  const projectQuery = projectId ? `project_id=${encodeURIComponent(projectId)}&` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<RuntimeTraceTimeline>(`/product/runtime/trace-timeline?${params.toString()}`),
    fetchJson<WorkflowRunRow[]>(`/product/workflow/runs?${projectQuery}limit=120`),
    fetchJson<AgentRunRow[]>(`/product/agents/runs?${projectQuery}limit=120`),
    fetchJson<AgentEventRow[]>(`/product/agents/events?${projectQuery}limit=160`)
  ]);
}

export function loadCostDashboardData(projectId?: string, scope?: string, sourceType?: string) {
  const ledgerParams = new URLSearchParams({ limit: "1000" });
  if (projectId) ledgerParams.set("project_id", projectId);
  if (scope) ledgerParams.set("scope", scope);
  if (sourceType) ledgerParams.set("source_type", sourceType);
  const dashboardParams = new URLSearchParams();
  if (projectId) dashboardParams.set("project_id", projectId);
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<RuntimeCostDashboard>(`/product/runtime/cost-dashboard?${dashboardParams.toString()}`),
    fetchJson<CostLedgerRow[]>(`/product/runtime/cost-ledger?${ledgerParams.toString()}`),
    fetchJson<AssetRow[]>(projectAssetPath(projectId, 260))
  ]);
}

export function loadRuntimePolicyEnforcement(projectId?: string) {
  const params = new URLSearchParams({ mode: "operating_system" });
  if (projectId) params.set("project_id", projectId);
  return fetchJson<Record<string, unknown>>(`/product/runtime/policy/enforcement-report?${params.toString()}`);
}

export function loadRuntimePolicyLegacyAudit() {
  return fetchJson<Record<string, unknown>>("/product/runtime/policy/legacy-entrypoint-audit");
}

export function loadRuntimePolicySurfaceCoverage(projectId?: string, workspacePath?: string) {
  const params = new URLSearchParams({ mode: "operating_system" });
  if (projectId) params.set("project_id", projectId);
  if (workspacePath) params.set("workspace_path", workspacePath);
  return fetchJson<Record<string, unknown>>(`/product/runtime/policy/surface-coverage?${params.toString()}`);
}

export function loadProviderHardStopEvidence(projectId?: string, workspacePath?: string) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (workspacePath) params.set("workspace_path", workspacePath);
  return fetchJson<Record<string, unknown>>(`/product/runtime/provider-hard-stop-evidence?${params.toString()}`);
}

export function previewRollback(transactionPathOrId: string, strategy = "restore_previous_versions") {
  return postJson("/product/runtime/rollback/preview", {
    transaction_path_or_id: transactionPathOrId,
    strategy,
    reason: "os console operator preview",
    persist: true
  }) as Promise<Record<string, unknown>>;
}

export function applyRollback(planPathOrId: string) {
  return postJson("/product/runtime/rollback/apply", {
    plan_path_or_id: planPathOrId,
    confirm: true,
    actor: "os-console"
  }) as Promise<Record<string, unknown>>;
}

export function verifyRollbackResult(resultPathOrId: string) {
  return postJson("/product/runtime/rollback/verify", {
    result_path_or_id: resultPathOrId
  }) as Promise<Record<string, unknown>>;
}

export function coordinateRollback(transactionPaths: string[], strategy = "physical_restore", confirm = false) {
  return postJson("/product/runtime/rollback/coordinate", {
    transaction_paths: transactionPaths,
    strategy,
    confirm,
    actor: "os-console",
    reason: "os console coordinated rollback"
  }) as Promise<Record<string, unknown>>;
}

export function createCostSnapshot(projectId?: string, workspacePath?: string, chapter?: number) {
  return postJson("/product/runtime/cost-snapshot", {
    project_id: projectId || null,
    workspace_path: workspacePath || null,
    chapter: chapter ?? null,
    persist_snapshots: true
  }) as Promise<Record<string, unknown>>;
}

export function loadInvalidationData(projectId?: string) {
  const projectQuery = projectId ? `project_id=${encodeURIComponent(projectId)}&` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ChangeImpactRow[]>(projectId ? `/product/impact/reports?project_id=${encodeURIComponent(projectId)}&limit=200` : "/product/impact/reports?limit=200"),
    fetchJson<AssetRow[]>(projectAssetPath(projectId, 260)),
    fetchJson<Record<string, unknown>>(`/product/novel-kg/dirty?${projectQuery}`),
    fetchJson<NodeRunRow[]>(`/product/workflow/node-runs?${projectQuery}limit=160`),
    fetchJson<WorkflowRunRow[]>(`/product/workflow/runs?${projectQuery}limit=120`)
  ]);
}

export function createImpactReport(targetPath: string, projectId?: string) {
  return postJson("/product/impact/report", {
    target_path: targetPath,
    max_depth: 5,
    project_id: projectId || null
  }) as Promise<Record<string, unknown>>;
}

export function refreshNovelKG(projectId?: string, workspacePath?: string, changedAssetPath?: string) {
  return postJson("/product/novel-kg/refresh", {
    project_id: projectId || null,
    workspace_path: workspacePath || null,
    changed_asset_path: changedAssetPath || null,
    apply_invalidation: Boolean(changedAssetPath)
  }) as Promise<Record<string, unknown>>;
}

export function runNovelKGGate(targetPath?: string, projectId?: string, workspacePath?: string) {
  return postJson("/product/novel-kg/gate", {
    target_path: targetPath || null,
    project_id: projectId || null,
    workspace_path: workspacePath || null
  }) as Promise<Record<string, unknown>>;
}

export function createNovelKGIdentityResolution(projectId?: string, workspacePath?: string) {
  return postJson("/product/novel-kg/identity-resolution", {
    snapshot_path: null,
    project_id: projectId || null,
    workspace_path: workspacePath || null,
    min_confidence: 0.68
  }) as Promise<Record<string, unknown>>;
}

export function loadReviewReworkData(projectId?: string) {
  const projectQuery = projectId ? `project_id=${encodeURIComponent(projectId)}&` : "";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<AssetRow[]>(projectAssetPath(projectId, 260)),
    fetchJson<RuntimeTraceTimeline>(`/product/runtime/trace-timeline?${projectQuery}limit=160`),
    fetchJson<RuntimeCostDashboard>(projectId ? `/product/runtime/cost-dashboard?project_id=${encodeURIComponent(projectId)}` : "/product/runtime/cost-dashboard")
  ]);
}

export function loadAssetDetail(path: string) {
  return fetchJson<AssetDetail>(`/product/assets/detail?path=${encodeURIComponent(path)}`);
}

export function updateReviewIssue(reviewPath: string, issueIndex: number, status: string, note?: string) {
  return fetchJson<Record<string, unknown>>("/product/reviews/issues", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ review_path: reviewPath, issue_index: issueIndex, status, note: note || null })
  });
}

export function updateReviewIssueAssetStatus(issueRef: string, status: string, note?: string) {
  return fetchJson<Record<string, unknown>>("/product/review-issues/status", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_ref: issueRef, status, note: note || "domain governance console" })
  });
}

export function runReview(draftPath: string, workspacePath?: string) {
  return postJson("/product/reviews/run", {
    draft_path: draftPath,
    workspace_path: workspacePath || null,
    comparison: false,
    update_workspace: true
  }) as Promise<Record<string, unknown>>;
}

export function createRevisionPlan(reviewPath: string, workspacePath?: string) {
  return postJson("/product/revisions/plan", {
    review_path: reviewPath,
    workspace_path: workspacePath || null
  }) as Promise<Record<string, unknown>>;
}

export function runReviewReworkLoop(payload: {
  review_path: string;
  draft_path?: string;
  issue_indexes?: number[];
  context_bundle_path?: string;
  workspace_path?: string;
  human_override?: boolean;
}) {
  return postJson("/product/revisions/rework-loop", {
    review_path: payload.review_path,
    draft_path: payload.draft_path || null,
    issue_indexes: payload.issue_indexes?.length ? payload.issue_indexes : null,
    context_bundle_path: payload.context_bundle_path || null,
    workspace_path: payload.workspace_path || null,
    human_override: Boolean(payload.human_override)
  }) as Promise<Record<string, unknown>>;
}

export function applyRevision(revisionPath: string, draftPath?: string, workspacePath?: string) {
  return postJson("/product/revisions/apply", {
    revision_path: revisionPath,
    draft_path: draftPath || null,
    workspace_path: workspacePath || null,
    confirmed: true,
    review_after: true
  }) as Promise<Record<string, unknown>>;
}

export function createPublishGate(draftPath: string, workspacePath?: string, humanOverride = false) {
  return postJson("/product/publishing/gate", {
    draft_path: draftPath,
    workspace_path: workspacePath || null,
    human_override: humanOverride
  }) as Promise<Record<string, unknown>>;
}

export function loadLongformStabilityData(projectId?: string, workspacePath?: string) {
  const params = new URLSearchParams({ limit: "320" });
  if (projectId) params.set("project_id", projectId);
  if (workspacePath) params.set("workspace_path", workspacePath);
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<AssetRow[]>(projectAssetPath(projectId, 320)),
    fetchJson<LongformStabilityDashboard>(`/product/longform-stability/dashboard?${params.toString()}`)
  ]);
}

export function runLongformExtraction(draftPath: string, workspacePath?: string, useModel = true) {
  return postJson("/product/longform-stability/extract", {
    draft_path: draftPath,
    workspace_path: workspacePath || null,
    use_model: useModel
  }) as Promise<Record<string, unknown>>;
}

export function upsertLongformControlAsset(payload: LongformControlAssetPayload) {
  return postJson("/product/longform-stability/control-asset", {
    asset_type: payload.asset_type,
    title: payload.title || null,
    project_id: payload.project_id || null,
    workspace_path: payload.workspace_path || null,
    content: payload.content || {}
  }) as Promise<Record<string, unknown>>;
}

export function calibrateLongformExtraction(draftPath: string, workspacePath?: string, expected?: Record<string, unknown>, useModel = true, persist = true) {
  return postJson("/product/longform-stability/calibrate", {
    draft_path: draftPath,
    workspace_path: workspacePath || null,
    expected: expected || {},
    use_model: useModel,
    persist
  }) as Promise<Record<string, unknown>>;
}

export function runLongformAcceptance(projectId?: string, workspacePath?: string, persist = true) {
  return postJson("/product/longform-stability/acceptance", {
    project_id: projectId || null,
    workspace_path: workspacePath || null,
    persist
  }) as Promise<Record<string, unknown>>;
}
