from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.api.product import create_project_with_defaults
from novel_forge.model_adapters.runtime import ProviderRuntimeGuard, evaluate_provider_runtime_guard
from novel_forge.modules.evaluation_center import create_evaluation_gate
from novel_forge.modules.canon_graph import run_canon_graph_plugin
from novel_forge.modules.longform_stability import create_arc_plan, create_canon_database, create_chapter_state_package, model_assisted_longform_extraction
from novel_forge.modules.mkaos import create_knowledge_card, create_usage_binding
from novel_forge.modules.genre_os import build_genre_strategy_pack, run_genre_risk_gate
from novel_forge.modules.platform_strategy import build_platform_strategy_pack
from novel_forge.modules.publishing import create_publish_gate_report
from novel_forge.modules.model_router import create_model_route
from novel_forge.modules.quality_eval import build_quality_rubric_pack, run_provider_quality_judge, run_quality_gate
from novel_forge.modules.runtime_ledger import record_gate_result, record_model_call_log
from novel_forge.modules.style_os import build_style_profile, extract_style_fingerprint, ingest_style_sample, run_style_drift_gate
from novel_forge.schemas import BaseAsset, DraftChapter, ReviewReport
from novel_forge.storage.local import LocalStorage


class ProviderJudgeAdapter:
    def review(self, payload: str, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "text": '{"recommendation":"ready","scores":{"genre_promise":91,"platform_rhythm":88,"style_adherence":86,"hook_strength":90,"conflict_density":87,"character_motivation":88,"canon_consistency":92,"ai_flavor_risk":85},"rationale":"provider-backed release fixture judgment"}',
            "usage": {"input_tokens": 1200, "output_tokens": 240, "total_tokens": 1440, "usage_source": "provider_fixture"},
            "cost": {"amount": 0.012, "currency": "USD", "source": "provider_fixture"},
        }


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


def create_production_ready_release_inputs(storage: LocalStorage, *, title: str = "Production Ready Release", include_v7: bool = True) -> dict[str, Any]:
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
    if include_v7:
        _v7_content_intelligence_evidence(storage, draft_path, project_id=project_id, workspace_path=workspace_path, source_policy=source_policy)
    else:
        create_evaluation_gate(
            storage,
            str(draft_path.relative_to(storage.root)),
            minimum_score=0.0,
            project_id=project_id,
            require_provider_runtime=True,
        )
    build_platform_strategy_pack(
        storage,
        {
            "project_id": project_id,
            "workspace_path": workspace_path,
            "platform": "local_serial",
            "topic": "账册追查",
            "genre": "悬疑",
        },
    )
    gate_path = create_publish_gate_report(
        storage,
        draft_path,
        workspace_path=workspace_path,
        envelope=production_envelope(project_id, "publish_gate_report", trace_id=f"trace-publish-ready-{project_id}", source_policy=source_policy),
        environment="production",
        source_policy=source_policy,
    )
    return {
        "project_id": project_id,
        "workspace_path": workspace_path,
        "draft_path": draft_path,
        "publish_gate_path": gate_path,
        "source_policy": source_policy,
    }


def _v7_content_intelligence_evidence(storage: LocalStorage, draft_path: Path, *, project_id: str, workspace_path: str, source_policy: dict[str, Any]) -> None:
    draft_asset = storage.read_asset(draft_path)
    draft_text = str(draft_asset.content.get("text", ""))
    envelope_base = {
        "project_id": project_id,
        "actor_type": "unit_test",
        "source": "tests.unit.publishing_fixtures",
        "source_policy": source_policy,
        "environment": "production",
    }
    genre = build_genre_strategy_pack(
        storage,
        genre="mystery",
        subgenre="police_procedural",
        project_id=project_id,
        platform_id="local_serial",
        environment="production",
        envelope={**envelope_base, "task_type": "genre_strategy", "asset_type": "genre_strategy_pack", "trace_id": f"trace-v7-genre-{project_id}"},
        source_policy=source_policy,
    )
    run_genre_risk_gate(
        storage,
        strategy_pack_path=genre["genre_strategy_pack_path"],
        target_path=draft_path,
        evidence={"线索不可回溯": "mitigated", "反转靠新增设定": "mitigated"},
        environment="production",
        envelope={**envelope_base, "task_type": "genre_risk_gate", "asset_type": "genre_risk_gate", "trace_id": f"trace-v7-genre-risk-{project_id}"},
    )
    sample = ingest_style_sample(
        storage,
        sample_text=draft_text,
        project_id=project_id,
        rights={"license": "project-owned", "allowed_usage": "style_parameter_extraction"},
        environment="production",
        envelope={**envelope_base, "task_type": "style_ingestion", "asset_type": "style_sample", "trace_id": f"trace-v7-style-sample-{project_id}"},
    )
    fingerprint = extract_style_fingerprint(
        storage,
        sample_path=sample["path"],
        environment="production",
        envelope={**envelope_base, "task_type": "style_fingerprint", "asset_type": "style_fingerprint", "trace_id": f"trace-v7-style-fp-{project_id}"},
    )
    style = build_style_profile(
        storage,
        fingerprint_path=fingerprint["path"],
        style_name="release fixture style",
        environment="production",
        envelope={**envelope_base, "task_type": "style_profile", "asset_type": "style_profile", "trace_id": f"trace-v7-style-profile-{project_id}"},
    )
    run_style_drift_gate(
        storage,
        style_profile_path=style["style_profile_path"],
        target_path=draft_path,
        environment="production",
        envelope={**envelope_base, "task_type": "style_drift_gate", "asset_type": "style_drift_report", "trace_id": f"trace-v7-style-drift-{project_id}"},
    )
    run_canon_graph_plugin(
        storage,
        {
            "plugin": "mystery_evidence_chain_engine",
            "target_path": str(draft_path),
            "project_id": project_id,
            "workspace_path": workspace_path,
            "persist_issues": False,
        },
    )
    rubric = build_quality_rubric_pack(
        storage,
        genre_id="mystery",
        platform_id="local_serial",
        style_profile_path=style["style_profile_path"],
        environment="production",
        envelope={**envelope_base, "task_type": "quality_eval", "asset_type": "quality_rubric_pack", "trace_id": f"trace-v7-rubric-{project_id}"},
    )
    create_model_route(
        storage,
        task_type="quality_judge",
        provider="unit-provider",
        model_name="premium-judge-v1",
        project_id=project_id,
        environment="production",
        approval_status="approved",
        approval_id=f"approval-v7-quality-{project_id}",
        approved_by="qa-lead",
        production_provider_allowlist=["unit-provider"],
        max_cost_per_run=1.0,
    )
    quality = run_provider_quality_judge(
        storage,
        suite_type="opening_3",
        target_paths=[str(draft_path)],
        rubric_path=rubric["path"],
        adapter=ProviderJudgeAdapter(),
        genre_strategy_pack_path=genre["genre_strategy_pack_path"],
        style_profile_path=style["style_profile_path"],
        platform_id="local_serial",
        environment="production",
        envelope={**envelope_base, "task_type": "quality_judge", "asset_type": "opening_3_report", "trace_id": f"trace-v7-quality-{project_id}"},
        provider_runtime_guard={"max_total_tokens": 2000, "cost_profile": {"input_per_1k": 0.005, "output_per_1k": 0.015}},
    )
    run_quality_gate(
        storage,
        quality_report_path=quality["path"],
        environment="production",
        envelope={**envelope_base, "task_type": "quality_gate", "asset_type": "evaluation_gate", "trace_id": f"trace-v7-quality-gate-{project_id}"},
    )


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
                "summary": "阿照在夜档司旧库追查桥南隐税卷，发现旧税筹与师父旧名相连，下一步必须独自去井口验灰。",
                "synopsis": "阿照在夜档司旧库追查桥南隐税卷，发现旧税筹与师父旧名相连。",
                "text": "阿照为了确认桥南隐税卷，必须在夜档司旧库里重新排账。因为陶主簿把旧竹筹藏进铺牌，所以她先把纸灯下的账页排成三列，但第三列却全都指向同一枚旧印。这个线索证明旧城隐税机制仍在运转，也让陶主簿想逼夜档司承接旧债的目标暴露。阿照决定不立刻摊牌，她选择留下半枚税筹作饵，代价是明夜必须独自去井口验灰。她刚锁上账册，井口忽然传来第二声钟，她发现半枚税筹背面还刻着师父的旧名。",
                "rag_quality_gate": {
                    "report_path": str(rag_path.relative_to(storage.root)),
                    "recommendation": "pass",
                    "context_budget_score": {"score": 96.0},
                },
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
            {"entity_id": "city_tax_office", "entity_type": "organization", "canonical_name": "城课司", "aliases": [], "forbidden_aliases": [], "role": "background_power", "status": "active"},
            {"entity_id": "mentor_debt", "entity_type": "case", "canonical_name": "师父旧债", "aliases": ["师门旧债"], "forbidden_aliases": [], "role": "mainline_debt", "status": "active"},
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
    _review_report(storage, draft_path, project_id=project_id, workspace_path=workspace_path)
    create_chapter_state_package(storage, draft_path, workspace_path=workspace_path)
    model_assisted_longform_extraction(storage, draft_path, workspace_path=workspace_path, use_model=False)


def _review_report(storage: LocalStorage, draft_path: Path, *, project_id: str, workspace_path: str) -> Path:
    draft = storage.read_asset(draft_path)
    return storage.write_asset(
        "reviews",
        ReviewReport(
            title="Ready structured review",
            source=draft.id,
            score=95.0,
            strengths=["clear motivation", "causal clue chain", "tracked ending hook"],
            weaknesses=[],
            issues=[],
            risk_level="low",
            revision_suggestions=[],
            next_action="accept",
            content={"target_asset_id": draft.id, "decision": "accept"},
            metadata={"project_id": project_id, "workspace_path": workspace_path, "workflow": "production-ready-fixture"},
            references=[draft.id, str(draft_path.relative_to(storage.root))],
        ),
    )


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
