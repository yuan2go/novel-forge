from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.api.product import create_project_with_defaults
from novel_forge.model_adapters.runtime import ProviderRuntimeGuard, evaluate_provider_runtime_guard
from novel_forge.modules.evaluation_center import create_evaluation_gate
from novel_forge.modules.longform_stability import create_arc_plan, create_canon_database, model_assisted_longform_extraction
from novel_forge.modules.mkaos import create_knowledge_card, create_usage_binding
from novel_forge.modules.platform_strategy import build_platform_strategy_pack
from novel_forge.modules.runtime_ledger import record_gate_result, record_model_call_log
from novel_forge.schemas import BaseAsset, DraftChapter, PublishGateReport
from novel_forge.storage.local import LocalStorage


def production_envelope(project_id: str, asset_type: str, *, trace_id: str, source_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "envelope_id": f"os-envelope-{trace_id}",
        "project_id": project_id,
        "task_type": "publish",
        "asset_type": asset_type,
        "actor_type": "unit_test",
        "source": "tests.unit.publishing_fixtures",
        "trace_id": trace_id,
        "source_policy": source_policy or {"raw_source_text_allowed": False, "generation_rag_allowed": True},
        "environment": "production",
    }


def create_production_ready_release_inputs(storage: LocalStorage, *, title: str = "Production Ready Release") -> dict[str, Any]:
    detail = create_project_with_defaults(storage.root, title)
    project_id = str(detail["project_id"])
    workspace_path = str(detail["path"])
    source_policy = {
        "raw_source_text_allowed": False,
        "generation_rag_allowed": True,
        "empty_pack_policy": "block",
        "compat_warning_allowed": False,
    }
    draft_path = _ready_draft(storage, project_id=project_id, workspace_path=workspace_path)
    _longform_evidence(storage, draft_path, project_id=project_id, workspace_path=workspace_path)
    _publish_knowledge(storage, project_id)
    record_provider_runtime_evidence(storage, project_id, workspace_path=workspace_path)
    platform_pack = build_platform_strategy_pack(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "platform": "local_serial",
            "topic": "账册追查",
            "genre": "悬疑",
        },
    )
    evaluation_gate = create_evaluation_gate(
        storage,
        str(draft_path.relative_to(storage.root)),
        minimum_score=0.0,
        project_id=project_id,
        require_provider_runtime=True,
    )
    gate_path = _ready_publish_gate(
        storage,
        draft_path=draft_path,
        project_id=project_id,
        workspace_path=workspace_path,
        evaluation_gate_path=evaluation_gate["path"],
        platform_strategy_pack_path=platform_pack["path"],
        source_policy=source_policy,
    )
    return {
        "project_id": project_id,
        "workspace_path": workspace_path,
        "draft_path": draft_path,
        "publish_gate_path": gate_path,
        "source_policy": source_policy,
    }


def record_provider_runtime_evidence(storage: LocalStorage, project_id: str, *, workspace_path: str = "") -> None:
    cancel_file = storage.root / "cancel.flag"
    cancel_file.write_text("cancel\n", encoding="utf-8")
    cases = [
        ("token", {"input_tokens": 80, "output_tokens": 40, "total_tokens": 120}, ProviderRuntimeGuard(max_total_tokens=100)),
        ("cost", {"input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000}, ProviderRuntimeGuard(max_cost=0.001, cost_profile={"per_1k": 0.01})),
        ("timeout", {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20, "elapsed_ms": 100}, ProviderRuntimeGuard(timeout_ms=20)),
        ("cancel", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, ProviderRuntimeGuard(cancel_file=str(cancel_file))),
    ]
    for label, usage, guard in cases:
        result = evaluate_provider_runtime_guard(operation=f"publish_{label}", provider="mock", usage=usage, guard=guard)
        record_gate_result(
            storage,
            gate_kind="provider_runtime_guard",
            status="failed",
            target_paths=[],
            result=result,
            trace={"trace_id": f"trace-publish-{label}", "span_id": f"span-publish-{label}"},
            project_id=project_id,
            workspace_path=workspace_path,
            message=result["message"],
        )
        record_model_call_log(
            storage,
            provider="mock",
            model="mock-publish",
            operation=f"publish_{label}",
            status="failed",
            usage=result.get("usage", {}),
            cost={"amount": 0.0, "currency": "USD", "source": "publish_guard_fixture"},
            trace={"trace_id": f"trace-publish-{label}", "span_id": f"span-publish-{label}"},
            project_id=project_id,
            workspace_path=workspace_path,
        )
    success = evaluate_provider_runtime_guard(
        operation="publish_success",
        provider="mock",
        usage={"input_tokens": 20, "output_tokens": 30, "total_tokens": 50, "elapsed_ms": 10},
        guard=ProviderRuntimeGuard(max_total_tokens=1000, timeout_ms=1000, max_cost=1.0, cost_profile={"per_1k": 0.01}),
    )
    record_gate_result(
        storage,
        gate_kind="provider_runtime_guard",
        status="passed",
        target_paths=[],
        result=success,
        trace={"trace_id": "trace-publish-success", "span_id": "span-publish-success"},
        project_id=project_id,
        workspace_path=workspace_path,
        message=success["message"],
    )
    record_model_call_log(
        storage,
        provider="mock",
        model="mock-publish",
        operation="publish_success",
        status="succeeded",
        usage=success.get("usage", {}),
        cost={"amount": 0.0005, "currency": "USD", "source": "publish_guard_fixture"},
        trace={"trace_id": "trace-publish-success", "span_id": "span-publish-success"},
        project_id=project_id,
        workspace_path=workspace_path,
    )


def _ready_draft(storage: LocalStorage, *, project_id: str, workspace_path: str) -> Path:
    rag_path = storage.write_asset("runs", BaseAsset(type="rag_quality_report", title="RAG ready", content={"recommendation": "pass"}, metadata={"project_id": project_id, "workspace_path": workspace_path}))
    stability_path = storage.write_asset(
        "reviews",
        BaseAsset(type="chapter_continuity_report", title="Stability ready", content={"recommendation": "pass", "gate_status": "passed"}, metadata={"project_id": project_id, "workspace_path": workspace_path}),
    )
    return storage.write_asset(
        "drafts",
        DraftChapter(
            title="Chapter 1",
            content={
                "chapter": 1,
                "text": "阿照在夜档司查到竹筹穿册。陶主簿把旧竹筹藏入铺牌，真相露出一角，旧城隐税机制被确认。",
                "copyright_boundary": "project-owned production-ready fixture",
            },
            metadata={
                "project_id": project_id,
                "workspace_path": workspace_path,
                "rag_quality_report_path": str(rag_path.relative_to(storage.root)),
                "rag_quality_recommendation": "pass",
                "stability_preflight_path": str(stability_path.relative_to(storage.root)),
                "stability_preflight_recommendation": "pass",
                "stability_preflight_gate_status": "passed",
            },
            references=[workspace_path],
        ),
    )


def _longform_evidence(storage: LocalStorage, draft_path: Path, *, project_id: str, workspace_path: str) -> None:
    create_canon_database(
        storage,
        entities=[
            {"entity_id": "azhao", "entity_type": "character", "canonical_name": "阿照", "aliases": [], "forbidden_aliases": ["沈砚"], "role": "protagonist", "status": "active"},
            {"entity_id": "night_archive_office", "entity_type": "organization", "canonical_name": "夜档司", "aliases": [], "forbidden_aliases": [], "role": "core_organization", "status": "active"},
            {"entity_id": "tao_clerk", "entity_type": "character", "canonical_name": "陶主簿", "aliases": [], "forbidden_aliases": [], "role": "visible_villain_agent", "status": "active"},
        ],
        project_id=project_id,
        workspace_path=workspace_path,
    )
    create_arc_plan(
        storage,
        arc_id="arc_ready",
        title="桥南隐税卷",
        chapter_range="1-10",
        arc_question="谁在复活旧城隐税机制？",
        protagonist_goal="找到隐税机制源头",
        villain_goal="逼夜档司承接旧债",
        project_id=project_id,
        workspace_path=workspace_path,
    )
    model_assisted_longform_extraction(storage, draft_path, workspace_path=workspace_path, use_model=False)


def _ready_publish_gate(
    storage: LocalStorage,
    *,
    draft_path: Path,
    project_id: str,
    workspace_path: str,
    evaluation_gate_path: str,
    platform_strategy_pack_path: str,
    source_policy: dict[str, Any],
) -> Path:
    draft = storage.read_asset(draft_path)
    envelope = production_envelope(project_id, "publish_gate_report", trace_id=f"trace-publish-ready-{project_id}", source_policy=source_policy)
    asset = PublishGateReport(
        title=f"Ready publish gate for {draft.title}",
        source=draft.id,
        tags=["publish-gate", "quality-gate", "release-control", "fixture-ready"],
        content={
            "target_asset_id": draft.id,
            "gates": {
                "chapter_audit_passed": True,
                "mkaos_risk_clear": True,
                "review_issue_blocking_clear": True,
                "evaluation_gate_passed": True,
                "provider_runtime_gate_passed": True,
                "platform_strategy_gate_passed": True,
            },
            "decision": "ready",
            "blocking_issues": [],
            "review_issue_paths": [],
            "required_reports": {},
            "human_override": False,
            "preflight": {"ready": True, "warnings": [], "missing": []},
            "longform_stability": {"status": "pass", "passed": True, "blocking_issues": []},
            "evaluation_gate": {
                "status": "passed",
                "required": True,
                "blocking": False,
                "path": evaluation_gate_path,
                "blocking_issues": [],
            },
            "provider_runtime_gate": {
                "status": "passed",
                "required": True,
                "blocking": False,
                "blocking_issues": [],
            },
            "platform_strategy_gate": {
                "status": "passed",
                "required": True,
                "blocking": False,
                "platform_strategy_pack_path": platform_strategy_pack_path,
                "blocking_issues": [],
            },
            "context_bundle_id": "",
            "context_bundle_path": "",
            "knowledge_context_contract": {},
            "mkaos_risk": {"blocking": False, "blocking_count": 0, "blocking_issues": [], "risk_items": []},
            "source_isolation": {
                "source_chunk_raw_text_allowed": False,
                "runtime_assets_in_generation_rag_allowed": False,
                "raw_source_text_allowed": False,
            },
            "os_envelope_id": envelope["envelope_id"],
        },
        metadata={
            "workflow": "publish-gate",
            "project_id": project_id,
            "workspace_path": workspace_path,
            "risk_level": "low",
            "environment": "production",
            "source_policy": source_policy,
            "os_envelope": envelope,
            "os_envelope_id": envelope["envelope_id"],
            "trace_id": envelope["trace_id"],
        },
        references=[draft.id, str(draft_path.relative_to(storage.root)), evaluation_gate_path, platform_strategy_pack_path],
    )
    return storage.write_asset("publishing", asset)


def _publish_knowledge(storage: LocalStorage, project_id: str) -> None:
    card = create_knowledge_card(
        storage,
        {
            "concept_name": "Publish governance",
            "core_explanation": "production publish must carry a MKAOS pack",
            "project_id": project_id,
            "weight": 1.0,
            "risk_level": "low",
        },
    )
    create_usage_binding(storage, card["asset"]["id"], {"flow": "publish", "usage_type": "required", "input_role": "publish_gate", "priority": 10})
