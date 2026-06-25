"use client";

import {
  Activity,
  Archive,
  BookOpen,
  Boxes,
  CheckCircle2,
  Copy,
  Database,
  FileSearch,
  GitPullRequest,
  Layers3,
  Languages,
  ListChecks,
  Network,
  PenLine,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Server,
  Trash2,
  UploadCloud,
  Workflow
} from "lucide-react";
import type { FormEvent, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_NOVEL_FORGE_API_URL ?? "http://localhost:8000";

type Health = {
  root: string;
  local_counts: Record<string, number>;
  configured_services: Record<string, boolean>;
  optional_dependencies: Record<string, boolean>;
  neo4j: { enabled: boolean; configured: boolean; reason: string };
};

type AssetRow = {
  path: string;
  category: string;
  type: string;
  title: string;
  tags: string[];
  source: string;
  score?: number;
  risk_level?: string;
  asset_status?: string;
};

type ProjectRow = {
  path: string;
  id: string;
  project_id: string;
  title: string;
  series_title: string;
  book_number?: number;
  chapter_count: number;
  latest_chapter: number;
  open_hook_count: number;
  open_issue_count: number;
  status: string;
  updated_at: string;
  project_config: ProjectConfig;
};

type SeriesRow = {
  series_title: string;
  book_count: number;
  project_count: number;
  latest_updated_at: string;
  projects: Array<{
    project_id: string;
    title: string;
    book_number?: number;
    status: string;
    path: string;
    chapter_count: number;
    open_issue_count: number;
  }>;
};

type ProjectConfig = {
  genre: string;
  target_platform: string;
  target_word_count: number;
  update_cadence: string;
  quality_threshold: number;
  audience: string;
  status: string;
};

type TaskCenter = {
  tasks: TaskRow[];
  workflow_runs: WorkflowRow[];
  summary: { task_count: number; workflow_run_count: number; by_status: Record<string, number> };
  steps: string[];
  timeline: TaskTimeline;
  recovery: RecoveryReport[];
  page?: { offset: number; limit: number; total: number };
};

type TaskRow = {
  path: string;
  id: string;
  run_id: string;
  step: string;
  status: string;
  task_type: string;
  event_count: number;
  input_paths: string[];
  output_paths: string[];
  error_message: string;
  message: string;
  recorded_at: string;
};

type WorkflowRow = {
  path: string;
  id: string;
  title: string;
  status: string;
  outputs: string[];
  task_statuses: string[];
  updated_at: string;
};

type TaskTimeline = {
  events: TimelineEvent[];
  runs: TimelineRun[];
  summary: { event_count: number; run_count: number; failed_count: number; latest_at: string };
};

type TimelineEvent = {
  path: string;
  id: string;
  run_id: string;
  step: string;
  status: string;
  task_type: string;
  input_paths: string[];
  output_paths: string[];
  error_message: string;
  recorded_at: string;
  message: string;
};

type TimelineRun = {
  run_id: string;
  status: string;
  progress_percent: number;
  completed_steps: number;
  total_steps: number;
  failed_steps: string[];
  latest_event_at: string;
};

type RecoveryReport = {
  run_id: string;
  failed_step: string;
  failed_status_path: string;
  input_paths: string[];
  output_paths: string[];
  error_message: string;
  recovery_instruction: string;
};

type DeadLetter = {
  path: string;
  id: string;
  task_name: string;
  task_id: string;
  error_type: string;
  error_message: string;
  recorded_at: string;
};

type BatchItem = {
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
  handoff_history: Array<{ path: string; id: string; status: string; generation: number; created_at: string }>;
  review_status: string;
  review_gate: { decision?: string; note?: string; reviewed_at?: string };
  raw: string;
  cleaned: string;
  decomposition: string;
  knowledge: string;
  material: string;
  updated_at: string;
};

type UploadResult = {
  upload_id: string;
  input_path: string;
  items: Array<{
    filename: string;
    path: string;
    format: string;
    size_bytes: number;
    sha256: string;
    duplicate: boolean;
    duplicate_of: string;
    preview: string;
    minio: { uploaded: boolean; error?: string; bucket?: string; object_name?: string };
  }>;
  rights: Record<string, unknown>;
};

type TaskControl = {
  config: { max_concurrent_batches: number; max_concurrent_steps: number };
  celery: {
    available: boolean;
    healthy: boolean;
    error: string;
    active_count: number;
    reserved_count: number;
    scheduled_count: number;
    queue_lengths: Record<string, unknown>;
  };
  queue_trend: Array<{ recorded_at: string; healthy: boolean; active_count: number; reserved_count: number; scheduled_count: number; queue_total: number; queues: Record<string, number> }>;
  dead_letters: { count: number };
  failed_batch_items: BatchItem[];
  waiting_handoffs: BatchItem[];
  heartbeat: string;
};

type ProjectScopeIssue = {
  kind: string;
  severity: string;
  path: string;
  id: string;
  type: string;
  title: string;
  project_id: string;
  workspace_path: string;
  expected_project_id?: string;
  expected_workspace_path?: string;
  inferred_project_id?: string;
  inferred_workspace_path?: string;
  linked_project_ids?: string[];
  repairable: boolean;
  message: string;
};

type ProjectScopeAudit = {
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
  issues: ProjectScopeIssue[];
  repairs: Array<{ kind: string; path: string; project_id: string }>;
};

type PostgresStrictCheck = {
  strict: boolean;
  write_through: boolean;
  database_url_configured: boolean;
  ready: boolean;
  checks: Array<{ name: string; ok: boolean; message: string; counts?: Record<string, number> }>;
  sync: Record<string, number>;
  errors: string[];
};

type EmbeddingHealth = {
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

type HandoffAcceptance = {
  handoff_path: string;
  handoff_id: string;
  status: string;
  checks: Array<{ index: number; check: string; status: string; note: string; updated_at: string }>;
  summary: { total: number; accepted: number; failed: number; pending: number; complete: boolean };
};

type BackupRow = { path: string; size_bytes: number; created_at: string };

type ProjectHealthReport = {
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
  task_control: TaskControl["config"];
  queue_trend: TaskControl["queue_trend"];
  recent_failures: TaskRow[];
  handoffs: HandoffRow[];
  backups: BackupRow[];
};

type DraftEditorState = {
  path: string;
  id: string;
  title: string;
  chapter: number | string;
  text: string;
  version_index: number;
  status: string;
};

type RevisionApplyResult = {
  mode: string;
  requires_confirmation: boolean;
  draft_path?: string;
  after_review_path?: string;
  score_before?: number;
  score_after?: number;
  target_score?: number;
  preview: { excerpt: string; score_before?: number; target_score?: number; steps: string[] };
};

type DraftWorkbench = {
  chapter_plans: WorkbenchRow[];
  drafts: WorkbenchRow[];
  reviews: WorkbenchRow[];
  revision_plans: WorkbenchRow[];
  workspace: ProjectRow[];
};

type WorkbenchRow = {
  path: string;
  id: string;
  type: string;
  title: string;
  source: string;
  chapter: number | string;
  score?: number;
  risk_level: string;
  updated_at: string;
  summary: string;
  tags: string[];
};

type AssetDetail = {
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
  lineage: { source: string; references: string[]; reference_assets: WorkbenchRow[] };
  asset: Record<string, unknown>;
};

type AssetVersions = {
  path: string;
  current_hash: string;
  versions: Array<{
    path: string;
    kind: string;
    sha256: string;
    size_bytes: number;
    updated_at: string;
    title: string;
    type: string;
  }>;
  diff: { from_path: string; to_path: string; unified_diff: string };
};

type AssetGraph = {
  path: string;
  start_id: string;
  depth: number;
  nodes: Array<{ id: string; path: string; category: string; type: string; title: string }>;
  edges: Array<{ source: string; target: string; relation: string }>;
};

type HandoffOutputValidation = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  handoff_path: string;
  handoff_id: string;
  expected_output_type: string;
  expected_output_dir: string;
  output_path: string;
  output_id: string;
  actual_output_type: string;
};

type HandoffRow = {
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

type GitHubSource = {
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

type Language = "en" | "zh";
type TabKey = "projects" | "health" | "tasks" | "assets" | "handoffs" | "batch" | "drafts" | "reviews";

const tabConfig: { key: TabKey; icon: ReactNode }[] = [
  { key: "projects", icon: <Boxes size={17} /> },
  { key: "health", icon: <Activity size={17} /> },
  { key: "tasks", icon: <ListChecks size={17} /> },
  { key: "assets", icon: <FileSearch size={17} /> },
  { key: "handoffs", icon: <Workflow size={17} /> },
  { key: "batch", icon: <Layers3 size={17} /> },
  { key: "drafts", icon: <PenLine size={17} /> },
  { key: "reviews", icon: <GitPullRequest size={17} /> }
];

const serviceIcons: Record<string, ReactNode> = {
  postgresql: <Database size={17} />,
  redis: <Activity size={17} />,
  celery: <Workflow size={17} />,
  qdrant: <Search size={17} />,
  minio: <UploadCloud size={17} />,
  neo4j: <Network size={17} />
};

const copy = {
  en: {
    title: "Production Console",
    refresh: "Refresh",
    runSample: "Run sample pipeline",
    run: "Run",
    language: "中文",
    metrics: { assets: "Assets", projects: "Projects", tasks: "Tasks", api: "API" },
    tabs: {
      projects: "Projects",
      health: "Health",
      tasks: "Tasks",
      assets: "Assets",
      handoffs: "Handoffs",
      batch: "Batch",
      drafts: "Drafts",
      reviews: "Review"
    },
    handoffs: {
      title: "Claude Code Handoffs",
      deconstruct: "Novel Deconstruction",
      knowledge: "Knowledge Parsing",
      githubKnowledge: "GitHub Knowledge Sources",
      input: "Input asset path",
      githubRefs: "Repository refs",
      genre: "Genre",
      reader: "Target reader",
      purpose: "Purpose",
      discipline: "Discipline",
      credibility: "Credibility",
      scope: "Scope",
      context: "Project context",
      createDeconstruct: "Create Deconstruct Handoff",
      createKnowledge: "Create Knowledge Handoff",
      createGithubKnowledge: "Create GitHub Knowledge Handoff",
      githubSources: "Registered Sources",
      add: "Add",
      list: "Handoff Queue",
      detail: "Handoff Detail",
      inputFiles: "Input Files",
      checks: "Acceptance Checks",
      noSelection: "No handoff selected",
      columns: ["Operation", "Status", "Skill", "Expected Output", "Source", "Action", "Path"],
      open: "Open",
      source: "Source",
      expected: "Expected",
      validation: "Validation",
      status: "Status",
      execution: "Execution",
      empty: "Empty"
    }
  },
  zh: {
    title: "生产管理台",
    refresh: "刷新",
    runSample: "运行样例流水线",
    run: "运行",
    language: "English",
    metrics: { assets: "资产", projects: "项目", tasks: "任务", api: "API" },
    tabs: {
      projects: "项目",
      health: "健康",
      tasks: "任务",
      assets: "资产",
      handoffs: "执行包",
      batch: "批处理",
      drafts: "稿件",
      reviews: "审稿"
    },
    handoffs: {
      title: "Claude Code 执行包",
      deconstruct: "网文拆解",
      knowledge: "多学科知识解析",
      githubKnowledge: "GitHub 知识源",
      input: "输入资产路径",
      githubRefs: "仓库 refs",
      genre: "题材",
      reader: "目标读者",
      purpose: "解析目的",
      discipline: "学科",
      credibility: "可信度",
      scope: "解析范围",
      context: "项目上下文",
      createDeconstruct: "生成拆解执行包",
      createKnowledge: "生成知识执行包",
      createGithubKnowledge: "生成 GitHub 知识执行包",
      githubSources: "登记来源",
      add: "加入",
      list: "执行包队列",
      detail: "执行包详情",
      inputFiles: "输入文件",
      checks: "验收项",
      noSelection: "未选择执行包",
      columns: ["操作", "状态", "技能", "期望产物", "来源", "动作", "路径"],
      open: "打开",
      source: "来源",
      expected: "期望产物",
      validation: "校验命令",
      status: "状态",
      execution: "执行信息",
      empty: "空"
    }
  }
} satisfies Record<Language, {
  title: string;
  refresh: string;
  runSample: string;
  run: string;
  language: string;
  metrics: { assets: string; projects: string; tasks: string; api: string };
  tabs: Record<TabKey, string>;
  handoffs: {
    title: string;
    deconstruct: string;
    knowledge: string;
    githubKnowledge: string;
    input: string;
    githubRefs: string;
    genre: string;
    reader: string;
    purpose: string;
    discipline: string;
    credibility: string;
    scope: string;
    context: string;
    createDeconstruct: string;
    createKnowledge: string;
    createGithubKnowledge: string;
    githubSources: string;
    add: string;
    list: string;
    detail: string;
    inputFiles: string;
    checks: string;
    noSelection: string;
    columns: string[];
    open: string;
    source: string;
    expected: string;
    validation: string;
    status: string;
    execution: string;
    empty: string;
  };
}>;

export default function AdminPage() {
  const [language, setLanguage] = useState<Language>("en");
  const [activeTab, setActiveTab] = useState<TabKey>("projects");
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [seriesRows, setSeriesRows] = useState<SeriesRow[]>([]);
  const [taskCenter, setTaskCenter] = useState<TaskCenter | null>(null);
  const [taskControl, setTaskControl] = useState<TaskControl | null>(null);
  const [scopeAudit, setScopeAudit] = useState<ProjectScopeAudit | null>(null);
  const [postgresStrict, setPostgresStrict] = useState<PostgresStrictCheck | null>(null);
  const [projectHealth, setProjectHealth] = useState<ProjectHealthReport | null>(null);
  const [backups, setBackups] = useState<BackupRow[]>([]);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [assetDetail, setAssetDetail] = useState<AssetDetail | null>(null);
  const [assetVersions, setAssetVersions] = useState<AssetVersions | null>(null);
  const [assetGraph, setAssetGraph] = useState<AssetGraph | null>(null);
  const [handoffs, setHandoffs] = useState<HandoffRow[]>([]);
  const [handoffDetail, setHandoffDetail] = useState<AssetDetail | null>(null);
  const [githubSources, setGithubSources] = useState<GitHubSource[]>([]);
  const [batchItems, setBatchItems] = useState<BatchItem[]>([]);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [drafts, setDrafts] = useState<DraftWorkbench | null>(null);
  const [draftEditor, setDraftEditor] = useState<DraftEditorState | null>(null);
  const [draftExport, setDraftExport] = useState<Record<string, unknown> | null>(null);
  const [reviewDetail, setReviewDetail] = useState<AssetDetail | null>(null);
  const [revisionPreview, setRevisionPreview] = useState<RevisionApplyResult | null>(null);
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState("");
  const [collectionTitle, setCollectionTitle] = useState("Saved asset set");
  const [projectTitle, setProjectTitle] = useState("New Novel Project");
  const [seriesTitle, setSeriesTitle] = useState("");
  const [bookNumber, setBookNumber] = useState("1");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [batchInput, setBatchInput] = useState("examples/sample_inputs");
  const [batchAnalysisMode, setBatchAnalysisMode] = useState("auto");
  const [batchDecompositionPath, setBatchDecompositionPath] = useState("");
  const [batchKnowledgePath, setBatchKnowledgePath] = useState("");
  const [selectedPlan, setSelectedPlan] = useState("");
  const [selectedDraft, setSelectedDraft] = useState("");
  const [selectedReview, setSelectedReview] = useState("");
  const [selectedRevision, setSelectedRevision] = useState("");
  const [selectedWorkspace, setSelectedWorkspace] = useState("");
  const [taskStatusFilter, setTaskStatusFilter] = useState("");
  const [taskTypeFilter, setTaskTypeFilter] = useState("");
  const [taskStepFilter, setTaskStepFilter] = useState("");
  const [taskOffset, setTaskOffset] = useState(0);
  const [restorePath, setRestorePath] = useState("");
  const [handoffInput, setHandoffInput] = useState("");
  const [handoffGenre, setHandoffGenre] = useState("");
  const [handoffReader, setHandoffReader] = useState("");
  const [handoffPurpose, setHandoffPurpose] = useState("");
  const [handoffDiscipline, setHandoffDiscipline] = useState("");
  const [handoffCredibility, setHandoffCredibility] = useState("");
  const [handoffScope, setHandoffScope] = useState("");
  const [handoffContext, setHandoffContext] = useState("");
  const [githubSourceRefs, setGithubSourceRefs] = useState("NiuTrans/Classical-Modern, ydli-ai/CSL");
  const [projectConfig, setProjectConfig] = useState<ProjectConfig>({
    genre: "",
    target_platform: "",
    target_word_count: 0,
    update_cadence: "",
    quality_threshold: 80,
    audience: "",
    status: "active"
  });
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const text = copy[language];

  const totalAssets = useMemo(() => {
    if (!health) return 0;
    return Object.values(health.local_counts).reduce((sum, value) => sum + value, 0);
  }, [health]);

  async function loadAll(
    projectOverride?: string,
    taskOverride?: { offset?: number; status?: string; taskType?: string; step?: string }
  ) {
    setError("");
    try {
      const [healthData, projectData, seriesData, controlData] = await Promise.all([
        fetchJson<Health>("/health"),
        fetchJson<ProjectRow[]>("/product/projects"),
        fetchJson<SeriesRow[]>("/product/series"),
        fetchJson<TaskControl>("/product/tasks/control")
      ]);
      const nextProjectId =
        projectOverride ||
        (selectedProjectId && projectData.some((project) => project.project_id === selectedProjectId)
          ? selectedProjectId
          : projectData[0]?.project_id || "");
      const selectedProject = projectData.find((project) => project.project_id === nextProjectId);
      const effectiveTaskOffset = taskOverride?.offset ?? taskOffset;
      const effectiveTaskStatus = taskOverride?.status ?? taskStatusFilter;
      const effectiveTaskType = taskOverride?.taskType ?? taskTypeFilter;
      const effectiveTaskStep = taskOverride?.step ?? taskStepFilter;
      const taskParams = new URLSearchParams({ limit: "80", offset: String(effectiveTaskOffset) });
      if (nextProjectId) taskParams.set("project_id", nextProjectId);
      if (effectiveTaskStatus) taskParams.set("status", effectiveTaskStatus);
      if (effectiveTaskType) taskParams.set("task_type", effectiveTaskType);
      if (effectiveTaskStep) taskParams.set("step", effectiveTaskStep);
      const taskPath = `/product/tasks?${taskParams.toString()}`;
      const assetPath = nextProjectId
        ? `/product/projects/${encodeURIComponent(nextProjectId)}/assets?limit=80`
        : "/assets?limit=40&rank=path";
      const draftPath = nextProjectId
        ? `/product/drafts?project_id=${encodeURIComponent(nextProjectId)}`
        : "/product/drafts";
      const batchPath = nextProjectId
        ? `/product/batch/items?limit=80&project_id=${encodeURIComponent(nextProjectId)}`
        : "/product/batch/items?limit=80";
      const handoffPath = nextProjectId
        ? `/product/handoffs?limit=80&project_id=${encodeURIComponent(nextProjectId)}`
        : "/product/handoffs?limit=80";
      const auditPath = nextProjectId
        ? `/product/projects/audit/scope?project_id=${encodeURIComponent(nextProjectId)}`
        : "/product/projects/audit/scope";
      const healthPath = nextProjectId
        ? `/product/system/health?project_id=${encodeURIComponent(nextProjectId)}`
        : "/product/system/health";
      const [taskData, assetData, draftData, batchData, handoffData, deadLetterData, githubSourceData, auditData, strictData, healthReport, backupRows] = await Promise.all([
        fetchJson<TaskCenter>(taskPath),
        fetchJson<AssetRow[]>(assetPath),
        fetchJson<DraftWorkbench>(draftPath),
        fetchJson<BatchItem[]>(batchPath),
        fetchJson<HandoffRow[]>(handoffPath),
        fetchJson<DeadLetter[]>("/product/tasks/dead-letters?limit=40"),
        fetchJson<GitHubSource[]>("/product/sources/github?allowed_pipeline=knowledge_card_extraction"),
        fetchJson<ProjectScopeAudit>(auditPath),
        fetchJson<PostgresStrictCheck>("/product/system/postgres/strict-check"),
        fetchJson<ProjectHealthReport>(healthPath),
        fetchJson<BackupRow[]>("/product/system/backups?limit=20")
      ]);
      setHealth(healthData);
      setTaskControl(controlData);
      setProjects(projectData);
      setSeriesRows(seriesData);
      setTaskCenter(taskData);
      setAssets(assetData);
      setDrafts(draftData);
      setBatchItems(batchData);
      setHandoffs(handoffData);
      setDeadLetters(deadLetterData);
      setGithubSources(githubSourceData);
      setScopeAudit(auditData);
      setPostgresStrict(strictData);
      setProjectHealth(healthReport);
      setBackups(backupRows);
      setSelectedProjectId(nextProjectId);
      if (selectedProject) {
        setSelectedWorkspace(selectedProject.path);
        setProjectConfig(selectedProject.project_config);
      }
      setSelectedPlan((current) => current || draftData.chapter_plans[0]?.path || "");
      setSelectedDraft((current) => current || draftData.drafts[0]?.path || "");
      setSelectedReview((current) => current || draftData.reviews[0]?.path || "");
      setSelectedRevision((current) => current || draftData.revision_plans[0]?.path || "");
      setHandoffInput((current) => current || assetData[0]?.path || draftData.chapter_plans[0]?.path || "");
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  async function loadDraftEditor(path: string) {
    if (!path) {
      setDraftEditor(null);
      return;
    }
    setDraftEditor(await fetchJson<DraftEditorState>(`/product/drafts/editor?path=${encodeURIComponent(path)}`));
  }

  async function loadReviewDetail(path: string) {
    if (!path) {
      setReviewDetail(null);
      return;
    }
    setReviewDetail(await fetchJson<AssetDetail>(`/product/assets/detail?path=${encodeURIComponent(path)}`));
  }

  async function searchAssets(event?: FormEvent) {
    event?.preventDefault();
    setError("");
    const params = new URLSearchParams({ limit: "40", rank: keyword.trim() ? "relevance" : "path" });
    if (keyword.trim()) params.set("keyword", keyword.trim());
    if (category) params.set("category", category);
    try {
      if (selectedProjectId) {
        setAssets(
          await fetchJson<AssetRow[]>(
            `/product/projects/${encodeURIComponent(selectedProjectId)}/assets?${params.toString()}`
          )
        );
      } else {
        setAssets(await fetchJson<AssetRow[]>(`/assets?${params.toString()}`));
      }
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  async function selectAsset(path: string) {
    setError("");
    try {
      const [detail, versions, graph] = await Promise.all([
        fetchJson<AssetDetail>(`/product/assets/detail?path=${encodeURIComponent(path)}`),
        fetchJson<AssetVersions>(`/product/assets/versions?path=${encodeURIComponent(path)}`),
        fetchJson<AssetGraph>(`/product/assets/graph?path=${encodeURIComponent(path)}&depth=1`)
      ]);
      setAssetDetail(detail);
      setAssetVersions(versions);
      setAssetGraph(graph);
      setActiveTab("assets");
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  async function selectHandoff(path: string) {
    setError("");
    try {
      setActiveTab("handoffs");
      setHandoffDetail(await fetchJson<AssetDetail>(`/product/assets/detail?path=${encodeURIComponent(path)}`));
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  async function runAction(action: () => Promise<unknown>, label: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await action();
      setNotice(`${label}: ${compactResult(result)}`);
      await loadAll();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language]);

  useEffect(() => {
    if (selectedDraft) {
      loadDraftEditor(selectedDraft).catch((caught) => setError(messageOf(caught)));
    }
  }, [selectedDraft]);

  useEffect(() => {
    if (selectedReview) {
      loadReviewDetail(selectedReview).catch((caught) => setError(messageOf(caught)));
    }
  }, [selectedReview]);

  useEffect(() => {
    const params = new URLSearchParams({ limit: "80", offset: String(taskOffset) });
    if (selectedProjectId) params.set("project_id", selectedProjectId);
    if (taskStatusFilter) params.set("status", taskStatusFilter);
    if (taskTypeFilter) params.set("task_type", taskTypeFilter);
    if (taskStepFilter) params.set("step", taskStepFilter);
    const events = new EventSource(`${API_BASE}/product/tasks/events?${params.toString()}`);
    events.onmessage = (event) => {
      try {
        setTaskCenter(JSON.parse(event.data));
      } catch {
        // Ignore malformed partial event data.
      }
    };
    events.onerror = () => events.close();
    return () => events.close();
  }, [selectedProjectId, taskOffset, taskStatusFilter, taskTypeFilter, taskStepFilter]);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Novel Forge V5</p>
          <h1>{text.title}</h1>
        </div>
        <div className="actions">
          <button
            title={text.language}
            onClick={() => setLanguage((current) => (current === "en" ? "zh" : "en"))}
            className="secondaryButton"
          >
            <Languages size={18} />
            {text.language}
          </button>
          <button title={text.refresh} onClick={() => loadAll()} className="iconButton">
            <RefreshCw size={18} />
          </button>
          <button
            title={text.runSample}
            onClick={() =>
              runAction(
                () => postJson("/pipeline/run", { sample: true, async_task: false }),
                "sample pipeline"
              )
            }
            disabled={busy}
            className="primaryButton"
          >
            <Play size={18} />
            {text.run}
          </button>
        </div>
      </header>

      <section className="summaryBand">
        <Metric label={text.metrics.assets} value={String(totalAssets)} />
        <Metric label={text.metrics.projects} value={String(projects.length)} />
        <Metric label={text.metrics.tasks} value={String(taskCenter?.summary.task_count ?? 0)} />
        <Metric label={text.metrics.api} value={API_BASE} code />
      </section>

      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <nav className="tabbar" aria-label="Workspaces">
        {tabConfig.map((tab) => (
          <button
            key={tab.key}
            className={activeTab === tab.key ? "tab active" : "tab"}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.icon}
            {text.tabs[tab.key]}
          </button>
        ))}
      </nav>

      {activeTab === "projects" ? (
        <ProjectsPanel
          language={language}
          health={health}
          scopeAudit={scopeAudit}
          postgresStrict={postgresStrict}
          projects={projects}
          seriesRows={seriesRows}
          projectTitle={projectTitle}
          setProjectTitle={setProjectTitle}
          seriesTitle={seriesTitle}
          setSeriesTitle={setSeriesTitle}
          bookNumber={bookNumber}
          setBookNumber={setBookNumber}
          selectedProjectId={selectedProjectId}
          selectedWorkspace={selectedWorkspace}
          projectConfig={projectConfig}
          setProjectConfig={setProjectConfig}
          busy={busy}
          onCreate={() =>
            runAction(
              () =>
                postJson("/product/projects", {
                  title: projectTitle,
                  series_title: seriesTitle || null,
                  book_number: bookNumber ? Number(bookNumber) : null
                }),
              "project created"
            )
          }
          onSelectProject={(project) => {
            setSelectedProjectId(project.project_id);
            setSelectedWorkspace(project.path);
            setProjectConfig(project.project_config);
            loadAll(project.project_id);
          }}
          onSaveConfig={() =>
            runAction(
              () =>
                fetchJson(`/product/projects/${encodeURIComponent(selectedProjectId)}/config`, {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(projectConfig)
                }),
              "project config saved"
            )
          }
          onPause={() =>
            runAction(
              () => postJson(`/product/projects/${encodeURIComponent(selectedProjectId)}/pause`, {}),
              "project paused"
            )
          }
          onArchive={() =>
            runAction(
              () => postJson(`/product/projects/${encodeURIComponent(selectedProjectId)}/archive`, {}),
              "project archived"
            )
          }
          onRestore={() =>
            runAction(
              () => postJson(`/product/projects/${encodeURIComponent(selectedProjectId)}/restore`, {}),
              "project restored"
            )
          }
          onDuplicate={() =>
            runAction(
              () => postJson(`/product/projects/${encodeURIComponent(selectedProjectId)}/duplicate`, { copy_references: true }),
              "project duplicated"
            )
          }
          onDelete={() =>
            runAction(
              () =>
                fetchJson(`/product/projects/${encodeURIComponent(selectedProjectId)}`, {
                  method: "DELETE"
                }),
              "project deleted"
            )
          }
          onRepairScope={() =>
            runAction(
              () =>
                postJson("/product/projects/audit/scope", {
                  project_id: selectedProjectId || null,
                  repair: true
                }),
              "project scope repaired"
            )
          }
          onSyncPostgres={() =>
            runAction(
              () => fetchJson("/product/system/postgres/strict-check?sync=true"),
              "postgres strict check"
            )
          }
          onOpenAsset={selectAsset}
        />
      ) : null}

      {activeTab === "health" ? (
        <HealthPanel
          language={language}
          report={projectHealth}
          backups={backups}
          restorePath={restorePath}
          setRestorePath={setRestorePath}
          onCreateBackup={() =>
            runAction(
              () => postJson("/product/system/backups", {}),
              "local backup created"
            )
          }
          onRestoreBackup={() =>
            runAction(
              () => postJson("/product/system/restore", { backup_path: restorePath, confirm: true }),
              "local backup restored"
            )
          }
          onOpenAsset={selectAsset}
          busy={busy}
        />
      ) : null}

      {activeTab === "tasks" ? (
        <TasksPanel
          language={language}
          taskCenter={taskCenter}
          taskControl={taskControl}
          deadLetters={deadLetters}
          batchItems={batchItems}
          statusFilter={taskStatusFilter}
          setStatusFilter={setTaskStatusFilter}
          typeFilter={taskTypeFilter}
          setTypeFilter={setTaskTypeFilter}
          stepFilter={taskStepFilter}
          setStepFilter={setTaskStepFilter}
          offset={taskOffset}
          setOffset={setTaskOffset}
          onApplyFilters={(override) => loadAll(undefined, override)}
          onOpenAsset={selectAsset}
          onSaveControl={(patch) =>
            runAction(
              async () => {
                const updated = await fetchJson<Record<string, unknown>>("/product/tasks/control", {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(patch)
                });
                setTaskControl(await fetchJson<TaskControl>("/product/tasks/control"));
                return updated;
              },
              "task control saved"
            )
          }
          onCancelTask={(taskId) =>
            runAction(
              () => postJson("/product/tasks/cancel", { task_id: taskId, terminate: false }),
              "task canceled"
            )
          }
          onRetry={(statusPath) =>
            runAction(
              () =>
                postJson("/product/tasks/retry", {
                  status_path: statusPath,
                  workspace_path: selectedWorkspace || null,
                  async_task: false
                }),
              "task retry"
            )
          }
          onRetryDeadLetter={(path) =>
            runAction(
              () => postJson("/product/tasks/dead-letters/retry", { dead_letter_path: path }),
              "dead letter retry"
            )
          }
          onRetryBatchItem={(itemPath) =>
            runAction(
              () =>
                postJson("/product/batch/items/retry", {
                  item_path: itemPath,
                  workspace_path: selectedWorkspace || null
                }),
              "batch item retry"
            )
          }
          onRetryFailedBatchItems={(itemPaths) =>
            runAction(
              () =>
                postJson("/product/batch/items/retry-bulk", {
                  item_paths: itemPaths,
                  workspace_path: selectedWorkspace || null
                }),
              "failed batch items retry"
            )
          }
          busy={busy}
        />
      ) : null}

      {activeTab === "assets" ? (
        <AssetsPanel
          language={language}
          health={health}
          assets={assets}
          detail={assetDetail}
          versions={assetVersions}
          graph={assetGraph}
          keyword={keyword}
          setKeyword={setKeyword}
          category={category}
          setCategory={setCategory}
          collectionTitle={collectionTitle}
          setCollectionTitle={setCollectionTitle}
          onSearch={searchAssets}
          onSelect={selectAsset}
          onSave={(path, patch) =>
            runAction(async () => {
              const updated = await fetchJson<AssetDetail>("/product/assets/detail", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path, ...patch })
              });
              setAssetDetail(updated);
              return updated;
            }, "asset saved")
          }
          onSaveContent={(path, content) =>
            runAction(async () => {
              const updated = await fetchJson<AssetDetail>("/product/assets/content", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path, content })
              });
              setAssetDetail(updated);
              return updated;
            }, "asset content saved")
          }
          onSaveCollection={() =>
            runAction(async () => {
              const collection = (await postJson("/product/assets/collections", {
                title: collectionTitle,
                purpose: "task_input",
                asset_paths: assets.map((asset) => asset.path),
                tags: ["saved-search"],
                workspace_path: selectedWorkspace || null
              })) as AssetDetail;
              const [versions, graph] = await Promise.all([
                fetchJson<AssetVersions>(`/product/assets/versions?path=${encodeURIComponent(collection.path)}`),
                fetchJson<AssetGraph>(`/product/assets/graph?path=${encodeURIComponent(collection.path)}&depth=1`)
              ]);
              setAssetDetail(collection);
              setAssetVersions(versions);
              setAssetGraph(graph);
              return collection;
            }, "asset collection saved")
          }
        />
      ) : null}

      {activeTab === "handoffs" ? (
        <HandoffsPanel
          language={language}
          text={text.handoffs}
          handoffs={handoffs}
          detail={handoffDetail}
          githubSources={githubSources}
          handoffInput={handoffInput}
          setHandoffInput={setHandoffInput}
          handoffGenre={handoffGenre}
          setHandoffGenre={setHandoffGenre}
          handoffReader={handoffReader}
          setHandoffReader={setHandoffReader}
          handoffPurpose={handoffPurpose}
          setHandoffPurpose={setHandoffPurpose}
          handoffDiscipline={handoffDiscipline}
          setHandoffDiscipline={setHandoffDiscipline}
          handoffCredibility={handoffCredibility}
          setHandoffCredibility={setHandoffCredibility}
          handoffScope={handoffScope}
          setHandoffScope={setHandoffScope}
          handoffContext={handoffContext}
          setHandoffContext={setHandoffContext}
          githubSourceRefs={githubSourceRefs}
          setGithubSourceRefs={setGithubSourceRefs}
          busy={busy}
          onCreateDeconstruct={() =>
            runAction(async () => {
              const detail = await postJson("/product/handoffs/deconstruct", {
                input_path: handoffInput,
                genre: handoffGenre,
                target_reader: handoffReader,
                purpose: handoffPurpose,
                workspace_path: selectedWorkspace || null
              });
              setHandoffDetail(detail as AssetDetail);
              return detail;
            }, "deconstruct handoff")
          }
          onCreateKnowledge={() =>
            runAction(async () => {
              const detail = await postJson("/product/handoffs/knowledge", {
                input_path: handoffInput,
                discipline: handoffDiscipline,
                credibility: handoffCredibility,
                scope: handoffScope,
                project_context: handoffContext,
                workspace_path: selectedWorkspace || null
              });
              setHandoffDetail(detail as AssetDetail);
              return detail;
            }, "knowledge handoff")
          }
          onCreateGithubKnowledge={() =>
            runAction(async () => {
              const result = await postJson("/product/handoffs/github-knowledge", {
                repo_refs: githubSourceRefs
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean),
                discipline: handoffDiscipline,
                credibility: handoffCredibility,
                scope: handoffScope,
                project_context: handoffContext,
                workspace_path: selectedWorkspace || null
              });
              const handoff = (result as { handoff?: AssetDetail }).handoff;
              if (handoff) setHandoffDetail(handoff);
              return result;
            }, "github knowledge handoff")
          }
          onSelect={selectHandoff}
        />
      ) : null}

      {activeTab === "batch" ? (
        <BatchPanel
          language={language}
          batchInput={batchInput}
          setBatchInput={setBatchInput}
          batchAnalysisMode={batchAnalysisMode}
          setBatchAnalysisMode={setBatchAnalysisMode}
          batchDecompositionPath={batchDecompositionPath}
          setBatchDecompositionPath={setBatchDecompositionPath}
          batchKnowledgePath={batchKnowledgePath}
          setBatchKnowledgePath={setBatchKnowledgePath}
          batchItems={batchItems}
          uploadResult={uploadResult}
          busy={busy}
          onUpload={(files) =>
            runAction(async () => {
              const form = new FormData();
              files.forEach((file) => form.append("files", file));
              form.append("rights_authorization", "test_fixture");
              form.append("copyright_note", "operator-confirmed upload; preserve abstraction boundary");
              form.append("allow_downstream_generation", "true");
              const uploaded = await fetchJson<UploadResult>("/product/uploads", {
                method: "POST",
                body: form
              });
              setUploadResult(uploaded);
              setBatchInput(uploaded.input_path);
              return uploaded;
            }, "files uploaded")
          }
          onRun={() =>
            runAction(
              () =>
                postJson("/product/batch/deconstruct", {
                  input_path: batchInput,
                  rights_authorization: "test_fixture",
                  copyright_note: "operator-confirmed import; preserve abstraction boundary",
                  allow_downstream_generation: true,
                  workspace_path: selectedWorkspace || null,
                  analysis_mode: batchAnalysisMode,
                  async_task: false
                }),
              "batch deconstruct"
            )
          }
          onContinueItem={(itemPath) =>
            runAction(
              () =>
                postJson("/product/batch/items/continue", {
                  item_path: itemPath,
                  decomposition_path: batchDecompositionPath || null,
                  knowledge_path: batchKnowledgePath || null,
                  workspace_path: selectedWorkspace || null
                }),
              "batch handoff continue"
            )
          }
          onRegenerateHandoff={(itemPath) =>
            runAction(
              () =>
                postJson("/product/batch/items/handoff/regenerate", {
                  item_path: itemPath,
                  workspace_path: selectedWorkspace || null,
                  reason: "operator requested regeneration"
                }),
              "batch handoff regenerated"
            )
          }
          onVoidHandoff={(itemPath) =>
            runAction(
              () =>
                postJson("/product/batch/items/handoff/void", {
                  item_path: itemPath,
                  reason: "operator voided handoff",
                  workspace_path: selectedWorkspace || null
                }),
              "batch handoff voided"
            )
          }
          onRetryItem={(itemPath) =>
            runAction(
              () =>
                postJson("/product/batch/items/retry", {
                  item_path: itemPath,
                  workspace_path: selectedWorkspace || null
                }),
              "batch item retry"
            )
          }
          onReviewItem={(itemPath, decision) =>
            runAction(
              () =>
                fetchJson("/product/batch/items/review", {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ item_path: itemPath, decision })
                }),
              `batch item ${decision}`
            )
          }
          onOpenAsset={selectAsset}
        />
      ) : null}

      {activeTab === "drafts" ? (
        <DraftsPanel
          language={language}
          drafts={drafts}
          selectedPlan={selectedPlan}
          setSelectedPlan={setSelectedPlan}
          selectedDraft={selectedDraft}
          setSelectedDraft={setSelectedDraft}
          draftEditor={draftEditor}
          setDraftEditor={setDraftEditor}
          draftExport={draftExport}
          selectedWorkspace={selectedWorkspace}
          setSelectedWorkspace={setSelectedWorkspace}
          busy={busy}
          onGenerate={() =>
            runAction(
              () =>
                postJson("/product/drafts/generate", {
                  chapter_plan_path: selectedPlan || null,
                  workspace_path: selectedWorkspace || null,
                  update_workspace: true
                }),
              "draft generated"
            )
          }
          onSaveDraft={() =>
            runAction(async () => {
              if (!draftEditor) return {};
              const saved = await postJson("/product/drafts/save", {
                draft_path: draftEditor.path,
                text: draftEditor.text,
                title: draftEditor.title,
                status: "edited",
                workspace_path: selectedWorkspace || null
              });
              await loadDraftEditor(String((saved as { draft_path?: string }).draft_path || draftEditor.path));
              return saved;
            }, "draft saved")
          }
          onExportDraft={(format) =>
            runAction(async () => {
              const exported = await postJson("/product/drafts/export", {
                draft_path: draftEditor?.path || selectedDraft,
                format
              });
              setDraftExport(exported as Record<string, unknown>);
              return exported;
            }, `draft exported ${format}`)
          }
          onOpenAsset={selectAsset}
        />
      ) : null}

      {activeTab === "reviews" ? (
        <ReviewPanel
          language={language}
          drafts={drafts}
          selectedDraft={selectedDraft}
          setSelectedDraft={setSelectedDraft}
          selectedReview={selectedReview}
          setSelectedReview={setSelectedReview}
          selectedRevision={selectedRevision}
          setSelectedRevision={setSelectedRevision}
          reviewDetail={reviewDetail}
          revisionPreview={revisionPreview}
          selectedWorkspace={selectedWorkspace}
          setSelectedWorkspace={setSelectedWorkspace}
          busy={busy}
          onReview={(comparison) =>
            runAction(
              () =>
                postJson("/product/reviews/run", {
                  draft_path: selectedDraft || null,
                  workspace_path: selectedWorkspace || null,
                  comparison,
                  update_workspace: true
                }),
              comparison ? "comparison review" : "review"
            )
          }
          onRevise={() =>
            runAction(
              () =>
                postJson("/product/revisions/plan", {
                  review_path: selectedReview || null,
                  workspace_path: selectedWorkspace || null
                }),
              "revision plan"
            )
          }
          onIssueStatus={(index, status) =>
            runAction(async () => {
              const updated = await fetchJson<AssetDetail>("/product/reviews/issues", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ review_path: selectedReview, issue_index: index, status })
              });
              setReviewDetail(updated);
              return updated;
            }, "issue status updated")
          }
          onPreviewRevision={() =>
            runAction(async () => {
              const preview = await postJson("/product/revisions/apply", {
                revision_path: selectedRevision,
                workspace_path: selectedWorkspace || null,
                confirmed: false,
                review_after: true
              });
              setRevisionPreview(preview as RevisionApplyResult);
              return preview;
            }, "revision preview")
          }
          onApplyRevision={() =>
            runAction(
              () =>
                postJson("/product/revisions/apply", {
                  revision_path: selectedRevision,
                  workspace_path: selectedWorkspace || null,
                  confirmed: true,
                  review_after: true
                }),
              "revision applied"
            )
          }
          onOpenAsset={selectAsset}
        />
      ) : null}
    </main>
  );
}

function Metric({ label, value, code = false }: { label: string; value: string; code?: boolean }) {
  return (
    <div>
      <span className="metricLabel">{label}</span>
      <strong className={code ? "pathText" : undefined}>{value}</strong>
    </div>
  );
}

function HealthPanel(props: {
  language: Language;
  report: ProjectHealthReport | null;
  backups: BackupRow[];
  restorePath: string;
  setRestorePath: (value: string) => void;
  onCreateBackup: () => void;
  onRestoreBackup: () => void;
  onOpenAsset: (path: string) => void;
  busy: boolean;
}) {
  const zh = props.language === "zh";
  const summary = props.report?.summary;
  return (
    <section className="workspaceGrid">
      <div className="panel">
        <PanelHeader title={zh ? "项目健康页" : "Project Health"} icon={<Activity size={18} />} />
        <div className="miniMetrics">
          <span className={summary?.scope_issue_count ? "badge warn" : "badge ok"}>{zh ? "范围问题" : "scope"}: {summary?.scope_issue_count ?? 0}</span>
          <span className={summary?.failed_task_count ? "badge warn" : "badge ok"}>{zh ? "失败任务" : "failed tasks"}: {summary?.failed_task_count ?? 0}</span>
          <span className={summary?.pending_handoff_count ? "badge muted" : "badge ok"}>{zh ? "待处理 handoff" : "pending handoffs"}: {summary?.pending_handoff_count ?? 0}</span>
          <span className="statPill">{zh ? "资产" : "assets"}: {summary?.asset_count ?? 0}</span>
          <span className="statPill">{zh ? "死信" : "dead letters"}: {summary?.dead_letter_count ?? 0}</span>
        </div>
        <div className="serviceGrid">
          <article className="serviceCard">
            <div className="serviceTitle"><Database size={17} /><span>PostgreSQL</span></div>
            <span className={props.report?.postgres.ready ? "badge ok" : props.report?.postgres.strict ? "badge warn" : "badge muted"}>
              {props.report?.postgres.ready ? "ready" : props.report?.postgres.strict ? "blocked" : "relaxed"}
            </span>
          </article>
          <article className="serviceCard">
            <div className="serviceTitle"><Workflow size={17} /><span>Celery</span></div>
            <span className={props.report?.celery.healthy ? "badge ok" : "badge muted"}>{props.report?.celery.healthy ? "healthy" : "offline"}</span>
          </article>
          <article className="serviceCard">
            <div className="serviceTitle"><Search size={17} /><span>Embedding / Qdrant</span></div>
            <span className={props.report?.embedding.ok ? "badge ok" : "badge warn"}>
              {props.report?.embedding.ok ? (props.report?.embedding.model ?? "ready") : (props.report?.embedding.missing_env_vars?.join(", ") || props.report?.embedding.error || "not ready")}
            </span>
          </article>
          <article className="serviceCard">
            <div className="serviceTitle"><ListChecks size={17} /><span>{zh ? "并发" : "Concurrency"}</span></div>
            <span className="badge muted">{props.report?.task_control.max_concurrent_steps ?? 1}</span>
          </article>
        </div>
        <h3>{zh ? "最近失败" : "Recent Failures"}</h3>
        <DataTable
          emptyText={zh ? "无失败" : "No failures"}
          columns={zh ? ["类型", "步骤", "状态", "资产"] : ["Type", "Step", "Status", "Asset"]}
          rows={(props.report?.recent_failures ?? []).map((task) => [
            task.task_type,
            task.step,
            <span className={task.status === "failed" ? "badge warn" : "badge muted"} key={`health-${task.path}`}>{task.status}</span>,
            <button className="linkButton" onClick={() => props.onOpenAsset(task.path)} key={task.path}>{task.path}</button>
          ])}
        />
      </div>
      <div className="panel">
        <PanelHeader title={zh ? "本地备份 / 恢复" : "Local Backup / Restore"} icon={<Archive size={18} />} />
        <div className="formGrid wide">
          <button className="primaryButton" disabled={props.busy} onClick={props.onCreateBackup}>
            <Archive size={18} />
            {zh ? "创建备份" : "Create Backup"}
          </button>
          <input value={props.restorePath} onChange={(event) => props.setRestorePath(event.target.value)} aria-label="Backup path" placeholder="data/backups/local-prod/...zip" />
          <button className="secondaryButton dangerButton" disabled={props.busy || !props.restorePath.trim()} onClick={props.onRestoreBackup}>
            <RotateCcw size={18} />
            {zh ? "恢复" : "Restore"}
          </button>
        </div>
        <DataTable
          emptyText={zh ? "暂无备份" : "No backups"}
          columns={zh ? ["时间", "大小", "路径"] : ["Created", "Size", "Path"]}
          rows={props.backups.map((backup) => [
            backup.created_at,
            String(backup.size_bytes),
            <button className="linkButton" onClick={() => props.setRestorePath(backup.path)} key={backup.path}>{backup.path}</button>
          ])}
        />
        <h3>{zh ? "队列趋势" : "Queue Trend"}</h3>
        <DataTable
          emptyText={zh ? "暂无趋势" : "No trend"}
          columns={zh ? ["时间", "队列", "活跃", "保留"] : ["Time", "Queued", "Active", "Reserved"]}
          rows={(props.report?.queue_trend ?? []).slice(-8).reverse().map((point) => [
            point.recorded_at,
            String(point.queue_total),
            String(point.active_count),
            String(point.reserved_count)
          ])}
        />
      </div>
    </section>
  );
}

function ProjectsPanel(props: {
  language: Language;
  health: Health | null;
  scopeAudit: ProjectScopeAudit | null;
  postgresStrict: PostgresStrictCheck | null;
  projects: ProjectRow[];
  seriesRows: SeriesRow[];
  projectTitle: string;
  setProjectTitle: (value: string) => void;
  seriesTitle: string;
  setSeriesTitle: (value: string) => void;
  bookNumber: string;
  setBookNumber: (value: string) => void;
  selectedProjectId: string;
  selectedWorkspace: string;
  projectConfig: ProjectConfig;
  setProjectConfig: (value: ProjectConfig) => void;
  busy: boolean;
  onCreate: () => void;
  onSelectProject: (project: ProjectRow) => void;
  onSaveConfig: () => void;
  onPause: () => void;
  onArchive: () => void;
  onRestore: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onRepairScope: () => void;
  onSyncPostgres: () => void;
  onOpenAsset: (path: string) => void;
}) {
  const zh = props.language === "zh";
  return (
    <section className="workspaceGrid">
      <div className="panel">
        <PanelHeader title={zh ? "项目空间" : "Project Space"} icon={<Boxes size={18} />} />
        <div className="formGrid">
          <input value={props.projectTitle} onChange={(event) => props.setProjectTitle(event.target.value)} aria-label={zh ? "项目标题" : "Project title"} />
          <input value={props.seriesTitle} onChange={(event) => props.setSeriesTitle(event.target.value)} aria-label={zh ? "系列标题" : "Series title"} placeholder={zh ? "系列" : "Series"} />
          <input value={props.bookNumber} onChange={(event) => props.setBookNumber(event.target.value)} aria-label={zh ? "书号" : "Book number"} type="number" min="1" />
          <button className="primaryButton" disabled={props.busy} onClick={props.onCreate}>
            <BookOpen size={18} />
            {zh ? "创建" : "Create"}
          </button>
        </div>
        <div className="configPanel">
          <div className="configHeader">
            <strong>{zh ? "当前项目" : "Current Project"}</strong>
            <span className="pathText">{props.selectedProjectId || (zh ? "无" : "None")}</span>
          </div>
          <div className="configGrid">
            <input
              value={props.projectConfig.genre}
              onChange={(event) => props.setProjectConfig({ ...props.projectConfig, genre: event.target.value })}
              aria-label={zh ? "题材" : "Genre"}
              placeholder={zh ? "题材" : "Genre"}
            />
            <input
              value={props.projectConfig.target_platform}
              onChange={(event) => props.setProjectConfig({ ...props.projectConfig, target_platform: event.target.value })}
              aria-label={zh ? "目标平台" : "Target platform"}
              placeholder={zh ? "平台" : "Platform"}
            />
            <input
              value={String(props.projectConfig.target_word_count || "")}
              onChange={(event) =>
                props.setProjectConfig({ ...props.projectConfig, target_word_count: Number(event.target.value || 0) })
              }
              aria-label={zh ? "目标字数" : "Target word count"}
              type="number"
              min="0"
              placeholder={zh ? "字数" : "Words"}
            />
            <input
              value={props.projectConfig.update_cadence}
              onChange={(event) => props.setProjectConfig({ ...props.projectConfig, update_cadence: event.target.value })}
              aria-label={zh ? "更新频率" : "Update cadence"}
              placeholder={zh ? "频率" : "Cadence"}
            />
            <input
              value={String(props.projectConfig.quality_threshold || 80)}
              onChange={(event) =>
                props.setProjectConfig({ ...props.projectConfig, quality_threshold: Number(event.target.value || 80) })
              }
              aria-label={zh ? "质量阈值" : "Quality threshold"}
              type="number"
              min="0"
              max="100"
            />
            <select
              value={props.projectConfig.status}
              onChange={(event) => props.setProjectConfig({ ...props.projectConfig, status: event.target.value })}
              aria-label={zh ? "项目状态" : "Project status"}
            >
              <option value="active">active</option>
              <option value="paused">paused</option>
              <option value="archived">archived</option>
            </select>
          </div>
          <input
            value={props.projectConfig.audience}
            onChange={(event) => props.setProjectConfig({ ...props.projectConfig, audience: event.target.value })}
            aria-label={zh ? "目标读者" : "Audience"}
            placeholder={zh ? "目标读者" : "Audience"}
          />
          <button className="secondaryButton" disabled={props.busy || !props.selectedProjectId} onClick={props.onSaveConfig}>
            <CheckCircle2 size={18} />
            {zh ? "保存配置" : "Save Config"}
          </button>
          <div className="actionRow">
            <button className="secondaryButton" disabled={props.busy || !props.selectedProjectId} onClick={props.onPause} title={zh ? "暂停" : "Pause"}>
              <Pause size={18} />
              {zh ? "暂停" : "Pause"}
            </button>
            <button className="secondaryButton" disabled={props.busy || !props.selectedProjectId} onClick={props.onRestore} title={zh ? "恢复" : "Restore"}>
              <RotateCcw size={18} />
              {zh ? "恢复" : "Restore"}
            </button>
            <button className="secondaryButton" disabled={props.busy || !props.selectedProjectId} onClick={props.onArchive} title={zh ? "归档" : "Archive"}>
              <Archive size={18} />
              {zh ? "归档" : "Archive"}
            </button>
            <button className="secondaryButton" disabled={props.busy || !props.selectedProjectId} onClick={props.onDuplicate} title={zh ? "复制" : "Duplicate"}>
              <Copy size={18} />
              {zh ? "复制" : "Duplicate"}
            </button>
            <button className="secondaryButton dangerButton" disabled={props.busy || !props.selectedProjectId} onClick={props.onDelete} title={zh ? "删除" : "Delete"}>
              <Trash2 size={18} />
              {zh ? "删除" : "Delete"}
            </button>
          </div>
        </div>
        <DataTable
          emptyText={zh ? "空" : "Empty"}
          columns={zh ? ["标题", "状态", "章节", "问题", "操作", "路径"] : ["Title", "Status", "Chapters", "Issues", "Action", "Path"]}
          rows={props.projects.map((project) => [
            project.title,
            project.project_config?.status || project.status,
            String(project.chapter_count),
            String(project.open_issue_count),
            <button className="secondaryButton tableButton" onClick={() => props.onSelectProject(project)} key={`select-${project.path}`}>
              {zh ? "选择" : "Select"}
            </button>,
            <button className="linkButton" onClick={() => props.onOpenAsset(project.path)} key={project.path}>
              {project.path}
            </button>
          ])}
        />
      </div>
      <div className="panel">
        <PanelHeader title={zh ? "服务" : "Services"} icon={<Server size={18} />} />
        <div className="serviceGrid">
          {Object.entries(props.health?.configured_services ?? {}).map(([name, configured]) => (
            <article key={name} className="serviceCard">
              <div className="serviceTitle">
                {serviceIcons[name] ?? <Server size={17} />}
                <span>{name}</span>
              </div>
              <span className={configured ? "badge ok" : "badge muted"}>{configured ? (zh ? "已配置" : "Configured") : (zh ? "本地" : "Local")}</span>
            </article>
          ))}
        </div>
        <div className="neoLine">
          <Network size={16} />
          <span>Neo4j: {props.health?.neo4j.reason ?? (zh ? "未检查" : "Not checked")}</span>
        </div>
        <div className="governanceBox">
          <div className="sectionHeaderLine">
            <h3>{zh ? "项目范围审计" : "Project Scope Audit"}</h3>
            <button className="secondaryButton tableButton" disabled={props.busy || !props.scopeAudit?.summary.repairable_count} onClick={props.onRepairScope}>
              <RefreshCw size={16} />
              {zh ? "修复" : "Repair"}
            </button>
          </div>
          <div className="miniMetrics">
            <span className={props.scopeAudit?.summary.issue_count ? "badge warn" : "badge ok"}>
              {zh ? "问题" : "issues"}: {props.scopeAudit?.summary.issue_count ?? 0}
            </span>
            <span className="statPill">{zh ? "可修复" : "repairable"}: {props.scopeAudit?.summary.repairable_count ?? 0}</span>
            <span className="statPill">{zh ? "错绑" : "handoff mix"}: {props.scopeAudit?.summary.handoff_mismatch_count ?? 0}</span>
          </div>
          <DataTable
            emptyText={zh ? "无项目范围问题" : "No project scope issues"}
            columns={zh ? ["级别", "类型", "信息", "路径"] : ["Severity", "Kind", "Message", "Path"]}
            rows={(props.scopeAudit?.issues ?? []).slice(0, 5).map((issue) => [
              <span className={issue.severity === "error" ? "badge warn" : "badge muted"} key={`sev-${issue.path}`}>
                {issue.severity}
              </span>,
              issue.kind,
              issue.message,
              <button className="linkButton" onClick={() => props.onOpenAsset(issue.path)} key={issue.path}>
                {issue.path}
              </button>
            ])}
          />
        </div>
        <div className="governanceBox">
          <div className="sectionHeaderLine">
            <h3>{zh ? "PostgreSQL 严格模式" : "PostgreSQL Strict Mode"}</h3>
            <button className="secondaryButton tableButton" disabled={props.busy} onClick={props.onSyncPostgres}>
              <Database size={16} />
              {zh ? "检查/同步" : "Check/Sync"}
            </button>
          </div>
          <div className="miniMetrics">
            <span className={props.postgresStrict?.ready ? "badge ok" : props.postgresStrict?.strict ? "badge warn" : "badge muted"}>
              {props.postgresStrict?.strict ? (props.postgresStrict.ready ? (zh ? "就绪" : "ready") : (zh ? "阻断" : "blocked")) : (zh ? "宽松" : "relaxed")}
            </span>
            <span className="statPill">database: {props.postgresStrict?.database_url_configured ? (zh ? "已配置" : "configured") : (zh ? "未配置" : "empty")}</span>
            <span className="statPill">write-through: {props.postgresStrict?.write_through ? "on" : "off"}</span>
          </div>
          {props.postgresStrict?.errors.length ? <p className="warnText">{props.postgresStrict.errors.join("; ")}</p> : null}
        </div>
        <h3>{zh ? "系列" : "Series"}</h3>
        <DataTable
          emptyText={zh ? "空" : "Empty"}
          columns={zh ? ["系列", "书籍", "项目", "最近更新"] : ["Series", "Books", "Projects", "Latest"]}
          rows={props.seriesRows.map((series) => [
            series.series_title,
            String(series.book_count),
            String(series.project_count),
            series.latest_updated_at
          ])}
        />
      </div>
    </section>
  );
}

function TasksPanel({
  language,
  taskCenter,
  taskControl,
  deadLetters,
  batchItems,
  statusFilter,
  setStatusFilter,
  typeFilter,
  setTypeFilter,
  stepFilter,
  setStepFilter,
  offset,
  setOffset,
  onApplyFilters,
  onOpenAsset,
  onSaveControl,
  onCancelTask,
  onRetry,
  onRetryDeadLetter,
  onRetryBatchItem,
  onRetryFailedBatchItems,
  busy
}: {
  language: Language;
  taskCenter: TaskCenter | null;
  taskControl: TaskControl | null;
  deadLetters: DeadLetter[];
  batchItems: BatchItem[];
  statusFilter: string;
  setStatusFilter: (value: string) => void;
  typeFilter: string;
  setTypeFilter: (value: string) => void;
  stepFilter: string;
  setStepFilter: (value: string) => void;
  offset: number;
  setOffset: (value: number) => void;
  onApplyFilters: (override?: { offset?: number; status?: string; taskType?: string; step?: string }) => void;
  onOpenAsset: (path: string) => void;
  onSaveControl: (patch: Record<string, number>) => void;
  onCancelTask: (taskId: string) => void;
  onRetry: (statusPath: string) => void;
  onRetryDeadLetter: (path: string) => void;
  onRetryBatchItem: (itemPath: string) => void;
  onRetryFailedBatchItems: (itemPaths: string[]) => void;
  busy: boolean;
}) {
  const [cancelId, setCancelId] = useState("");
  const [maxBatches, setMaxBatches] = useState(1);
  const [maxSteps, setMaxSteps] = useState(1);
  const [showTimeline, setShowTimeline] = useState(false);
  const zh = language === "zh";
  const failedBatchItems = batchItems.filter((item) => item.status === "failed");
  const page = taskCenter?.page ?? { offset, limit: 80, total: taskCenter?.tasks.length ?? 0 };
  const canPrev = page.offset > 0;
  const canNext = page.offset + page.limit < page.total;

  useEffect(() => {
    setMaxBatches(taskControl?.config.max_concurrent_batches ?? 1);
    setMaxSteps(taskControl?.config.max_concurrent_steps ?? 1);
  }, [taskControl?.config.max_concurrent_batches, taskControl?.config.max_concurrent_steps]);

  return (
    <section className="panel">
      <PanelHeader title={zh ? "任务中心" : "Task Center"} icon={<ListChecks size={18} />} />
      <div className="miniMetrics">
        {Object.entries(taskCenter?.summary.by_status ?? {}).map(([status, count]) => (
          <span key={status} className="statPill">
            {status}: {count}
          </span>
        ))}
        <span className="statPill">{zh ? "事件" : "events"}: {taskCenter?.timeline.summary.event_count ?? 0}</span>
        <span className="statPill">{zh ? "运行" : "runs"}: {taskCenter?.timeline.summary.run_count ?? 0}</span>
        <span className="statPill">{zh ? "失败" : "failed"}: {taskCenter?.timeline.summary.failed_count ?? 0}</span>
        <span className={taskControl?.celery.healthy ? "badge ok" : "badge muted"}>{zh ? "worker" : "worker"}: {taskControl?.celery.healthy ? (zh ? "健康" : "healthy") : (zh ? "离线" : "offline")}</span>
        <span className="statPill">{zh ? "活跃" : "active"}: {taskControl?.celery.active_count ?? 0}</span>
        <span className="statPill">{zh ? "保留" : "reserved"}: {taskControl?.celery.reserved_count ?? 0}</span>
        <span className="statPill">{zh ? "死信" : "dead letters"}: {taskControl?.dead_letters.count ?? 0}</span>
        <span className="statPill">{zh ? "队列" : "queues"}: {queueLengthText(taskControl?.celery.queue_lengths)}</span>
      </div>
      <div className="controlGrid">
        <input type="number" min="1" value={maxBatches} onChange={(event) => setMaxBatches(Number(event.target.value || 1))} aria-label="Max concurrent batches" />
        <input type="number" min="1" value={maxSteps} onChange={(event) => setMaxSteps(Number(event.target.value || 1))} aria-label="Max concurrent steps" />
        <button className="secondaryButton" disabled={busy} onClick={() => onSaveControl({ max_concurrent_batches: maxBatches, max_concurrent_steps: maxSteps })}>
          <Save size={18} />
          {zh ? "保存限制" : "Save Limits"}
        </button>
        <input value={cancelId} onChange={(event) => setCancelId(event.target.value)} aria-label="Celery task id" placeholder={zh ? "Celery 任务 ID" : "Celery task id"} />
        <button className="secondaryButton dangerButton" disabled={busy || !cancelId.trim()} onClick={() => onCancelTask(cancelId.trim())}>
          <Trash2 size={18} />
          {zh ? "取消" : "Cancel"}
        </button>
      </div>
      <div className="filterGrid">
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label={zh ? "任务状态" : "Task status"}>
          <option value="">{zh ? "全部状态" : "All statuses"}</option>
          {["pending", "running", "completed", "failed", "waiting_handoff"].map((status) => (
            <option key={status} value={status}>{status}</option>
          ))}
        </select>
        <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} aria-label={zh ? "任务类型" : "Task type"}>
          <option value="">{zh ? "全部类型" : "All types"}</option>
          {["workflow", "handoff", "batch"].map((taskType) => (
            <option key={taskType} value={taskType}>{taskType}</option>
          ))}
        </select>
        <select value={stepFilter} onChange={(event) => setStepFilter(event.target.value)} aria-label={zh ? "步骤" : "Step"}>
          <option value="">{zh ? "全部步骤" : "All steps"}</option>
          {(taskCenter?.steps ?? []).map((step) => (
            <option key={step} value={step}>{step}</option>
          ))}
        </select>
        <button className="secondaryButton" disabled={busy} onClick={() => { setOffset(0); onApplyFilters({ offset: 0 }); }}>
          <Search size={18} />
          {zh ? "筛选" : "Filter"}
        </button>
        <button className="secondaryButton" disabled={busy} onClick={() => { setStatusFilter(""); setTypeFilter(""); setStepFilter(""); setOffset(0); onApplyFilters({ offset: 0, status: "", taskType: "", step: "" }); }}>
          <RotateCcw size={18} />
          {zh ? "清空" : "Reset"}
        </button>
      </div>
      <h3>{zh ? "运行进度" : "Run Progress"}</h3>
      <DataTable
        emptyText={zh ? "空" : "Empty"}
        columns={zh ? ["运行", "状态", "进度", "失败", "最近"] : ["Run", "Status", "Progress", "Failed", "Latest"]}
        rows={(taskCenter?.timeline.runs ?? []).map((run) => [
          <span className="pathText" key={run.run_id}>
            {run.run_id}
          </span>,
          <span className={run.status === "completed" ? "badge ok" : run.status === "failed" ? "badge warn" : "badge muted"} key="status">
            {run.status}
          </span>,
          <Progress value={run.progress_percent} key="progress" />,
          run.failed_steps.join(", "),
          run.latest_event_at
        ])}
      />
      <h3>{zh ? "最新任务状态" : "Latest Task Status"}</h3>
      <div className="paginationLine">
        <span className="statPill">{page.total ? `${page.offset + 1}-${Math.min(page.offset + page.limit, page.total)} / ${page.total}` : "0 / 0"}</span>
        <button className="secondaryButton tableButton" disabled={!canPrev || busy} onClick={() => { const nextOffset = Math.max(0, page.offset - page.limit); setOffset(nextOffset); onApplyFilters({ offset: nextOffset }); }}>
          {zh ? "上一页" : "Prev"}
        </button>
        <button className="secondaryButton tableButton" disabled={!canNext || busy} onClick={() => { const nextOffset = page.offset + page.limit; setOffset(nextOffset); onApplyFilters({ offset: nextOffset }); }}>
          {zh ? "下一页" : "Next"}
        </button>
      </div>
      <DataTable
        emptyText={zh ? "空" : "Empty"}
        columns={zh ? ["类型", "步骤", "状态", "事件", "消息", "输出", "操作", "状态资产"] : ["Type", "Step", "Status", "Events", "Message", "Outputs", "Action", "Status Asset"]}
        rows={(taskCenter?.tasks ?? []).map((task) => [
          task.task_type || "workflow",
          task.step,
          <span className={task.status === "completed" ? "badge ok" : task.status === "failed" ? "badge warn" : "badge muted"} key="status">
            {task.status}
          </span>,
          String(task.event_count ?? 1),
          task.message || task.error_message || `${task.step} ${task.status}`,
          task.output_paths.join(", "),
          task.status === "failed" && (task.task_type || "workflow") !== "handoff" ? (
            <button className="secondaryButton tableButton" disabled={busy} onClick={() => onRetry(task.path)} key={`retry-${task.path}`}>
              {zh ? "重试" : "Retry"}
            </button>
          ) : (
            ""
          ),
          <button className="linkButton" onClick={() => onOpenAsset(task.path)} key={task.path}>
            {task.path}
          </button>
        ])}
      />
      <div className="sectionHeaderLine">
        <h3>{zh ? "完整事件日志" : "Full Event Timeline"}</h3>
        <button className="secondaryButton tableButton" onClick={() => setShowTimeline((value) => !value)}>
          {showTimeline ? (zh ? "收起" : "Collapse") : (zh ? "展开" : "Expand")}
        </button>
      </div>
      {showTimeline ? (
        <DataTable
          emptyText={zh ? "空" : "Empty"}
          columns={zh ? ["时间", "类型", "步骤", "状态", "消息", "资产"] : ["Time", "Type", "Step", "Status", "Message", "Asset"]}
          rows={(taskCenter?.timeline.events ?? []).map((event) => [
            event.recorded_at,
            event.task_type || "workflow",
            event.step,
            <span className={event.status === "completed" ? "badge ok" : event.status === "failed" ? "badge warn" : "badge muted"} key="status">
              {event.status}
            </span>,
            event.message,
            <button className="linkButton" onClick={() => onOpenAsset(event.path)} key={event.path}>
              {event.path}
            </button>
          ])}
        />
      ) : (
        <div className="emptyCell">
          {zh ? "默认隐藏完整 timeline，展开后可查看 pending/running/completed 等全部事件。" : "Full timeline is hidden by default. Expand to inspect every pending/running/completed event."}
        </div>
      )}
      <h3>{zh ? "失败恢复" : "Recovery"}</h3>
      <div className="recoveryList">
        {(taskCenter?.recovery ?? []).map((report) => (
          <div className="recoveryRow" key={report.failed_status_path}>
            <div>
              <strong>{report.failed_step}</strong>
              <p>{report.recovery_instruction}</p>
              <span className="pathText">{report.failed_status_path}</span>
            </div>
            <button className="secondaryButton tableButton" disabled={busy} onClick={() => onRetry(report.failed_status_path)}>
              {zh ? "重试" : "Retry"}
            </button>
          </div>
        ))}
        {!taskCenter?.recovery?.length ? <div className="emptyCell">{zh ? "没有失败任务" : "No failed tasks"}</div> : null}
      </div>
      <h3>{zh ? "死信队列" : "Dead Letters"}</h3>
      <DataTable
        emptyText={zh ? "空" : "Empty"}
        columns={zh ? ["时间", "任务", "错误", "操作", "资产"] : ["Time", "Task", "Error", "Action", "Asset"]}
        rows={deadLetters.map((letter) => [
          letter.recorded_at,
          letter.task_name,
          `${letter.error_type}: ${letter.error_message}`,
          <button className="secondaryButton tableButton" disabled={busy} onClick={() => onRetryDeadLetter(letter.path)} key={`retry-${letter.path}`}>
            {zh ? "重试" : "Retry"}
          </button>,
          <button className="linkButton" onClick={() => onOpenAsset(letter.path)} key={letter.path}>
            {letter.path}
          </button>
        ])}
      />
      <h3>{zh ? "批处理恢复" : "Batch Recovery"}</h3>
      <div className="sectionActionLine">
        <button
          className="secondaryButton"
          disabled={busy || !failedBatchItems.length}
          onClick={() => onRetryFailedBatchItems(failedBatchItems.map((item) => item.path))}
        >
          <RefreshCw size={18} />
          {zh ? "批量重跑失败项" : "Retry Failed Items"}
        </button>
      </div>
      <DataTable
        emptyText={zh ? "没有失败或等待 handoff 的批处理项" : "No failed or waiting batch items"}
        columns={zh ? ["状态", "来源", "错误", "Handoff", "操作", "Item"] : ["Status", "Source", "Error", "Handoff", "Action", "Item"]}
        rows={batchItems
          .filter((item) => item.status === "failed" || item.status === "waiting_handoff")
          .map((item) => [
            <span className={item.status === "failed" ? "badge warn" : "badge muted"} key={`status-${item.path}`}>
              {item.status}
            </span>,
            item.source_name || item.source_path,
            item.error_message,
            item.handoff_path ? (
              <button className="linkButton" onClick={() => onOpenAsset(item.handoff_path)} key={`handoff-${item.path}`}>
                {item.handoff_status || "pending"}
              </button>
            ) : (
              ""
            ),
            item.status === "failed" ? (
              <button className="secondaryButton tableButton" disabled={busy} onClick={() => onRetryBatchItem(item.path)} key={`retry-item-${item.path}`}>
                {zh ? "重跑 item" : "Retry Item"}
              </button>
            ) : (
              ""
            ),
            <button className="linkButton" onClick={() => onOpenAsset(item.path)} key={item.path}>
              {item.path}
            </button>
          ])}
      />
    </section>
  );
}

function Progress({ value }: { value: number }) {
  return (
    <div className="progressWrap">
      <div className="progressTrack">
        <div className="progressFill" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
      <span>{value}%</span>
    </div>
  );
}

function AssetsPanel(props: {
  language: Language;
  health: Health | null;
  assets: AssetRow[];
  detail: AssetDetail | null;
  versions: AssetVersions | null;
  graph: AssetGraph | null;
  keyword: string;
  setKeyword: (value: string) => void;
  category: string;
  setCategory: (value: string) => void;
  collectionTitle: string;
  setCollectionTitle: (value: string) => void;
  onSearch: (event?: FormEvent) => void;
  onSelect: (path: string) => void;
  onSave: (path: string, patch: Record<string, unknown>) => void;
  onSaveContent: (path: string, content: Record<string, unknown>) => void;
  onSaveCollection: () => void;
}) {
  const zh = props.language === "zh";
  return (
    <section className="splitGrid">
      <div className="panel">
        <PanelHeader title={zh ? "资产目录" : "Asset Catalog"} icon={<FileSearch size={18} />} />
        <form className="searchBar" onSubmit={props.onSearch}>
          <input value={props.keyword} onChange={(event) => props.setKeyword(event.target.value)} placeholder={zh ? "关键词" : "Keyword"} aria-label={zh ? "关键词" : "Keyword"} />
          <select value={props.category} onChange={(event) => props.setCategory(event.target.value)} aria-label={zh ? "分类" : "Category"}>
            <option value="">{zh ? "全部分类" : "All categories"}</option>
            {Object.keys(props.health?.local_counts ?? {}).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <button className="primaryButton">
            <Search size={18} />
            {zh ? "搜索" : "Search"}
          </button>
        </form>
        <div className="collectionBar">
          <input value={props.collectionTitle} onChange={(event) => props.setCollectionTitle(event.target.value)} aria-label="Asset collection title" />
          <button className="secondaryButton" disabled={!props.assets.length} onClick={props.onSaveCollection}>
            <Save size={18} />
            {zh ? "保存集合" : "Save Set"}
          </button>
        </div>
        <DataTable
          emptyText={zh ? "空" : "Empty"}
          columns={zh ? ["标题", "分类", "类型", "标签", "路径"] : ["Title", "Category", "Type", "Tags", "Path"]}
          rows={props.assets.map((asset) => [
            asset.title || asset.path,
            asset.category,
            asset.type,
            asset.tags.slice(0, 4).join(", "),
            <button className="linkButton" onClick={() => props.onSelect(asset.path)} key={asset.path}>
              {asset.path}
            </button>
          ])}
        />
      </div>
      <AssetDetailPanel
        language={props.language}
        detail={props.detail}
        versions={props.versions}
        graph={props.graph}
        onSelect={props.onSelect}
        onSave={props.onSave}
        onSaveContent={props.onSaveContent}
      />
    </section>
  );
}

function AssetDetailPanel({
  language,
  detail,
  versions,
  graph,
  onSelect,
  onSave,
  onSaveContent
}: {
  language: Language;
  detail: AssetDetail | null;
  versions: AssetVersions | null;
  graph: AssetGraph | null;
  onSelect: (path: string) => void;
  onSave: (path: string, patch: Record<string, unknown>) => void;
  onSaveContent: (path: string, content: Record<string, unknown>) => void;
}) {
  const zh = language === "zh";
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [status, setStatus] = useState("active");
  const [risk, setRisk] = useState("unknown");
  const [notes, setNotes] = useState("");
  const [contentJson, setContentJson] = useState("{}");
  const [contentError, setContentError] = useState("");

  useEffect(() => {
    setTitle(detail?.summary.title ?? "");
    setTags((detail?.summary.tags ?? []).join(", "));
    setStatus(detail?.summary.asset_status || "active");
    setRisk(detail?.summary.risk_level || "unknown");
    setNotes(detail?.summary.operator_notes ?? "");
    setContentJson(JSON.stringify((detail?.asset.content as Record<string, unknown> | undefined) ?? {}, null, 2));
    setContentError("");
  }, [detail]);

  function saveContent() {
    if (!detail) return;
    setContentError("");
    try {
      const parsed = JSON.parse(contentJson);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(zh ? "content 必须是 JSON 对象" : "content must be a JSON object");
      }
      onSaveContent(detail.path, parsed as Record<string, unknown>);
    } catch (caught) {
      setContentError(messageOf(caught));
    }
  }

  return (
    <div className="panel">
      <PanelHeader title={zh ? "资产详情" : "Asset Detail"} icon={<FileSearch size={18} />} />
      {detail ? (
        <div className="detailStack">
          <div className="detailTitle">{detail.summary.title || detail.summary.id}</div>
          <div className="miniMetrics">
            <span className="statPill">{detail.summary.type}</span>
            {detail.summary.score !== undefined ? <span className="statPill">score: {detail.summary.score}</span> : null}
            {detail.summary.risk_level ? <span className="statPill">risk: {detail.summary.risk_level}</span> : null}
            {detail.summary.asset_status ? <span className="statPill">status: {detail.summary.asset_status}</span> : null}
          </div>
          <div className="editGrid">
            <input value={title} onChange={(event) => setTitle(event.target.value)} aria-label="Asset title" />
            <input value={tags} onChange={(event) => setTags(event.target.value)} aria-label="Asset tags" />
            <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Asset status">
              <option value="active">active</option>
              <option value="draft">draft</option>
              <option value="needs_review">needs_review</option>
              <option value="approved">approved</option>
              <option value="archived">archived</option>
              <option value="blocked">blocked</option>
            </select>
            <select value={risk} onChange={(event) => setRisk(event.target.value)} aria-label="Risk level">
              <option value="unknown">unknown</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
            <textarea value={notes} onChange={(event) => setNotes(event.target.value)} aria-label="Operator notes" />
            <button
              className="secondaryButton"
              onClick={() =>
                onSave(detail.path, {
                  title,
                  tags: tags
                    .split(",")
                    .map((tag) => tag.trim())
                    .filter(Boolean),
                  status,
                  risk_level: risk,
                  notes
                })
              }
            >
              <Save size={18} />
              {zh ? "保存" : "Save"}
            </button>
          </div>
          <p className="previewText">{detail.summary.preview || detail.path}</p>
          <div className="lineageList">
            {detail.lineage.reference_assets.map((item) => (
              <button className="linkButton" key={item.path} onClick={() => onSelect(item.path)}>
                {item.type}: {item.title}
              </button>
            ))}
          </div>
          {detail.summary.type === "claude_code_handoff" ? (
            <HandoffAssetWorkbench language={language} detail={detail} onSelect={onSelect} />
          ) : (
            <TypedAssetWorkbench language={language} detail={detail} onSelect={onSelect} />
          )}
          <div className="contentEditor">
            <div className="sectionHeaderLine">
              <h3>{zh ? "结构化内容" : "Structured Content"}</h3>
              <button className="secondaryButton tableButton" onClick={saveContent}>
                <Save size={16} />
                {zh ? "保存内容" : "Save Content"}
              </button>
            </div>
            <textarea
              className="jsonEditor"
              value={contentJson}
              onChange={(event) => setContentJson(event.target.value)}
              aria-label={zh ? "资产内容 JSON" : "Asset content JSON"}
            />
            {contentError ? <p className="warnText">{contentError}</p> : null}
          </div>
          <h3>{zh ? "版本" : "Versions"}</h3>
          <DataTable
            emptyText={zh ? "空" : "Empty"}
            columns={zh ? ["类型", "更新", "大小", "哈希", "路径"] : ["Kind", "Updated", "Size", "Hash", "Path"]}
            rows={(versions?.versions ?? []).map((version) => [
              version.kind,
              version.updated_at,
              String(version.size_bytes),
              <span className="pathText" key={`hash-${version.path}`}>{version.sha256.slice(0, 12)}</span>,
              <span className="pathText" key={version.path}>{version.path}</span>
            ])}
          />
          {versions?.diff.unified_diff ? <pre className="diffBlock">{versions.diff.unified_diff}</pre> : null}
          <h3>{zh ? "引用图谱" : "Reference Graph"}</h3>
          <DataTable
            emptyText={zh ? "空" : "Empty"}
            columns={zh ? ["类型", "标题", "路径"] : ["Type", "Title", "Path"]}
            rows={(graph?.nodes ?? []).map((node) => [
              node.type,
              node.title || node.id,
              <button className="linkButton" onClick={() => onSelect(node.path)} key={node.path}>
                {node.path}
              </button>
            ])}
          />
          <pre className="diffBlock">{JSON.stringify(graph?.edges ?? [], null, 2)}</pre>
          <pre>{JSON.stringify(detail.asset, null, 2)}</pre>
        </div>
      ) : (
        <div className="emptyCell">{zh ? "未选择资产" : "No asset selected"}</div>
      )}
    </div>
  );
}

function TypedAssetWorkbench({
  language,
  detail,
  onSelect
}: {
  language: Language;
  detail: AssetDetail;
  onSelect: (path: string) => void;
}) {
  const zh = language === "zh";
  const asset = detail.asset;
  const content = asset.content && typeof asset.content === "object" ? (asset.content as Record<string, unknown>) : {};
  const metadata = asset.metadata && typeof asset.metadata === "object" ? (asset.metadata as Record<string, unknown>) : {};
  const type = String(asset.type ?? "");
  if (!["decomposition_report", "knowledge_card", "material_card", "draft_chapter", "review_report", "revision_plan", "batch_task_item"].includes(type)) {
    return null;
  }
  return (
    <div className="typedWorkbench">
      <div className="sectionHeaderLine">
        <h3>{zh ? "资产工作台" : "Asset Workbench"}</h3>
        <span className="statPill">{type}</span>
      </div>
      {type === "decomposition_report" ? (
        <div className="typedGrid">
          <TypedBlock title={zh ? "摘要" : "Summary"} value={String(content.summary ?? "")} />
          <TypedList title={zh ? "商业模式" : "Commercial Patterns"} values={content.commercial_patterns} />
          <TypedList title={zh ? "叙事模式" : "Narrative Patterns"} values={content.narrative_patterns} />
          <TypedList title={zh ? "钩子" : "Hooks"} values={content.hook_patterns} />
        </div>
      ) : null}
      {type === "knowledge_card" ? (
        <div className="typedGrid">
          <TypedList title={zh ? "原则" : "Principles"} values={content.principles} />
          <TypedList title={zh ? "约束" : "Constraints"} values={content.constraints} />
          <TypedList title={zh ? "审稿检查" : "Review Checks"} values={content.review_checks} />
          <TypedBlock title={zh ? "来源许可" : "License Review"} value={String(metadata.license_review_status ?? metadata.copyright_boundary ?? "")} />
        </div>
      ) : null}
      {type === "material_card" ? (
        <div className="typedGrid">
          <TypedList title={zh ? "可用模式" : "Usable Patterns"} values={content.usable_patterns} />
          <TypedList title={zh ? "禁止复制" : "Do Not Copy"} values={content.do_not_copy} />
          <TypedList title={zh ? "适用场景" : "Use Cases"} values={content.use_cases} />
        </div>
      ) : null}
      {type === "draft_chapter" ? (
        <div className="typedGrid">
          <TypedBlock title={zh ? "章节" : "Chapter"} value={String(content.chapter ?? "")} />
          <TypedBlock title={zh ? "状态" : "Status"} value={String(metadata.draft_status ?? "")} />
          <TypedBlock title={zh ? "版本" : "Version"} value={`v${String(metadata.version_index ?? 0)}`} />
          <TypedBlock title={zh ? "正文预览" : "Text Preview"} value={String(content.text ?? "").slice(0, 600)} />
        </div>
      ) : null}
      {type === "review_report" ? (
        <div className="typedGrid">
          <TypedBlock title={zh ? "评分" : "Score"} value={String(asset.score ?? "")} />
          <TypedBlock title={zh ? "摘要" : "Summary"} value={String(content.summary ?? "")} />
          <TypedList title={zh ? "问题" : "Issues"} values={Array.isArray(asset.issues) ? (asset.issues as Array<Record<string, unknown>>).map((issue) => `${String(issue.status ?? "open")}: ${String(issue.message ?? issue.dimension ?? "")}`) : []} />
          <TypedList title={zh ? "建议" : "Suggestions"} values={asset.revision_suggestions} />
        </div>
      ) : null}
      {type === "revision_plan" ? (
        <div className="typedGrid">
          <TypedList title={zh ? "修订步骤" : "Steps"} values={content.steps} />
          <TypedBlock title={zh ? "目标评分" : "Target Score"} value={String(content.target_score ?? "")} />
          <TypedList title={zh ? "必须保留" : "Must Preserve"} values={content.must_preserve} />
        </div>
      ) : null}
      {type === "batch_task_item" ? (
        <div className="typedGrid">
          <TypedBlock title={zh ? "状态" : "Status"} value={String(content.status ?? "")} />
          <TypedBlock title={zh ? "源文件" : "Source"} value={String(content.source_path ?? "")} />
          <TypedList title={zh ? "步骤" : "Steps"} values={Array.isArray(content.steps) ? (content.steps as Array<Record<string, unknown>>).map((step) => `${String(step.step)}: ${String(step.status)}`) : []} />
          <div>
            <h3>{zh ? "输出" : "Outputs"}</h3>
            <div className="lineageList">
              {(Array.isArray(content.output_paths) ? content.output_paths : []).map((path) => (
                <button className="linkButton" key={String(path)} onClick={() => onSelect(String(path))}>
                  {String(path)}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TypedBlock({ title, value }: { title: string; value: string }) {
  return (
    <div className="typedBlock">
      <h3>{title}</h3>
      <p>{value || "-"}</p>
    </div>
  );
}

function TypedList({ title, values }: { title: string; values: unknown }) {
  const items = Array.isArray(values) ? values.map(String).filter(Boolean) : [];
  return (
    <div className="typedBlock">
      <h3>{title}</h3>
      {items.length ? (
        <ul className="checkList">
          {items.slice(0, 10).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>-</p>
      )}
    </div>
  );
}

function HandoffAssetWorkbench({
  language,
  detail,
  onSelect
}: {
  language: Language;
  detail: AssetDetail;
  onSelect: (path: string) => void;
}) {
  const zh = language === "zh";
  const content = detail.asset.content && typeof detail.asset.content === "object"
    ? (detail.asset.content as Record<string, unknown>)
    : {};
  const sourceAsset = content.source_asset && typeof content.source_asset === "object"
    ? (content.source_asset as Record<string, unknown>)
    : {};
  const manual = content.manual_execution && typeof content.manual_execution === "object"
    ? (content.manual_execution as Record<string, unknown>)
    : {};
  const inputFiles = Array.isArray(content.input_files) ? (content.input_files as Array<Record<string, unknown>>) : [];
  const instructions = Array.isArray(content.instructions) ? content.instructions.map(String) : [];
  const checks = Array.isArray(content.acceptance_checks) ? content.acceptance_checks.map(String) : [];
  const boundOutputs = Array.isArray(content.bound_outputs) ? (content.bound_outputs as Array<Record<string, unknown>>) : [];
  const sourcePath = String(sourceAsset.path ?? "");
  const expectedType = String(content.expected_output_type ?? "");
  const expectedDir = String(content.expected_output_dir ?? "");
  const validationCommand = String(manual.validation_command ?? "make validate");
  const [outputPath, setOutputPath] = useState("");
  const [validation, setValidation] = useState<HandoffOutputValidation | null>(null);
  const [acceptance, setAcceptance] = useState<HandoffAcceptance | null>(null);
  const [actionMessage, setActionMessage] = useState("");
  const promptText = buildHandoffPrompt(detail, content, sourcePath, inputFiles, instructions, checks, validationCommand);

  useEffect(() => {
    setOutputPath(boundOutputs[0]?.path ? String(boundOutputs[0].path) : "");
    setValidation(null);
    fetchJson<HandoffAcceptance>(`/product/handoffs/acceptance?handoff_path=${encodeURIComponent(detail.path)}`)
      .then(setAcceptance)
      .catch((caught) => setActionMessage(messageOf(caught)));
    setActionMessage("");
  }, [detail.path]);

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(promptText);
      setActionMessage(zh ? "执行提示已复制" : "Execution prompt copied");
    } catch (caught) {
      setActionMessage(messageOf(caught));
    }
  }

  async function validateOutput(bind: boolean) {
    setActionMessage("");
    setValidation(null);
    try {
      const path = bind ? "/product/handoffs/bind-output" : "/product/handoffs/validate-output";
      const result = await postJson(path, {
        handoff_path: detail.path,
        output_path: outputPath,
        mark_completed: true
      });
      const nextValidation = (bind ? (result as { validation: HandoffOutputValidation }).validation : result) as HandoffOutputValidation;
      setValidation(nextValidation);
      setActionMessage(
        nextValidation.valid
          ? bind
            ? (zh ? "输出资产已绑定" : "Output asset bound")
            : (zh ? "输出资产匹配" : "Output asset matches")
          : (zh ? "输出资产不匹配" : "Output asset does not match")
      );
      if (bind) onSelect(detail.path);
    } catch (caught) {
      setActionMessage(messageOf(caught));
    }
  }

  async function updateAcceptance(index: number, status: string) {
    setActionMessage("");
    try {
      const updated = await fetchJson<HandoffAcceptance>("/product/handoffs/acceptance", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handoff_path: detail.path, check_index: index, status })
      });
      setAcceptance(updated);
      setActionMessage(zh ? "验收状态已更新" : "Acceptance updated");
    } catch (caught) {
      setActionMessage(messageOf(caught));
    }
  }

  async function markFailed() {
    try {
      await postJson("/product/handoffs/fail", { handoff_path: detail.path, reason: "operator marked handoff failed" });
      setActionMessage(zh ? "执行包已标记失败" : "Handoff marked failed");
      onSelect(detail.path);
    } catch (caught) {
      setActionMessage(messageOf(caught));
    }
  }

  async function retryCurrentHandoff() {
    try {
      const result = await postJson("/product/handoffs/retry", { handoff_path: detail.path, reason: "operator requested retry" });
      const handoff = (result as { handoff?: AssetDetail }).handoff;
      setActionMessage(zh ? "已生成新的执行包" : "New handoff generated");
      if (handoff?.path) onSelect(handoff.path);
    } catch (caught) {
      setActionMessage(messageOf(caught));
    }
  }

  return (
    <div className="handoffWorkbench">
      <div className="sectionHeaderLine">
        <h3>{zh ? "Claude Code 执行包工作台" : "Claude Code Handoff Workbench"}</h3>
        <button className="secondaryButton tableButton" onClick={copyPrompt}>
          <Copy size={16} />
          {zh ? "复制执行提示" : "Copy Prompt"}
        </button>
        <button className="secondaryButton tableButton" onClick={retryCurrentHandoff}>
          <RefreshCw size={16} />
          {zh ? "重做" : "Retry"}
        </button>
        <button className="secondaryButton tableButton dangerButton" onClick={markFailed}>
          <Trash2 size={16} />
          {zh ? "失败" : "Fail"}
        </button>
      </div>
      <div className="handoffDetailGrid">
        <div>
          <strong>{zh ? "源文件" : "Source"}</strong>
          {sourcePath ? (
            <button className="linkButton pathText" onClick={() => onSelect(sourcePath)}>
              {sourcePath}
            </button>
          ) : (
            <span className="pathText">{String(detail.asset.source ?? "")}</span>
          )}
        </div>
        <div>
          <strong>{zh ? "技能" : "Skill"}</strong>
          <span>{String(content.skill ?? "")}</span>
        </div>
        <div>
          <strong>{zh ? "期望输出" : "Expected Output"}</strong>
          <span>{expectedType} {"->"} {expectedDir}</span>
        </div>
        <div>
          <strong>{zh ? "校验命令" : "Validation"}</strong>
          <span className="pathText">{validationCommand}</span>
        </div>
      </div>
      <DataTable
        emptyText={zh ? "空" : "Empty"}
        columns={zh ? ["角色", "路径", "必读"] : ["Role", "Path", "Required"]}
        rows={inputFiles.map((item) => [
          String(item.role ?? ""),
          <span className="pathText" key={`input-${String(item.path)}`}>{String(item.path ?? "")}</span>,
          String(Boolean(item.must_read))
        ])}
      />
      <div className="handoffListGrid">
        <div>
          <h3>{zh ? "执行指令" : "Instructions"}</h3>
          <ul className="checkList">
            {instructions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3>{zh ? "验收项" : "Acceptance"}</h3>
          <div className="acceptanceList">
            {(acceptance?.checks ?? checks.map((check, index) => ({ index, check, status: "pending", note: "", updated_at: "" }))).map((item) => (
              <div className="acceptanceItem" key={`${item.index}-${item.check}`}>
                <span className={item.status === "accepted" ? "badge ok" : item.status === "pending" ? "badge muted" : "badge warn"}>{item.status}</span>
                <p>{item.check}</p>
                <div className="actionRow compact">
                  <button className="secondaryButton tableButton" onClick={() => updateAcceptance(item.index, "accepted")}>
                    {zh ? "通过" : "Accept"}
                  </button>
                  <button className="secondaryButton tableButton" onClick={() => updateAcceptance(item.index, "needs_fix")}>
                    {zh ? "需修复" : "Needs Fix"}
                  </button>
                </div>
              </div>
            ))}
          </div>
          {acceptance ? (
            <div className="miniMetrics">
              <span className={acceptance.summary.complete ? "badge ok" : "badge muted"}>
                {zh ? "通过" : "accepted"}: {acceptance.summary.accepted}/{acceptance.summary.total}
              </span>
              <span className={acceptance.summary.failed ? "badge warn" : "badge muted"}>
                {zh ? "失败" : "failed"}: {acceptance.summary.failed}
              </span>
            </div>
          ) : null}
        </div>
      </div>
      <pre className="promptBlock">{promptText}</pre>
      <div className="formGrid wide">
        <input value={outputPath} onChange={(event) => setOutputPath(event.target.value)} aria-label="Handoff output asset path" placeholder={expectedDir ? `${expectedDir}/...json` : "data/.../*.json"} />
        <button className="secondaryButton" disabled={!outputPath.trim()} onClick={() => validateOutput(false)}>
          <CheckCircle2 size={18} />
          {zh ? "校验输出" : "Validate"}
        </button>
        <button className="primaryButton" disabled={!outputPath.trim()} onClick={() => validateOutput(true)}>
          <Save size={18} />
          {zh ? "绑定输出" : "Bind Output"}
        </button>
      </div>
      {validation || actionMessage ? (
        <div className={validation?.valid ? "validationLine ok" : actionMessage && !validation ? "validationLine muted" : "validationLine warn"}>
          <strong>{actionMessage || (validation?.valid ? "valid" : "invalid")}</strong>
          {validation ? (
            <span>
              {validation.expected_output_type} / {validation.actual_output_type || "-"}
              {validation.errors.length ? `: ${validation.errors.join("; ")}` : ""}
              {validation.warnings.length ? ` (${validation.warnings.join("; ")})` : ""}
            </span>
          ) : null}
        </div>
      ) : null}
      <DataTable
        emptyText={zh ? "未绑定输出" : "No bound outputs"}
        columns={zh ? ["类型", "标题", "时间", "路径"] : ["Type", "Title", "Bound", "Path"]}
        rows={boundOutputs.map((item) => [
          String(item.type ?? ""),
          String(item.title ?? item.id ?? ""),
          String(item.bound_at ?? ""),
          <button className="linkButton" onClick={() => onSelect(String(item.path ?? ""))} key={`bound-${String(item.path)}`}>
            {String(item.path ?? "")}
          </button>
        ])}
      />
    </div>
  );
}

function buildHandoffPrompt(
  detail: AssetDetail,
  content: Record<string, unknown>,
  sourcePath: string,
  inputFiles: Array<Record<string, unknown>>,
  instructions: string[],
  checks: string[],
  validationCommand: string
) {
  return [
    "Claude Code / Codex handoff",
    `Handoff asset: ${detail.path}`,
    `Operation: ${String(content.operation ?? "")}`,
    `Skill: ${String(content.skill ?? "")}`,
    `Runtime: ${String(content.runtime ?? "")}/${String(content.runtime_model ?? "")}`,
    `Source asset: ${sourcePath || String(detail.asset.source ?? "")}`,
    `Expected output: ${String(content.expected_output_type ?? "")} -> ${String(content.expected_output_dir ?? "")}`,
    `Validation command: ${validationCommand}`,
    "",
    "Input files:",
    ...inputFiles.map((item) => `- ${String(item.role ?? "input")}: ${String(item.path ?? "")}${item.must_read ? " (must read)" : ""}`),
    "",
    "Instructions:",
    ...instructions.map((item, index) => `${index + 1}. ${item}`),
    "",
    "Acceptance checks:",
    ...checks.map((item) => `- ${item}`),
    "",
    "After writing the output asset, return to Novel Forge and bind the output path to this handoff."
  ].join("\n");
}

function HandoffsPanel(props: {
  language: Language;
  text: typeof copy.en.handoffs;
  handoffs: HandoffRow[];
  detail: AssetDetail | null;
  githubSources: GitHubSource[];
  handoffInput: string;
  setHandoffInput: (value: string) => void;
  handoffGenre: string;
  setHandoffGenre: (value: string) => void;
  handoffReader: string;
  setHandoffReader: (value: string) => void;
  handoffPurpose: string;
  setHandoffPurpose: (value: string) => void;
  handoffDiscipline: string;
  setHandoffDiscipline: (value: string) => void;
  handoffCredibility: string;
  setHandoffCredibility: (value: string) => void;
  handoffScope: string;
  setHandoffScope: (value: string) => void;
  handoffContext: string;
  setHandoffContext: (value: string) => void;
  githubSourceRefs: string;
  setGithubSourceRefs: (value: string) => void;
  busy: boolean;
  onCreateDeconstruct: () => void;
  onCreateKnowledge: () => void;
  onCreateGithubKnowledge: () => void;
  onSelect: (path: string) => void;
}) {
  const content = props.detail?.asset.content && typeof props.detail.asset.content === "object"
    ? (props.detail.asset.content as Record<string, unknown>)
    : {};
  const sourceAsset = content.source_asset && typeof content.source_asset === "object"
    ? (content.source_asset as Record<string, unknown>)
    : {};
  return (
    <section className="splitGrid">
      <div className="panel">
        <PanelHeader title={props.text.title} icon={<Workflow size={18} />} />
        <div className="handoffForms">
          <div className="handoffForm">
            <h3>{props.text.deconstruct}</h3>
            <input value={props.handoffInput} onChange={(event) => props.setHandoffInput(event.target.value)} aria-label={props.text.input} placeholder={props.text.input} />
            <div className="formGrid compact">
              <input value={props.handoffGenre} onChange={(event) => props.setHandoffGenre(event.target.value)} aria-label={props.text.genre} placeholder={props.text.genre} />
              <input value={props.handoffReader} onChange={(event) => props.setHandoffReader(event.target.value)} aria-label={props.text.reader} placeholder={props.text.reader} />
            </div>
            <input value={props.handoffPurpose} onChange={(event) => props.setHandoffPurpose(event.target.value)} aria-label={props.text.purpose} placeholder={props.text.purpose} />
            <button className="primaryButton" disabled={props.busy || !props.handoffInput.trim()} onClick={props.onCreateDeconstruct}>
              <Workflow size={18} />
              {props.text.createDeconstruct}
            </button>
          </div>
          <div className="handoffForm">
            <h3>{props.text.knowledge}</h3>
            <input value={props.handoffInput} onChange={(event) => props.setHandoffInput(event.target.value)} aria-label={props.text.input} placeholder={props.text.input} />
            <div className="formGrid compact">
              <input value={props.handoffDiscipline} onChange={(event) => props.setHandoffDiscipline(event.target.value)} aria-label={props.text.discipline} placeholder={props.text.discipline} />
              <input value={props.handoffCredibility} onChange={(event) => props.setHandoffCredibility(event.target.value)} aria-label={props.text.credibility} placeholder={props.text.credibility} />
            </div>
            <input value={props.handoffScope} onChange={(event) => props.setHandoffScope(event.target.value)} aria-label={props.text.scope} placeholder={props.text.scope} />
            <input value={props.handoffContext} onChange={(event) => props.setHandoffContext(event.target.value)} aria-label={props.text.context} placeholder={props.text.context} />
            <button className="secondaryButton" disabled={props.busy || !props.handoffInput.trim()} onClick={props.onCreateKnowledge}>
              <FileSearch size={18} />
              {props.text.createKnowledge}
            </button>
          </div>
          <div className="handoffForm">
            <h3>{props.text.githubKnowledge}</h3>
            <input value={props.githubSourceRefs} onChange={(event) => props.setGithubSourceRefs(event.target.value)} aria-label={props.text.githubRefs} placeholder={props.text.githubRefs} />
            <div className="formGrid compact">
              <input value={props.handoffDiscipline} onChange={(event) => props.setHandoffDiscipline(event.target.value)} aria-label={props.text.discipline} placeholder={props.text.discipline} />
              <input value={props.handoffContext} onChange={(event) => props.setHandoffContext(event.target.value)} aria-label={props.text.context} placeholder={props.text.context} />
            </div>
            <button className="secondaryButton" disabled={props.busy || !props.githubSourceRefs.trim()} onClick={props.onCreateGithubKnowledge}>
              <Database size={18} />
              {props.text.createGithubKnowledge}
            </button>
          </div>
        </div>
        <h3>{props.text.githubSources}</h3>
        <DataTable
          emptyText={props.text.empty}
          columns={["Repo", "Category", "Risk", "License", "Action"]}
          rows={props.githubSources.slice(0, 12).map((source) => [
            <a href={source.url} target="_blank" rel="noreferrer" key={`repo-${source.id}`}>{source.repo}</a>,
            source.category,
            <span className={source.commercial_risk.includes("high") ? "badge warn" : "badge muted"} key={`risk-${source.id}`}>
              {source.commercial_risk}
            </span>,
            source.license_check,
            <button
              className="secondaryButton tableButton"
              disabled={props.busy}
              onClick={() =>
                props.setGithubSourceRefs(
                  Array.from(
                    new Set(
                      [...props.githubSourceRefs.split(",").map((item) => item.trim()).filter(Boolean), source.repo]
                    )
                  ).join(", ")
                )
              }
              key={`add-${source.id}`}
            >
              {props.text.add}
            </button>
          ])}
        />
        <h3>{props.text.list}</h3>
        <DataTable
          emptyText={props.text.empty}
          columns={props.text.columns}
          rows={props.handoffs.map((handoff) => [
            handoff.operation,
            <span className={handoff.status === "completed" ? "badge ok" : handoff.status === "failed" ? "badge warn" : "badge muted"} key={`status-${handoff.path}`}>
              {handoff.status}
            </span>,
            handoff.skill,
            handoff.expected_output_type,
            handoff.source_path,
            <button className="secondaryButton tableButton" onClick={() => props.onSelect(handoff.path)} key={`open-${handoff.path}`}>
              {props.text.open}
            </button>,
            <button className="linkButton" onClick={() => props.onSelect(handoff.path)} key={handoff.path}>
              {handoff.path}
            </button>
          ])}
        />
      </div>
      <div className="panel">
        <PanelHeader title={props.text.detail} icon={<FileSearch size={18} />} />
        {props.detail ? (
          <div className="detailStack">
            <div className="detailTitle">{props.detail.summary.title || props.detail.summary.id}</div>
            <div className="miniMetrics">
              <span className="statPill">{String(content.operation ?? "")}</span>
              <span className="statPill">{props.text.status}: {String(content.status ?? "")}</span>
              <span className="statPill">{String(content.runtime ?? "")}/{String(content.runtime_model ?? "")}</span>
            </div>
            <div className="handoffDetailGrid">
              <div>
                <strong>{props.text.source}</strong>
                <span className="pathText">{String(sourceAsset.path ?? props.detail.asset.source ?? "")}</span>
              </div>
              <div>
                <strong>{props.text.expected}</strong>
                <span>{String(content.expected_output_type ?? "")} {"->"} {String(content.expected_output_dir ?? "")}</span>
              </div>
              <div>
                <strong>{props.text.validation}</strong>
                <span className="pathText">{String((content.manual_execution as Record<string, unknown> | undefined)?.validation_command ?? "make validate")}</span>
              </div>
            </div>
            <HandoffAssetWorkbench language={props.language} detail={props.detail} onSelect={props.onSelect} />
          </div>
        ) : (
          <div className="emptyCell">{props.text.noSelection}</div>
        )}
      </div>
    </section>
  );
}

function BatchPanel(props: {
  language: Language;
  batchInput: string;
  setBatchInput: (value: string) => void;
  batchAnalysisMode: string;
  setBatchAnalysisMode: (value: string) => void;
  batchDecompositionPath: string;
  setBatchDecompositionPath: (value: string) => void;
  batchKnowledgePath: string;
  setBatchKnowledgePath: (value: string) => void;
  batchItems: BatchItem[];
  uploadResult: UploadResult | null;
  busy: boolean;
  onUpload: (files: File[]) => void;
  onRun: () => void;
  onContinueItem: (itemPath: string) => void;
  onRegenerateHandoff: (itemPath: string) => void;
  onVoidHandoff: (itemPath: string) => void;
  onRetryItem: (itemPath: string) => void;
  onReviewItem: (itemPath: string, decision: string) => void;
  onOpenAsset: (path: string) => void;
}) {
  const zh = props.language === "zh";
  const [files, setFiles] = useState<File[]>([]);
  return (
    <section className="panel">
      <PanelHeader title={zh ? "批量拆书" : "Batch Deconstruction"} icon={<Layers3 size={18} />} />
      <div className="uploadBox">
        <input
          type="file"
          multiple
          onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          aria-label="Upload source files"
        />
        <button className="secondaryButton" disabled={props.busy || files.length === 0} onClick={() => props.onUpload(files)}>
          <UploadCloud size={18} />
          {zh ? "上传" : "Upload"}
        </button>
      </div>
      {props.uploadResult ? (
        <div className="uploadPreview">
          {props.uploadResult.items.map((item) => (
            <div className="uploadItem" key={item.path}>
              <strong>{item.filename}</strong>
              <span className="pathText">{item.path}</span>
              <span className={item.duplicate ? "badge warn" : "badge ok"}>{item.duplicate ? "duplicate" : item.format}</span>
              <span className={item.minio.uploaded ? "badge ok" : "badge muted"}>MinIO: {item.minio.uploaded ? "uploaded" : "local"}</span>
              <p>{item.preview}</p>
            </div>
          ))}
        </div>
      ) : null}
      <div className="formGrid wide">
        <input value={props.batchInput} onChange={(event) => props.setBatchInput(event.target.value)} aria-label="Source path" />
        <select value={props.batchAnalysisMode} onChange={(event) => props.setBatchAnalysisMode(event.target.value)} aria-label={zh ? "解析模式" : "Analysis mode"}>
          <option value="auto">{zh ? "自动解析" : "Auto"}</option>
          <option value="claude_code">{zh ? "Claude Code 执行包" : "Claude Code handoff"}</option>
        </select>
        <button className="primaryButton" disabled={props.busy} onClick={props.onRun}>
          <Play size={18} />
          {zh ? "开始" : "Start"}
        </button>
      </div>
      <div className="formGrid compact">
        <input
          value={props.batchDecompositionPath}
          onChange={(event) => props.setBatchDecompositionPath(event.target.value)}
          aria-label={zh ? "人工拆解资产路径" : "Manual decomposition path"}
          placeholder={zh ? "人工 DecompositionReport 路径，可空" : "Manual DecompositionReport path, optional"}
        />
        <input
          value={props.batchKnowledgePath}
          onChange={(event) => props.setBatchKnowledgePath(event.target.value)}
          aria-label={zh ? "人工知识卡路径" : "Manual knowledge path"}
          placeholder={zh ? "人工 KnowledgeCard 路径，可空" : "Manual KnowledgeCard path, optional"}
        />
      </div>
      <div className="processStrip">
        {(props.batchAnalysisMode === "claude_code"
          ? ["ingest", "clean", "claude-handoff", "manual output", "materials"]
          : ["ingest", "clean", "decompose", "knowledge", "materials"]
        ).map((step) => (
          <span key={step}>
            <CheckCircle2 size={16} />
            {step}
          </span>
        ))}
      </div>
      <DataTable
        emptyText={zh ? "空" : "Empty"}
        columns={zh ? ["来源", "模式", "状态", "审核", "步骤", "输出", "操作", "条目"] : ["Source", "Mode", "Status", "Review", "Steps", "Outputs", "Action", "Item"]}
        rows={props.batchItems.map((item) => [
          item.source_name || item.source_path,
          <span className={item.analysis_mode === "claude_code" ? "badge warn" : "badge muted"} key={`mode-${item.path}`}>
            {item.analysis_mode || "auto"}
          </span>,
          <span className={item.status === "completed" ? "badge ok" : item.status === "failed" ? "badge warn" : "badge muted"} key="status">
            {item.status}
          </span>,
          <div className="tableActions" key={`review-${item.path}`}>
            <span className={item.review_status === "approved" ? "badge ok" : item.review_status ? "badge warn" : "badge muted"}>
              {item.review_status || "pending"}
            </span>
            <button className="linkButton" disabled={props.busy} onClick={() => props.onReviewItem(item.path, "approved")}>
              {zh ? "通过" : "approve"}
            </button>
            <button className="linkButton" disabled={props.busy} onClick={() => props.onReviewItem(item.path, "needs_revision")}>
              {zh ? "修订" : "revise"}
            </button>
            <button className="linkButton" disabled={props.busy} onClick={() => props.onReviewItem(item.path, "rejected")}>
              {zh ? "拒绝" : "reject"}
            </button>
          </div>,
          item.steps.map((step) => `${step.step}:${step.status}`).join(" | "),
          item.material ? (
            <button className="linkButton" onClick={() => props.onOpenAsset(item.material)} key={`material-${item.path}`}>
              {item.material}
            </button>
          ) : item.handoff_path ? (
            <button className="linkButton" onClick={() => props.onOpenAsset(item.handoff_path)} key={`handoff-${item.path}`}>
              {item.handoff_path}
            </button>
          ) : (
            item.output_paths.join(", ")
          ),
          <div className="tableActions" key={`actions-${item.path}`}>
            {item.status === "waiting_handoff" ? (
              <>
                <button className="secondaryButton tableButton" disabled={props.busy} onClick={() => props.onContinueItem(item.path)}>
                  {zh ? "继续" : "Continue"}
                </button>
                <button className="secondaryButton tableButton" disabled={props.busy} onClick={() => props.onRegenerateHandoff(item.path)}>
                  {zh ? "重生成" : "Regenerate"}
                </button>
                <button className="secondaryButton dangerButton tableButton" disabled={props.busy} onClick={() => props.onVoidHandoff(item.path)}>
                  {zh ? "作废" : "Void"}
                </button>
              </>
            ) : null}
            {item.status === "failed" ? (
              item.analysis_mode === "claude_code" ? (
                <button className="secondaryButton tableButton" disabled={props.busy} onClick={() => props.onRegenerateHandoff(item.path)}>
                  {zh ? "重生成" : "Regenerate"}
                </button>
              ) : (
                <button className="secondaryButton tableButton" disabled={props.busy} onClick={() => props.onRetryItem(item.path)}>
                  {zh ? "重试" : "Retry"}
                </button>
              )
            ) : null}
          </div>,
          <button className="linkButton" onClick={() => props.onOpenAsset(item.path)} key={item.path}>
            {item.path}
          </button>
        ])}
      />
    </section>
  );
}

function DraftsPanel(props: {
  language: Language;
  drafts: DraftWorkbench | null;
  selectedPlan: string;
  setSelectedPlan: (value: string) => void;
  selectedDraft: string;
  setSelectedDraft: (value: string) => void;
  draftEditor: DraftEditorState | null;
  setDraftEditor: (value: DraftEditorState | null) => void;
  draftExport: Record<string, unknown> | null;
  selectedWorkspace: string;
  setSelectedWorkspace: (value: string) => void;
  busy: boolean;
  onGenerate: () => void;
  onSaveDraft: () => void;
  onExportDraft: (format: string) => void;
  onOpenAsset: (path: string) => void;
}) {
  const zh = props.language === "zh";
  return (
    <section className="panel">
      <PanelHeader title={zh ? "稿件工作台" : "Draft Workbench"} icon={<PenLine size={18} />} />
      <div className="formGrid">
        <SelectPath label={zh ? "章节计划" : "Chapter plan"} latestLabel={zh ? "最新" : "Latest"} value={props.selectedPlan} onChange={props.setSelectedPlan} rows={props.drafts?.chapter_plans ?? []} />
        <SelectPath label={zh ? "草稿" : "Draft"} latestLabel={zh ? "最新" : "Latest"} value={props.selectedDraft} onChange={props.setSelectedDraft} rows={props.drafts?.drafts ?? []} />
        <SelectPath label={zh ? "工作区" : "Workspace"} latestLabel={zh ? "最新" : "Latest"} value={props.selectedWorkspace} onChange={props.setSelectedWorkspace} rows={props.drafts?.workspace ?? []} />
        <button className="primaryButton" disabled={props.busy} onClick={props.onGenerate}>
          <PenLine size={18} />
          {zh ? "生成草稿" : "Draft"}
        </button>
      </div>
      {props.draftEditor ? (
        <div className="editorGrid">
          <input
            value={props.draftEditor.title}
            onChange={(event) => props.setDraftEditor({ ...props.draftEditor!, title: event.target.value })}
            aria-label="Draft title"
          />
          <div className="actionRow">
            <button className="secondaryButton" disabled={props.busy} onClick={props.onSaveDraft}>
              <Save size={18} />
              {zh ? "保存草稿" : "Save Draft"}
            </button>
            <button className="secondaryButton" disabled={props.busy} onClick={() => props.onExportDraft("markdown")}>MD</button>
            <button className="secondaryButton" disabled={props.busy} onClick={() => props.onExportDraft("docx")}>DOCX</button>
            <button className="secondaryButton" disabled={props.busy} onClick={() => props.onExportDraft("epub")}>EPUB</button>
          </div>
          <textarea
            className="draftEditor"
            value={props.draftEditor.text}
            onChange={(event) => props.setDraftEditor({ ...props.draftEditor!, text: event.target.value })}
            aria-label="Draft text"
          />
          <div className="miniMetrics">
            <span className="statPill">version: {props.draftEditor.version_index}</span>
            <span className="statPill">status: {props.draftEditor.status}</span>
            {props.draftExport?.path ? <span className="statPill">export: {String(props.draftExport.path)}</span> : null}
          </div>
        </div>
      ) : null}
      <DataTable
        emptyText={zh ? "空" : "Empty"}
        columns={zh ? ["章节", "标题", "摘要", "路径"] : ["Chapter", "Title", "Summary", "Path"]}
        rows={(props.drafts?.drafts ?? []).map((draft) => [
          String(draft.chapter || ""),
          draft.title,
          draft.summary,
          <div className="tableActions" key={draft.path}>
            <button className="linkButton" onClick={() => props.setSelectedDraft(draft.path)}>
              {zh ? "编辑" : "Edit"}
            </button>
            <button className="linkButton" onClick={() => props.onOpenAsset(draft.path)}>
              {draft.path}
            </button>
          </div>
        ])}
      />
    </section>
  );
}

function ReviewPanel(props: {
  language: Language;
  drafts: DraftWorkbench | null;
  selectedDraft: string;
  setSelectedDraft: (value: string) => void;
  selectedReview: string;
  setSelectedReview: (value: string) => void;
  selectedRevision: string;
  setSelectedRevision: (value: string) => void;
  reviewDetail: AssetDetail | null;
  revisionPreview: RevisionApplyResult | null;
  selectedWorkspace: string;
  setSelectedWorkspace: (value: string) => void;
  busy: boolean;
  onReview: (comparison: boolean) => void;
  onRevise: () => void;
  onIssueStatus: (index: number, status: string) => void;
  onPreviewRevision: () => void;
  onApplyRevision: () => void;
  onOpenAsset: (path: string) => void;
}) {
  const zh = props.language === "zh";
  const issues = Array.isArray(props.reviewDetail?.asset.issues) ? (props.reviewDetail?.asset.issues as Array<Record<string, unknown>>) : [];
  return (
    <section className="workspaceGrid">
      <div className="panel">
        <PanelHeader title={zh ? "审稿流程" : "Review Flow"} icon={<GitPullRequest size={18} />} />
        <div className="formGrid">
          <SelectPath label={zh ? "草稿" : "Draft"} latestLabel={zh ? "最新" : "Latest"} value={props.selectedDraft} onChange={props.setSelectedDraft} rows={props.drafts?.drafts ?? []} />
          <SelectPath label={zh ? "工作区" : "Workspace"} latestLabel={zh ? "最新" : "Latest"} value={props.selectedWorkspace} onChange={props.setSelectedWorkspace} rows={props.drafts?.workspace ?? []} />
          <button className="primaryButton" disabled={props.busy} onClick={() => props.onReview(false)}>
            <FileSearch size={18} />
            {zh ? "审稿" : "Review"}
          </button>
          <button className="secondaryButton" disabled={props.busy} onClick={() => props.onReview(true)}>
            <GitPullRequest size={18} />
            {zh ? "对比" : "Compare"}
          </button>
        </div>
        <DataTable
          emptyText={zh ? "空" : "Empty"}
          columns={zh ? ["标题", "评分", "风险", "路径"] : ["Title", "Score", "Risk", "Path"]}
          rows={(props.drafts?.reviews ?? []).map((review) => [
            review.title,
            String(review.score ?? ""),
            review.risk_level,
            <button className="linkButton" onClick={() => props.onOpenAsset(review.path)} key={review.path}>
              {review.path}
            </button>
          ])}
        />
        <h3>{zh ? "问题状态" : "Issue States"}</h3>
        <DataTable
          emptyText={zh ? "空" : "Empty"}
          columns={zh ? ["问题", "状态", "操作"] : ["Issue", "Status", "Action"]}
          rows={issues.map((issue, index) => [
            String(issue.message ?? issue.dimension ?? `Issue ${index + 1}`),
            String(issue.status ?? "open"),
            <div className="tableActions" key={`issue-${index}`}>
              {["accepted", "ignored", "fixed"].map((status) => (
                <button className="linkButton" key={status} disabled={props.busy} onClick={() => props.onIssueStatus(index, status)}>
                  {status}
                </button>
              ))}
            </div>
          ])}
        />
      </div>
      <div className="panel">
        <PanelHeader title={zh ? "修订计划" : "Revision Plans"} icon={<Workflow size={18} />} />
        <div className="formGrid compact">
          <SelectPath label={zh ? "审稿" : "Review"} latestLabel={zh ? "最新" : "Latest"} value={props.selectedReview} onChange={props.setSelectedReview} rows={props.drafts?.reviews ?? []} />
          <button className="primaryButton" disabled={props.busy} onClick={props.onRevise}>
            <Workflow size={18} />
            {zh ? "计划" : "Plan"}
          </button>
        </div>
        <div className="formGrid compact">
          <SelectPath label={zh ? "修订" : "Revision"} latestLabel={zh ? "最新" : "Latest"} value={props.selectedRevision} onChange={props.setSelectedRevision} rows={props.drafts?.revision_plans ?? []} />
          <button className="secondaryButton" disabled={props.busy || !props.selectedRevision} onClick={props.onPreviewRevision}>
            {zh ? "预览" : "Preview"}
          </button>
          <button className="primaryButton" disabled={props.busy || !props.selectedRevision} onClick={props.onApplyRevision}>
            {zh ? "应用" : "Apply"}
          </button>
        </div>
        {props.revisionPreview ? (
          <div className="revisionPreview">
            <div className="miniMetrics">
              <span className="statPill">mode: {props.revisionPreview.mode}</span>
              <span className="statPill">before: {props.revisionPreview.preview.score_before ?? ""}</span>
              <span className="statPill">target: {props.revisionPreview.preview.target_score ?? ""}</span>
            </div>
            <p>{props.revisionPreview.preview.excerpt}</p>
          </div>
        ) : null}
        <DataTable
          emptyText={zh ? "空" : "Empty"}
          columns={zh ? ["标题", "来源", "路径"] : ["Title", "Source", "Path"]}
          rows={(props.drafts?.revision_plans ?? []).map((revision) => [
            revision.title,
            revision.source,
            <button className="linkButton" onClick={() => props.onOpenAsset(revision.path)} key={revision.path}>
              {revision.path}
            </button>
          ])}
        />
      </div>
    </section>
  );
}

function SelectPath(props: {
  label: string;
  latestLabel?: string;
  value: string;
  onChange: (value: string) => void;
  rows: Array<{ path: string; title: string }>;
}) {
  return (
    <label className="selectWrap">
      <span>{props.label}</span>
      <select value={props.value} onChange={(event) => props.onChange(event.target.value)}>
        <option value="">{props.latestLabel ?? "Latest"}</option>
        {props.rows.map((row) => (
          <option key={row.path} value={row.path}>
            {row.title || row.path}
          </option>
        ))}
      </select>
    </label>
  );
}

function PanelHeader({ title, icon }: { title: string; icon: ReactNode }) {
  return (
    <div className="panelHeader">
      <h2>{title}</h2>
      {icon}
    </div>
  );
}

function DataTable({ columns, rows, emptyText = "Empty" }: { columns: string[]; rows: ReactNode[][]; emptyText?: string }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
          {!rows.length ? (
            <tr>
              <td colSpan={columns.length} className="emptyCell">
                {emptyText}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function postJson(path: string, body: Record<string, unknown>) {
  return fetchJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

function compactResult(result: unknown): string {
  if (!result || typeof result !== "object") return String(result ?? "done");
  const data = result as Record<string, unknown>;
  return String(data.path ?? data.draft_path ?? data.review_path ?? data.revision_path ?? data.task_id ?? data.processed ?? "done");
}

function queueLengthText(value?: Record<string, unknown>): string {
  if (!value) return "offline";
  const queues = value.queues;
  if (queues && typeof queues === "object") {
    return Object.entries(queues as Record<string, unknown>)
      .map(([name, count]) => `${name}:${count}`)
      .join(" ");
  }
  if (value.error) return "offline";
  return "0";
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
