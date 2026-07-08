import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;

function read(relativePath) {
  return readFileSync(join(root, relativePath), "utf8");
}

describe("Novel Forge admin feature architecture", () => {
  it("keeps V6/V7 navigation groups and local factory centers wired", () => {
    const navigation = read("app/shared/navigation.tsx");
    for (const label of ["工作区", "创作资产", "分析拆解", "生产流程", "管理工具"]) {
      assert.match(navigation, new RegExp(label));
    }
    for (const key of ["publishing_center", "reader_feedback", "data_statistics", "settings_center", "health"]) {
      assert.match(navigation, new RegExp(key));
    }
    assert.doesNotMatch(navigation, /会员|付费|邀请|团队空间/);
  });

  it("has routed feature modules for P2 centers", () => {
    for (const path of [
      "app/features/assets/AssetsCenterPage.tsx",
      "app/features/impact/ChangeImpactPage.tsx",
      "app/features/quality/QualityGatePage.tsx",
      "app/features/evaluation/EvaluationCenterPage.tsx",
      "app/features/settings/SettingsCenterPage.tsx",
      "app/features/tasks/TasksCenterPage.tsx"
    ]) {
      assert.equal(existsSync(join(root, path)), true, `${path} should exist`);
    }
  });

  it("has routed Novel OS runtime consoles wired to real runtime APIs", () => {
    const navigation = read("app/shared/navigation.tsx");
    for (const token of ["OS Runtime", "editor_chief_console", "workflow_runtime", "agent_dispatch", "trace_timeline", "cost_dashboard", "invalidation_map", "review_rework_board", "longform_stability"]) {
      assert.match(navigation, new RegExp(token));
    }

    for (const path of [
      "app/os/page.tsx",
      "app/editor-chief/page.tsx",
      "app/workflow-runtime/page.tsx",
      "app/agent-dispatch/page.tsx",
      "app/novel-kg/page.tsx",
      "app/trace-timeline/page.tsx",
      "app/cost-dashboard/page.tsx",
      "app/invalidation/page.tsx",
      "app/review-rework/page.tsx",
      "app/longform-stability/page.tsx",
      "app/features/os/OperatingSystemConsolePage.tsx",
      "app/features/os/EditorChiefConsolePage.tsx",
      "app/features/os/WorkflowRuntimeConsolePage.tsx",
      "app/features/os/AgentDispatchCenterPage.tsx",
      "app/features/os/TraceTimelinePage.tsx",
      "app/features/os/CostDashboardPage.tsx",
      "app/features/os/InvalidationMapPage.tsx",
      "app/features/os/ReviewReworkBoardPage.tsx",
      "app/features/os/LongformStabilityPage.tsx"
    ]) {
      assert.equal(existsSync(join(root, path)), true, `${path} should exist`);
    }

    const osApi = read("app/features/os/api.ts");
    for (const endpoint of [
      "/product/workflow/runtime-console",
      "/product/workflow/scheduler/tick",
      "/product/agents/scheduler/queue",
      "/product/agents/scheduler/tick",
      "/product/agents/operation-coverage",
      "/product/agents/hard-stop-dashboard",
      "/product/agents/dag",
      "/product/agents/rollback-rehearsal",
      "/product/agents/dead-letter-repair",
      "/product/runtime/trace-timeline",
      "/product/runtime/cost-ledger",
      "/product/runtime/cost-dashboard",
      "/product/runtime/policy/enforcement-report",
      "/product/runtime/policy/legacy-entrypoint-audit",
      "/product/runtime/policy/surface-coverage",
      "/product/runtime/provider-hard-stop-evidence",
      "/product/runtime/rollback/preview",
      "/product/runtime/rollback/apply",
      "/product/runtime/rollback/verify",
      "/product/runtime/rollback/coordinate",
      "/product/novel-kg/refresh",
      "/product/novel-kg/identity-resolution",
      "/product/revisions/rework-loop",
      "/product/publishing/gate",
      "/product/longform-stability/dashboard",
      "/product/longform-stability/extract",
      "/product/longform-stability/acceptance",
      "/product/longform-stability/control-asset",
      "/product/longform-stability/calibrate",
      "/product/agents/center",
      "/product/editor-chief/snapshot"
    ]) {
      assert.match(osApi, new RegExp(endpoint.replaceAll("/", "\\/")));
    }

    const editorChiefConsole = read("app/features/os/EditorChiefConsolePage.tsx");
    for (const token of ["这本书现在健康吗", "主线是否偏了", "人物是否崩了", "伏笔是否乱了", "最近10章是否疲劳", "下10章应该怎么写", "哪些问题必须先修", "是否可以发布"]) {
      assert.match(editorChiefConsole, new RegExp(token));
    }

    const workflowConsole = read("app/features/os/WorkflowRuntimeConsolePage.tsx");
    assert.match(workflowConsole, /DAG Graph/);

    const agentConsole = read("app/features/os/AgentDispatchCenterPage.tsx");
    for (const token of ["Agent Center v2 Control", "Run Graph", "Gate Timeline", "Checkpoint List", "Budget Burn", "Gov Repair", "DL Repairs", "Governance Dead-letter Review", "Build reviewed payload", "Submit Reviewed Repair Payload", "confirm_governance_review", "guarded repair endpoint only", "Governance Repair Audit Trail", "queue recovery evidence", "rollback rehearsal retained", "Review required", "no automatic repair", "Dead-letter Queue", "Rollback Preview", "Rollback Rehearsal", "Repair Dead Letter", "SLA \\/ Duration", "Evidence Drawer", "Operation Coverage Full"]) {
      assert.match(agentConsole, new RegExp(token));
    }

    const costConsole = read("app/features/os/CostDashboardPage.tsx");
    assert.match(costConsole, /Cost Trend/);

    const osConsole = read("app/features/os/OperatingSystemConsolePage.tsx");
    assert.match(osConsole, /Coordinate Preview/);
    assert.match(osConsole, /Coordinate Apply/);
    assert.match(osConsole, /Longform Stability/);
    assert.match(osConsole, /OS Surface Coverage/);
    assert.match(osConsole, /Provider Hard-stop Evidence/);

    const longformConsole = read("app/features/os/LongformStabilityPage.tsx");
    for (const token of ["Arc Visualization", "Model assisted", "OS acceptance gate", "Chapter Stability", "Acceptance Checks", "Editable OS Control Assets", "Extraction Calibration", "Save Control Asset", "Calibrate Draft"]) {
      assert.match(longformConsole, new RegExp(token));
    }
  });

  it("has routed Novel OS editable consoles for longform governance", () => {
    const navigation = read("app/shared/navigation.tsx");
    for (const token of ["agent_center", "permission_center", "canon_console", "character_console", "arc_console", "foreshadowing_console", "review_issue_console", "longform_recap", "loop_runs", "publish_gate_console", "feedback_console"]) {
      assert.match(navigation, new RegExp(token));
    }
    for (const path of [
      "app/features/os/EditableAssetConsolePage.tsx",
      "app/agent-center/page.tsx",
      "app/permission-center/page.tsx",
      "app/canon-console/page.tsx",
      "app/character-console/page.tsx",
      "app/arc-console/page.tsx",
      "app/foreshadowing-console/page.tsx",
      "app/review-issues/page.tsx",
      "app/longform-recap/page.tsx",
      "app/loop-runs/page.tsx",
      "app/publish-gate/page.tsx",
      "app/feedback-console/page.tsx"
    ]) {
      assert.equal(existsSync(join(root, path)), true, `${path} should exist`);
    }
    const editable = read("app/features/os/EditableAssetConsolePage.tsx");
    for (const token of ["saveAssetContent", "createCreativeAsset", "Asset List", "Editable Content", "Lineage", "Domain Governance Editor", "Bulk Governance Tools", "canon_database", "character_state_ledger", "arc_plan", "foreshadowing_graph", "review_issue"]) {
      assert.match(editable, new RegExp(token));
    }
    const osApi = read("app/features/os/api.ts");
    assert.match(osApi, /\/product\/review-issues\/status/);
    const governanceApi = read("app/features/governance/api.ts");
    for (const endpoint of ["/product/permission-center/snapshot", "/product/permission-center/policies", "/product/permission-center/evaluate"]) {
      assert.match(governanceApi, new RegExp(endpoint.replaceAll("/", "\\/")));
    }
    const governancePages = read("app/features/governance/GovernancePages.tsx");
    for (const token of ["Permission Center", "human approval gate", "agent/tool/source/publish/bypass", "Evaluate Publish"]) {
      assert.match(governancePages, new RegExp(token));
    }
  });

  it("exposes asset graph, publishing calendar, version registry, and impact visualization in source", () => {
    const assets = read("app/features/assets/AssetsCenterPage.tsx");
    assert.match(assets, /loadAssetGraph/);
    assert.match(assets, /引用图谱/);
    assert.match(assets, /assetGraphCanvas layered/);
    for (const token of ["题材策略", "素材运营", "知识治理", "设定书连续性"]) {
      assert.match(assets, new RegExp(token));
    }

    const quality = read("app/features/quality/QualityGatePage.tsx");
    for (const token of ["发布日历", "发布版本库", "平台规则与发布日志", "preparePlatformRelease", "adapterDryRun", "原创性风险解释", "整改建议与结构相似", "标题/简介/标签优化"]) {
      assert.match(quality, new RegExp(token));
    }

    const impact = read("app/features/impact/ChangeImpactPage.tsx");
    for (const token of ["影响图谱", "impact_edges", "severity_summary"]) {
      assert.match(impact, new RegExp(token));
    }
  });

  it("keeps API client contracts for P2 endpoints explicit", () => {
    const assetsApi = read("app/features/assets/api.ts");
    assert.match(assetsApi, /\/product\/assets\/graph/);

    const dashboardApi = read("app/features/dashboard/api.ts");
    assert.match(dashboardApi, /\/product\/projects\/operating-dashboard/);

    const projectsPage = read("app/features/projects/ProjectsPage.tsx");
    assert.match(projectsPage, /创建项目向导/);
    assert.match(projectsPage, /经营排序/);

    const qualityApi = read("app/features/quality/api.ts");
    for (const endpoint of ["/product/publishing/plan", "/product/publishing/log", "/product/publishing/release-package", "/product/publishing/adapters", "/product/publishing/adapter-release"]) {
      assert.match(qualityApi, new RegExp(endpoint.replaceAll("/", "\\/")));
    }

    const kgApi = read("app/features/kg/api.ts");
    assert.match(kgApi, /\/product\/novel-kg\/semantic-extraction/);
    assert.match(kgApi, /\/product\/novel-kg\/identity-resolution/);

    const feedbackApi = read("app/features/feedback/api.ts");
    assert.match(feedbackApi, /\/product\/feedback\/publish-loop/);
    assert.match(feedbackApi, /\/product\/feedback\/reader-simulation/);
    assert.match(feedbackApi, /\/product\/feedback\/real-backflow/);

    const mkaosApi = read("app/features/mkaos/api.ts");
    for (const endpoint of ["/product/mkaos/packs", "/product/mkaos/knowledge-graph/build", "/product/mkaos/evolution/run", "/product/mkaos/lineage/query", "/product/mkaos/lineage/query-path", "/product/mkaos/lineage/diff", "/product/mkaos/lineage/export", "/product/mkaos/lineage/weight-governance", "/product/mkaos/production-gate/run", "/product/mkaos/production-gate/coverage", "/product/mkaos/model-extraction/jobs", "/product/mkaos/mutations", "/product/mkaos/regression/run", "/product/mkaos/acceptance/knowledge-asset-os"]) {
      assert.match(mkaosApi, new RegExp(endpoint.replaceAll("/", "\\/")));
    }
    for (const token of ["unwrapMkaos", "applyMkaosWeightGovernance", "diffMkaosLineageIndexes", "exportMkaosLineageGraph", "buildMkaosGateCoverage"]) {
      assert.match(mkaosApi, new RegExp(token));
    }
  });

  it("upgrades the MKAOS console into a knowledge asset operations workbench", () => {
    const mkaosConsole = read("app/features/mkaos/MkaosConsolePage.tsx");
    for (const token of ["Source Evidence 原文层默认折叠", "Quality Dashboard", "Pack Debugger", "Knowledge Graph", "Knowledge Evolution", "Graph Explorer", "Lineage Audit", "Regression Cases", "MKAOS Acceptance", "operator-only evidence", "mkaosGraphCanvas", "mkaosGraphExplorer"]) {
      assert.match(mkaosConsole, new RegExp(token));
    }
    const globals = read("app/globals.css");
    assert.match(globals, /\.mkaosGraphCanvas/);
    assert.match(globals, /\.mkaosGraphExplorer/);
  });

  it("wires MKAOS ingestion and creative extraction workbench routes", () => {
    for (const path of [
      "app/features/mkaos/MkaosIngestionPages.tsx",
      "app/mkaos/import/page.tsx",
      "app/mkaos/repositories/page.tsx",
      "app/mkaos/books/page.tsx",
      "app/mkaos/extraction-jobs/page.tsx",
      "app/mkaos/creative-assets/page.tsx",
      "app/mkaos/quality/page.tsx",
      "app/mkaos/model-extraction/page.tsx",
      "app/mkaos/model-extraction/jobs/page.tsx",
      "app/mkaos/model-extraction/review/page.tsx",
      "app/mkaos/model-extraction/benchmarks/page.tsx",
      "app/mkaos/model-extraction/prompts/page.tsx",
      "app/mkaos/production-gate/page.tsx",
      "app/mkaos/production-gate/reports/page.tsx",
      "app/mkaos/knowledge-graph/page.tsx",
      "app/mkaos/lineage/page.tsx",
      "app/mkaos/impact/page.tsx",
      "app/mkaos/feedback-attribution/page.tsx"
    ]) {
      assert.equal(existsSync(join(root, path)), true, `${path} should exist`);
    }
    const mkaosApi = read("app/features/mkaos/api.ts");
    for (const endpoint of [
      "/product/mkaos/ingestion/repositories",
      "/product/mkaos/ingestion/jobs",
      "/product/mkaos/books",
      "/product/mkaos/parallel-pairs",
      "/product/mkaos/extraction/jobs",
      "/product/mkaos/convert/creative-assets",
      "/product/mkaos/quality/evaluate-extraction",
      "/product/mkaos/quality/check-leakage",
      "/product/mkaos/quality/gate-knowledge-pack",
      "/product/mkaos/model-extraction/jobs",
      "/product/mkaos/model-extraction/review-queue",
      "/product/mkaos/model-extraction/benchmark/run",
      "/product/mkaos/model-extraction/regression/run",
      "/product/mkaos/model-extraction/prompts",
      "/product/mkaos/production-gate/reports",
      "/product/mkaos/production-gate/latest",
      "/product/mkaos/lineage/build-index",
      "/product/mkaos/lineage/asset-impact",
      "/product/mkaos/lineage/feedback-to-knowledge",
      "/product/mkaos/lineage/weight-governance"
    ]) {
      assert.match(mkaosApi, new RegExp(endpoint.replaceAll("/", "\\/")));
    }
    for (const token of ["loadMkaosIngestionJob", "resumeMkaosIngestionJob", "cancelMkaosIngestionJob", "/resume", "/cancel"]) {
      assert.match(mkaosApi, new RegExp(token.replaceAll("/", "\\/")));
    }
    const ingestionPage = read("app/features/mkaos/MkaosIngestionPages.tsx");
    for (const token of ["titleForMode", "Parallel Pairs", "Creative Assets", "Extraction Quality Gate", "Model Extraction Jobs", "Extraction Review Queue", "MKAOS Production Gate", "Knowledge Graph / Lineage", "Feedback Attribution", "raw source text 只进入 evidence layer", "Resume Job", "Cancel Job"]) {
      assert.match(ingestionPage, new RegExp(token));
    }
  });

  it("wires industrial deep workbench panels for analysis, context, editor, production, evaluation, and control", () => {
    const analysis = read("app/features/analysis/AnalysisCenterPage.tsx");
    for (const token of ["语义深度评分", "模式可视化", "semantic_depth"]) {
      assert.match(analysis, new RegExp(token));
    }

    const context = read("app/features/context/ContextBuilderPage.tsx");
    for (const token of ["人工精调来源", "发送前上下文确认", "finalConfirmed"]) {
      assert.match(context, new RegExp(token));
    }

    const editor = read("app/features/editor/EditorPage.tsx");
    for (const token of ["富文本编辑区", "相关资料侧栏", "版本历史侧栏", "EDITOR_COMMANDS"]) {
      assert.match(editor, new RegExp(token));
    }

    const production = read("app/features/production/ProductionChainPage.tsx");
    for (const token of ["章节队列", "Preflight Checklist", "进度历史", "pauseChapterProduction", "cancelChapterProduction"]) {
      assert.match(production, new RegExp(token));
    }

    const evaluation = read("app/features/evaluation/EvaluationCenterPage.tsx");
    for (const token of ["真实 Provider 批量评测", "路由生效回归", "runBenchmarkBatch"]) {
      assert.match(evaluation, new RegExp(token));
    }

    const control = read("app/features/control/ProductionControlPage.tsx");
    for (const token of ["Agent 全边界证明", "Runtime Guard Probe", "Workflow Scheduler", "runWorkflowSchedulerTick", "enqueueWorkflowSchedulerLoop", "runAgentBoundaryAudit"]) {
      assert.match(control, new RegExp(token));
    }
  });

  it("keeps content intelligence artifact repairs review-only", () => {
    const contentIntelligence = read("app/features/content-intelligence/ContentIntelligencePages.tsx");
    for (const token of [
      "Review-only repair boundary",
      "It never edits outlines, chapters, characters, release packages, or platform state.",
      "status: \"needs_review\"",
      "Review note",
      "Save review marker",
      "No story plan, chapter, or release package was changed.",
      "role=\"status\"",
      "artifactSummaryGrid"
    ]) {
      assert.match(contentIntelligence, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
  });

  it("contains an optional Playwright browser smoke test", () => {
    const smoke = read("tests/playwright-smoke.test.mjs");
    assert.match(smoke, /playwright/);
    assert.match(smoke, /NOVEL_FORGE_WEB_BASE_URL/);
    assert.match(smoke, /NOVEL_FORGE_API_BASE_URL/);
    assert.match(smoke, /assertBackendFixture/);
    assert.match(smoke, /\/product\/workflow\/processor-contracts/);
    assert.match(smoke, /\/product\/os\/retrieval\/pgvector-capabilities/);
    assert.match(smoke, /个人本地小说工厂/);
  });
});
