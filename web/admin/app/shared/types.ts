export type ProjectRow = {
  version?: number;
  path: string;
  id?: string;
  project_id: string;
  workspace_id?: string;
  asset_version_id?: string;
  content_hash?: string;
  title: string;
  series_title?: string;
  book_number?: number;
  chapter_count?: number;
  latest_chapter?: number;
  open_hook_count?: number;
  open_issue_count?: number;
  status?: string;
  recommendation?: string;
  task_type?: string;
  cost_estimate?: { cost?: number; currency?: string; source?: string };
  updated_at?: string;
  project_config?: Record<string, unknown>;
};

export type ProjectOperatingRow = {
  project_id: string;
  path: string;
  title: string;
  status: string;
  series_title?: string;
  chapter_count: number;
  asset_count: number;
  draft_count: number;
  review_count: number;
  profile_binding_count: number;
  profile_binding_total: number;
  missing_profiles: string[];
  risk_score: number;
  momentum_score: number;
  investment_score: number;
  open_issue_count: number;
  failed_task_count: number;
  pending_handoff_count: number;
  bottleneck: { severity: string; kind: string; label: string; suggestion: string };
  today_action: { action: string; label: string; href: string; reason: string };
  today_priority_rank: number;
  updated_at?: string;
};

export type ProjectOperatingDashboard = {
  summary: {
    project_count: number;
    active_project_count: number;
    high_risk_project_count: number;
    blocked_project_count: number;
    average_investment_score: number;
  };
  projects: ProjectOperatingRow[];
  today_priorities: Array<{
    project_id: string;
    title: string;
    action: string;
    label: string;
    reason: string;
    href: string;
    risk_score: number;
    investment_score: number;
    bottleneck: string;
  }>;
  bottlenecks: Array<{ project_id: string; title: string; severity: string; kind: string; label: string; suggestion: string }>;
};

export type AssetRow = {
  path: string;
  id?: string;
  asset_id?: string;
  asset_version_id?: string;
  category?: string;
  type: string;
  title: string;
  source?: string;
  chapter?: number | string;
  score?: number;
  risk_level?: string;
  asset_status?: string;
  status?: string;
  project_role?: string;
  updated_at?: string;
  summary?: string;
  tags?: string[];
  channel?: string;
  release_version?: string;
  version_key?: string;
  draft_path?: string;
  calendar_count?: number;
  next_scheduled_at?: string;
  chapter_queue_count?: number;
  platform_targets?: Array<Record<string, unknown>>;
  platform_rules?: Record<string, unknown>;
  gate_policy?: Record<string, unknown>;
  metadata_optimization?: Record<string, unknown>;
  cover_asset?: Record<string, unknown>;
  platform_feedback?: Record<string, unknown>;
  risk_explanations?: Array<Record<string, unknown>>;
  remediation_plan?: Array<Record<string, unknown>>;
  structure_similarity_matrix?: Array<Record<string, unknown>>;
  rollback_available?: boolean;
  release_package_path?: string;
  scheduled_at?: string;
  published_at?: string;
  external_url?: string;
};

export type AssetDetail = {
  path: string;
  summary: {
    id: string;
    type: string;
    title: string;
    tags: string[];
    source: string;
    chapter: number | string;
    score?: number;
    risk_level: string;
    asset_status: string;
    operator_notes: string;
    rights: Record<string, unknown>;
    preview: string;
  };
  lineage: { source: string; references: string[]; reference_assets: AssetRow[] };
  asset: Record<string, unknown>;
};

export type AssetGraphNode = {
  id: string;
  path: string;
  category?: string;
  type: string;
  title: string;
  layout?: { level?: number; x?: number; y?: number; cluster?: string };
};

export type AssetGraphEdge = {
  source: string;
  target: string;
  relation: string;
};

export type AssetGraph = {
  path: string;
  start_id: string;
  depth: number;
  nodes: AssetGraphNode[];
  edges: AssetGraphEdge[];
  layout?: Record<string, unknown>;
};

export type Health = {
  root: string;
  local_counts: Record<string, number>;
  configured_services: Record<string, boolean>;
  optional_dependencies: Record<string, boolean>;
  neo4j?: { enabled: boolean; configured: boolean; reason: string };
};

export type FeatureAssetRow = {
  path: string;
  id: string;
  asset_id?: string;
  asset_version_id?: string;
  type: string;
  title: string;
  project_id?: string;
  workspace_path?: string;
  source?: string;
  score?: number;
  risk_level?: string;
  status?: string;
  asset_status?: string;
  recommendation?: string;
  updated_at?: string;
  summary?: string;
  tags?: string[];
  content?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type ModuleCompletionReport = {
  snapshot_kind: string;
  project_id?: string;
  summary: {
    module_count: number;
    completed_count: number;
    partial_count: number;
    average_completion: number;
    blocking_count: number;
  };
  modules: Array<{
    key: string;
    name: string;
    status: string;
    completion_percent: number;
    code_score: number;
    runtime_asset_score: number;
    runtime_asset_counts: Record<string, number>;
    implemented: string[];
    remaining: string[];
    evidence_files: Array<{ path: string; exists: boolean }>;
    acceptance: string;
  }>;
  generated_at: string;
};

export type TaskRow = {
  path?: string;
  id?: string;
  operation_id?: string;
  version?: number;
  root_operation_id?: string;
  project_id?: string;
  workspace_id?: string;
  run_id: string;
  task_type: string;
  step: string;
  status: string;
  progress?: number;
  progress_percent?: number;
  event_count?: number;
  input_paths?: string[];
  output_paths?: string[];
  recorded_at?: string;
  updated_at?: string;
  error_message?: string;
  message?: string;
};

export type AgentEventRow = {
  path: string;
  id: string;
  agent_run_id: string;
  agent_run_path: string;
  event_type: string;
  status: string;
  message: string;
  payload?: Record<string, unknown>;
  project_id?: string;
  created_at?: string;
};

export type TaskCenter = {
  tasks: TaskRow[];
  latest?: TaskRow[];
  workflow_runs?: Array<Record<string, unknown>>;
  summary: { task_count: number; workflow_run_count?: number; by_status: Record<string, number>; by_step?: Record<string, number> };
  timeline: { events: TaskRow[]; summary?: Record<string, unknown> };
  recovery?: Array<Record<string, unknown>>;
  page?: { offset: number; limit: number; total: number };
  pagination?: { limit: number; offset: number; next_offset?: number | null };
};

export type TaskControl = {
  celery: {
    healthy: boolean;
    active_count: number;
    reserved_count: number;
    scheduled_count: number;
    workers: Record<string, unknown>;
    queue_lengths?: Record<string, unknown>;
  };
  config: Record<string, unknown>;
  queue_trend: Array<Record<string, unknown>>;
  scheduler?: {
    kind?: string;
    readiness?: string;
    status?: string;
    owner?: string;
    last_tick?: string;
    outbox_lag?: number;
    workers?: Array<{ status?: string; worker_id?: string; worker_kind?: string }>;
  };
  dead_letters?: { count: number };
};

export type DeadLetter = {
  path?: string;
  id?: string;
  kind?: string;
  operation_id?: string;
  project_id?: string;
  attempt_count?: number;
  task_name: string;
  task_id: string;
  error_type?: string;
  error_message: string;
  recorded_at?: string;
  created_at: string;
};

export type HandoffRow = {
  path: string;
  id: string;
  title: string;
  operation: string;
  skill: string;
  status: string;
  runtime: string;
  runtime_model: string;
  source_path: string;
  expected_output_type: string;
  expected_output_dir: string;
  validation_command: string;
  input_files: Array<{ path: string; role: string; must_read?: boolean; content_policy?: string }>;
  acceptance_checks: string[];
  project_id: string;
  workspace_path: string;
  updated_at: string;
};

export type HandoffAcceptance = {
  handoff_path: string;
  handoff_id: string;
  status: string;
  checks: Array<{ index: number; check: string; status: string; note: string; updated_at: string }>;
  summary: { total: number; accepted: number; failed: number; pending: number; complete: boolean };
};

export type HandoffOutputValidation = {
  ok: boolean;
  errors: string[];
  handoff_id: string;
  expected_output_type: string;
  expected_output_dir: string;
  output_path: string;
  output_id: string;
  actual_output_type: string;
};

export type GitHubSource = {
  id: string;
  repo: string;
  url: string;
  category: string;
  type: string;
  disciplines: string[];
  use_for: string[];
  allowed_pipeline: string[];
  forbidden_pipeline: string[];
  license_check: string;
  commercial_risk: string;
};

export type BatchItem = {
  path: string;
  id: string;
  batch_id: string;
  item_index: number;
  source_path: string;
  source_name: string;
  status: string;
  steps: Array<{ step: string; status: string; output_path?: string; error_message?: string }>;
  output_paths: string[];
  error_message: string;
  retry_count: number;
  analysis_mode: string;
  handoff_path: string;
  handoff_id: string;
  handoff_status: string;
  handoff_generation: number;
  review_status: string;
  updated_at: string;
};

export type NodeRunRow = {
  path: string;
  id: string;
  run_id: string;
  node_id: string;
  node_type: string;
  operation: string;
  status: string;
  input_count: number;
  output_count: number;
  project_id: string;
  workspace_path: string;
  started_at: string;
  finished_at: string;
  error: string;
};

export type WorkflowDefinitionRow = {
  path: string;
  id: string;
  workflow_id: string;
  name: string;
  version: string;
  entry_node_id: string;
  status: string;
  node_count: number;
  updated_at?: string;
};

export type WorkflowRunRow = {
  path: string;
  id: string;
  run_id: string;
  workflow_id: string;
  status: string;
  blocked_node_id: string;
  blocked_status: string;
  blocked_reason: string;
  node_run_count: number;
  agent_run_count: number;
  output_count: number;
  trace_id: string;
  project_id: string;
  workspace_path: string;
  started_at: string;
  finished_at: string;
  updated_at?: string;
};

export type AgentRunRow = {
  path: string;
  id: string;
  run_id: string;
  agent_type: string;
  operation: string;
  status: string;
  input_count: number;
  output_count: number;
  contract_id: string;
  contract_path: string;
  model_provider: string;
  model_name: string;
  prompt_version: string;
  token_budget: number;
  token_used: number;
  cost_estimate: number;
  error: string;
  human_gate: Record<string, unknown>;
  input_assets?: string[];
  output_assets?: string[];
  checkpoint?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  project_id: string;
  workspace_path: string;
  started_at: string;
  finished_at: string;
  updated_at: string;
};

export type BackupRow = { path: string; size_bytes: number; created_at: string };

export type PostgresStrictCheck = {
  strict: boolean;
  write_through: boolean;
  database_url_configured: boolean;
  ready: boolean;
  checks: Array<{ name: string; ok: boolean; message: string; counts?: Record<string, number> }>;
  sync: Record<string, number>;
  errors: string[];
};

export type EmbeddingHealth = {
  ok: boolean;
  configured?: boolean;
  semantic_model?: boolean;
  external_api?: boolean;
  model?: string;
  provider?: string;
  dimensions?: number;
  message?: string;
  error?: string;
  missing_env_vars?: string[];
};

export type ProjectScopeAudit = {
  project_id: string;
  workspace_path: string;
  repair: boolean;
  summary: {
    issue_count: number;
    repaired_count: number;
    unscoped_count: number;
    cross_project_count: number;
    handoff_mismatch_count: number;
    repairable_count: number;
  };
  issues: Array<Record<string, unknown>>;
  repairs: Array<Record<string, unknown>>;
};

export type ProjectHealthReport = {
  project_id: string;
  heartbeat: string;
  summary: {
    asset_count: number;
    task_count: number;
    failed_task_count: number;
    pending_handoff_count: number;
    scope_issue_count: number;
    dead_letter_count: number;
  };
  scope_audit: ProjectScopeAudit;
  postgres: PostgresStrictCheck;
  embedding: EmbeddingHealth;
  celery: TaskControl["celery"];
  task_control: Record<string, unknown>;
  queue_trend: TaskControl["queue_trend"];
  recent_failures: TaskRow[];
  handoffs: HandoffRow[];
  backups: BackupRow[];
};

export type QdrantSearchResult = {
  backend: string;
  query: string;
  count: number;
  results: Array<{
    rank: number;
    path: string;
    type?: string;
    title?: string;
    score?: number;
    preview?: string;
    explanation?: { reason?: string; score?: number; backend?: string };
  }>;
};

export type MinioStatus = {
  configured: boolean;
  available?: boolean;
  bucket: string;
  error?: string;
  objects: Array<{ category: string; path: string; object_name: string; exists: boolean; size: number; etag: string; error: string }>;
};

export type FeedbackAssetRow = {
  path: string;
  id: string;
  type: string;
  title: string;
  project_id: string;
  workspace_path: string;
  row_count: number;
  average_rating: number;
  confidence: string;
  sentiment_distribution: Record<string, number>;
  character_heat?: Array<{ character: string; mentions: number; heat: number }>;
  follow_read_risk?: { level?: string; score?: number; negative_ratio?: number };
  read_metrics?: Record<string, number>;
  engagement_metrics?: Record<string, number>;
  chapter_dropoffs?: Array<{ chapter: number; reads: number; drop_rate: number; explicit_drop_signals: number; average_rating: number; risk: string }>;
  reader_simulation?: {
    predicted_score?: number;
    dropout_risk?: string;
    pleasure_gaps?: string[];
    next_chapter_expectations?: string[];
    revision_suggestions?: string[];
    recommendation?: string;
  };
  target_updates?: Record<string, { status?: string; path?: string; updates?: unknown[] }>;
  next_chapter_strategy?: {
    primary_strategy?: string;
    constraints?: string[];
    actions?: string[];
    focus_character?: string;
    risk_level?: string;
  };
  recommendation: string;
  status: string;
  updated_at: string;
};

export type MetricSnapshotRow = {
  path: string;
  id: string;
  title: string;
  project_id: string;
  workspace_path: string;
  snapshot_at: string;
  throughput: Record<string, number>;
  quality: Record<string, number>;
  task_health: Record<string, number>;
  agent_health: Record<string, number>;
  storage_health: Record<string, number>;
  trends?: Record<string, number>;
  model_cost?: { token_used?: number; cost_estimate?: number; provider_counts?: Record<string, number>; benchmark_run_count?: number };
  originality?: { risk_counts?: Record<string, number>; high_or_medium_count?: number; risk_rate?: number };
  recommendations: string[];
  risk_level: string;
  updated_at: string;
};
