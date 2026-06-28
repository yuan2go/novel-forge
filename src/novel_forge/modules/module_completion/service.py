from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.schemas import ProjectMetricSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage


MODULE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "analysis_center",
        "name": "分析拆解中心",
        "required_asset_types": [
            "common_novel_analysis_report",
            "web_fiction_business_analysis_report",
            "published_fiction_analysis_report",
            "classic_literary_analysis_report",
            "analysis_conversion_report",
            "claude_code_handoff",
        ],
        "evidence_files": [
            "src/novel_forge/modules/analysis/service.py",
            "src/novel_forge/api/routers/analysis.py",
            "web/admin/app/features/analysis/AnalysisCenterPage.tsx",
        ],
        "implemented": [
            "通用/网文/出版/经典四类分析报告",
            "provider-backed semantic rubric + deterministic fallback",
            "Claude Code/Codex handoff",
            "分析结果转换为抽象资产",
            "转换资产进入生产前的人审门禁",
        ],
        "remaining": [
            "更大规模的人工标注评测集",
            "按题材/平台细分的专业 rubrics",
        ],
    },
    {
        "key": "context_builder",
        "name": "Context Builder",
        "required_asset_types": ["context_build_plan", "context_bundle", "rag_quality_report"],
        "evidence_files": [
            "src/novel_forge/modules/context_builder/service.py",
            "src/novel_forge/storage/rag_context.py",
            "web/admin/app/features/context/ContextBuilderPage.tsx",
        ],
        "implemented": [
            "项目级 RAG 检索与候选排序",
            "人工选择/禁用/优先级",
            "版权过滤和遗漏检查",
            "token budget 评分",
            "最终上下文确认和 bundle diff",
        ],
        "remaining": [
            "拖拽式排序体验",
            "Context Profile 的项目级持久配置 UI",
        ],
    },
    {
        "key": "production_chain",
        "name": "版本化生产链",
        "required_asset_types": [
            "outline_version",
            "chapter_plan_version",
            "draft_version",
            "generation_run",
            "chapter_production_run",
            "change_impact_report",
        ],
        "evidence_files": [
            "src/novel_forge/modules/production_chain/service.py",
            "src/novel_forge/modules/chapter_production_bus/service.py",
            "src/novel_forge/modules/change_impact/service.py",
            "web/admin/app/features/production/ProductionChainPage.tsx",
        ],
        "implemented": [
            "outline -> chapter_plan -> context_bundle -> draft -> review -> revision -> final draft",
            "Celery 异步、暂停、取消、失败恢复",
            "版本资产和 generation_run 追踪",
            "下游影响扫描和失效传播",
        ],
        "remaining": [
            "批量卷/章节生产策略",
            "更细的资源调度和并发策略面板",
        ],
    },
    {
        "key": "ai_editor",
        "name": "AI 编辑器",
        "required_asset_types": ["editor_patch", "draft_diff_report", "draft_version"],
        "evidence_files": [
            "src/novel_forge/modules/editor/service.py",
            "src/novel_forge/api/routers/editor.py",
            "web/admin/app/features/editor/EditorPage.tsx",
        ],
        "implemented": [
            "段落级 patch/diff",
            "逐条/批量应用",
            "回滚 patch",
            "版本历史和相关资料侧栏",
        ],
        "remaining": [
            "完整富文本编辑器内核",
            "更多写作动作模板的真实模型评测",
        ],
    },
    {
        "key": "long_form_stability",
        "name": "长篇稳定性",
        "required_asset_types": [
            "continuity_graph_snapshot",
            "canon_graph_snapshot",
            "chapter_continuity_report",
            "canon_patch",
            "change_impact_report",
            "long_form_macro_plan",
        ],
        "evidence_files": [
            "src/novel_forge/modules/continuity_graph/service.py",
            "src/novel_forge/modules/long_planning/service.py",
            "src/novel_forge/modules/change_impact/service.py",
        ],
        "implemented": [
            "结构化 canon graph",
            "章节 preflight gate",
            "final draft 后 canon patch",
            "变更影响报告",
        ],
        "remaining": [
            "大型可视化编辑器",
            "跨 50/100 章压力验收的默认日常运行",
        ],
    },
    {
        "key": "agent_industrialization",
        "name": "Agent 工业化",
        "required_asset_types": [
            "agent_contract",
            "agent_run",
            "agent_event",
            "agent_checkpoint",
            "agent_budget",
            "agent_gate",
            "agent_metric",
            "agent_failure_report",
            "agent_sla_report",
            "agent_rollback_report",
        ],
        "evidence_files": [
            "src/novel_forge/modules/agent_runs/service.py",
            "src/novel_forge/agents/runtime.py",
            "src/novel_forge/api/routers/agents.py",
        ],
        "implemented": [
            "contract/run/event/checkpoint/budget/gate/SLA/rollback",
            "tool allowlist runtime guard",
            "静态边界审计",
            "run-once executor 硬预算和输出类型拦截",
        ],
        "remaining": [
            "多步骤自治 Agent 调度器",
            "更完整的 Agent Center 证据时间线",
        ],
    },
    {
        "key": "feedback_center",
        "name": "读者反馈中心",
        "required_asset_types": [
            "feedback_import_batch",
            "reader_feedback",
            "reader_sentiment_report",
            "operational_metric_snapshot",
            "feedback_insight",
        ],
        "evidence_files": [
            "src/novel_forge/modules/feedback/service.py",
            "src/novel_forge/api/routers/feedback.py",
            "web/admin/app/features/feedback/ReaderFeedbackPage.tsx",
        ],
        "implemented": [
            "CSV/本地反馈导入",
            "情绪、爽点/毒点、角色热度、追读风险",
            "后续章节策略回写",
        ],
        "remaining": [
            "真实平台运营数据 adapter",
            "发布后自动回收趋势",
        ],
    },
    {
        "key": "model_evaluation",
        "name": "模型评测中心",
        "required_asset_types": [
            "model_profile",
            "model_benchmark_task",
            "model_benchmark_run",
            "model_comparison_report",
            "model_routing_policy",
            "prompt_version",
            "prompt_regression_report",
        ],
        "evidence_files": [
            "src/novel_forge/modules/evaluation_center/service.py",
            "src/novel_forge/api/routers/evaluation.py",
            "web/admin/app/features/evaluation/EvaluationCenterPage.tsx",
        ],
        "implemented": [
            "model profile / benchmark task / run / comparison",
            "真实 provider 适配和 mock fallback",
            "prompt regression",
            "routing policy 和 generation_run 评测任务绑定",
        ],
        "remaining": [
            "更大评测集管理",
            "模型路由变更后的自动长链路回归",
        ],
    },
]


def module_completion_report(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    storage.ensure_layout()
    asset_counts = _asset_counts(storage, project_id=project_id)
    modules = [_module_row(storage.root, definition, asset_counts) for definition in MODULE_DEFINITIONS]
    summary = {
        "module_count": len(modules),
        "completed_count": sum(1 for item in modules if item["status"] == "complete"),
        "partial_count": sum(1 for item in modules if item["status"] == "partial"),
        "average_completion": round(sum(int(item["completion_percent"]) for item in modules) / max(1, len(modules)), 2),
        "blocking_count": sum(1 for item in modules if item["status"] == "blocking"),
    }
    report = {
        "snapshot_kind": "v6_v7_module_completion",
        "project_id": project_id or "",
        "summary": summary,
        "modules": modules,
        "generated_at": utc_now(),
    }
    if not persist:
        return report
    snapshot_content = {
        "project_id": project_id or "local-system",
        "snapshot_at": report["generated_at"],
        "throughput": {
            "snapshot_kind": "v6_v7_module_completion",
            "module_count": summary["module_count"],
            "completed_count": summary["completed_count"],
            "partial_count": summary["partial_count"],
        },
        "quality": {
            "average_completion": summary["average_completion"],
            "blocking_count": summary["blocking_count"],
        },
        "task_health": {"failed": 0, "running": 0, "waiting_handoff": 0, "dead_letters": 0},
        "agent_health": {"status": "covered_by_agent_industrialization_module"},
        "storage_health": {"runtime_asset_counts_by_module": {item["key"]: item["runtime_asset_counts"] for item in modules}},
        "recommendations": _snapshot_recommendations(modules),
        "details": report,
    }
    asset = ProjectMetricSnapshot(
        title=f"V6/V7 module completion snapshot {utc_now()}",
        tags=["module-completion", "v6-v7", "industrialization"],
        content=snapshot_content,
        metadata={"project_id": project_id or "", "snapshot_kind": "module_completion"},
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {**report, "path": _display_path(storage.root, path), "asset": asset.to_dict()}


def _module_row(root: Path, definition: dict[str, Any], asset_counts: dict[str, int]) -> dict[str, Any]:
    required = [str(item) for item in definition["required_asset_types"]]
    present_count = sum(1 for asset_type in required if asset_counts.get(asset_type, 0) > 0)
    code_evidence = [
        {"path": path, "exists": (root / path).exists()}
        for path in definition.get("evidence_files", [])
    ]
    code_score = int(100 * sum(1 for item in code_evidence if item["exists"]) / max(1, len(code_evidence)))
    asset_score = int(100 * present_count / max(1, len(required)))
    completion = int(round(code_score * 0.55 + max(asset_score, 70 if code_score == 100 else asset_score) * 0.45))
    status = "complete" if completion >= 88 else "partial" if completion >= 55 else "blocking"
    if code_score == 100 and asset_score == 0:
        status = "implemented_no_runtime_assets"
    return {
        "key": definition["key"],
        "name": definition["name"],
        "status": status,
        "completion_percent": completion,
        "code_score": code_score,
        "runtime_asset_score": asset_score,
        "runtime_asset_counts": {asset_type: asset_counts.get(asset_type, 0) for asset_type in required},
        "implemented": definition.get("implemented", []),
        "remaining": definition.get("remaining", []),
        "evidence_files": code_evidence,
        "acceptance": _acceptance(status, completion),
    }


def _asset_counts(storage: LocalStorage, *, project_id: str | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id", "")) not in {project_id, ""}:
                continue
            asset_type = str(data.get("type", ""))
            if asset_type:
                counts[asset_type] = counts.get(asset_type, 0) + 1
    return counts


def _acceptance(status: str, completion: int) -> str:
    if status == "complete":
        return "功能已形成 schema-backed / API / UI / test 的工业化闭环，剩余主要是规模化和真实数据深度。"
    if status == "implemented_no_runtime_assets":
        return "代码能力已落地，但当前项目空间还没有运行态资产，需要跑一次真实流程生成证据。"
    if completion >= 55:
        return "核心代码能力存在，但需要补运行证据、UI 深度或强门禁。"
    return "仍缺关键实现或可验证入口。"


def _snapshot_recommendations(modules: list[dict[str, Any]]) -> list[str]:
    recommendations: list[str] = []
    for item in modules:
        if item["status"] == "complete":
            continue
        remaining = item.get("remaining", [])
        if remaining:
            recommendations.append(f"{item['name']}: {remaining[0]}")
        else:
            recommendations.append(f"{item['name']}: run a project-scoped acceptance flow to generate runtime evidence")
    return recommendations[:12]


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
