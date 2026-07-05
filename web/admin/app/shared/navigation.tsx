import {
  Activity,
  BarChart3,
  BookMarked,
  BookOpenCheck,
  BookOpen,
  Boxes,
  CheckCircle2,
  CreditCard,
  Database,
  FileSearch,
  GitPullRequest,
  Home,
  Layers3,
  Library,
  ListChecks,
  MessageSquareText,
  Network,
  PenLine,
  Route,
  Save,
  Send,
  Server,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Wand2,
  Workflow
} from "lucide-react";
import type { ReactNode } from "react";

export type NavGroupKey = "workspace" | "os" | "assets" | "analysis" | "production" | "management";

export type NavItemKey =
  | "workbench"
  | "projects"
  | "os_console"
  | "editor_chief_console"
  | "workflow_runtime"
  | "agent_center"
  | "agent_registry"
  | "agent_dispatch"
  | "agent_operation_coverage"
  | "audit_log"
  | "permission_center"
  | "canon_console"
  | "canon_graph_v2"
  | "character_console"
  | "arc_console"
  | "foreshadowing_console"
  | "review_issue_console"
  | "longform_recap"
  | "loop_runs"
  | "novel_kg_workbench"
  | "trace_timeline"
  | "retrieval_status"
  | "cost_dashboard"
  | "invalidation_map"
  | "review_rework_board"
  | "longform_stability"
  | "long_chain_proof"
  | "genre_console"
  | "topic_library"
  | "material_library"
  | "knowledge_library"
  | "mkaos"
  | "novel_kg"
  | "setting_bible"
  | "style_center"
  | "style_console_v2"
  | "writing_templates"
  | "quality_standards"
  | "analysis_center"
  | "web_fiction_analysis"
  | "published_fiction_analysis"
  | "classic_literary_analysis"
  | "asset_converter"
  | "batch_deconstruction"
  | "outline_generation"
  | "chapter_plan_generation"
  | "context_builder"
  | "chapter_production"
  | "ai_editor"
  | "review_center"
  | "originality_center"
  | "publishing_center"
  | "publish_gate_console"
  | "reader_feedback"
  | "feedback_console"
  | "production_control"
  | "change_impact"
  | "model_evaluation"
  | "quality_eval_v2"
  | "publishing_feedback_v2"
  | "analytics_dashboard"
  | "data_statistics"
  | "settings_center"
  | "task_center"
  | "handoffs"
  | "health";

export type NavItem = {
  key: NavItemKey;
  label: string;
  description: string;
  href: string;
  icon: ReactNode;
};

export type NavGroup = {
  key: NavGroupKey;
  label: string;
  items: NavItem[];
};

export const navGroups: NavGroup[] = [
  {
    key: "workspace",
    label: "工作区",
    items: [
      { key: "workbench", label: "工作台", description: "本地小说工厂总览", href: "/", icon: <Home size={17} /> },
      { key: "projects", label: "项目管理", description: "项目生命周期与绑定配置", href: "/projects", icon: <Boxes size={17} /> }
    ]
  },
  {
    key: "os",
    label: "OS Runtime",
    items: [
      { key: "os_console", label: "OS 控制台", description: "Novel Operating System 总览", href: "/os", icon: <Activity size={17} /> },
      { key: "editor_chief_console", label: "总编控制台", description: "全书健康、主线、人物、伏笔、疲劳和发布判断", href: "/editor-chief", icon: <BookOpenCheck size={17} /> },
      { key: "workflow_runtime", label: "Workflow Runtime", description: "DAG、ready queue 和 resume 控制台", href: "/workflow-runtime", icon: <Workflow size={17} /> },
      { key: "agent_center", label: "Agent Center", description: "AgentTask、Loop、Issue 和运行证据", href: "/agent-center", icon: <ListChecks size={17} /> },
      { key: "agent_registry", label: "Agent Registry", description: "Agent 元数据、生命周期和调度资格", href: "/agent-registry", icon: <ListChecks size={17} /> },
      { key: "agent_dispatch", label: "Agent Dispatch", description: "Agent queue、lease、recover 和 contract", href: "/agent-dispatch", icon: <ListChecks size={17} /> },
      { key: "agent_operation_coverage", label: "Operation Coverage", description: "V7 Agent operation coverage", href: "/agent-operation-coverage", icon: <ListChecks size={17} /> },
      { key: "audit_log", label: "Audit Log", description: "治理级 audit trail 和证据导出", href: "/audit-log", icon: <FileSearch size={17} /> },
      { key: "permission_center", label: "Permission Center", description: "agent/tool/source/publish/bypass 权限和人工审批", href: "/permission-center", icon: <ShieldCheck size={17} /> },
      { key: "canon_console", label: "Canon Console", description: "正典、事实账本和设定规则", href: "/canon-console", icon: <BookOpenCheck size={17} /> },
      { key: "canon_graph_v2", label: "Canon Graph 2.0", description: "题材插件一致性 gate", href: "/canon-graph-v2", icon: <Network size={17} /> },
      { key: "character_console", label: "Character Console", description: "人物卡和人物状态账本", href: "/character-console", icon: <BookMarked size={17} /> },
      { key: "arc_console", label: "Arc Console", description: "长篇主线、阶段弧线和章节状态", href: "/arc-console", icon: <GitPullRequest size={17} /> },
      { key: "foreshadowing_console", label: "Foreshadowing", description: "伏笔线程、伏笔图谱和回收状态", href: "/foreshadowing-console", icon: <Network size={17} /> },
      { key: "novel_kg_workbench", label: "Novel KG Workbench", description: "实体、关系、路径、影响和 KG gate", href: "/novel-kg", icon: <Network size={17} /> },
      { key: "review_issue_console", label: "Review Issues", description: "阻断问题、修订任务和 rework", href: "/review-issues", icon: <ShieldCheck size={17} /> },
      { key: "longform_recap", label: "Longform Recap", description: "长篇复盘报告和治理写回", href: "/longform-recap", icon: <BookOpenCheck size={17} /> },
      { key: "loop_runs", label: "Loop Runs", description: "LoopRun、step、checkpoint 和 report", href: "/loop-runs", icon: <Route size={17} /> },
      { key: "trace_timeline", label: "Trace Timeline", description: "统一 trace/span 时间线", href: "/trace-timeline", icon: <Route size={17} /> },
      { key: "retrieval_status", label: "Retrieval / pgvector", description: "pgvector PoC、source isolation 和 dirty index", href: "/retrieval", icon: <Database size={17} /> },
      { key: "cost_dashboard", label: "Cost Dashboard", description: "成本账本、模型调用和预算告警", href: "/cost-dashboard", icon: <CreditCard size={17} /> },
      { key: "invalidation_map", label: "Invalidation Map", description: "变更影响、KG dirty 和下游失效", href: "/invalidation", icon: <GitPullRequest size={17} /> },
      { key: "review_rework_board", label: "Review Rework", description: "审稿问题到发布门禁闭环", href: "/review-rework", icon: <ShieldCheck size={17} /> },
      { key: "longform_stability", label: "Longform Stability", description: "正典、章节状态、卷级推进和 OS 验收", href: "/longform-stability", icon: <BookOpenCheck size={17} /> },
      { key: "long_chain_proof", label: "Long-chain Proof", description: "50/100/300 章内容智能 proof", href: "/long-chain-proof", icon: <GitPullRequest size={17} /> }
    ]
  },
  {
    key: "assets",
    label: "创作资产",
    items: [
      { key: "topic_library", label: "题材库", description: "平台、题材、选题资产", href: "/assets?library=topics", icon: <BookMarked size={17} /> },
      { key: "material_library", label: "素材库", description: "可复用素材卡", href: "/assets?library=materials", icon: <Library size={17} /> },
      { key: "knowledge_library", label: "知识库", description: "多学科知识卡", href: "/assets?library=knowledge", icon: <Database size={17} /> },
      { key: "mkaos", label: "MKAOS", description: "知识中枢、规则中枢和使用留痕", href: "/mkaos", icon: <Database size={17} /> },
      { key: "novel_kg", label: "Novel KG", description: "实体、关系、时间线和伏笔图谱", href: "/kg", icon: <Network size={17} /> },
      { key: "genre_console", label: "Genre Console", description: "Genre OS 策略包和风险 gate", href: "/genre-console", icon: <Library size={17} /> },
      { key: "setting_bible", label: "设定书", description: "世界观、连续性和长篇设定", href: "/assets?library=bible", icon: <BookOpen size={17} /> },
      { key: "style_center", label: "文风中心", description: "参数化 style profile", href: "/assets?library=style", icon: <Wand2 size={17} /> },
      { key: "style_console_v2", label: "Style Console", description: "Style OS 样本隔离和漂移 gate", href: "/style-console", icon: <Wand2 size={17} /> },
      { key: "writing_templates", label: "写作模板", description: "冲突、节奏、钩子和修辞模板", href: "/templates", icon: <PenLine size={17} /> },
      { key: "quality_standards", label: "精品标准", description: "质量标准和审稿规则", href: "/assets?library=quality", icon: <ShieldCheck size={17} /> }
    ]
  },
  {
    key: "analysis",
    label: "分析拆解",
    items: [
      { key: "analysis_center", label: "分析拆解中心", description: "统一分析入口", href: "/analysis", icon: <FileSearch size={17} /> },
      { key: "web_fiction_analysis", label: "网文商业结构", description: "商业结构和爽点拆解", href: "/analysis?mode=web_fiction_business", icon: <Layers3 size={17} /> },
      { key: "published_fiction_analysis", label: "出版技法拆解", description: "出版小说技法抽象", href: "/analysis?mode=published_fiction", icon: <BookOpen size={17} /> },
      { key: "classic_literary_analysis", label: "名著深度拆解", description: "经典名著结构分析", href: "/analysis?mode=classic_literary", icon: <BookMarked size={17} /> },
      { key: "asset_converter", label: "资产转换器", description: "拆解报告转可复用资产", href: "/analysis?mode=converter", icon: <Workflow size={17} /> },
      { key: "batch_deconstruction", label: "批量拆书", description: "批处理 item 和 Claude Code 模式", href: "/batch", icon: <ListChecks size={17} /> }
    ]
  },
  {
    key: "production",
    label: "生产流程",
    items: [
      { key: "outline_generation", label: "大纲生成", description: "大纲版本链", href: "/production?stage=outline", icon: <GitPullRequest size={17} /> },
      { key: "chapter_plan_generation", label: "细纲生成", description: "章节计划版本链", href: "/production?stage=chapter_plan", icon: <ListChecks size={17} /> },
      { key: "context_builder", label: "上下文构建器", description: "RAG 与 token 预算", href: "/context", icon: <Network size={17} /> },
      { key: "chapter_production", label: "章节生产", description: "生成记录和稿件版本", href: "/manuscript", icon: <PenLine size={17} /> },
      { key: "ai_editor", label: "AI 编辑器", description: "patch、diff 和回滚", href: "/editor", icon: <Save size={17} /> },
      { key: "review_center", label: "审稿中心", description: "审稿和修订闭环", href: "/review", icon: <CheckCircle2 size={17} /> },
      { key: "originality_center", label: "原创性保护", description: "原创风险与质量门禁", href: "/quality?tab=originality", icon: <ShieldCheck size={17} /> },
      { key: "publishing_center", label: "发布中心", description: "发布前门禁和 release package", href: "/quality?tab=publishing", icon: <Send size={17} /> },
      { key: "publish_gate_console", label: "Publish Gate", description: "发布门禁和 release package 控制台", href: "/publish-gate", icon: <Send size={17} /> },
      { key: "reader_feedback", label: "读者反馈", description: "评论导入和策略回写", href: "/feedback", icon: <MessageSquareText size={17} /> },
      { key: "feedback_console", label: "Feedback Console", description: "读者反馈、编辑反馈和回写证据", href: "/feedback-console", icon: <MessageSquareText size={17} /> }
    ]
  },
  {
    key: "management",
    label: "管理工具",
    items: [
      { key: "production_control", label: "生产总控", description: "运行实体观测", href: "/control", icon: <Activity size={17} /> },
      { key: "change_impact", label: "变更影响", description: "长篇变更影响分析", href: "/impact", icon: <GitPullRequest size={17} /> },
      { key: "model_evaluation", label: "模型评测", description: "Benchmark 和模型路由", href: "/evaluation", icon: <SlidersHorizontal size={17} /> },
      { key: "quality_eval_v2", label: "Quality Eval 2.0", description: "Opening/Golden/Volume/Longform 质量套件", href: "/quality-eval-v2", icon: <ShieldCheck size={17} /> },
      { key: "publishing_feedback_v2", label: "Publish Feedback 2.0", description: "手动发布包、回执、评论聚类和回流提案", href: "/publishing-feedback-v2", icon: <Send size={17} /> },
      { key: "analytics_dashboard", label: "Analytics", description: "ClickHouse optional OLAP 离线投影", href: "/analytics", icon: <BarChart3 size={17} /> },
      { key: "data_statistics", label: "数据统计", description: "产能、质量、成本趋势", href: "/statistics", icon: <BarChart3 size={17} /> },
      { key: "settings_center", label: "设置中心", description: "本地生产配置", href: "/settings", icon: <Settings size={17} /> },
      { key: "task_center", label: "任务中心", description: "任务、timeline 和恢复", href: "/tasks", icon: <ListChecks size={17} /> },
      { key: "handoffs", label: "Handoff", description: "Claude Code / Codex 执行包", href: "/handoffs", icon: <Workflow size={17} /> },
      { key: "health", label: "健康检查", description: "服务、备份和存储状态", href: "/health", icon: <Server size={17} /> }
    ]
  }
];

export function navItemForPath(pathname: string): NavItem | undefined {
  const items = navGroups.flatMap((group) => group.items);
  return items.find((item) => item.href === pathname) ?? items.find((item) => item.href.split("?")[0] === pathname);
}
