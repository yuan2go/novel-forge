"use client";

import {
  Activity,
  Archive,
  BarChart3,
  BookMarked,
  BookOpen,
  Boxes,
  CheckCircle2,
  Copy,
  Database,
  FileSearch,
  GitPullRequest,
  Home,
  Layers3,
  Languages,
  Library,
  ListChecks,
  MessageSquareText,
  Network,
  PenLine,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UploadCloud,
  Wand2,
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

type CreativeAssetRow = {
  path: string;
  category: string;
  library: string;
  type: string;
  id: string;
  title: string;
  tags: string[];
  source: string;
  project_id: string;
  workspace_path: string;
  scope: string;
  risk_level: string;
  asset_status: string;
  updated_at: string;
  preview: string;
};

type CreativeLibrary = {
  key: string;
  title: string;
  title_zh: string;
  description: string;
  description_zh: string;
  asset_types: string[];
  categories: string[];
  assets: CreativeAssetRow[];
};

type CreativeAssetCreateResult = {
  path: string;
  library: string;
  asset: Record<string, unknown>;
  validation: { ok: boolean; errors: string[] };
};

type StyleTrend = {
  project_id: string;
  count: number;
  average_score: number;
  latest_score: number;
  rows: Array<{
    path: string;
    id: string;
    title: string;
    target_draft_id: string;
    score: number;
    risk: string;
    drift_count: number;
    updated_at: string;
  }>;
};

type AnalysisReportRow = {
  path: string;
  id: string;
  type: string;
  title: string;
  source: string;
  project_id: string;
  workspace_path: string;
  copyright_risk: string;
  abstraction_level: string;
  use_in_generation_rag: boolean;
  created_assets: number;
  updated_at: string;
  summary: string;
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
  platform_profile_id?: string;
  platform_profile_path?: string;
  genre_market_profile_id?: string;
  genre_market_profile_path?: string;
  quality_standard_profile_id?: string;
  quality_standard_profile_path?: string;
  style_profile_id?: string;
  style_profile_path?: string;
  style_blend_preset_id?: string;
  style_blend_preset_path?: string;
  continuity_bible_id?: string;
  continuity_bible_path?: string;
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
  semantic_review?: {
    enabled?: boolean;
    ok?: boolean;
    score?: number;
    minimum_score?: number;
    provider?: string;
    model?: string;
    summary?: string;
    error?: string;
  };
  handoff_path: string;
  handoff_id: string;
  expected_output_type: string;
  expected_output_dir: string;
  output_path: string;
  output_id: string;
  actual_output_type: string;
};

type QdrantSearchResult = {
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

type MinioStatus = {
  configured: boolean;
  available?: boolean;
  bucket: string;
  error?: string;
  objects: Array<{ category: string; path: string; object_name: string; exists: boolean; size: number; etag: string; error: string }>;
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
type TabKey =
  | "workbench"
  | "projects"
  | "topic_library"
  | "material_library"
  | "knowledge_library"
  | "setting_bible"
  | "style_center"
  | "writing_templates"
  | "quality_standards"
  | "analysis_center"
  | "web_fiction_analysis"
  | "published_fiction_analysis"
  | "classic_literary_analysis"
  | "asset_converter"
  | "outline_generation"
  | "chapter_plan_generation"
  | "context_builder"
  | "chapter_production"
  | "ai_editor"
  | "review_center"
  | "originality_center"
  | "publishing_center"
  | "reader_feedback"
  | "production_control"
  | "change_impact"
  | "model_evaluation"
  | "data_statistics"
  | "settings_center"
  | "task_center"
  | "health"
  | "handoffs"
  | "studio"
  | "tasks"
  | "assets"
  | "batch"
  | "drafts"
  | "reviews";

type NavGroupKey = "workspace" | "assets" | "analysis" | "production" | "management";

const navGroups: Array<{ key: NavGroupKey; items: Array<{ key: TabKey; icon: ReactNode }> }> = [
  {
    key: "workspace",
    items: [
      { key: "workbench", icon: <Home size={17} /> },
      { key: "projects", icon: <Boxes size={17} /> }
    ]
  },
  {
    key: "assets",
    items: [
      { key: "topic_library", icon: <BookMarked size={17} /> },
      { key: "material_library", icon: <Library size={17} /> },
      { key: "knowledge_library", icon: <Database size={17} /> },
      { key: "setting_bible", icon: <BookOpen size={17} /> },
      { key: "style_center", icon: <Wand2 size={17} /> },
      { key: "writing_templates", icon: <PenLine size={17} /> },
      { key: "quality_standards", icon: <ShieldCheck size={17} /> }
    ]
  },
  {
    key: "analysis",
    items: [
      { key: "analysis_center", icon: <FileSearch size={17} /> },
      { key: "web_fiction_analysis", icon: <Layers3 size={17} /> },
      { key: "published_fiction_analysis", icon: <BookOpen size={17} /> },
      { key: "classic_literary_analysis", icon: <BookMarked size={17} /> },
      { key: "asset_converter", icon: <Workflow size={17} /> }
    ]
  },
  {
    key: "production",
    items: [
      { key: "outline_generation", icon: <GitPullRequest size={17} /> },
      { key: "chapter_plan_generation", icon: <ListChecks size={17} /> },
      { key: "context_builder", icon: <Network size={17} /> },
      { key: "chapter_production", icon: <PenLine size={17} /> },
      { key: "ai_editor", icon: <Save size={17} /> },
      { key: "review_center", icon: <CheckCircle2 size={17} /> },
      { key: "originality_center", icon: <ShieldCheck size={17} /> },
      { key: "publishing_center", icon: <Send size={17} /> },
      { key: "reader_feedback", icon: <MessageSquareText size={17} /> }
    ]
  },
  {
    key: "management",
    items: [
      { key: "production_control", icon: <Activity size={17} /> },
      { key: "change_impact", icon: <GitPullRequest size={17} /> },
      { key: "model_evaluation", icon: <SlidersHorizontal size={17} /> },
      { key: "data_statistics", icon: <BarChart3 size={17} /> },
      { key: "settings_center", icon: <Settings size={17} /> },
      { key: "task_center", icon: <ListChecks size={17} /> },
      { key: "handoffs", icon: <Workflow size={17} /> },
      { key: "health", icon: <Server size={17} /> }
    ]
  }
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
    nav: {
      workspace: "Workspace",
      assets: "Creative Assets",
      analysis: "Analysis",
      production: "Production",
      management: "Management Tools"
    },
    status: {
      localMode: "Local mode",
      dataSync: "Data sync",
      modelStatus: "Model",
      autosave: "Autosave",
      search: "Search project, asset, task",
      notifications: "Notifications",
      healthy: "ready",
      warning: "attention",
      offline: "offline"
    },
    tabs: {
      workbench: "Workbench",
      projects: "Projects",
      topic_library: "Topic Library",
      material_library: "Material Library",
      knowledge_library: "Knowledge Library",
      setting_bible: "Setting Bible",
      style_center: "Style Center",
      writing_templates: "Writing Templates",
      quality_standards: "Quality Standards",
      analysis_center: "Analysis Center",
      web_fiction_analysis: "Web Fiction Analysis",
      published_fiction_analysis: "Published Fiction Analysis",
      classic_literary_analysis: "Classic Literary Analysis",
      asset_converter: "Asset Converter",
      outline_generation: "Outline Generation",
      chapter_plan_generation: "Chapter Plan",
      context_builder: "Context Builder",
      chapter_production: "Chapter Production",
      ai_editor: "AI Editor",
      review_center: "Review Center",
      originality_center: "Originality Protection",
      publishing_center: "Publishing Center",
      reader_feedback: "Reader Feedback",
      production_control: "Production Control",
      change_impact: "Change Impact",
      model_evaluation: "Model Evaluation",
      data_statistics: "Data Statistics",
      settings_center: "Settings",
      task_center: "Task Center",
      health: "Health",
      handoffs: "Handoffs",
      studio: "Studio",
      tasks: "Tasks",
      assets: "Assets",
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
    nav: {
      workspace: "工作区",
      assets: "创作资产",
      analysis: "分析拆解",
      production: "生产流程",
      management: "管理工具"
    },
    status: {
      localMode: "本地模式",
      dataSync: "数据同步",
      modelStatus: "模型状态",
      autosave: "自动保存",
      search: "搜索项目、资产、任务",
      notifications: "通知",
      healthy: "就绪",
      warning: "需关注",
      offline: "离线"
    },
    tabs: {
      workbench: "工作台",
      projects: "项目",
      topic_library: "题材库",
      material_library: "素材库",
      knowledge_library: "知识库",
      setting_bible: "设定书",
      style_center: "文风中心",
      writing_templates: "写作模板",
      quality_standards: "精品标准",
      analysis_center: "分析拆解中心",
      web_fiction_analysis: "网文商业结构拆解",
      published_fiction_analysis: "出版小说技法拆解",
      classic_literary_analysis: "经典名著深度拆解",
      asset_converter: "资产转换器",
      outline_generation: "大纲生成",
      chapter_plan_generation: "细纲生成",
      context_builder: "上下文构建器",
      chapter_production: "章节生产",
      ai_editor: "AI 编辑器",
      review_center: "审稿中心",
      originality_center: "原创性保护中心",
      publishing_center: "发布中心",
      reader_feedback: "读者反馈中心",
      production_control: "生产总控中心",
      change_impact: "变更影响分析中心",
      model_evaluation: "模型评测中心",
      data_statistics: "数据统计",
      settings_center: "设置中心",
      task_center: "任务中心",
      health: "健康",
      handoffs: "执行包",
      studio: "创作台",
      tasks: "任务",
      assets: "资产",
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
  nav: Record<NavGroupKey, string>;
  status: {
    localMode: string;
    dataSync: string;
    modelStatus: string;
    autosave: string;
    search: string;
    notifications: string;
    healthy: string;
    warning: string;
    offline: string;
  };
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
  const [activeTab, setActiveTab] = useState<TabKey>("workbench");
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
  const [creativeLibraries, setCreativeLibraries] = useState<CreativeLibrary[]>([]);
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
  const [creativeAssetTitle, setCreativeAssetTitle] = useState("New creative asset");
  const [creativeAssetType, setCreativeAssetType] = useState("");
  const [creativeKeyword, setCreativeKeyword] = useState("");
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
  const [taskDateFrom, setTaskDateFrom] = useState("");
  const [taskDateTo, setTaskDateTo] = useState("");
  const [taskOffset, setTaskOffset] = useState(0);
  const [restorePath, setRestorePath] = useState("");
  const [qdrantQuery, setQdrantQuery] = useState("");
  const [qdrantResult, setQdrantResult] = useState<QdrantSearchResult | null>(null);
  const [minioStatus, setMinioStatus] = useState<MinioStatus | null>(null);
  const [styleTrend, setStyleTrend] = useState<StyleTrend | null>(null);
  const [analysisReports, setAnalysisReports] = useState<AnalysisReportRow[]>([]);
  const [analysisSourcePath, setAnalysisSourcePath] = useState("");
  const [analysisReportPath, setAnalysisReportPath] = useState("");
  const [analysisTargets, setAnalysisTargets] = useState("writing_template, material_card, review_rule_pack");
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
    status: "active",
    platform_profile_id: "",
    platform_profile_path: "",
    genre_market_profile_id: "",
    genre_market_profile_path: "",
    quality_standard_profile_id: "",
    quality_standard_profile_path: "",
    style_profile_id: "",
    style_profile_path: "",
    style_blend_preset_id: "",
    style_blend_preset_path: "",
    continuity_bible_id: "",
    continuity_bible_path: ""
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
    taskOverride?: { offset?: number; status?: string; taskType?: string; step?: string; dateFrom?: string; dateTo?: string }
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
      const effectiveDateFrom = taskOverride?.dateFrom ?? taskDateFrom;
      const effectiveDateTo = taskOverride?.dateTo ?? taskDateTo;
      const taskParams = new URLSearchParams({ limit: "80", offset: String(effectiveTaskOffset) });
      if (nextProjectId) taskParams.set("project_id", nextProjectId);
      if (effectiveTaskStatus) taskParams.set("status", effectiveTaskStatus);
      if (effectiveTaskType) taskParams.set("task_type", effectiveTaskType);
      if (effectiveTaskStep) taskParams.set("step", effectiveTaskStep);
      if (effectiveDateFrom) taskParams.set("date_from", effectiveDateFrom);
      if (effectiveDateTo) taskParams.set("date_to", effectiveDateTo);
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
      const creativeLibraryPath = nextProjectId
        ? `/product/libraries/creative?project_id=${encodeURIComponent(nextProjectId)}&limit_per_library=40`
        : "/product/libraries/creative?limit_per_library=40";
      const styleTrendPath = nextProjectId
        ? `/product/styles/trend?project_id=${encodeURIComponent(nextProjectId)}&limit=40`
        : "/product/styles/trend?limit=40";
      const analysisReportPath = nextProjectId
        ? `/product/analysis/reports?project_id=${encodeURIComponent(nextProjectId)}&limit=80`
        : "/product/analysis/reports?limit=80";
      const [taskData, assetData, draftData, batchData, handoffData, deadLetterData, githubSourceData, auditData, strictData, healthReport, backupRows, creativeLibraryData, styleTrendData, analysisReportData] = await Promise.all([
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
        fetchJson<BackupRow[]>("/product/system/backups?limit=20"),
        fetchJson<CreativeLibrary[]>(creativeLibraryPath),
        fetchJson<StyleTrend>(styleTrendPath),
        fetchJson<AnalysisReportRow[]>(analysisReportPath)
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
      setCreativeLibraries(creativeLibraryData);
      setStyleTrend(styleTrendData);
      setAnalysisReports(analysisReportData);
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
      setAnalysisSourcePath((current) => current || assetData[0]?.path || draftData.chapter_plans[0]?.path || "");
      setAnalysisReportPath((current) => current || analysisReportData[0]?.path || "");
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
      setActiveTab(tabForAssetType(String(detail.asset.type ?? "")));
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

  async function refreshCreativeLibrary(libraryKey: string, keywordOverride?: string) {
    const params = new URLSearchParams({ limit: "100" });
    if (selectedProjectId) params.set("project_id", selectedProjectId);
    const effectiveKeyword = keywordOverride ?? creativeKeyword;
    if (effectiveKeyword.trim()) params.set("keyword", effectiveKeyword.trim());
    const rows = await fetchJson<CreativeAssetRow[]>(`/product/libraries/creative/${encodeURIComponent(libraryKey)}?${params.toString()}`);
    setCreativeLibraries((current) =>
      current.map((library) => (library.key === libraryKey ? { ...library, assets: rows } : library))
    );
    return rows;
  }

  async function openAssetWithoutTabSwitch(path: string) {
    const [detail, versions, graph] = await Promise.all([
      fetchJson<AssetDetail>(`/product/assets/detail?path=${encodeURIComponent(path)}`),
      fetchJson<AssetVersions>(`/product/assets/versions?path=${encodeURIComponent(path)}`),
      fetchJson<AssetGraph>(`/product/assets/graph?path=${encodeURIComponent(path)}&depth=1`)
    ]);
    setAssetDetail(detail);
    setAssetVersions(versions);
    setAssetGraph(graph);
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
    if (taskDateFrom) params.set("date_from", taskDateFrom);
    if (taskDateTo) params.set("date_to", taskDateTo);
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
  }, [selectedProjectId, taskOffset, taskStatusFilter, taskTypeFilter, taskStepFilter, taskDateFrom, taskDateTo]);

  const selectedProject = projects.find((project) => project.project_id === selectedProjectId);
  const pageTitle = text.tabs[activeTab];
  const pageSubtitle = pageSummary(activeTab, language);
  const notificationCount =
    (projectHealth?.summary.failed_task_count ?? 0) +
    (projectHealth?.summary.pending_handoff_count ?? 0) +
    (projectHealth?.summary.scope_issue_count ?? 0) +
    (projectHealth?.summary.dead_letter_count ?? 0);
  const dataSyncOk = Boolean(postgresStrict?.ready && !scopeAudit?.summary.issue_count);
  const modelOk = Boolean(projectHealth?.embedding?.ok);
  const autosaveOk = Boolean(draftEditor || selectedDraft || !selectedProjectId);
  const activeCreativeLibraryKey = creativeLibraryKeyForTab(activeTab);
  const activeCreativeLibrary = activeCreativeLibraryKey
    ? creativeLibraries.find((library) => library.key === activeCreativeLibraryKey)
    : null;
  const analysisTabs: TabKey[] = ["analysis_center", "web_fiction_analysis", "published_fiction_analysis", "classic_literary_analysis", "asset_converter"];
  const batchTabs: TabKey[] = ["batch"];
  const draftTabs: TabKey[] = ["chapter_production", "ai_editor", "drafts"];
  const reviewTabs: TabKey[] = ["review_center", "reviews"];
  const placeholderTabs: TabKey[] = [
    "writing_templates",
    "outline_generation",
    "chapter_plan_generation",
    "context_builder",
    "reader_feedback",
    "production_control",
    "change_impact",
    "model_evaluation",
    "data_statistics",
    "settings_center"
  ];

  return (
    <main className="factoryShell">
      <aside className="factorySidebar" aria-label={language === "zh" ? "小说工厂导航" : "Novel factory navigation"}>
        <div className="factoryBrand">
          <p className="eyebrow">Novel Forge V6/V7</p>
          <h1>{text.title}</h1>
          <span className="localModeBadge">{text.status.localMode}</span>
        </div>

        <div className="projectBadge">
          <span>{language === "zh" ? "当前项目" : "Current Project"}</span>
          <strong>{selectedProject?.title || (language === "zh" ? "未选择项目" : "No project selected")}</strong>
          <small>{selectedWorkspace || selectedProjectId || "local workspace"}</small>
        </div>

        <nav className="sidebarNav">
          {navGroups.map((group) => (
            <div className="navGroup" key={group.key}>
              <p>{text.nav[group.key]}</p>
              {group.items.map((item) => (
                <button
                  key={item.key}
                  className={activeTab === item.key ? "navItem active" : "navItem"}
                  onClick={() => setActiveTab(item.key)}
                >
                  {item.icon}
                  <span>{text.tabs[item.key]}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <section className="factoryWorkspace">
        <header className="factoryTopbar">
          <div className="statusStrip" aria-label={language === "zh" ? "系统状态" : "System status"}>
            <span className="statusPill ok">{text.status.localMode}</span>
            <span className={dataSyncOk ? "statusPill ok" : "statusPill warn"}>
              {text.status.dataSync}: {dataSyncOk ? text.status.healthy : text.status.warning}
            </span>
            <span className={modelOk ? "statusPill ok" : "statusPill warn"}>
              {text.status.modelStatus}: {modelOk ? text.status.healthy : text.status.warning}
            </span>
            <span className={autosaveOk ? "statusPill ok" : "statusPill muted"}>
              {text.status.autosave}: {autosaveOk ? text.status.healthy : text.status.offline}
            </span>
          </div>
          <div className="topbarTools">
            <form
              className="globalSearch"
              onSubmit={(event) => {
                setActiveTab("material_library");
                searchAssets(event);
              }}
            >
              <Search size={17} />
              <input
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder={text.status.search}
                aria-label={text.status.search}
              />
            </form>
            <span className={notificationCount ? "notificationPill warn" : "notificationPill"}>
              {text.status.notifications}: {notificationCount}
            </span>
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

        <section className="factoryPageHeader">
          <div>
            <p className="eyebrow">{language === "zh" ? "个人本地小说工厂" : "Personal Local Novel Factory"}</p>
            <h2>{pageTitle}</h2>
            <p>{pageSubtitle}</p>
          </div>
          <div className="pageHeaderMeta">
            <span className="statPill">{projectConfig.genre || (language === "zh" ? "题材未设" : "genre unset")}</span>
            <span className="statPill">{projectConfig.target_platform || (language === "zh" ? "平台未设" : "platform unset")}</span>
          </div>
        </section>

        <section className="summaryBand factoryMetrics">
          <Metric label={text.metrics.assets} value={String(totalAssets)} />
          <Metric label={text.metrics.projects} value={String(projects.length)} />
          <Metric label={text.metrics.tasks} value={String(taskCenter?.summary.task_count ?? 0)} />
          <Metric label={text.metrics.api} value={API_BASE} code />
        </section>

        {notice ? <div className="noticeLine">{notice}</div> : null}
        {error ? <div className="errorLine">{error}</div> : null}

        <div className="factoryPageBody">
      {activeTab === "workbench" || activeTab === "studio" ? (
        <StudioPanel
          language={language}
          projects={projects}
          selectedProjectId={selectedProjectId}
          selectedWorkspace={selectedWorkspace}
          projectConfig={projectConfig}
          drafts={drafts}
          selectedPlan={selectedPlan}
          setSelectedPlan={setSelectedPlan}
          selectedDraft={selectedDraft}
          setSelectedDraft={setSelectedDraft}
          draftEditor={draftEditor}
          setDraftEditor={setDraftEditor}
          draftExport={draftExport}
          assets={assets}
          batchItems={batchItems}
          handoffs={handoffs}
          taskCenter={taskCenter}
          taskControl={taskControl}
          projectHealth={projectHealth}
          githubSources={githubSources}
          uploadResult={uploadResult}
          busy={busy}
          onGenerateDraft={() =>
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
          onOpenHandoff={selectHandoff}
          onOpenTab={setActiveTab}
        />
      ) : null}

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
          creativeLibraries={creativeLibraries}
          busy={busy}
          onCreate={() =>
            runAction(
              () =>
                postJson("/product/projects", {
                  title: projectTitle,
                  series_title: seriesTitle || null,
                  book_number: bookNumber ? Number(bookNumber) : null,
                  platform_profile_path: projectConfig.platform_profile_path || null,
                  genre_market_profile_path: projectConfig.genre_market_profile_path || null,
                  quality_standard_profile_path: projectConfig.quality_standard_profile_path || null,
                  style_profile_path: projectConfig.style_profile_path || null,
                  continuity_bible_path: projectConfig.continuity_bible_path || null
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
          qdrantQuery={qdrantQuery}
          setQdrantQuery={setQdrantQuery}
          qdrantResult={qdrantResult}
          minioStatus={minioStatus}
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
          onArchiveEvents={() =>
            runAction(
              () => postJson("/product/system/events/archive", { keep_latest: 500, confirm: true }),
              "task events archived"
            )
          }
          onQdrantIndex={() =>
            runAction(
              () => postJson("/product/qdrant/index", { batch_size: 32 }),
              "qdrant index rebuilt"
            )
          }
          onQdrantSearch={() =>
            runAction(async () => {
              const result = await postJson("/product/qdrant/search", {
                query: qdrantQuery,
                project_id: selectedProjectId || null,
                limit: 12
              }) as QdrantSearchResult;
              setQdrantResult(result);
              return result;
            }, "qdrant search")
          }
          onMinioSync={() =>
            runAction(
              () => postJson("/product/minio/sync", {}),
              "minio synced"
            )
          }
          onRefreshMinio={() =>
            runAction(async () => {
              const status = await fetchJson<MinioStatus>("/product/minio/objects?limit=40");
              setMinioStatus(status);
              return status;
            }, "minio status")
          }
          onOpenAsset={selectAsset}
          busy={busy}
        />
      ) : null}

      {activeTab === "task_center" || activeTab === "tasks" ? (
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
          dateFrom={taskDateFrom}
          setDateFrom={setTaskDateFrom}
          dateTo={taskDateTo}
          setDateTo={setTaskDateTo}
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

      {activeCreativeLibraryKey ? (
        <CreativeLibraryPanel
          language={language}
          library={activeCreativeLibrary}
          fallbackLibraryKey={activeCreativeLibraryKey}
          selectedProjectId={selectedProjectId}
          selectedWorkspace={selectedWorkspace}
          createTitle={creativeAssetTitle}
          setCreateTitle={setCreativeAssetTitle}
          createType={creativeAssetType}
          setCreateType={setCreativeAssetType}
          keyword={creativeKeyword}
          setKeyword={setCreativeKeyword}
          detail={assetDetail}
          versions={assetVersions}
          graph={assetGraph}
          selectedDraft={selectedDraft}
          styleTrend={styleTrend}
          busy={busy}
          onSelect={selectAsset}
          onRefresh={(libraryKey, keywordValue) =>
            runAction(
              () => refreshCreativeLibrary(libraryKey, keywordValue),
              "creative library refreshed"
            )
          }
          onCreate={(assetType, title) =>
            runAction(async () => {
              const created = await postJson("/product/creative-assets", {
                asset_type: assetType,
                title,
                project_id: selectedProjectId || null,
                workspace_path: selectedWorkspace || null,
                scope: selectedProjectId ? "project" : "global"
              }) as CreativeAssetCreateResult;
              await refreshCreativeLibrary(created.library);
              await openAssetWithoutTabSwitch(created.path);
              return created;
            }, "creative asset created")
          }
          onSave={(path, patch) =>
            runAction(async () => {
              const updated = await fetchJson<AssetDetail>("/product/assets/detail", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path, ...patch })
              });
              setAssetDetail(updated);
              if (activeCreativeLibraryKey) await refreshCreativeLibrary(activeCreativeLibraryKey);
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
              if (activeCreativeLibraryKey) await refreshCreativeLibrary(activeCreativeLibraryKey);
              return updated;
            }, "asset content saved")
          }
          onSaveTyped={(path, fields) =>
            runAction(async () => {
              const updated = await fetchJson<AssetDetail>("/product/assets/typed", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path, fields })
              });
              setAssetDetail(updated);
              if (activeCreativeLibraryKey) await refreshCreativeLibrary(activeCreativeLibraryKey);
              return updated;
            }, "typed asset saved")
          }
          onStyleDecompose={(sourcePath) =>
            runAction(async () => {
              const created = await postJson("/product/styles/decompose", {
                source_path: sourcePath,
                workspace_path: selectedWorkspace || null
              }) as { path: string };
              await refreshCreativeLibrary("style_center");
              await openAssetWithoutTabSwitch(created.path);
              return created;
            }, "style decomposed")
          }
          onStyleReview={(draftPath, styleProfilePath) =>
            runAction(async () => {
              const created = await postJson("/product/styles/review", {
                draft_path: draftPath,
                style_profile_path: styleProfilePath || null,
                workspace_path: selectedWorkspace || null
              }) as { path: string };
              await refreshCreativeLibrary("style_center");
              await openAssetWithoutTabSwitch(created.path);
              const trendPath = selectedProjectId
                ? `/product/styles/trend?project_id=${encodeURIComponent(selectedProjectId)}&limit=40`
                : "/product/styles/trend?limit=40";
              setStyleTrend(await fetchJson<StyleTrend>(trendPath));
              return created;
            }, "style reviewed")
          }
          onQualityScore={(targetPath) =>
            runAction(async () => {
              const created = await postJson("/product/quality/score", {
                target_path: targetPath,
                workspace_path: selectedWorkspace || null
              }) as { path: string };
              await refreshCreativeLibrary("quality_standards");
              await openAssetWithoutTabSwitch(created.path);
              return created;
            }, "quality scored")
          }
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
          onSaveTyped={(path, fields) =>
            runAction(async () => {
              const updated = await fetchJson<AssetDetail>("/product/assets/typed", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path, fields })
              });
              setAssetDetail(updated);
              return updated;
            }, "typed asset saved")
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

      {analysisTabs.includes(activeTab) ? (
        <AnalysisPanel
          language={language}
          tab={activeTab}
          reports={analysisReports}
          assets={assets}
          handoffs={handoffs}
          sourcePath={analysisSourcePath}
          setSourcePath={setAnalysisSourcePath}
          reportPath={analysisReportPath}
          setReportPath={setAnalysisReportPath}
          targets={analysisTargets}
          setTargets={setAnalysisTargets}
          busy={busy}
          onRunAnalysis={(analysisType) =>
            runAction(async () => {
              const created = await postJson("/product/analysis/run", {
                source_path: analysisSourcePath,
                analysis_type: analysisType,
                workspace_path: selectedWorkspace || null
              }) as { path: string };
              setAnalysisReportPath(created.path);
              await openAssetWithoutTabSwitch(created.path);
              return created;
            }, "analysis report created")
          }
          onCreateHandoff={(analysisType) =>
            runAction(async () => {
              const created = await postJson("/product/analysis/handoff", {
                input_path: analysisSourcePath,
                analysis_type: analysisType,
                workspace_path: selectedWorkspace || null,
                purpose: pageSummary(activeTab, language)
              }) as { path: string; asset?: Record<string, unknown> };
              if (created.path) {
                await selectHandoff(created.path);
              }
              return created;
            }, "analysis handoff created")
          }
          onConvert={(reportPathOverride) =>
            runAction(async () => {
              const converted = await postJson("/product/analysis/convert", {
                report_path: reportPathOverride || analysisReportPath,
                targets: analysisTargets
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean),
                workspace_path: selectedWorkspace || null,
                reuse_scope: selectedProjectId ? "project" : "global"
              }) as { path: string; created_assets?: Array<{ path: string }> };
              await openAssetWithoutTabSwitch(converted.path);
              return converted;
            }, "analysis converted")
          }
          onOpenAsset={selectAsset}
          onOpenHandoff={selectHandoff}
        />
      ) : null}

      {batchTabs.includes(activeTab) ? (
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

      {draftTabs.includes(activeTab) ? (
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

      {reviewTabs.includes(activeTab) ? (
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
      {activeTab === "originality_center" || activeTab === "publishing_center" ? (
        <QualityGatePanel
          language={language}
          mode={activeTab}
          assets={assets}
          drafts={drafts}
          selectedDraft={selectedDraft}
          setSelectedDraft={setSelectedDraft}
          selectedWorkspace={selectedWorkspace}
          setSelectedWorkspace={setSelectedWorkspace}
          busy={busy}
          onRunOriginality={() =>
            runAction(async () => {
              const created = (await postJson("/product/audits/originality", {
                draft_path: selectedDraft,
                workspace_path: selectedWorkspace || null
              })) as { path?: string; originality_report_path?: string };
              if (created.path || created.originality_report_path) {
                await openAssetWithoutTabSwitch(String(created.path || created.originality_report_path));
              }
              return created;
            }, "originality report")
          }
          onRunChapterAudit={() =>
            runAction(async () => {
              const created = (await postJson("/product/audits/chapter", {
                draft_path: selectedDraft,
                workspace_path: selectedWorkspace || null
              })) as { path?: string; chapter_audit_path?: string };
              if (created.path || created.chapter_audit_path) {
                await openAssetWithoutTabSwitch(String(created.path || created.chapter_audit_path));
              }
              return created;
            }, "chapter audit")
          }
          onRunPublishGate={() =>
            runAction(async () => {
              const created = (await postJson("/product/publishing/gate", {
                draft_path: selectedDraft,
                workspace_path: selectedWorkspace || null,
                human_override: false
              })) as { path?: string; publish_gate_report_path?: string };
              if (created.path || created.publish_gate_report_path) {
                await openAssetWithoutTabSwitch(String(created.path || created.publish_gate_report_path));
              }
              return created;
            }, "publish gate")
          }
          onCreateReleasePackage={() =>
            runAction(async () => {
              const created = (await postJson("/product/publishing/release-package", {
                draft_path: selectedDraft,
                workspace_path: selectedWorkspace || null,
                channel: "local",
                human_override: false
              })) as { path?: string; release_package_path?: string };
              if (created.path || created.release_package_path) {
                await openAssetWithoutTabSwitch(String(created.path || created.release_package_path));
              }
              return created;
            }, "release package")
          }
          onOpenAsset={selectAsset}
        />
      ) : null}
          {placeholderTabs.includes(activeTab) ? (
            <FactoryPlaceholderPage
              language={language}
              tab={activeTab}
              assets={assets}
              projects={projects}
              taskCenter={taskCenter}
              taskControl={taskControl}
              projectHealth={projectHealth}
              drafts={drafts}
              handoffs={handoffs}
              batchItems={batchItems}
              onOpenTab={setActiveTab}
            />
          ) : null}
        </div>
      </section>
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

function creativeLibraryKeyForTab(tab: TabKey): string | null {
  const mapping: Partial<Record<TabKey, string>> = {
    topic_library: "topic_library",
    material_library: "material_library",
    knowledge_library: "knowledge_library",
    setting_bible: "setting_bible",
    style_center: "style_center",
    quality_standards: "quality_standards"
  };
  return mapping[tab] ?? null;
}

function tabForAssetType(assetType: string): TabKey {
  if (["platform_profile", "genre_market_profile", "topic_seed", "topic_fit_report"].includes(assetType)) {
    return "topic_library";
  }
  if (["material_card", "asset_collection", "writing_template", "craft_template"].includes(assetType)) {
    return "material_library";
  }
  if (assetType === "knowledge_card") {
    return "knowledge_library";
  }
  if (["world_bible", "character_card", "continuity_bible", "foreshadowing_thread", "power_scale_rule"].includes(assetType)) {
    return "setting_bible";
  }
  if (["style_profile", "style_decomposition_report", "style_blend_preset", "style_review_report"].includes(assetType)) {
    return "style_center";
  }
  if (["quality_standard_profile", "review_rule_pack", "quality_score_report"].includes(assetType)) {
    return "quality_standards";
  }
  if (assetType === "originality_report") {
    return "originality_center";
  }
  if (["publish_gate_report", "release_package"].includes(assetType)) {
    return "publishing_center";
  }
  if (["draft_chapter"].includes(assetType)) {
    return "chapter_production";
  }
  if (["review_report", "revision_plan", "chapter_audit_report"].includes(assetType)) {
    return "review_center";
  }
  if (assetType === "web_fiction_business_analysis_report" || assetType === "common_novel_analysis_report") {
    return "web_fiction_analysis";
  }
  if (assetType === "published_fiction_analysis_report") {
    return "published_fiction_analysis";
  }
  if (assetType === "classic_literary_analysis_report") {
    return "classic_literary_analysis";
  }
  if (assetType === "analysis_conversion_report") {
    return "asset_converter";
  }
  if (["task_status", "task_dead_letter", "workflow_run", "batch_task_item"].includes(assetType)) {
    return "task_center";
  }
  if (assetType === "claude_code_handoff") {
    return "handoffs";
  }
  return "material_library";
}

function pageSummary(tab: TabKey, language: Language): string {
  const zh = language === "zh";
  const summaries: Record<TabKey, string> = {
    workbench: zh ? "阅读、改稿、生成链路、资料来源和 Agent 工作观察集中在一个工作面。" : "Read, edit, trace generation, inspect sources, and observe agent work in one surface.",
    projects: zh ? "管理本地项目生命周期、配置、项目隔离和系列信息。" : "Manage local project lifecycle, configuration, project scope, and series structure.",
    topic_library: zh ? "沉淀题材、平台适配、商业潜力和选题风险。" : "Track genre ideas, platform fit, market potential, and topic risks.",
    material_library: zh ? "管理可复用素材卡、拆解转化资产和任务输入集。" : "Manage reusable material cards, converted analysis assets, and task input sets.",
    knowledge_library: zh ? "区分 GitHub、多学科、本地上传和项目内知识卡来源。" : "Separate GitHub, multidisciplinary, local upload, and project knowledge sources.",
    setting_bible: zh ? "承载世界观、人物、时间线、伏笔、战力和长期连续性资产。" : "Hold worldview, characters, timelines, foreshadowing, power scale, and continuity assets.",
    style_center: zh ? "用参数化文风资产控制表达，不做具体作者模仿。" : "Control prose with parameterized style assets without imitating specific authors.",
    writing_templates: zh ? "管理冲突、节奏、章节钩子、修辞和可复用写作模板。" : "Manage conflict, pacing, chapter hook, rhetoric, and reusable craft templates.",
    quality_standards: zh ? "沉淀精品标准、审稿规则包和质量门禁依据。" : "Store quality standards, review rule packs, and gate criteria.",
    analysis_center: zh ? "统一观察导入、拆解、handoff、知识化和素材化流程。" : "Observe import, analysis, handoff, knowledge extraction, and material conversion.",
    web_fiction_analysis: zh ? "面向网文商业结构、爽点、钩子、节奏和人设机制拆解。" : "Analyze web fiction structure, payoffs, hooks, pacing, and character mechanics.",
    published_fiction_analysis: zh ? "面向出版小说技法、场景经营、叙事结构和角色弧光拆解。" : "Analyze published-fiction craft, scene design, narrative structure, and arcs.",
    classic_literary_analysis: zh ? "面向经典名著的主题、人物、结构和可抽象技法拆解。" : "Analyze classics for theme, character, structure, and abstract craft.",
    asset_converter: zh ? "把拆解报告转换为可复用、可审计、带版权边界的资产。" : "Convert analysis reports into reusable, auditable assets with copyright boundaries.",
    outline_generation: zh ? "规划长纲版本、分卷结构、冲突升级链和目标读者承诺。" : "Plan outline versions, volume arcs, conflict escalation, and reader promises.",
    chapter_plan_generation: zh ? "管理章节目标、信息点、钩子、冲突和字数预算。" : "Manage chapter goals, information beats, hooks, conflicts, and word budgets.",
    context_builder: zh ? "构建人物、世界观、前文摘要、知识卡、伏笔和素材卡上下文。" : "Build context from characters, worldview, recaps, knowledge cards, foreshadowing, and materials.",
    chapter_production: zh ? "生成、编辑、保存、导出章节正文并保留版本记录。" : "Generate, edit, save, export, and version chapter drafts.",
    ai_editor: zh ? "面向段落级修订、diff、回滚和人工确认的编辑入口。" : "Entry for paragraph edits, diffs, rollback, and human confirmation.",
    review_center: zh ? "执行章节审稿、评分、问题状态、修订计划和修订前后对比。" : "Run chapter review, scoring, issue states, revision plans, and comparisons.",
    originality_center: zh ? "观察原创性风险、来源边界、抽象层级和发布前风险。" : "Observe originality risk, source boundaries, abstraction level, and pre-release risk.",
    publishing_center: zh ? "管理发布门禁、导出稿件、平台检查和发布记录。" : "Manage publish gates, exports, platform checks, and release logs.",
    reader_feedback: zh ? "导入评论反馈，识别爽点、毒点、期待和后续调整建议。" : "Import reader feedback and identify payoffs, pain points, expectations, and adjustments.",
    production_control: zh ? "观察生产任务、队列压力、失败恢复、worker 和 dead-letter。" : "Observe production tasks, queue pressure, recovery, workers, and dead letters.",
    change_impact: zh ? "追踪设定、角色、大纲或章节变更对后续资产的影响。" : "Track impact from setting, character, outline, or chapter changes.",
    model_evaluation: zh ? "比较模型在拆解、知识、正文、审稿和编辑任务上的质量与成本。" : "Compare model quality and cost across analysis, knowledge, drafting, review, and editing.",
    data_statistics: zh ? "查看产能、质量趋势、失败率、审稿通过率和成本指标。" : "Inspect throughput, quality trend, failure rate, review pass rate, and cost metrics.",
    settings_center: zh ? "管理本地模型、提示词、平台规则、审稿规则和存储配置。" : "Manage local models, prompts, platform rules, review rules, and storage configuration.",
    task_center: zh ? "查看最新状态、事件日志、失败恢复、批量重跑和队列状态。" : "View latest status, event logs, recovery, batch retry, and queue state.",
    health: zh ? "检查 Postgres、Redis/Celery、Qdrant、MinIO、备份和项目健康。" : "Check Postgres, Redis/Celery, Qdrant, MinIO, backups, and project health.",
    handoffs: zh ? "生成、验收、绑定 Claude Code/Codex 执行包和人工 gate。" : "Create, accept, bind, and gate Claude Code/Codex handoffs.",
    studio: zh ? "阅读、改稿、生成链路、资料来源和 Agent 工作观察集中在一个工作面。" : "Read, edit, trace generation, inspect sources, and observe agent work in one surface.",
    tasks: zh ? "查看最新状态、事件日志、失败恢复、批量重跑和队列状态。" : "View latest status, event logs, recovery, batch retry, and queue state.",
    assets: zh ? "管理可复用素材卡、拆解转化资产和任务输入集。" : "Manage reusable material cards, converted analysis assets, and task input sets.",
    batch: zh ? "面向网文商业结构、爽点、钩子、节奏和人设机制拆解。" : "Analyze web fiction structure, payoffs, hooks, pacing, and character mechanics.",
    drafts: zh ? "生成、编辑、保存、导出章节正文并保留版本记录。" : "Generate, edit, save, export, and version chapter drafts.",
    reviews: zh ? "执行章节审稿、评分、问题状态、修订计划和修订前后对比。" : "Run chapter review, scoring, issue states, revision plans, and comparisons."
  };
  return summaries[tab];
}

function FactoryPlaceholderPage(props: {
  language: Language;
  tab: TabKey;
  assets: AssetRow[];
  projects: ProjectRow[];
  taskCenter: TaskCenter | null;
  taskControl: TaskControl | null;
  projectHealth: ProjectHealthReport | null;
  drafts: DraftWorkbench | null;
  handoffs: HandoffRow[];
  batchItems: BatchItem[];
  onOpenTab: (tab: TabKey) => void;
}) {
  const zh = props.language === "zh";
  const title = copy[props.language].tabs[props.tab];
  const matchingAssets = props.assets.filter((asset) => assetMatchesPage(props.tab, asset)).slice(0, 12);
  const failedCount = props.projectHealth?.summary.failed_task_count ?? props.taskCenter?.summary.by_status.failed ?? 0;
  const activeQueue = props.taskControl?.celery.active_count ?? 0;
  const handoffCount = props.projectHealth?.summary.pending_handoff_count ?? props.handoffs.filter((item) => item.status !== "completed").length;
  const actions = placeholderActions(props.tab, zh);

  return (
    <section className="placeholderPage">
      <div className="panel placeholderHero">
        <div>
          <p className="eyebrow">{zh ? "V6/V7 工作台入口" : "V6/V7 workspace entry"}</p>
          <h2>{title}</h2>
          <p>{pageSummary(props.tab, props.language)}</p>
        </div>
        <div className="placeholderActions">
          {actions.map((action) => (
            <button className={action.primary ? "primaryButton" : "secondaryButton"} key={action.label} onClick={() => props.onOpenTab(action.tab)}>
              {action.icon}
              {action.label}
            </button>
          ))}
        </div>
      </div>

      <div className="placeholderGrid">
        <div className="placeholderMetric panel">
          <span>{zh ? "相关资产" : "Related assets"}</span>
          <strong>{matchingAssets.length}</strong>
        </div>
        <div className="placeholderMetric panel">
          <span>{zh ? "任务失败" : "Failed tasks"}</span>
          <strong>{failedCount}</strong>
        </div>
        <div className="placeholderMetric panel">
          <span>{zh ? "活跃队列" : "Active queue"}</span>
          <strong>{activeQueue}</strong>
        </div>
        <div className="placeholderMetric panel">
          <span>Handoff</span>
          <strong>{handoffCount}</strong>
        </div>
      </div>

      <div className="splitGrid">
        <div className="panel">
          <PanelHeader title={zh ? "资产命中" : "Asset Matches"} icon={<FileSearch size={18} />} />
          <DataTable
            emptyText={zh ? "暂无匹配资产" : "No matching assets"}
            columns={zh ? ["类型", "标题", "来源/状态", "路径"] : ["Type", "Title", "Source/Status", "Path"]}
            rows={matchingAssets.map((asset) => [
              asset.type || asset.category,
              asset.title || asset.path,
              asset.source || asset.asset_status || asset.risk_level || "-",
              asset.path
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title={zh ? "当前生产状态" : "Production State"} icon={<Activity size={18} />} />
          <DataTable
            emptyText={zh ? "暂无状态" : "No state"}
            columns={zh ? ["项目", "数量", "状态"] : ["Item", "Count", "Status"]}
            rows={[
              [zh ? "项目" : "Projects", props.projects.length, props.projects[0]?.status || "-"],
              [zh ? "批处理 item" : "Batch items", props.batchItems.length, props.batchItems.some((item) => item.status === "failed") ? "attention" : "ready"],
              [zh ? "草稿" : "Drafts", props.drafts?.drafts.length ?? 0, props.drafts?.drafts[0]?.title || "-"],
              [zh ? "最近事件" : "Recent events", props.taskCenter?.timeline.events.length ?? 0, props.taskCenter?.timeline.summary.latest_at || "-"]
            ]}
          />
        </div>
      </div>
    </section>
  );
}

function placeholderActions(tab: TabKey, zh: boolean): Array<{ label: string; tab: TabKey; icon: ReactNode; primary?: boolean }> {
  if (["topic_library", "setting_bible", "style_center", "writing_templates", "quality_standards"].includes(tab)) {
    return [
      { label: zh ? "打开资产工作台" : "Open Assets", tab: "material_library", icon: <FileSearch size={18} />, primary: true },
      { label: zh ? "进入审稿中心" : "Review Center", tab: "review_center", icon: <CheckCircle2 size={18} /> }
    ];
  }
  if (["published_fiction_analysis", "classic_literary_analysis", "asset_converter"].includes(tab)) {
    return [
      { label: zh ? "进入拆解中心" : "Analysis Center", tab: "analysis_center", icon: <Layers3 size={18} />, primary: true },
      { label: zh ? "打开 Handoff" : "Open Handoffs", tab: "handoffs", icon: <Workflow size={18} /> }
    ];
  }
  if (["outline_generation", "chapter_plan_generation", "context_builder"].includes(tab)) {
    return [
      { label: zh ? "进入章节生产" : "Chapter Production", tab: "chapter_production", icon: <PenLine size={18} />, primary: true },
      { label: zh ? "打开任务中心" : "Task Center", tab: "task_center", icon: <ListChecks size={18} /> }
    ];
  }
  if (["originality_center", "publishing_center", "reader_feedback"].includes(tab)) {
    return [
      { label: zh ? "进入审稿中心" : "Review Center", tab: "review_center", icon: <CheckCircle2 size={18} />, primary: true },
      { label: zh ? "进入章节生产" : "Chapter Production", tab: "chapter_production", icon: <PenLine size={18} /> }
    ];
  }
  return [
    { label: zh ? "打开任务中心" : "Task Center", tab: "task_center", icon: <ListChecks size={18} />, primary: true },
    { label: zh ? "检查健康页" : "Open Health", tab: "health", icon: <Activity size={18} /> }
  ];
}

function assetMatchesPage(tab: TabKey, asset: AssetRow): boolean {
  const haystack = `${asset.type} ${asset.category} ${asset.title} ${asset.source} ${asset.tags.join(" ")}`.toLowerCase();
  const needles: Partial<Record<TabKey, string[]>> = {
    topic_library: ["topic", "genre", "market", "platform_profile"],
    setting_bible: ["world", "character", "continuity", "foreshadowing", "power", "timeline"],
    style_center: ["style"],
    writing_templates: ["template", "craft", "rhetoric", "hook", "conflict"],
    quality_standards: ["quality", "standard", "rubric", "review_rule"],
    analysis_center: ["analysis_report", "analysis", "deconstruction", "conversion"],
    web_fiction_analysis: ["web_fiction_business_analysis_report", "common_novel_analysis_report", "web", "decomposition"],
    published_fiction_analysis: ["published_fiction_analysis_report", "published", "craft_analysis"],
    classic_literary_analysis: ["classic_literary_analysis_report", "classic", "literary"],
    asset_converter: ["analysis_conversion_report", "conversion", "converted", "material_card", "knowledge_card"],
    outline_generation: ["outline", "long_outline"],
    chapter_plan_generation: ["chapter_plan", "detailed_outline"],
    context_builder: ["context", "rag", "summary", "knowledge_card", "material_card"],
    originality_center: ["originality", "originality_report", "copyright", "risk"],
    publishing_center: ["publish", "publish_gate_report", "release_package", "release", "export"],
    reader_feedback: ["feedback", "reader", "sentiment", "comment"],
    production_control: ["task", "workflow", "batch_item"],
    change_impact: ["impact", "lineage", "graph"],
    model_evaluation: ["model", "benchmark", "prompt"],
    data_statistics: ["metric", "snapshot", "report"],
    settings_center: ["profile", "config", "rule"]
  };
  const pageNeedles = needles[tab] ?? [];
  return pageNeedles.some((needle) => haystack.includes(needle));
}

function StudioPanel(props: {
  language: Language;
  projects: ProjectRow[];
  selectedProjectId: string;
  selectedWorkspace: string;
  projectConfig: ProjectConfig;
  drafts: DraftWorkbench | null;
  selectedPlan: string;
  setSelectedPlan: (value: string) => void;
  selectedDraft: string;
  setSelectedDraft: (value: string) => void;
  draftEditor: DraftEditorState | null;
  setDraftEditor: (value: DraftEditorState | null) => void;
  draftExport: Record<string, unknown> | null;
  assets: AssetRow[];
  batchItems: BatchItem[];
  handoffs: HandoffRow[];
  taskCenter: TaskCenter | null;
  taskControl: TaskControl | null;
  projectHealth: ProjectHealthReport | null;
  githubSources: GitHubSource[];
  uploadResult: UploadResult | null;
  busy: boolean;
  onGenerateDraft: () => void;
  onSaveDraft: () => void;
  onExportDraft: (format: string) => void;
  onOpenAsset: (path: string) => void;
  onOpenHandoff: (path: string) => void;
  onOpenTab: (tab: TabKey) => void;
}) {
  const zh = props.language === "zh";
  const project = props.projects.find((item) => item.project_id === props.selectedProjectId);
  const draftRows = props.drafts?.drafts ?? [];
  const currentDraftRow = draftRows.find((item) => item.path === props.selectedDraft) ?? draftRows[0];
  const draftText = props.draftEditor?.text ?? "";
  const paragraphs = draftText.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const sourceRows = buildStudioSourceRows(props.assets, props.batchItems, props.handoffs, props.githubSources, props.uploadResult, zh);
  const decompositionRows = props.assets.filter((asset) => asset.type === "decomposition_report" || asset.category === "decompositions");
  const knowledgeRows = props.assets.filter((asset) => asset.type === "knowledge_card" || asset.category === "knowledge");
  const githubKnowledgeRows = knowledgeRows.filter((asset) => knowledgeOrigin(asset, props.handoffs, props.batchItems) === "github");
  const localKnowledgeRows = knowledgeRows.filter((asset) => knowledgeOrigin(asset, props.handoffs, props.batchItems) !== "github");
  const materialRows = props.assets.filter((asset) => asset.type === "material_card" || asset.category === "materials");
  const productionSteps = buildProductionSteps(props.assets, props.batchItems, props.handoffs, props.drafts, props.taskCenter, zh);
  const agentRows = buildAgentWorkRows(props.assets, props.batchItems, props.handoffs, props.drafts, props.taskCenter, props.taskControl, props.projectHealth, zh);
  const latestEvents = (props.taskCenter?.timeline.events ?? []).slice(0, 12);

  return (
    <section className="studioPage">
      <div className="studioHeader panel">
        <div>
          <p className="eyebrow">{zh ? "小说生产驾驶舱" : "Novel Production Studio"}</p>
          <h2>{project?.title || (zh ? "未选择项目" : "No Project Selected")}</h2>
          <div className="miniMetrics">
            <span className="statPill">{props.projectConfig.genre || (zh ? "未设题材" : "genre unset")}</span>
            <span className="statPill">{props.projectConfig.target_platform || (zh ? "未设平台" : "platform unset")}</span>
            <span className={props.projectHealth?.summary.failed_task_count ? "badge warn" : "badge ok"}>
              {zh ? "失败任务" : "failed tasks"}: {props.projectHealth?.summary.failed_task_count ?? 0}
            </span>
            <span className={props.projectHealth?.summary.pending_handoff_count ? "badge warn" : "badge ok"}>
              handoff: {props.projectHealth?.summary.pending_handoff_count ?? 0}
            </span>
          </div>
        </div>
        <div className="studioActions">
          <button className="secondaryButton" onClick={() => props.onOpenTab("projects")}>
            <Boxes size={18} />
            {zh ? "项目" : "Project"}
          </button>
          <button className="secondaryButton" onClick={() => props.onOpenTab("task_center")}>
            <ListChecks size={18} />
            {zh ? "任务" : "Tasks"}
          </button>
          <button className="secondaryButton" onClick={() => props.onOpenTab("material_library")}>
            <FileSearch size={18} />
            {zh ? "资产" : "Assets"}
          </button>
        </div>
      </div>

      <div className="studioMainGrid">
        <div className="panel novelWorkbench">
          <PanelHeader title={zh ? "阅读与改稿" : "Read And Edit"} icon={<BookOpen size={18} />} />
          <div className="studioSelectorGrid">
            <SelectPath label={zh ? "章节计划" : "Chapter Plan"} latestLabel={zh ? "最新" : "Latest"} value={props.selectedPlan} onChange={props.setSelectedPlan} rows={props.drafts?.chapter_plans ?? []} />
            <SelectPath label={zh ? "草稿章节" : "Draft Chapter"} latestLabel={zh ? "最新" : "Latest"} value={props.selectedDraft} onChange={props.setSelectedDraft} rows={draftRows} />
          </div>
          <div className="sectionActionLine">
            <button className="primaryButton" disabled={props.busy || !props.selectedPlan} onClick={props.onGenerateDraft}>
              <PenLine size={18} />
              {zh ? "生成/重生成" : "Generate"}
            </button>
            <button className="secondaryButton" disabled={props.busy || !props.draftEditor} onClick={props.onSaveDraft}>
              <Save size={18} />
              {zh ? "保存修改" : "Save Edits"}
            </button>
            <button className="secondaryButton tableButton" disabled={props.busy || !props.draftEditor} onClick={() => props.onExportDraft("markdown")}>MD</button>
            <button className="secondaryButton tableButton" disabled={props.busy || !props.draftEditor} onClick={() => props.onExportDraft("docx")}>DOCX</button>
            <button className="secondaryButton tableButton" disabled={props.busy || !props.draftEditor} onClick={() => props.onExportDraft("epub")}>EPUB</button>
          </div>
          <input
            value={props.draftEditor?.title ?? currentDraftRow?.title ?? ""}
            onChange={(event) => props.draftEditor && props.setDraftEditor({ ...props.draftEditor, title: event.target.value })}
            aria-label={zh ? "章节标题" : "Chapter title"}
            placeholder={zh ? "章节标题" : "Chapter title"}
          />
          <div className="readerEditorGrid">
            <article className="novelReader">
              <div className="readerMeta">
                <span className="statPill">v{props.draftEditor?.version_index ?? currentDraftRow?.chapter ?? "-"}</span>
                <span className="statPill">{props.draftEditor?.status ?? currentDraftRow?.risk_level ?? "draft"}</span>
              </div>
              <h2>{props.draftEditor?.title || currentDraftRow?.title || (zh ? "未选择草稿" : "No draft selected")}</h2>
              <div className="readerBody">
                {paragraphs.length ? paragraphs.map((paragraph, index) => <p key={`${index}-${paragraph.slice(0, 16)}`}>{paragraph}</p>) : <p>{zh ? "选择或生成草稿后可阅读正文。" : "Select or generate a draft to read the chapter."}</p>}
              </div>
            </article>
            <textarea
              className="studioDraftEditor"
              value={draftText}
              onChange={(event) => props.draftEditor && props.setDraftEditor({ ...props.draftEditor, text: event.target.value })}
              aria-label={zh ? "正文编辑器" : "Draft editor"}
            />
          </div>
          {props.draftExport ? <p className="previewText">{zh ? "最近导出" : "Latest export"}: {String(props.draftExport.path ?? "")}</p> : null}
        </div>

        <div className="panel generationPanel">
          <PanelHeader title={zh ? "生成链路" : "Generation Trace"} icon={<Workflow size={18} />} />
          <div className="productionSteps">
            {productionSteps.map((step) => (
              <button className={`productionStep ${step.status}`} key={step.key} onClick={() => props.onOpenTab(step.tab)}>
                <span>{step.label}</span>
                <strong>{step.count}</strong>
                <small>{step.detail}</small>
              </button>
            ))}
          </div>
          <h3>{zh ? "最近生成事件" : "Recent Events"}</h3>
          <DataTable
            emptyText={zh ? "暂无事件" : "No events"}
            columns={zh ? ["Agent", "步骤", "状态", "时间", "资产"] : ["Agent", "Step", "Status", "Time", "Asset"]}
            rows={latestEvents.map((event) => [
              agentNameForStep(event.step, event.task_type, zh),
              event.step,
              <span className={event.status === "completed" ? "badge ok" : event.status === "failed" ? "badge warn" : "badge muted"} key={`event-${event.path}`}>{event.status}</span>,
              event.recorded_at,
              <button className="linkButton" key={event.path} onClick={() => props.onOpenAsset(event.path)}>{event.path}</button>
            ])}
          />
          <h3>{zh ? "Handoff 观察" : "Handoff Watch"}</h3>
          <DataTable
            emptyText={zh ? "暂无 handoff" : "No handoffs"}
            columns={zh ? ["操作", "状态", "技能", "来源", "产物"] : ["Operation", "Status", "Skill", "Source", "Output"]}
            rows={props.handoffs.slice(0, 8).map((handoff) => [
              <button className="linkButton" key={handoff.path} onClick={() => props.onOpenHandoff(handoff.path)}>{handoff.operation}</button>,
              <span className={handoff.status === "completed" ? "badge ok" : handoff.status === "failed" ? "badge warn" : "badge muted"} key={`status-${handoff.path}`}>{handoff.status}</span>,
              handoff.skill,
              handoff.source_path,
              handoff.expected_output_type
            ])}
          />
        </div>
      </div>

      <div className="studioSecondaryGrid">
        <div className="panel">
          <PanelHeader title={zh ? "资料来源与拆解结果" : "Sources And Deconstruction"} icon={<FileSearch size={18} />} />
          <DataTable
            emptyText={zh ? "暂无资料来源" : "No sources"}
            columns={zh ? ["来源", "名称", "状态/风险", "产物", "路径"] : ["Source", "Name", "Status/Risk", "Output", "Path"]}
            rows={sourceRows.slice(0, 14).map((row) => [
              <span className={row.kindClass} key={`kind-${row.key}`}>{row.kind}</span>,
              row.name,
              row.status,
              row.output,
              row.path ? <button className="linkButton" key={row.key} onClick={() => row.openAs === "handoff" ? props.onOpenHandoff(row.path) : props.onOpenAsset(row.path)}>{row.path}</button> : "-"
            ])}
          />
          <div className="knowledgeSplit">
            <div>
              <h3>{zh ? "GitHub 多学科知识" : "GitHub Knowledge"}</h3>
              <DataTable
                emptyText={zh ? "暂无 GitHub 知识卡" : "No GitHub knowledge cards"}
                columns={zh ? ["标题", "风险", "来源", "资产"] : ["Title", "Risk", "Source", "Asset"]}
                rows={githubKnowledgeRows.slice(0, 8).map((asset) => [
                  asset.title || asset.path,
                  asset.risk_level || "-",
                  asset.source || "github",
                  <button className="linkButton" key={asset.path} onClick={() => props.onOpenAsset(asset.path)}>{asset.path}</button>
                ])}
              />
            </div>
            <div>
              <h3>{zh ? "本地上传/项目知识" : "Local Knowledge"}</h3>
              <DataTable
                emptyText={zh ? "暂无本地知识卡" : "No local knowledge cards"}
                columns={zh ? ["标题", "状态", "来源", "资产"] : ["Title", "Status", "Source", "Asset"]}
                rows={localKnowledgeRows.slice(0, 8).map((asset) => [
                  asset.title || asset.path,
                  asset.asset_status || "-",
                  sourceLabelForAsset(asset, props.batchItems, zh),
                  <button className="linkButton" key={asset.path} onClick={() => props.onOpenAsset(asset.path)}>{asset.path}</button>
                ])}
              />
            </div>
          </div>
          <h3>{zh ? "小说拆解 / 素材化" : "Novel Deconstruction / Materials"}</h3>
          <DataTable
            emptyText={zh ? "暂无拆解产物" : "No deconstruction outputs"}
            columns={zh ? ["类型", "标题", "来源", "资产"] : ["Type", "Title", "Source", "Asset"]}
            rows={[...decompositionRows.slice(0, 8), ...materialRows.slice(0, 8)].map((asset) => [
              asset.type,
              asset.title || asset.path,
              sourceLabelForAsset(asset, props.batchItems, zh),
              <button className="linkButton" key={asset.path} onClick={() => props.onOpenAsset(asset.path)}>{asset.path}</button>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title={zh ? "Agent 工作观察" : "Agent Work Board"} icon={<Activity size={18} />} />
          <DataTable
            emptyText={zh ? "暂无 Agent 状态" : "No agent state"}
            columns={zh ? ["Agent", "输入", "工具/技能", "状态", "产物"] : ["Agent", "Input", "Tool/Skill", "Status", "Output"]}
            rows={agentRows.map((row) => [
              <strong key={`agent-${row.agent}`}>{row.agent}</strong>,
              row.input,
              row.skill,
              <span className={row.statusClass} key={`status-${row.agent}`}>{row.status}</span>,
              row.output
            ])}
          />
          <h3>{zh ? "当前任务压力" : "Queue Pressure"}</h3>
          <div className="miniMetrics">
            <span className={props.taskControl?.celery.healthy ? "badge ok" : "badge warn"}>worker: {props.taskControl?.celery.healthy ? "healthy" : "offline"}</span>
            <span className="statPill">active: {props.taskControl?.celery.active_count ?? 0}</span>
            <span className="statPill">reserved: {props.taskControl?.celery.reserved_count ?? 0}</span>
            <span className={props.projectHealth?.scope_audit.summary.issue_count ? "badge warn" : "badge ok"}>scope: {props.projectHealth?.scope_audit.summary.issue_count ?? 0}</span>
          </div>
        </div>
      </div>
    </section>
  );
}

type StudioSourceRow = {
  key: string;
  kind: string;
  kindClass: string;
  name: string;
  status: string;
  output: string;
  path: string;
  openAs: "asset" | "handoff" | "";
};

type ProductionStep = {
  key: string;
  label: string;
  count: number;
  detail: string;
  status: "ok" | "warn" | "muted";
  tab: TabKey;
};

type AgentWorkRow = {
  agent: string;
  input: string;
  skill: string;
  status: string;
  statusClass: string;
  output: string;
};

function buildStudioSourceRows(
  assets: AssetRow[],
  batchItems: BatchItem[],
  handoffs: HandoffRow[],
  githubSources: GitHubSource[],
  uploadResult: UploadResult | null,
  zh: boolean
): StudioSourceRow[] {
  const rows: StudioSourceRow[] = [];
  for (const source of githubSources.slice(0, 10)) {
    rows.push({
      key: `github-${source.repo}`,
      kind: "GitHub",
      kindClass: source.commercial_risk === "low" ? "badge ok" : "badge warn",
      name: source.repo,
      status: `${source.commercial_risk || "risk"} / ${source.license_check || "license"}`,
      output: source.allowed_pipeline.join(", "),
      path: "",
      openAs: "",
    });
  }
  for (const item of uploadResult?.items ?? []) {
    rows.push({
      key: `upload-${item.sha256}`,
      kind: zh ? "本地上传" : "Local Upload",
      kindClass: item.duplicate ? "badge warn" : "badge ok",
      name: item.filename,
      status: item.duplicate ? (zh ? "重复" : "duplicate") : item.minio.uploaded ? "MinIO" : "local",
      output: `${item.format} / ${item.size_bytes} bytes`,
      path: "",
      openAs: "",
    });
  }
  for (const item of batchItems.slice(0, 20)) {
    rows.push({
      key: `batch-${item.path}`,
      kind: sourceKindForPath(item.source_path, zh),
      kindClass: item.status === "completed" ? "badge ok" : item.status === "failed" ? "badge warn" : "badge muted",
      name: item.source_name || item.source_path,
      status: item.status,
      output: item.material || item.knowledge || item.decomposition || item.handoff_path || item.analysis_mode,
      path: item.path,
      openAs: "asset",
    });
  }
  for (const asset of assets.filter((row) => row.category === "raw" || row.type === "source_document").slice(0, 20)) {
    rows.push({
      key: `raw-${asset.path}`,
      kind: sourceKindForPath(asset.source || asset.path, zh),
      kindClass: "badge muted",
      name: asset.title || asset.path,
      status: asset.asset_status || "-",
      output: asset.type,
      path: asset.path,
      openAs: "asset",
    });
  }
  for (const handoff of handoffs.slice(0, 20)) {
    rows.push({
      key: `handoff-source-${handoff.path}`,
      kind: handoff.source_path.toLowerCase().includes("github") ? "GitHub" : zh ? "执行包输入" : "Handoff Input",
      kindClass: handoff.status === "completed" ? "badge ok" : handoff.status === "failed" ? "badge warn" : "badge muted",
      name: handoff.operation,
      status: handoff.status,
      output: handoff.expected_output_type,
      path: handoff.path,
      openAs: "handoff",
    });
  }
  return dedupeSourceRows(rows);
}

function dedupeSourceRows(rows: StudioSourceRow[]): StudioSourceRow[] {
  const seen = new Set<string>();
  const result: StudioSourceRow[] = [];
  for (const row of rows) {
    const key = row.path || row.key;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(row);
  }
  return result;
}

function sourceKindForPath(path: string, zh: boolean): string {
  const text = path.toLowerCase();
  if (text.includes("github")) return "GitHub";
  if (text.includes("uploads") || text.includes("upload")) return zh ? "本地上传" : "Local Upload";
  if (text.includes("gutenberg") || text.includes("cbeta") || text.includes("cbdb") || text.includes("chgis")) return zh ? "外部数据包" : "External Dataset";
  return zh ? "本地资料" : "Local Source";
}

function knowledgeOrigin(asset: AssetRow, handoffs: HandoffRow[], batchItems: BatchItem[]): "github" | "upload" | "local" {
  const text = `${asset.path} ${asset.title} ${asset.tags.join(" ")} ${asset.source}`.toLowerCase();
  if (text.includes("github")) return "github";
  const handoff = handoffs.find((item) => item.id === asset.source || item.path === asset.source || item.source_path === asset.source);
  if (handoff?.source_path.toLowerCase().includes("github")) return "github";
  if (handoff?.source_path.toLowerCase().includes("upload")) return "upload";
  if (batchItems.some((item) => item.knowledge === asset.path && item.source_path.toLowerCase().includes("upload"))) return "upload";
  return "local";
}

function sourceLabelForAsset(asset: AssetRow, batchItems: BatchItem[], zh: boolean): string {
  const origin = knowledgeOrigin(asset, [], batchItems);
  if (origin === "github") return "GitHub";
  if (origin === "upload") return zh ? "本地上传" : "Local Upload";
  if (asset.category === "raw") return zh ? "原始资料" : "Raw Source";
  return zh ? "项目资产" : "Project Asset";
}

function buildProductionSteps(
  assets: AssetRow[],
  batchItems: BatchItem[],
  handoffs: HandoffRow[],
  drafts: DraftWorkbench | null,
  taskCenter: TaskCenter | null,
  zh: boolean
): ProductionStep[] {
  const failedTasks = taskCenter?.summary.by_status.failed ?? 0;
  const waitingHandoffs = handoffs.filter((item) => item.status !== "completed" && item.status !== "superseded").length;
  const rawCount = assets.filter((item) => item.category === "raw" || item.type === "source_document").length;
  const decompositionCount = assets.filter((item) => item.category === "decompositions" || item.type === "decomposition_report").length;
  const knowledgeCount = assets.filter((item) => item.category === "knowledge" || item.type === "knowledge_card").length;
  const materialCount = assets.filter((item) => item.category === "materials" || item.type === "material_card").length;
  const draftCount = drafts?.drafts.length ?? assets.filter((item) => item.type === "draft_chapter").length;
  const reviewCount = drafts?.reviews.length ?? assets.filter((item) => item.type === "review_report").length;
  return [
    {
      key: "sources",
      label: zh ? "资料" : "Sources",
      count: rawCount + batchItems.length,
      detail: zh ? "本地上传 / 外部登记" : "uploads and registries",
      status: stepStatus(rawCount + batchItems.length, false),
      tab: "web_fiction_analysis",
    },
    {
      key: "deconstruct",
      label: zh ? "拆解" : "Deconstruct",
      count: decompositionCount,
      detail: zh ? "网文结构 / 章节机制" : "structure and chapter mechanics",
      status: stepStatus(decompositionCount, failedTasks > 0),
      tab: "web_fiction_analysis",
    },
    {
      key: "knowledge",
      label: zh ? "知识" : "Knowledge",
      count: knowledgeCount,
      detail: waitingHandoffs ? `${waitingHandoffs} handoff` : (zh ? "知识卡" : "knowledge cards"),
      status: waitingHandoffs ? "warn" : stepStatus(knowledgeCount, false),
      tab: "handoffs",
    },
    {
      key: "materials",
      label: zh ? "素材" : "Materials",
      count: materialCount,
      detail: zh ? "可复用素材卡" : "reusable material cards",
      status: stepStatus(materialCount, false),
      tab: "material_library",
    },
    {
      key: "draft",
      label: zh ? "正文" : "Draft",
      count: draftCount,
      detail: zh ? "章节草稿 / 版本" : "chapters and versions",
      status: stepStatus(draftCount, false),
      tab: "chapter_production",
    },
    {
      key: "review",
      label: zh ? "审修" : "Review",
      count: reviewCount,
      detail: zh ? "评分 / 修订计划" : "scores and revision plans",
      status: stepStatus(reviewCount, failedTasks > 0),
      tab: "review_center",
    },
  ];
}

function stepStatus(count: number, hasFailure: boolean): "ok" | "warn" | "muted" {
  if (hasFailure) return "warn";
  return count > 0 ? "ok" : "muted";
}

function buildAgentWorkRows(
  assets: AssetRow[],
  batchItems: BatchItem[],
  handoffs: HandoffRow[],
  drafts: DraftWorkbench | null,
  taskCenter: TaskCenter | null,
  taskControl: TaskControl | null,
  projectHealth: ProjectHealthReport | null,
  zh: boolean
): AgentWorkRow[] {
  const countType = (type: string) => assets.filter((asset) => asset.type === type || asset.category === type).length;
  const failedTasks = taskCenter?.summary.by_status.failed ?? 0;
  const scopeIssues = projectHealth?.scope_audit.summary.issue_count ?? 0;
  const handoffPending = handoffs.filter((item) => item.status !== "completed" && item.status !== "superseded").length;
  const rows: AgentWorkRow[] = [
    {
      agent: "Chief Editor Agent",
      input: zh ? "项目状态 / 风险 / 审修结果" : "project state, risks, reviews",
      skill: "quality-review, long-outline",
      status: scopeIssues || failedTasks ? (zh ? "需决策" : "needs decision") : (zh ? "稳定" : "stable"),
      statusClass: scopeIssues || failedTasks ? "badge warn" : "badge ok",
      output: zh ? `范围问题 ${scopeIssues}` : `${scopeIssues} scope issues`,
    },
    {
      agent: "Knowledge Agent",
      input: zh ? "GitHub / 本地资料 / 拆解报告" : "GitHub, local sources, decompositions",
      skill: "multidisciplinary-knowledge",
      status: handoffPending ? (zh ? "等待执行包" : "handoff pending") : (zh ? "可用" : "ready"),
      statusClass: handoffPending ? "badge warn" : "badge ok",
      output: `${countType("knowledge_card")} knowledge`,
    },
    {
      agent: "Material Agent",
      input: zh ? "知识卡 / 拆解卡" : "knowledge and decomposition cards",
      skill: "material-curation, anti-copy-abstraction",
      status: countType("material_card") ? (zh ? "已产出" : "producing") : (zh ? "待素材" : "waiting"),
      statusClass: countType("material_card") ? "badge ok" : "badge muted",
      output: `${countType("material_card")} materials`,
    },
    {
      agent: "Draft Agent",
      input: zh ? "章节计划 / RAG 上下文" : "chapter plan and RAG context",
      skill: "prose-generation, chapter-outline",
      status: drafts?.drafts.length ? (zh ? "可编辑" : "editable") : (zh ? "待草稿" : "waiting"),
      statusClass: drafts?.drafts.length ? "badge ok" : "badge muted",
      output: `${drafts?.drafts.length ?? 0} drafts`,
    },
    {
      agent: "Review Agent",
      input: zh ? "草稿 / rubric / 质量阈值" : "drafts, rubric, thresholds",
      skill: "quality-review",
      status: drafts?.reviews.length ? (zh ? "有审稿" : "reviewed") : (zh ? "待审" : "waiting"),
      statusClass: drafts?.reviews.length ? "badge ok" : "badge muted",
      output: `${drafts?.reviews.length ?? 0} reviews`,
    },
    {
      agent: "Quality Agent",
      input: zh ? "schema / scope audit / 任务日志" : "schema, scope audit, task logs",
      skill: "validation, recovery",
      status: failedTasks ? (zh ? "需恢复" : "recovery needed") : (zh ? "通过" : "passing"),
      statusClass: failedTasks ? "badge warn" : "badge ok",
      output: `${taskCenter?.timeline.summary.event_count ?? 0} events`,
    },
    {
      agent: "Engineering Agent",
      input: zh ? "API / worker / 存储服务" : "API, workers, storage services",
      skill: "FastAPI, Celery, Postgres",
      status: taskControl?.celery.healthy ? (zh ? "worker 在线" : "worker online") : (zh ? "本地模式" : "local mode"),
      statusClass: taskControl?.celery.healthy ? "badge ok" : "badge muted",
      output: `${taskControl?.dead_letters.count ?? 0} dead letters`,
    },
    {
      agent: "Outline / World / Character Agents",
      input: zh ? "题材配置 / 世界观 / 人物资产" : "genre config, world, character assets",
      skill: "long-outline, worldbuilding, character-design",
      status: countType("outlines") || countType("worlds") || countType("characters") ? (zh ? "已建模" : "modeled") : (zh ? "待建模" : "waiting"),
      statusClass: countType("outlines") || countType("worlds") || countType("characters") ? "badge ok" : "badge muted",
      output: `${countType("outlines") + countType("worlds") + countType("characters")} assets`,
    },
  ];
  return rows;
}

function agentNameForStep(step: string, taskType: string, zh: boolean): string {
  const value = `${taskType} ${step}`.toLowerCase();
  if (value.includes("handoff")) return "Claude Code / Codex";
  if (value.includes("decompose") || value.includes("knowledge")) return "Knowledge Agent";
  if (value.includes("material")) return "Material Agent";
  if (value.includes("draft")) return "Draft Agent";
  if (value.includes("review")) return "Review Agent";
  if (value.includes("revise")) return "Review Agent";
  if (value.includes("world") || value.includes("character") || value.includes("outline")) return "Outline Agent";
  if (value.includes("failed") || value.includes("validate")) return "Quality Agent";
  return zh ? "工程/流程 Agent" : "Engineering Agent";
}

function HealthPanel(props: {
  language: Language;
  report: ProjectHealthReport | null;
  backups: BackupRow[];
  restorePath: string;
  setRestorePath: (value: string) => void;
  qdrantQuery: string;
  setQdrantQuery: (value: string) => void;
  qdrantResult: QdrantSearchResult | null;
  minioStatus: MinioStatus | null;
  onCreateBackup: () => void;
  onRestoreBackup: () => void;
  onArchiveEvents: () => void;
  onQdrantIndex: () => void;
  onQdrantSearch: () => void;
  onMinioSync: () => void;
  onRefreshMinio: () => void;
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
            <button className="secondaryButton tableButton" disabled={props.busy} onClick={props.onQdrantIndex}>
              {zh ? "重建索引" : "Reindex"}
            </button>
          </article>
          <article className="serviceCard">
            <div className="serviceTitle"><UploadCloud size={17} /><span>MinIO</span></div>
            <span className={props.minioStatus?.available ? "badge ok" : props.minioStatus?.configured ? "badge warn" : "badge muted"}>
              {props.minioStatus?.available ? props.minioStatus.bucket : props.minioStatus?.configured ? "offline" : "not checked"}
            </span>
            <button className="secondaryButton tableButton" disabled={props.busy} onClick={props.onMinioSync}>
              {zh ? "同步" : "Sync"}
            </button>
          </article>
        </div>
        <div className="formGrid wide">
          <input value={props.qdrantQuery} onChange={(event) => props.setQdrantQuery(event.target.value)} aria-label="Qdrant query" placeholder={zh ? "向量检索查询" : "Vector search query"} />
          <button className="secondaryButton" disabled={props.busy || !props.qdrantQuery.trim()} onClick={props.onQdrantSearch}>
            <Search size={18} />
            {zh ? "检索" : "Search"}
          </button>
          <button className="secondaryButton" disabled={props.busy} onClick={props.onRefreshMinio}>
            <RefreshCw size={18} />
            {zh ? "刷新对象" : "Refresh Objects"}
          </button>
        </div>
        <DataTable
          emptyText={zh ? "暂无检索结果" : "No vector hits"}
          columns={zh ? ["排名", "分数", "标题", "解释", "资产"] : ["Rank", "Score", "Title", "Explanation", "Asset"]}
          rows={(props.qdrantResult?.results ?? []).map((hit) => [
            String(hit.rank),
            String(hit.score ?? ""),
            hit.title || hit.path,
            hit.explanation?.reason || "",
            <button className="linkButton" onClick={() => props.onOpenAsset(hit.path)} key={hit.path}>{hit.path}</button>
          ])}
        />
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
          <button className="secondaryButton" disabled={props.busy} onClick={props.onArchiveEvents}>
            <Archive size={18} />
            {zh ? "归档旧事件" : "Archive Events"}
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
        <h3>{zh ? "MinIO 对象" : "MinIO Objects"}</h3>
        <DataTable
          emptyText={zh ? "暂无对象状态" : "No object status"}
          columns={zh ? ["分类", "状态", "大小", "对象", "资产"] : ["Category", "Status", "Size", "Object", "Asset"]}
          rows={(props.minioStatus?.objects ?? []).map((object) => [
            object.category,
            <span className={object.exists ? "badge ok" : "badge muted"} key={`exists-${object.path}`}>{object.exists ? "synced" : "local"}</span>,
            String(object.size || ""),
            <span className="pathText" key={`object-${object.path}`}>{object.object_name}</span>,
            <button className="linkButton" onClick={() => props.onOpenAsset(object.path)} key={object.path}>{object.path}</button>
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
  creativeLibraries: CreativeLibrary[];
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
          <div className="bindingPanel">
            <div className="sectionHeaderLine">
              <h3>{zh ? "生产输入绑定" : "Production Input Bindings"}</h3>
              <span className="statPill">{projectBindingReady(props.projectConfig) ? (zh ? "完整" : "ready") : (zh ? "待补齐" : "incomplete")}</span>
            </div>
            <div className="bindingGrid">
              <ProjectBindingSelect
                label={zh ? "平台画像" : "Platform Profile"}
                value={props.projectConfig.platform_profile_path || ""}
                options={creativeAssetOptions(props.creativeLibraries, "platform_profile")}
                onChange={(path) => props.setProjectConfig({ ...props.projectConfig, platform_profile_path: path })}
              />
              <ProjectBindingSelect
                label={zh ? "题材市场" : "Genre Market"}
                value={props.projectConfig.genre_market_profile_path || ""}
                options={creativeAssetOptions(props.creativeLibraries, "genre_market_profile")}
                onChange={(path) => props.setProjectConfig({ ...props.projectConfig, genre_market_profile_path: path })}
              />
              <ProjectBindingSelect
                label={zh ? "精品标准" : "Quality Standard"}
                value={props.projectConfig.quality_standard_profile_path || ""}
                options={creativeAssetOptions(props.creativeLibraries, "quality_standard_profile")}
                onChange={(path) => props.setProjectConfig({ ...props.projectConfig, quality_standard_profile_path: path })}
              />
              <ProjectBindingSelect
                label={zh ? "文风目标" : "Style Target"}
                value={props.projectConfig.style_profile_path || ""}
                options={creativeAssetOptions(props.creativeLibraries, "style_profile")}
                onChange={(path) => props.setProjectConfig({ ...props.projectConfig, style_profile_path: path })}
              />
              <ProjectBindingSelect
                label={zh ? "连续性设定" : "Continuity Bible"}
                value={props.projectConfig.continuity_bible_path || ""}
                options={creativeAssetOptions(props.creativeLibraries, "continuity_bible")}
                onChange={(path) => props.setProjectConfig({ ...props.projectConfig, continuity_bible_path: path })}
              />
            </div>
          </div>
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

function ProjectBindingSelect({
  label,
  value,
  options,
  onChange
}: {
  label: string;
  value: string;
  options: CreativeAssetRow[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="bindingField">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">auto / unbound</option>
        {options.map((asset) => (
          <option value={asset.path} key={asset.path}>
            {asset.title || asset.path}
          </option>
        ))}
      </select>
    </label>
  );
}

function creativeAssetOptions(libraries: CreativeLibrary[], assetType: string): CreativeAssetRow[] {
  return libraries.flatMap((library) => library.assets).filter((asset) => asset.type === assetType);
}

function projectBindingReady(config: ProjectConfig): boolean {
  return Boolean(
    config.platform_profile_path &&
    config.genre_market_profile_path &&
    config.quality_standard_profile_path &&
    config.style_profile_path &&
    config.continuity_bible_path
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
  dateFrom,
  setDateFrom,
  dateTo,
  setDateTo,
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
  dateFrom: string;
  setDateFrom: (value: string) => void;
  dateTo: string;
  setDateTo: (value: string) => void;
  offset: number;
  setOffset: (value: number) => void;
  onApplyFilters: (override?: { offset?: number; status?: string; taskType?: string; step?: string; dateFrom?: string; dateTo?: string }) => void;
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
        <input value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} aria-label={zh ? "开始时间" : "Date from"} placeholder={zh ? "开始时间 ISO" : "Date from ISO"} />
        <input value={dateTo} onChange={(event) => setDateTo(event.target.value)} aria-label={zh ? "结束时间" : "Date to"} placeholder={zh ? "结束时间 ISO" : "Date to ISO"} />
        <button className="secondaryButton" disabled={busy} onClick={() => { setOffset(0); onApplyFilters({ offset: 0 }); }}>
          <Search size={18} />
          {zh ? "筛选" : "Filter"}
        </button>
        <button className="secondaryButton" disabled={busy} onClick={() => { setStatusFilter(""); setTypeFilter(""); setStepFilter(""); setDateFrom(""); setDateTo(""); setOffset(0); onApplyFilters({ offset: 0, status: "", taskType: "", step: "", dateFrom: "", dateTo: "" }); }}>
          <RotateCcw size={18} />
          {zh ? "清空" : "Reset"}
        </button>
      </div>
      <h3>{zh ? "队列压力趋势" : "Queue Pressure Trend"}</h3>
      <DataTable
        emptyText={zh ? "暂无趋势" : "No trend"}
        columns={zh ? ["时间", "健康", "排队", "活跃", "保留", "计划"] : ["Time", "Healthy", "Queued", "Active", "Reserved", "Scheduled"]}
        rows={(taskControl?.queue_trend ?? []).slice(-10).reverse().map((point) => [
          point.recorded_at,
          <span className={point.healthy ? "badge ok" : "badge warn"} key={point.recorded_at}>{point.healthy ? "yes" : "no"}</span>,
          String(point.queue_total),
          String(point.active_count),
          String(point.reserved_count),
          String(point.scheduled_count)
        ])}
      />
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

function CreativeLibraryPanel(props: {
  language: Language;
  library: CreativeLibrary | null | undefined;
  fallbackLibraryKey: string;
  selectedProjectId: string;
  selectedWorkspace: string;
  createTitle: string;
  setCreateTitle: (value: string) => void;
  createType: string;
  setCreateType: (value: string) => void;
  keyword: string;
  setKeyword: (value: string) => void;
  detail: AssetDetail | null;
  versions: AssetVersions | null;
  graph: AssetGraph | null;
  selectedDraft: string;
  styleTrend: StyleTrend | null;
  busy: boolean;
  onSelect: (path: string) => void;
  onRefresh: (libraryKey: string, keyword: string) => void;
  onCreate: (assetType: string, title: string) => void;
  onSave: (path: string, patch: Record<string, unknown>) => void;
  onSaveContent: (path: string, content: Record<string, unknown>) => void;
  onSaveTyped: (path: string, fields: Record<string, unknown>) => void;
  onStyleDecompose: (sourcePath: string) => void;
  onStyleReview: (draftPath: string, styleProfilePath?: string) => void;
  onQualityScore: (targetPath: string) => void;
}) {
  const zh = props.language === "zh";
  const library = props.library;
  const title = library ? (zh ? library.title_zh : library.title) : props.fallbackLibraryKey;
  const description = library ? (zh ? library.description_zh : library.description) : "";
  const assetTypes = library?.asset_types ?? [];
  const selectedType = assetTypes.includes(props.createType) ? props.createType : assetTypes[0] ?? "";
  const selectedDetailType = String(props.detail?.asset.type ?? "");
  const detailBelongsToLibrary = Boolean(library?.asset_types.includes(selectedDetailType));

  return (
    <section className="creativeLibraryPage">
      <div className="panel creativeLibraryHero">
        <div>
          <p className="eyebrow">{zh ? "创作资产工作台" : "Creative Asset Workbench"}</p>
          <h2>{title}</h2>
          <p>{description || pageSummary(props.fallbackLibraryKey as TabKey, props.language)}</p>
          <div className="miniMetrics">
            <span className="statPill">{zh ? "项目" : "project"}: {props.selectedProjectId || (zh ? "全局" : "global")}</span>
            <span className="statPill">{zh ? "资产类型" : "types"}: {assetTypes.length}</span>
            <span className="statPill">{zh ? "资产数" : "assets"}: {library?.assets.length ?? 0}</span>
          </div>
        </div>
        <div className="creativeCreateBox">
          <select value={selectedType} onChange={(event) => props.setCreateType(event.target.value)} aria-label={zh ? "资产类型" : "Asset type"}>
            {assetTypes.map((assetType) => (
              <option key={assetType} value={assetType}>
                {assetType}
              </option>
            ))}
          </select>
          <input
            value={props.createTitle}
            onChange={(event) => props.setCreateTitle(event.target.value)}
            aria-label={zh ? "资产标题" : "Asset title"}
            placeholder={zh ? "资产标题" : "Asset title"}
          />
          <button
            className="primaryButton"
            disabled={props.busy || !selectedType || !props.createTitle.trim()}
            onClick={() => props.onCreate(selectedType, props.createTitle.trim())}
          >
            <Save size={18} />
            {zh ? "创建资产" : "Create Asset"}
          </button>
        </div>
      </div>

      {props.fallbackLibraryKey === "style_center" ? (
        <section className="panel operationPanel">
          <div className="sectionHeaderLine">
            <h3>{zh ? "文风任务" : "Style Operations"}</h3>
            <span className="statPill">{zh ? "平均" : "avg"}: {props.styleTrend?.average_score ?? 0}</span>
            <span className="statPill">{zh ? "最近" : "latest"}: {props.styleTrend?.latest_score ?? 0}</span>
          </div>
          <div className="actionRow">
            <button className="secondaryButton" disabled={props.busy || !props.detail?.path} onClick={() => props.detail?.path && props.onStyleDecompose(props.detail.path)}>
              <Wand2 size={18} />
              {zh ? "拆解选中资产文风" : "Decompose Selected Style"}
            </button>
            <button className="secondaryButton" disabled={props.busy || !props.selectedDraft} onClick={() => props.onStyleReview(props.selectedDraft, props.detail?.asset.type === "style_profile" ? props.detail.path : undefined)}>
              <ShieldCheck size={18} />
              {zh ? "评分当前草稿" : "Review Current Draft"}
            </button>
          </div>
          <DataTable
            emptyText={zh ? "暂无文风评分" : "No style reviews"}
            columns={zh ? ["分数", "风险", "漂移", "报告"] : ["Score", "Risk", "Drift", "Report"]}
            rows={(props.styleTrend?.rows ?? []).slice(0, 5).map((row) => [
              String(row.score),
              <span className={row.risk === "low" ? "badge ok" : row.risk === "high" ? "badge warn" : "badge muted"} key={`risk-${row.path}`}>{row.risk}</span>,
              String(row.drift_count),
              <button className="linkButton" onClick={() => props.onSelect(row.path)} key={row.path}>{row.path}</button>
            ])}
          />
        </section>
      ) : null}

      {props.fallbackLibraryKey === "quality_standards" ? (
        <section className="panel operationPanel">
          <div className="sectionHeaderLine">
            <h3>{zh ? "质量门禁" : "Quality Gate"}</h3>
            <span className="statPill">{zh ? "当前草稿" : "draft"}: {props.selectedDraft || "-"}</span>
          </div>
          <button className="secondaryButton" disabled={props.busy || !props.selectedDraft} onClick={() => props.onQualityScore(props.selectedDraft)}>
            <ShieldCheck size={18} />
            {zh ? "按精品标准评分当前草稿" : "Score Current Draft"}
          </button>
        </section>
      ) : null}

      <section className="splitGrid">
        <div className="panel">
          <PanelHeader title={zh ? "资产列表" : "Assets"} icon={<Library size={18} />} />
          <form
            className="searchBar"
            onSubmit={(event) => {
              event.preventDefault();
              props.onRefresh(props.fallbackLibraryKey, props.keyword);
            }}
          >
            <input
              value={props.keyword}
              onChange={(event) => props.setKeyword(event.target.value)}
              aria-label={zh ? "库内搜索" : "Library search"}
              placeholder={zh ? "库内搜索" : "Search in library"}
            />
            <button className="secondaryButton" disabled={props.busy}>
              <Search size={18} />
              {zh ? "搜索" : "Search"}
            </button>
            <button
              type="button"
              className="secondaryButton"
              disabled={props.busy}
              onClick={() => {
                props.setKeyword("");
                props.onRefresh(props.fallbackLibraryKey, "");
              }}
            >
              <RefreshCw size={18} />
              {zh ? "刷新" : "Refresh"}
            </button>
          </form>
          <div className="libraryTypeGrid">
            {assetTypes.map((assetType) => (
              <button className={selectedType === assetType ? "typeChip active" : "typeChip"} key={assetType} onClick={() => props.setCreateType(assetType)}>
                {assetType}
              </button>
            ))}
          </div>
          <DataTable
            emptyText={zh ? "暂无资产" : "No assets"}
            columns={zh ? ["标题", "类型", "状态", "风险", "更新时间", "路径"] : ["Title", "Type", "Status", "Risk", "Updated", "Path"]}
            rows={(library?.assets ?? []).map((asset) => [
              asset.title || asset.path,
              asset.type,
              <span className={asset.asset_status === "approved" ? "badge ok" : asset.asset_status === "blocked" ? "badge warn" : "badge muted"} key={`status-${asset.path}`}>
                {asset.asset_status}
              </span>,
              <span className={asset.risk_level === "high" ? "badge warn" : asset.risk_level === "low" ? "badge ok" : "badge muted"} key={`risk-${asset.path}`}>
                {asset.risk_level}
              </span>,
              asset.updated_at,
              <button className="linkButton" onClick={() => props.onSelect(asset.path)} key={asset.path}>
                {asset.path}
              </button>
            ])}
          />
        </div>
        <AssetDetailPanel
          language={props.language}
          detail={detailBelongsToLibrary ? props.detail : null}
          versions={props.versions}
          graph={props.graph}
          onSelect={props.onSelect}
          onSave={props.onSave}
          onSaveContent={props.onSaveContent}
          onSaveTyped={props.onSaveTyped}
        />
      </section>
    </section>
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
  onSaveTyped: (path: string, fields: Record<string, unknown>) => void;
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
        onSaveTyped={props.onSaveTyped}
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
  onSaveContent,
  onSaveTyped
}: {
  language: Language;
  detail: AssetDetail | null;
  versions: AssetVersions | null;
  graph: AssetGraph | null;
  onSelect: (path: string) => void;
  onSave: (path: string, patch: Record<string, unknown>) => void;
  onSaveContent: (path: string, content: Record<string, unknown>) => void;
  onSaveTyped: (path: string, fields: Record<string, unknown>) => void;
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
            <TypedAssetWorkbench language={language} detail={detail} onSelect={onSelect} onSaveTyped={onSaveTyped} />
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
  onSelect,
  onSaveTyped
}: {
  language: Language;
  detail: AssetDetail;
  onSelect: (path: string) => void;
  onSaveTyped: (path: string, fields: Record<string, unknown>) => void;
}) {
  const zh = language === "zh";
  const asset = detail.asset;
  const content = asset.content && typeof asset.content === "object" ? (asset.content as Record<string, unknown>) : {};
  const metadata = asset.metadata && typeof asset.metadata === "object" ? (asset.metadata as Record<string, unknown>) : {};
  const type = String(asset.type ?? "");
  const editFields = typedEditableFields(type, content, metadata, asset, zh);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  useEffect(() => {
    setEditValues(Object.fromEntries(editFields.map((field) => [field.key, field.value])));
  }, [detail.path]);
  const phase3Types = [
    "platform_profile",
    "genre_market_profile",
    "topic_seed",
    "topic_fit_report",
    "world_bible",
    "character_card",
    "continuity_bible",
    "foreshadowing_thread",
    "power_scale_rule",
    "style_profile",
    "style_decomposition_report",
    "style_blend_preset",
    "quality_standard_profile",
    "review_rule_pack",
    "quality_score_report",
    "style_review_report",
    "chapter_audit_report",
    "originality_report",
    "publish_gate_report",
    "release_package",
    "common_novel_analysis_report",
    "web_fiction_business_analysis_report",
    "published_fiction_analysis_report",
    "classic_literary_analysis_report",
    "analysis_conversion_report",
    "writing_template",
    "craft_template"
  ];
  if (!["decomposition_report", "knowledge_card", "material_card", "draft_chapter", "review_report", "revision_plan", "batch_task_item", ...phase3Types].includes(type)) {
    return null;
  }
  return (
    <div className="typedWorkbench">
      <div className="sectionHeaderLine">
        <h3>{zh ? "资产工作台" : "Asset Workbench"}</h3>
        <span className="statPill">{type}</span>
      </div>
      {editFields.length ? (
        <div className="typedEditPanel">
          <div className="sectionHeaderLine">
            <h3>{zh ? "类型化编辑" : "Typed Editing"}</h3>
            <button className="secondaryButton tableButton" onClick={() => onSaveTyped(detail.path, typedEditPayload(editFields, editValues))}>
              <Save size={16} />
              {zh ? "保存字段" : "Save Fields"}
            </button>
          </div>
          <div className="typedEditGrid">
            {editFields.map((field) => (
              <label key={field.key} className="typedEditField">
                <span>{field.label}</span>
                {field.input === "checkbox" ? (
                  <input
                    type="checkbox"
                    checked={editValues[field.key] === "true"}
                    onChange={(event) => setEditValues({ ...editValues, [field.key]: event.target.checked ? "true" : "false" })}
                  />
                ) : field.input === "number" ? (
                  <input
                    type="number"
                    value={editValues[field.key] ?? ""}
                    onChange={(event) => setEditValues({ ...editValues, [field.key]: event.target.value })}
                  />
                ) : (
                  <textarea
                    value={editValues[field.key] ?? ""}
                    onChange={(event) => setEditValues({ ...editValues, [field.key]: event.target.value })}
                  />
                )}
              </label>
            ))}
          </div>
        </div>
      ) : null}
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
      {type === "chapter_audit_report" ? (
        <div className="typedGrid">
          <TypedBlock title={zh ? "建议" : "Recommendation"} value={String(content.recommendation ?? "")} />
          <TypedBlock title={zh ? "维度分" : "Dimension Scores"} value={formatJson(content.dimension_scores)} />
          <TypedList title={zh ? "问题" : "Issues"} values={Array.isArray(content.issues) ? (content.issues as Array<Record<string, unknown>>).map((issue) => `${String(issue.severity ?? "")}: ${String(issue.message ?? issue.dimension ?? "")}`) : []} />
          <TypedBlock title={zh ? "门禁结果" : "Gate Results"} value={formatJson(content.gate_results)} />
          <TypedBlock title={zh ? "关联报告" : "Linked Reports"} value={formatJson(content.linked_reports)} />
        </div>
      ) : null}
      {type === "originality_report" ? (
        <div className="typedGrid">
          <TypedBlock title={zh ? "风险等级" : "Risk Level"} value={String(content.risk_level ?? "")} />
          <TypedBlock title={zh ? "建议" : "Recommendation"} value={String(content.recommendation ?? "")} />
          <TypedList title={zh ? "相似检查" : "Similarity Checks"} values={Array.isArray(content.similarity_checks) ? (content.similarity_checks as Array<Record<string, unknown>>).map((item) => `${String(item.source_title ?? item.source_asset_id ?? "")}: ${String(item.similarity ?? "")} (${String(item.risk ?? "")})`) : []} />
          <TypedList title={zh ? "风险命中" : "Forbidden Element Hits"} values={Array.isArray(content.forbidden_element_hits) ? (content.forbidden_element_hits as Array<Record<string, unknown>>).map((item) => `${String(item.kind ?? "")}: ${String(item.element ?? "")}`) : []} />
          <TypedBlock title={zh ? "人工门禁" : "Human Gate"} value={String(content.human_gate_required ?? "")} />
        </div>
      ) : null}
      {type === "publish_gate_report" ? (
        <div className="typedGrid">
          <TypedBlock title={zh ? "决策" : "Decision"} value={String(content.decision ?? "")} />
          <TypedBlock title={zh ? "门禁" : "Gates"} value={formatJson(content.gates)} />
          <TypedList title={zh ? "阻断问题" : "Blocking Issues"} values={Array.isArray(content.blocking_issues) ? (content.blocking_issues as Array<Record<string, unknown>>).map((issue) => `${String(issue.severity ?? "")}: ${String(issue.message ?? issue.dimension ?? "")}`) : []} />
          <TypedBlock title={zh ? "所需报告" : "Required Reports"} value={formatJson(content.required_reports)} />
          <TypedBlock title={zh ? "人工覆盖" : "Human Override"} value={String(content.human_override ?? "")} />
        </div>
      ) : null}
      {type === "release_package" ? (
        <div className="typedGrid">
          <TypedBlock title={zh ? "状态" : "Status"} value={String(content.status ?? "")} />
          <TypedList title={zh ? "候选标题" : "Title Candidates"} values={content.title_candidates} />
          <TypedBlock title={zh ? "摘要" : "Summary"} value={String(content.summary ?? "")} />
          <TypedList title={zh ? "标签" : "Tags"} values={content.tags} />
          <TypedBlock title={zh ? "渠道" : "Channel"} value={String(content.channel ?? "")} />
        </div>
      ) : null}
      {[
        "common_novel_analysis_report",
        "web_fiction_business_analysis_report",
        "published_fiction_analysis_report",
        "classic_literary_analysis_report",
        "analysis_conversion_report"
      ].includes(type) ? (
        <div className="typedGrid">
          <TypedBlock title={zh ? "版权/RAG 边界" : "Copyright/RAG Boundary"} value={`${String(metadata.copyright_risk ?? content.copyright_risk ?? "unknown")} / RAG: ${String(metadata.use_in_generation_rag ?? false)}`} />
          <TypedBlock title={zh ? "抽象层级" : "Abstraction"} value={String(metadata.abstraction_level ?? content.abstraction_level ?? "")} />
          <TypedBlock title={zh ? "源资产" : "Source Asset"} value={String(content.source_asset_id ?? content.source_report_id ?? "")} />
          <TypedList title={zh ? "可复用项" : "Reusable Items"} values={analysisReusableItems(type, content)} />
          <TypedBlock title={zh ? "结构/技法 JSON" : "Structure/Craft JSON"} value={analysisStructureJson(type, content)} />
          {type === "analysis_conversion_report" ? (
            <TypedList title={zh ? "已创建资产" : "Created Assets"} values={Array.isArray(content.created_assets) ? (content.created_assets as Array<Record<string, unknown>>).map((item) => `${String(item.type ?? "")}: ${String(item.path ?? "")}`) : []} />
          ) : null}
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
      {phase3Types.includes(type) ? <CreativeTypedSummary language={language} content={content} /> : null}
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

function CreativeTypedSummary({ language, content }: { language: Language; content: Record<string, unknown> }) {
  const zh = language === "zh";
  return (
    <div className="typedGrid">
      {Object.entries(content).slice(0, 12).map(([key, value]) => {
        if (Array.isArray(value)) {
          return <TypedList title={key} values={value} key={key} />;
        }
        return (
          <TypedBlock
            title={key}
            value={typeof value === "object" && value !== null ? JSON.stringify(value, null, 2) : String(value ?? "")}
            key={key}
          />
        );
      })}
      {!Object.keys(content).length ? <TypedBlock title={zh ? "内容" : "Content"} value="-" /> : null}
    </div>
  );
}

function analysisReusableItems(type: string, content: Record<string, unknown>): unknown {
  if (type === "common_novel_analysis_report") return content.reusable_findings;
  if (type === "web_fiction_business_analysis_report") return content.reusable_assets;
  if (type === "published_fiction_analysis_report") return content.transferable_techniques;
  if (type === "classic_literary_analysis_report") return content.transferable_abstractions;
  if (type === "analysis_conversion_report") return content.conversion_targets;
  return [];
}

function analysisStructureJson(type: string, content: Record<string, unknown>): string {
  const keysByType: Record<string, string[]> = {
    common_novel_analysis_report: ["structure_map", "character_map", "conflict_map", "theme_map"],
    web_fiction_business_analysis_report: ["platform_pattern", "reader_promise", "hook_system", "payoff_loop", "pacing_model"],
    published_fiction_analysis_report: ["craft_dimensions", "scene_design", "character_arc", "narrative_distance", "language_texture"],
    classic_literary_analysis_report: ["deep_structure", "theme_system", "symbol_system", "social_relation_model", "fate_curve"],
    analysis_conversion_report: ["created_assets", "rejected_items", "conversion_policy"]
  };
  const subset = Object.fromEntries((keysByType[type] ?? []).map((key) => [key, content[key]]));
  return JSON.stringify(subset, null, 2);
}

type TypedEditField = {
  key: string;
  label: string;
  value: string;
  input: "textarea" | "number" | "checkbox";
};

function typedEditableFields(
  type: string,
  content: Record<string, unknown>,
  metadata: Record<string, unknown>,
  asset: Record<string, unknown>,
  zh: boolean
): TypedEditField[] {
  const label = (cn: string, en: string) => (zh ? cn : en);
  const field = (key: string, title: string, value: unknown, input: TypedEditField["input"] = "textarea"): TypedEditField => ({
    key,
    label: title,
    value: typedFieldDisplayValue(value),
    input
  });
  if (type === "decomposition_report") {
    return [
      field("summary", label("摘要", "Summary"), content.summary),
      field("commercial_patterns", label("商业模式", "Commercial Patterns"), content.commercial_patterns),
      field("narrative_patterns", label("叙事模式", "Narrative Patterns"), content.narrative_patterns),
      field("character_mechanisms", label("人物机制", "Character Mechanisms"), content.character_mechanisms),
      field("conflict_patterns", label("冲突模式", "Conflict Patterns"), content.conflict_patterns),
      field("emotion_curve", label("情绪曲线", "Emotion Curve"), content.emotion_curve),
      field("hook_patterns", label("钩子模式", "Hook Patterns"), content.hook_patterns)
    ];
  }
  if (type === "knowledge_card") {
    return [
      field("principles", label("原则", "Principles"), content.principles),
      field("constraints", label("约束", "Constraints"), content.constraints),
      field("review_checks", label("审稿检查", "Review Checks"), content.review_checks),
      field("license_review_status", label("许可审核", "License Review"), metadata.license_review_status),
      field("raw_text_used", label("使用原文", "Raw Text Used"), metadata.raw_text_used ? "true" : "false", "checkbox")
    ];
  }
  if (type === "material_card") {
    return [
      field("usable_patterns", label("可用模式", "Usable Patterns"), content.usable_patterns),
      field("do_not_copy", label("禁止复制", "Do Not Copy"), content.do_not_copy),
      field("use_cases", label("适用场景", "Use Cases"), content.use_cases)
    ];
  }
  if (type === "draft_chapter") {
    return [
      field("chapter", label("章节", "Chapter"), content.chapter, "number"),
      field("text", label("正文", "Text"), content.text),
      field("draft_status", label("草稿状态", "Draft Status"), metadata.draft_status)
    ];
  }
  if (type === "review_report") {
    return [
      field("summary", label("摘要", "Summary"), content.summary),
      field("score", label("评分", "Score"), asset.score, "number"),
      field("risk_level", label("风险", "Risk"), asset.risk_level),
      field("strengths", label("优点", "Strengths"), asset.strengths),
      field("weaknesses", label("问题", "Weaknesses"), asset.weaknesses),
      field("revision_suggestions", label("修订建议", "Revision Suggestions"), asset.revision_suggestions),
      field("next_action", label("下一步", "Next Action"), asset.next_action)
    ];
  }
  if (type === "revision_plan") {
    return [
      field("steps", label("步骤", "Steps"), content.steps),
      field("target_score", label("目标评分", "Target Score"), content.target_score, "number"),
      field("must_preserve", label("必须保留", "Must Preserve"), content.must_preserve)
    ];
  }
  if (type === "chapter_audit_report") {
    return [
      field("target_asset_id", label("目标资产", "Target Asset"), content.target_asset_id),
      field("dimension_scores", label("维度分 JSON", "Dimension Scores JSON"), content.dimension_scores),
      field("issues", label("问题 JSON", "Issues JSON"), content.issues),
      field("gate_results", label("门禁结果 JSON", "Gate Results JSON"), content.gate_results),
      field("linked_reports", label("关联报告 JSON", "Linked Reports JSON"), content.linked_reports),
      field("recommendation", label("建议", "Recommendation"), content.recommendation)
    ];
  }
  if (type === "originality_report") {
    return [
      field("target_asset_id", label("目标资产", "Target Asset"), content.target_asset_id),
      field("source_asset_ids", label("来源资产", "Source Assets"), content.source_asset_ids),
      field("similarity_checks", label("相似检查 JSON", "Similarity Checks JSON"), content.similarity_checks),
      field("forbidden_element_hits", label("风险命中 JSON", "Forbidden Hits JSON"), content.forbidden_element_hits),
      field("plot_skeleton_risk", label("情节骨架风险", "Plot Skeleton Risk"), content.plot_skeleton_risk),
      field("character_setup_risk", label("角色配置风险", "Character Setup Risk"), content.character_setup_risk),
      field("style_expression_risk", label("风格表达风险", "Style Expression Risk"), content.style_expression_risk),
      field("risk_level", label("总风险", "Risk Level"), content.risk_level),
      field("recommendation", label("建议", "Recommendation"), content.recommendation),
      field("human_gate_required", label("人工门禁", "Human Gate Required"), content.human_gate_required ? "true" : "false", "checkbox")
    ];
  }
  if (type === "publish_gate_report") {
    return [
      field("target_asset_id", label("目标资产", "Target Asset"), content.target_asset_id),
      field("gates", label("门禁 JSON", "Gates JSON"), content.gates),
      field("decision", label("决策", "Decision"), content.decision),
      field("blocking_issues", label("阻断问题 JSON", "Blocking Issues JSON"), content.blocking_issues),
      field("required_reports", label("所需报告 JSON", "Required Reports JSON"), content.required_reports),
      field("human_override", label("人工覆盖", "Human Override"), content.human_override ? "true" : "false", "checkbox")
    ];
  }
  if (type === "release_package") {
    return [
      field("target_asset_id", label("目标资产", "Target Asset"), content.target_asset_id),
      field("publish_gate_report_id", label("门禁报告", "Publish Gate Report"), content.publish_gate_report_id),
      field("title_candidates", label("候选标题", "Title Candidates"), content.title_candidates),
      field("summary", label("摘要", "Summary"), content.summary),
      field("tags", label("标签", "Tags"), content.tags),
      field("channel", label("渠道", "Channel"), content.channel),
      field("status", label("状态", "Status"), content.status)
    ];
  }
  if (
    [
      "common_novel_analysis_report",
      "web_fiction_business_analysis_report",
      "published_fiction_analysis_report",
      "classic_literary_analysis_report",
      "analysis_conversion_report"
    ].includes(type)
  ) {
    return [
      field("source_asset_id", label("源资产", "Source Asset"), content.source_asset_id ?? content.source_report_id),
      field("copyright_risk", label("版权风险", "Copyright Risk"), content.copyright_risk ?? metadata.copyright_risk),
      field("abstraction_level", label("抽象层级", "Abstraction Level"), content.abstraction_level ?? metadata.abstraction_level),
      field("analysis_metrics", label("分析指标 JSON", "Analysis Metrics JSON"), content.analysis_metrics),
      field("reusable_findings", label("可复用发现", "Reusable Findings"), analysisReusableItems(type, content)),
      field("conversion_targets", label("转换目标", "Conversion Targets"), content.conversion_targets),
      field("created_assets", label("已创建资产 JSON", "Created Assets JSON"), content.created_assets),
      field("rejected_items", label("拒绝项 JSON", "Rejected Items JSON"), content.rejected_items)
    ];
  }
  const phase3Editable = new Set([
    "platform_profile",
    "genre_market_profile",
    "topic_seed",
    "topic_fit_report",
    "world_bible",
    "character_card",
    "continuity_bible",
    "foreshadowing_thread",
    "power_scale_rule",
    "style_profile",
    "style_decomposition_report",
    "style_blend_preset",
    "quality_standard_profile",
    "review_rule_pack",
    "quality_score_report",
    "style_review_report",
    "common_novel_analysis_report",
    "web_fiction_business_analysis_report",
    "published_fiction_analysis_report",
    "classic_literary_analysis_report",
    "analysis_conversion_report",
    "writing_template",
    "craft_template"
  ]);
  if (phase3Editable.has(type)) {
    return creativeBusinessFields(type, content, field, label);
  }
  return [];
}

function creativeBusinessFields(
  type: string,
  content: Record<string, unknown>,
  field: (key: string, title: string, value: unknown, input?: TypedEditField["input"]) => TypedEditField,
  label: (cn: string, en: string) => string
): TypedEditField[] {
  const map: Record<string, Array<[string, string, string, TypedEditField["input"]?]>> = {
    platform_profile: [
      ["platform_id", "平台 ID", "Platform ID"],
      ["platform_name", "平台名称", "Platform Name"],
      ["business_model", "商业模型", "Business Model"],
      ["reader_expectation", "读者预期", "Reader Expectations"],
      ["chapter_length_range", "章节字数范围 JSON", "Chapter Length Range JSON"],
      ["update_frequency", "更新频率", "Update Frequency"],
      ["opening_rules", "开篇规则 JSON", "Opening Rules JSON"],
      ["review_risks", "审核/商业风险", "Review Risks"],
      ["genre_fit", "适配题材", "Genre Fit"],
      ["style_tendency", "文风倾向", "Style Tendency"]
    ],
    genre_market_profile: [
      ["genre", "题材", "Genre"],
      ["platform_id", "平台 ID", "Platform ID"],
      ["reader_promise", "读者承诺", "Reader Promise"],
      ["common_hooks", "常用钩子", "Common Hooks"],
      ["common_conflicts", "常用冲突", "Common Conflicts"],
      ["fatigue_points", "疲劳点", "Fatigue Points"],
      ["differentiation_axes", "差异化轴", "Differentiation Axes"],
      ["chapter_rhythm_template", "章节节奏模板", "Chapter Rhythm Template"]
    ],
    topic_seed: [
      ["logline", "一句话卖点", "Logline"],
      ["reader_attraction", "读者吸引点", "Reader Attraction"],
      ["differentiation", "差异化", "Differentiation"],
      ["platform_id", "平台 ID", "Platform ID"],
      ["genre", "题材", "Genre"],
      ["reader_promise", "读者承诺", "Reader Promise"],
      ["differentiation_axes", "差异化轴", "Differentiation Axes"]
    ],
    topic_fit_report: [
      ["topic_seed_id", "题材种子", "Topic Seed"],
      ["platform_id", "平台 ID", "Platform ID"],
      ["genre", "题材", "Genre"],
      ["scores", "评分 JSON", "Scores JSON"],
      ["recommendation", "建议", "Recommendation"],
      ["must_adjust", "必须调整", "Must Adjust"]
    ],
    asset_collection: [
      ["purpose", "集合用途", "Purpose"],
      ["asset_paths", "资产路径", "Asset Paths"],
      ["selection_criteria", "筛选标准", "Selection Criteria"],
      ["use_cases", "适用场景", "Use Cases"],
      ["excluded_assets", "排除资产", "Excluded Assets"]
    ],
    world_bible: [
      ["setting", "设定概述", "Setting"],
      ["rules", "世界规则", "Rules"],
      ["conflict_system", "冲突系统", "Conflict System"]
    ],
    character_card: [
      ["role", "角色定位", "Role"],
      ["external_goal", "外部目标", "External Goal"],
      ["internal_need", "内部需求", "Internal Need"],
      ["motivation_chain", "动机链", "Motivation Chain"]
    ],
    continuity_bible: [
      ["project_id", "项目 ID", "Project ID"],
      ["worldview_rules", "世界观规则", "Worldview Rules"],
      ["timeline", "时间线", "Timeline"],
      ["entities", "实体状态", "Entities"],
      ["open_threads", "开放线程", "Open Threads"],
      ["constraints", "连续性约束", "Constraints"]
    ],
    foreshadowing_thread: [
      ["thread_id", "伏笔 ID", "Thread ID"],
      ["setup", "投放", "Setup"],
      ["payoff_plan", "回收计划", "Payoff Plan"],
      ["status", "状态", "Status"],
      ["related_chapters", "相关章节", "Related Chapters"]
    ],
    power_scale_rule: [
      ["scale_id", "体系 ID", "Scale ID"],
      ["levels", "等级", "Levels"],
      ["constraints", "约束", "Constraints"],
      ["violation_checks", "违规检查", "Violation Checks"]
    ],
    style_profile: [
      ["style_id", "文风 ID", "Style ID"],
      ["name", "名称", "Name"],
      ["scope", "范围", "Scope"],
      ["source_boundary", "来源边界 JSON", "Source Boundary JSON"],
      ["language_parameters", "语言参数 JSON", "Language Parameters JSON"],
      ["narrative_parameters", "叙事参数 JSON", "Narrative Parameters JSON"],
      ["emotion_parameters", "情绪参数 JSON", "Emotion Parameters JSON"],
      ["forbidden_patterns", "禁用模式", "Forbidden Patterns"]
    ],
    style_decomposition_report: [
      ["source_asset_id", "来源资产", "Source Asset"],
      ["extract_level", "提取级别", "Extract Level"],
      ["style_features", "风格特征 JSON", "Style Features JSON"],
      ["usable_parameters", "可用参数 JSON", "Usable Parameters JSON"],
      ["do_not_copy", "禁止复制", "Do Not Copy"],
      ["risk_level", "风险", "Risk Level"]
    ],
    style_blend_preset: [
      ["name", "名称", "Name"],
      ["components", "混合组件 JSON", "Components JSON"],
      ["conflict_resolution", "冲突解决 JSON", "Conflict Resolution JSON"]
    ],
    style_review_report: [
      ["target_draft_id", "目标草稿", "Target Draft"],
      ["expected_style_profile_id", "目标文风", "Expected Style Profile"],
      ["style_match_score", "匹配分", "Style Match Score", "number"],
      ["drift_points", "漂移点", "Drift Points"],
      ["ai_taste_points", "AI 味问题", "AI Taste Points"],
      ["rewrite_suggestions", "改写建议", "Rewrite Suggestions"],
      ["copyright_style_risk", "版权风格风险", "Copyright Style Risk"]
    ],
    quality_standard_profile: [
      ["standard_id", "标准 ID", "Standard ID"],
      ["name", "名称", "Name"],
      ["platform_id", "平台 ID", "Platform ID"],
      ["genre", "题材", "Genre"],
      ["target_length", "篇幅目标", "Target Length"],
      ["dimensions", "维度 JSON", "Dimensions JSON"],
      ["hard_gates", "硬门禁", "Hard Gates"]
    ],
    review_rule_pack: [
      ["rule_pack_id", "规则包 ID", "Rule Pack ID"],
      ["name", "名称", "Name"],
      ["dimensions", "维度 JSON", "Dimensions JSON"],
      ["checks", "检查项", "Checks"],
      ["severity_policy", "严重度策略 JSON", "Severity Policy JSON"]
    ],
    quality_score_report: [
      ["target_asset_id", "目标资产", "Target Asset"],
      ["standard_id", "标准 ID", "Standard ID"],
      ["overall_score", "总分", "Overall Score", "number"],
      ["scores", "维度分 JSON", "Scores JSON"],
      ["gate_results", "门禁结果 JSON", "Gate Results JSON"],
      ["recommendation", "建议", "Recommendation"]
    ],
    writing_template: [
      ["template_id", "模板 ID", "Template ID"],
      ["name", "名称", "Name"],
      ["template_kind", "模板类型", "Template Kind"],
      ["structure", "结构", "Structure"],
      ["usage_constraints", "使用约束", "Usage Constraints"],
      ["anti_copy_rules", "防复制规则", "Anti-copy Rules"]
    ],
    craft_template: [
      ["template_id", "模板 ID", "Template ID"],
      ["name", "名称", "Name"],
      ["craft_domain", "技法领域", "Craft Domain"],
      ["pattern", "模式", "Pattern"],
      ["use_cases", "适用场景", "Use Cases"],
      ["risks", "风险", "Risks"]
    ]
  };
  return (map[type] ?? Object.keys(content).map((key) => [key, key, key] as [string, string, string])).map(([key, cn, en, input]) =>
    field(key, label(cn, en), content[key], input ?? (typeof content[key] === "number" ? "number" : "textarea"))
  );
}

function typedFieldDisplayValue(value: unknown): string {
  if (Array.isArray(value)) {
    if (value.some((item) => typeof item === "object" && item !== null)) {
      return JSON.stringify(value, null, 2);
    }
    return value.map(String).join("\n");
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return value === undefined || value === null ? "" : String(value);
}

function formatJson(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function typedEditPayload(fields: TypedEditField[], values: Record<string, string>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const field of fields) {
    if (field.input === "checkbox") {
      payload[field.key] = values[field.key] === "true";
    } else if (field.input === "number") {
      payload[field.key] = values[field.key] === "" ? 0 : Number(values[field.key]);
    } else {
      payload[field.key] = values[field.key] ?? "";
    }
  }
  return payload;
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
        mark_completed: true,
        semantic_review: true
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
              {validation.semantic_review?.enabled === false ? "" : ` | review ${validation.semantic_review?.score ?? "-"} / ${validation.semantic_review?.minimum_score ?? "-"}`}
              {validation.errors.length ? `: ${validation.errors.join("; ")}` : ""}
              {validation.warnings.length ? ` (${validation.warnings.join("; ")})` : ""}
              {validation.semantic_review?.error ? ` provider: ${validation.semantic_review.error}` : ""}
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

function AnalysisPanel(props: {
  language: Language;
  tab: TabKey;
  reports: AnalysisReportRow[];
  assets: AssetRow[];
  handoffs: HandoffRow[];
  sourcePath: string;
  setSourcePath: (value: string) => void;
  reportPath: string;
  setReportPath: (value: string) => void;
  targets: string;
  setTargets: (value: string) => void;
  busy: boolean;
  onRunAnalysis: (analysisType: string) => void;
  onCreateHandoff: (analysisType: string) => void;
  onConvert: (reportPath?: string) => void;
  onOpenAsset: (path: string) => void;
  onOpenHandoff: (path: string) => void;
}) {
  const zh = props.language === "zh";
  const selectedType = analysisTypeForTab(props.tab);
  const [analysisType, setAnalysisType] = useState(selectedType);
  useEffect(() => {
    setAnalysisType(selectedType);
  }, [selectedType]);
  const visibleReports = props.reports.filter((report) => {
    if (props.tab === "analysis_center" || props.tab === "asset_converter") return true;
    return report.type === analysisReportTypeForRequest(analysisType);
  });
  const analysisHandoffs = props.handoffs.filter((handoff) =>
    [
      "hot_novel_business_deconstruction",
      "published_fiction_craft_analysis",
      "classic_literary_depth_analysis",
      "analysis_to_asset_conversion"
    ].includes(handoff.operation)
  );
  const reportCounts = {
    web: props.reports.filter((report) => report.type === "web_fiction_business_analysis_report").length,
    published: props.reports.filter((report) => report.type === "published_fiction_analysis_report").length,
    classic: props.reports.filter((report) => report.type === "classic_literary_analysis_report").length,
    conversions: props.reports.filter((report) => report.type === "analysis_conversion_report").length
  };
  return (
    <section className="panel">
      <PanelHeader title={copy[props.language].tabs[props.tab]} icon={<FileSearch size={18} />} />
      <div className="typedGrid">
        <Metric label={zh ? "网文商业报告" : "Web fiction reports"} value={String(reportCounts.web)} />
        <Metric label={zh ? "出版技法报告" : "Published craft reports"} value={String(reportCounts.published)} />
        <Metric label={zh ? "名著深读报告" : "Classic reports"} value={String(reportCounts.classic)} />
        <Metric label={zh ? "转换记录" : "Conversions"} value={String(reportCounts.conversions)} />
      </div>
      <div className="noticeLine">
        {zh
          ? "分析报告只用于结构学习和审稿观察，默认不进入正文生成 RAG；必须先转换成抽象资产。"
          : "Analysis reports are for structural learning and review only. They do not enter generation RAG until converted into abstract assets."}
      </div>
      <div className="formGrid wide">
        <label className="inlineField">
          <span>{zh ? "源资产路径" : "Source asset path"}</span>
          <input value={props.sourcePath} onChange={(event) => props.setSourcePath(event.target.value)} />
        </label>
        <label className="inlineField">
          <span>{zh ? "分析类型" : "Analysis type"}</span>
          <select value={analysisType} onChange={(event) => setAnalysisType(event.target.value)}>
            <option value="web_fiction_business">{zh ? "网文商业结构" : "Web fiction business"}</option>
            <option value="published_fiction">{zh ? "出版小说技法" : "Published fiction craft"}</option>
            <option value="classic_literary">{zh ? "经典名著深读" : "Classic literary depth"}</option>
            <option value="common">{zh ? "通用小说结构" : "Common novel analysis"}</option>
          </select>
        </label>
        <button className="primaryButton" disabled={props.busy || !props.sourcePath} onClick={() => props.onRunAnalysis(analysisType)}>
          <Play size={18} />
          {zh ? "运行本地分析" : "Run Local Analysis"}
        </button>
        <button className="secondaryButton" disabled={props.busy || !props.sourcePath} onClick={() => props.onCreateHandoff(analysisType)}>
          <Workflow size={18} />
          Claude Code
        </button>
      </div>
      <div className="processStrip">
        {["select source", "analyze", "human/model handoff", "convert", "review assets"].map((step) => (
          <span key={step}>
            <CheckCircle2 size={16} />
            {step}
          </span>
        ))}
      </div>
      {props.assets.length ? (
        <div className="assetChipGrid">
          {props.assets.slice(0, 10).map((asset) => (
            <button className="linkButton" key={asset.path} onClick={() => props.setSourcePath(asset.path)}>
              {asset.type}: {asset.title || asset.path}
            </button>
          ))}
        </div>
      ) : null}

      <div className="splitGrid">
        <div className="panel nestedPanel">
          <PanelHeader title={zh ? "分析报告" : "Analysis Reports"} icon={<Layers3 size={18} />} />
          <DataTable
            emptyText={zh ? "暂无分析报告" : "No analysis reports"}
            columns={zh ? ["类型", "标题", "风险", "RAG", "转换资产", "操作"] : ["Type", "Title", "Risk", "RAG", "Converted", "Action"]}
            rows={visibleReports.map((report) => [
              <span className="badge muted" key={`type-${report.path}`}>{report.type}</span>,
              report.title,
              <span className={report.copyright_risk === "high" ? "badge warn" : "badge ok"} key={`risk-${report.path}`}>
                {report.copyright_risk || "unknown"}
              </span>,
              report.use_in_generation_rag ? "enabled" : "blocked",
              String(report.created_assets),
              <div className="tableActions" key={`actions-${report.path}`}>
                <button className="linkButton" onClick={() => props.onOpenAsset(report.path)}>{zh ? "打开" : "Open"}</button>
                {report.type !== "analysis_conversion_report" ? (
                  <button
                    className="secondaryButton tableButton"
                    onClick={() => {
                      props.setReportPath(report.path);
                      props.onConvert(report.path);
                    }}
                    disabled={props.busy}
                  >
                    {zh ? "转换" : "Convert"}
                  </button>
                ) : null}
              </div>
            ])}
          />
        </div>
        <div className="panel nestedPanel">
          <PanelHeader title={zh ? "统一资产转换器" : "Unified Asset Converter"} icon={<Workflow size={18} />} />
          <div className="formStack">
            <label className="inlineField">
              <span>{zh ? "报告路径" : "Report path"}</span>
              <input value={props.reportPath} onChange={(event) => props.setReportPath(event.target.value)} />
            </label>
            <label className="inlineField">
              <span>{zh ? "目标资产类型" : "Target asset types"}</span>
              <input value={props.targets} onChange={(event) => props.setTargets(event.target.value)} />
            </label>
            <button className="primaryButton" disabled={props.busy || !props.reportPath} onClick={() => props.onConvert(props.reportPath)}>
              <Archive size={18} />
              {zh ? "转换为抽象资产" : "Convert to Abstract Assets"}
            </button>
          </div>
          <ul className="checkList">
            {(zh
              ? ["报告本身不进正文 RAG", "高版权风险默认阻断素材/模板化", "输出资产带 reuse_scope 与 abstraction_level", "转换记录可追溯"]
              : ["Reports stay out of generation RAG", "High copyright risk blocks material/template conversion", "Outputs carry reuse_scope and abstraction_level", "Conversion is traceable"]
            ).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="panel nestedPanel">
        <PanelHeader title={zh ? "分析 Handoff" : "Analysis Handoffs"} icon={<Workflow size={18} />} />
        <DataTable
          emptyText={zh ? "暂无分析 handoff" : "No analysis handoffs"}
          columns={zh ? ["操作", "状态", "期望输出", "来源", "路径"] : ["Operation", "Status", "Expected", "Source", "Path"]}
          rows={analysisHandoffs.map((handoff) => [
            handoff.operation,
            <span className={handoff.status === "completed" ? "badge ok" : handoff.status === "failed" ? "badge warn" : "badge muted"} key={`status-${handoff.path}`}>
              {handoff.status}
            </span>,
            handoff.expected_output_type,
            handoff.source_path,
            <button className="linkButton" onClick={() => props.onOpenHandoff(handoff.path)} key={handoff.path}>
              {handoff.path}
            </button>
          ])}
        />
      </div>
    </section>
  );
}

function analysisTypeForTab(tab: TabKey): string {
  const mapping: Partial<Record<TabKey, string>> = {
    web_fiction_analysis: "web_fiction_business",
    published_fiction_analysis: "published_fiction",
    classic_literary_analysis: "classic_literary",
    asset_converter: "web_fiction_business",
    analysis_center: "web_fiction_business"
  };
  return mapping[tab] ?? "web_fiction_business";
}

function analysisReportTypeForRequest(analysisType: string): string {
  const mapping: Record<string, string> = {
    common: "common_novel_analysis_report",
    web_fiction_business: "web_fiction_business_analysis_report",
    published_fiction: "published_fiction_analysis_report",
    classic_literary: "classic_literary_analysis_report"
  };
  return mapping[analysisType] ?? "web_fiction_business_analysis_report";
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

function QualityGatePanel(props: {
  language: Language;
  mode: "originality_center" | "publishing_center";
  assets: AssetRow[];
  drafts: DraftWorkbench | null;
  selectedDraft: string;
  setSelectedDraft: (value: string) => void;
  selectedWorkspace: string;
  setSelectedWorkspace: (value: string) => void;
  busy: boolean;
  onRunOriginality: () => void;
  onRunChapterAudit: () => void;
  onRunPublishGate: () => void;
  onCreateReleasePackage: () => void;
  onOpenAsset: (path: string) => void;
}) {
  const zh = props.language === "zh";
  const reportTypes =
    props.mode === "originality_center"
      ? ["originality_report", "chapter_audit_report"]
      : ["publish_gate_report", "release_package", "chapter_audit_report", "originality_report"];
  const reports = props.assets.filter((asset) => reportTypes.includes(asset.type));
  const latest = (type: string) => reports.find((asset) => asset.type === type);
  return (
    <section className="workspaceGrid">
      <div className="panel">
        <PanelHeader
          title={props.mode === "originality_center" ? (zh ? "原创性保护工作台" : "Originality Protection Workbench") : (zh ? "发布门禁工作台" : "Publishing Gate Workbench")}
          icon={props.mode === "originality_center" ? <ShieldCheck size={18} /> : <Send size={18} />}
        />
        <div className="formGrid">
          <SelectPath label={zh ? "目标草稿" : "Target Draft"} latestLabel={zh ? "请选择草稿" : "Select Draft"} value={props.selectedDraft} onChange={props.setSelectedDraft} rows={props.drafts?.drafts ?? []} />
          <SelectPath label={zh ? "项目工作区" : "Project Workspace"} latestLabel={zh ? "当前项目" : "Current Project"} value={props.selectedWorkspace} onChange={props.setSelectedWorkspace} rows={props.drafts?.workspace ?? []} />
        </div>
        <div className="summaryBand">
          <Metric label={zh ? "原创性报告" : "Originality"} value={latest("originality_report")?.risk_level || "-"} />
          <Metric label={zh ? "章节审稿" : "Chapter Audit"} value={latest("chapter_audit_report")?.risk_level || "-"} />
          <Metric label={zh ? "发布门禁" : "Publish Gate"} value={latest("publish_gate_report")?.risk_level || "-"} />
          <Metric label={zh ? "发布包" : "Release"} value={latest("release_package")?.asset_status || latest("release_package")?.risk_level || "-"} />
        </div>
        <div className="quickActions">
          <button className="primaryButton" disabled={props.busy || !props.selectedDraft} onClick={props.onRunOriginality}>
            <ShieldCheck size={18} />
            {zh ? "运行原创性检查" : "Run Originality Check"}
          </button>
          <button className="secondaryButton" disabled={props.busy || !props.selectedDraft} onClick={props.onRunChapterAudit}>
            <FileSearch size={18} />
            {zh ? "生成章节审稿" : "Create Chapter Audit"}
          </button>
          <button className="secondaryButton" disabled={props.busy || !props.selectedDraft} onClick={props.onRunPublishGate}>
            <CheckCircle2 size={18} />
            {zh ? "执行发布门禁" : "Run Publish Gate"}
          </button>
          <button className="primaryButton" disabled={props.busy || !props.selectedDraft} onClick={props.onCreateReleasePackage}>
            <Send size={18} />
            {zh ? "生成发布包" : "Create Release Package"}
          </button>
        </div>
      </div>
      <div className="panel">
        <PanelHeader title={zh ? "门禁证据链" : "Gate Evidence Chain"} icon={<ListChecks size={18} />} />
        <DataTable
          emptyText={zh ? "还没有门禁报告" : "No gate reports yet"}
          columns={zh ? ["类型", "标题", "风险/状态", "路径"] : ["Type", "Title", "Risk/Status", "Path"]}
          rows={reports.map((asset) => [
            asset.type,
            asset.title,
            asset.risk_level || asset.asset_status || "-",
            <button className="linkButton" key={asset.path} onClick={() => props.onOpenAsset(asset.path)}>
              {asset.path}
            </button>
          ])}
        />
      </div>
      <div className="panel">
        <PanelHeader title={zh ? "V6 发布前约束" : "V6 Pre-release Constraints"} icon={<SlidersHorizontal size={18} />} />
        <ul className="checkList">
          <li>{zh ? "章节生成必须携带平台、题材、精品标准、文风和连续性设定。" : "Chapter production must carry platform, genre, quality, style, and continuity profiles."}</li>
          <li>{zh ? "原创性报告高风险会阻断发布门禁。" : "High originality risk blocks the publish gate."}</li>
          <li>{zh ? "发布包只能从通过门禁的草稿生成；未通过时状态为 blocked。" : "Release packages are ready only after the gate passes; otherwise they are blocked."}</li>
          <li>{zh ? "报告资产都按项目隔离，并可从资产详情页追溯来源。" : "All report assets remain project-scoped and traceable from asset details."}</li>
        </ul>
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
