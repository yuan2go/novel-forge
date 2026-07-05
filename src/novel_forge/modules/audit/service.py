from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from novel_forge.core.asset_scan import read_json_for_scan
from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.exception_policy import recoverable_asset_scan_error, require_recoverable_asset_scan_error
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.context_builder import build_flow_context_bundle, knowledge_context_contract_from_result, knowledge_context_contract_metadata
from novel_forge.modules.longform_stability import create_revision_task_from_gate, evaluate_longform_stability_gate
from novel_forge.modules.mkaos import list_risk_knowledge
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment, normalize_runtime_request_policy
from novel_forge.modules.publishing.release_gate import release_package_gate_evidence
from novel_forge.modules.production_context import build_production_context, filter_project_safe_references
from novel_forge.modules.review_issue import assert_no_blocking_review_issues, blocking_review_issues, review_issues_to_gate_issues
from novel_forge.modules.runtime_policy import provider_hard_stop_evidence_report
from novel_forge.modules.semantic_enhancement import analyze_story_semantics
from novel_forge.modules.standards import create_quality_score_report
from novel_forge.modules.style import create_style_review_report
from novel_forge.schemas import ChapterAuditReport, OriginalityReport, PublishGateReport, ReleasePackage
from novel_forge.storage.local import LocalStorage


def create_originality_report(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
) -> Path:
    path = resolve_path(storage.root, draft_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    target_text = _asset_text(target)
    direct_sources = _candidate_source_assets(storage, target.to_dict(), context)
    library_scan = _reference_library_scan(storage, target.to_dict(), context)
    source_assets = _dedupe_assets([*direct_sources, *library_scan["included_assets"]])
    checks = [_similarity_check(target_text, source) for source in source_assets]
    checks = [item for item in checks if item["source_asset_id"] != target.id]
    skeleton_checks = [_plot_skeleton_check(target.to_dict(), source) for source in source_assets if source.get("id") != target.id]
    role_checks = [_role_configuration_check(target.to_dict(), source) for source in source_assets if source.get("id") != target.id]
    forbidden_hits = _forbidden_element_hits(target_text, source_assets)
    risk_scores = _originality_risks(checks, skeleton_checks, role_checks, forbidden_hits, context, target.to_dict())
    risk_level = _max_risk(
        [
            risk_scores["plot_skeleton_risk"],
            risk_scores["character_setup_risk"],
            risk_scores["style_expression_risk"],
            risk_scores["source_license_risk"],
        ]
    )
    risk_explanations = _originality_risk_explanations(checks, skeleton_checks, role_checks, forbidden_hits, risk_scores, library_scan)
    remediation_plan = _originality_remediation_plan(risk_level, risk_explanations)
    recommendation = "pass"
    if risk_level == "medium":
        recommendation = "revise_before_publish"
    if risk_level == "high":
        recommendation = "block_publish"
    asset = OriginalityReport(
        title=f"Originality report for {target.title}",
        source=target.id,
        tags=["originality", "copyright-boundary", "publish-gate"],
        content={
            "target_asset_id": target.id,
            "source_asset_ids": _dedupe([str(item.get("id", "")) for item in source_assets]),
            "similarity_checks": checks,
            "plot_skeleton_checks": skeleton_checks,
            "role_configuration_checks": role_checks,
            "structure_similarity_matrix": _structure_similarity_matrix(checks, skeleton_checks, role_checks),
            "forbidden_element_hits": forbidden_hits,
            "reference_library_scan": {
                "scanned_count": library_scan["scanned_count"],
                "included_count": len(library_scan["included_assets"]),
                "excluded_count": len(library_scan["excluded"]),
                "excluded": library_scan["excluded"][:30],
                "scope": library_scan["scope"],
            },
            "model_assisted_review": _model_assisted_originality_review(checks, skeleton_checks, role_checks, forbidden_hits, library_scan),
            "plot_skeleton_risk": risk_scores["plot_skeleton_risk"],
            "character_setup_risk": risk_scores["character_setup_risk"],
            "style_expression_risk": risk_scores["style_expression_risk"],
            "source_license_risk": risk_scores["source_license_risk"],
            "risk_explanations": risk_explanations,
            "remediation_plan": remediation_plan,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "human_gate_required": risk_level in {"medium", "high"},
            "policy": {
                "protected_text_copying": "blocked",
                "allowed_use": "abstract structures and project-owned generated text only",
            },
        },
        metadata={
            "workflow": "originality-protection-gate",
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "created_at": utc_now(),
            "risk_level": risk_level,
        },
        references=filter_project_safe_references(
            storage,
            str(project.get("project_id", "")),
            _dedupe([target.id, *[str(item.get("id", "")) for item in source_assets]]),
        ),
    )
    with AgentExecutionContext(
        storage,
        agent_key="review",
        operation="create-originality-report",
        input_assets=[path],
        output_types=["originality_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        run.guard("write_originality_report", "originality_report")
        output = storage.write_asset("reviews", asset)
        run.succeed(output_assets=[_display_path(storage.root, output)])
        return output


def create_chapter_audit_report(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    quality_path: str | Path | None = None,
    style_path: str | Path | None = None,
    originality_path: str | Path | None = None,
) -> Path:
    path = resolve_path(storage.root, draft_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    quality_path = resolve_path(storage.root, quality_path) if quality_path else create_quality_score_report(storage, path, workspace_path=workspace_path)
    style_path = resolve_path(storage.root, style_path) if style_path else create_style_review_report(storage, path, workspace_path=workspace_path)
    originality_path = resolve_path(storage.root, originality_path) if originality_path else create_originality_report(storage, path, workspace_path=workspace_path)
    quality = _read_asset_dict(storage, quality_path)
    style = _read_asset_dict(storage, style_path)
    originality = _read_asset_dict(storage, originality_path)
    runtime_gate_evidence = _draft_runtime_gate_evidence(target.to_dict())
    platform_compliance = _platform_compliance(target.to_dict(), context)
    semantic_review = analyze_story_semantics(
        storage,
        target_path=path,
        project_id=str(project.get("project_id", "")) or None,
        workspace_path=str(project.get("workspace_path", "")) or workspace_path,
        production_context=context,
    )
    dimension_scores = _chapter_dimension_scores(quality, style, originality, context, runtime_gate_evidence, platform_compliance, semantic_review)
    gate_results, issues = _chapter_gate_results(dimension_scores, quality, style, originality, context, runtime_gate_evidence, platform_compliance, semantic_review)
    recommendation = "pass"
    if any(issue.get("severity") == "high" for issue in issues):
        recommendation = "block_publish"
    elif issues:
        recommendation = "revise"
    asset = ChapterAuditReport(
        title=f"Chapter audit for {target.title}",
        source=target.id,
        tags=["chapter-audit", "quality-gate", "review"],
        content={
            "target_asset_id": target.id,
            "dimension_scores": dimension_scores,
            "issues": issues,
            "gate_results": gate_results,
            "linked_reports": {
                "quality_score_report_path": _display_path(storage.root, Path(quality_path)),
                "style_review_report_path": _display_path(storage.root, Path(style_path)),
                "originality_report_path": _display_path(storage.root, Path(originality_path)),
                "rag_quality_report_path": runtime_gate_evidence.get("rag_quality_report_path", ""),
                "stability_preflight_path": runtime_gate_evidence.get("stability_preflight_path", ""),
            },
            "runtime_gate_evidence": runtime_gate_evidence,
            "platform_compliance": platform_compliance,
            "semantic_review": semantic_review,
            "recommendation": recommendation,
            "production_context": context,
        },
        metadata={
            "workflow": "chapter-quality-audit",
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "created_at": utc_now(),
            "risk_level": "high" if recommendation == "block_publish" else ("medium" if recommendation == "revise" else "low"),
        },
        references=filter_project_safe_references(
            storage,
            str(project.get("project_id", "")),
            _dedupe([target.id, _asset_id(quality), _asset_id(style), _asset_id(originality), *context.get("profile_references", [])]),
        ),
    )
    with AgentExecutionContext(
        storage,
        agent_key="review",
        operation="create-chapter-audit-report",
        input_assets=[path, quality_path, style_path, originality_path],
        output_types=["chapter_audit_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        run.guard("write_chapter_audit_report", "chapter_audit_report")
        output = storage.write_asset("reviews", asset)
        run.succeed(output_assets=[_display_path(storage.root, output)])
        return output


def create_publish_gate_report(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    chapter_audit_path: str | Path | None = None,
    human_override: bool = False,
    envelope: dict[str, Any] | None = None,
    environment: str = "",
    source_policy: dict[str, Any] | None = None,
) -> Path:
    path = resolve_path(storage.root, draft_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    runtime_request = normalize_runtime_request_policy(
        envelope_payload=envelope,
        environment=environment,
        source_policy=_publish_source_policy(source_policy),
        operation="publishing.publish_gate",
    )
    environment = str(runtime_request["environment"])
    envelope = runtime_request["envelope"] if runtime_request.get("envelope") else None
    resolved_source_policy = _publish_source_policy(runtime_request["source_policy"])
    _assert_publish_envelope_before_side_effect(
        storage,
        envelope=envelope,
        environment=environment,
        project_id=str(project.get("project_id", "")),
        asset_type="publish_gate_report",
        source_policy=resolved_source_policy,
        operation="publishing.publish_gate",
    )
    publish_context = build_flow_context_bundle(
        storage,
        path,
        flow="publish",
        project_id=str(project.get("project_id", "")),
        workspace_path=str(project.get("workspace_path", "")),
        chapter_id=str(target.content.get("chapter", "")) if isinstance(target.content, dict) else "",
        current_goal="publish gate",
        token_budget=4000,
        source_policy=resolved_source_policy,
        environment=environment,
        os_envelope=envelope,
    )
    context_bundle = publish_context.get("asset", {}) if isinstance(publish_context.get("asset", {}), dict) else {}
    context_bundle_id = str(context_bundle.get("id", ""))
    knowledge_contract = knowledge_context_contract_from_result(publish_context)
    os_envelope = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="publishing.publish_gate",
        project_id=str(project.get("project_id", "")),
        task_type="publish",
        asset_type="publish_gate_report",
        actor_type="publishing_service",
        source="audit.create_publish_gate_report",
        context_bundle_id=context_bundle_id,
        source_policy=resolved_source_policy,
        environment=environment,
        bypass_reason="publish gate local compatibility path",
        require_for_production=True,
    )
    audit_path = resolve_path(storage.root, chapter_audit_path) if chapter_audit_path else create_chapter_audit_report(storage, path, workspace_path=workspace_path)
    audit = _read_asset_dict(storage, audit_path)
    gate_data = _publish_gates(audit, context)
    mkaos_risk = _mkaos_risk_summary(storage, str(project.get("project_id", "")))
    gate_data["gates"]["mkaos_risk_clear"] = not mkaos_risk["blocking"]
    gate_data["blocking_issues"].extend(mkaos_risk["blocking_issues"])
    longform_gate = evaluate_longform_stability_gate(storage, path, workspace_path=workspace_path)
    gate_data["gates"]["longform_stability_passed"] = bool(longform_gate.get("passed"))
    for key, value in longform_gate.get("gates", {}).items():
        gate_data["gates"][f"longform_{key}"] = bool(value)
    gate_data["blocking_issues"].extend(longform_gate.get("blocking_issues", []))
    related_asset_ids = _related_review_issue_asset_ids(target.to_dict())
    review_issue_rows = blocking_review_issues(storage, target_asset_id=target.id, project_id=str(project.get("project_id", "")) or None, related_asset_ids=related_asset_ids)
    gate_data["blocking_issues"].extend(review_issues_to_gate_issues(review_issue_rows))
    gate_data["gates"]["review_issue_blocking_clear"] = not review_issue_rows
    production_policy = is_production_environment(environment)
    evaluation_gate = _evaluation_gate_summary(storage, target.to_dict(), _display_path(storage.root, path), project_id=str(project.get("project_id", "")), required=production_policy)
    gate_data["gates"]["evaluation_gate_passed"] = not evaluation_gate["blocking"]
    gate_data["blocking_issues"].extend(evaluation_gate["blocking_issues"])
    provider_runtime_gate = _provider_runtime_gate_summary(storage, project_id=str(project.get("project_id", "")), workspace_path=str(project.get("workspace_path", "")), required=production_policy)
    gate_data["gates"]["provider_runtime_gate_passed"] = not provider_runtime_gate["blocking"]
    gate_data["blocking_issues"].extend(provider_runtime_gate["blocking_issues"])
    platform_strategy_gate = _platform_strategy_gate_summary(storage, context, project_id=str(project.get("project_id", "")), required=production_policy)
    gate_data["gates"]["platform_strategy_gate_passed"] = not platform_strategy_gate["blocking"]
    gate_data["blocking_issues"].extend(platform_strategy_gate["blocking_issues"])
    blocking = gate_data["blocking_issues"]
    decision = "ready"
    if any(issue.get("severity") in {"high", "critical"} for issue in blocking):
        decision = "blocked"
    elif blocking:
        decision = "needs_revision"
    if human_override and decision != "blocked":
        decision = "ready"
    asset = PublishGateReport(
        title=f"Publish gate for {target.title}",
        source=target.id,
        tags=["publish-gate", "quality-gate", "release-control"],
        content={
            "target_asset_id": target.id,
            "gates": gate_data["gates"],
            "decision": decision,
            "blocking_issues": blocking,
            "review_issue_paths": [row.get("path", "") for row in review_issue_rows],
            "required_reports": {
                "chapter_audit_report_path": _display_path(storage.root, Path(audit_path)),
                "longform_stability_reports": longform_gate.get("required_reports", {}),
                **(audit.get("content", {}).get("linked_reports", {}) if isinstance(audit.get("content", {}), dict) else {}),
            },
            "human_override": bool(human_override),
            "preflight": context.get("preflight", {}),
            "longform_stability": longform_gate,
            "evaluation_gate": evaluation_gate,
            "provider_runtime_gate": provider_runtime_gate,
            "platform_strategy_gate": platform_strategy_gate,
            "context_bundle_id": context_bundle_id,
            "context_bundle_path": str(publish_context.get("path", "")),
            "knowledge_context_contract": knowledge_contract,
            "mkaos_risk": mkaos_risk,
            "source_isolation": {
                "source_chunk_raw_text_allowed": False,
                "runtime_assets_in_generation_rag_allowed": False,
                "raw_source_text_allowed": False,
                "context_bundle_path": str(publish_context.get("path", "")),
            },
            "os_envelope_id": os_envelope.get("envelope_id", ""),
        },
        metadata={
            "workflow": "publish-gate",
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "created_at": utc_now(),
            "risk_level": "high" if decision == "blocked" else ("medium" if decision == "needs_revision" else "low"),
            **envelope_asset_metadata(os_envelope),
            "context_bundle_id": context_bundle_id,
            "context_bundle_path": str(publish_context.get("path", "")),
            **knowledge_context_contract_metadata(knowledge_contract),
        },
        references=filter_project_safe_references(
            storage,
            str(project.get("project_id", "")),
            _dedupe([target.id, _asset_id(audit), str(publish_context.get("path", "")), *context.get("profile_references", [])]),
        ),
    )
    with AgentExecutionContext(
        storage,
        agent_key="publishing",
        operation="create-publish-gate-report",
        input_assets=[path, audit_path, str(publish_context.get("path", ""))],
        output_types=["publish_gate_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
        knowledge_context_contract=knowledge_contract,
    ) as run:
        run.guard("read_asset")
        run.guard("write_publish_gate_report", "publish_gate_report")
        output = storage.write_asset("publishing", asset)
        if decision != "ready":
            create_revision_task_from_gate(
                storage,
                output,
                path,
                blocking_issues=blocking,
                workspace_path=str(project.get("workspace_path", "")) or workspace_path,
            )
        run.succeed(output_assets=[_display_path(storage.root, output)])
        return output


def create_release_package(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    publish_gate_path: str | Path | None = None,
    channel: str = "local",
    human_override: bool = False,
    envelope: dict[str, Any] | None = None,
    environment: str = "",
    source_policy: dict[str, Any] | None = None,
) -> Path:
    path = resolve_path(storage.root, draft_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    runtime_request = normalize_runtime_request_policy(
        envelope_payload=envelope,
        environment=environment,
        source_policy=_publish_source_policy(source_policy),
        operation="publishing.release_package",
    )
    environment = str(runtime_request["environment"])
    envelope = runtime_request["envelope"] if runtime_request.get("envelope") else None
    resolved_source_policy = _publish_source_policy(runtime_request["source_policy"])
    _assert_publish_envelope_before_side_effect(
        storage,
        envelope=envelope,
        environment=environment,
        project_id=str(project.get("project_id", "")),
        asset_type="release_package",
        source_policy=resolved_source_policy,
        operation="publishing.release_package",
    )
    gate_path = resolve_path(storage.root, publish_gate_path) if publish_gate_path else create_publish_gate_report(
        storage,
        path,
        workspace_path=workspace_path,
        human_override=human_override,
        envelope=envelope,
        environment=environment,
        source_policy=resolved_source_policy,
    )
    gate = _read_asset_dict(storage, gate_path)
    decision = gate.get("content", {}).get("decision", "blocked") if isinstance(gate.get("content", {}), dict) else "blocked"
    if decision == "blocked" and _gate_has_mkaos_blocker(gate):
        raise ValueError("release_package blocked by MKAOS high/critical risk")
    gate_content = gate.get("content", {}) if isinstance(gate.get("content", {}), dict) else {}
    release_gate_evidence = release_package_gate_evidence(gate, production=is_production_environment(environment))
    if is_production_environment(environment) and release_gate_evidence["blocking"]:
        dimensions = ", ".join(str(issue.get("dimension", "")) for issue in release_gate_evidence["blocking_issues"])
        raise ValueError(f"release_package blocked by gate evidence: {dimensions}")
    if is_production_environment(environment) and decision != "ready":
        raise ValueError(f"release_package blocked by publish gate decision: {decision}")
    status = "ready" if decision == "ready" else "blocked"
    gate_envelope = gate.get("metadata", {}).get("os_envelope", {}) if isinstance(gate.get("metadata", {}), dict) and isinstance(gate.get("metadata", {}).get("os_envelope", {}), dict) else {}
    os_envelope = enforce_os_envelope(
        storage,
        envelope_payload=envelope or gate_envelope,
        operation="publishing.release_package",
        project_id=str(project.get("project_id", "")),
        task_type="publish",
        asset_type="release_package",
        actor_type="publishing_service",
        source="audit.create_release_package",
        context_bundle_id=str(gate_content.get("context_bundle_id", "")),
        source_policy=resolved_source_policy,
        environment=environment or str(gate_envelope.get("environment", "")),
        bypass_reason="release package local compatibility path",
        require_for_production=True,
    )
    assert_no_blocking_review_issues(
        storage,
        target_asset_id=target.id,
        project_id=str(project.get("project_id", "")) or None,
        related_asset_ids=_related_review_issue_asset_ids(target.to_dict()),
        gate="release_package",
    )
    text = _asset_text(target)
    release_version = make_id("release_version", f"{target.id}:{channel}:{utc_now()}")
    asset = ReleasePackage(
        title=f"Release package for {target.title}",
        source=target.id,
        tags=["release-package", str(channel or "local")],
        content={
            "release_version": release_version,
            "version_key": f"{target.id}:{release_version}",
            "target_asset_id": target.id,
            "publish_gate_report_id": _asset_id(gate),
            "title_candidates": _title_candidates(target.title, context),
            "summary": _summary(text),
            "tags": _release_tags(context, target),
            "metadata_optimization": _publishing_metadata_optimization(target.title, text, context),
            "cover_asset": _cover_asset_requirements(context, channel or "local"),
            "platform_review_feedback": {
                "status": "not_submitted",
                "feedback_source": "manual_or_webhook_adapter",
                "feedback_items": [],
                "回流说明": "平台审核反馈进入 publishing_log 后，再回流到审稿规则、章节计划和发布策略。",
            },
            "channel": channel or "local",
            "status": status,
            "draft_path": _display_path(storage.root, path),
            "publish_gate_report_path": _display_path(storage.root, Path(gate_path)),
            "platform_rules": _release_platform_rules(context, channel or "local"),
            "known_risks": gate_content.get("blocking_issues", []),
            "review_report": gate_content.get("required_reports", {}),
            "context_bundle_id": gate_content.get("context_bundle_id", ""),
            "context_bundle_path": gate_content.get("context_bundle_path", ""),
            "mkaos_risk": gate_content.get("mkaos_risk", {}),
            "evaluation_gate": gate_content.get("evaluation_gate", {}),
            "provider_runtime_gate": gate_content.get("provider_runtime_gate", {}),
            "platform_strategy_gate": gate_content.get("platform_strategy_gate", {}),
            "release_gate_evidence": release_gate_evidence,
            "source_isolation": {
                "source_chunk_raw_text_allowed": False,
                "runtime_assets_in_generation_rag_allowed": False,
                "raw_source_text_allowed": False,
                "release_package_raw_text_included": False,
            },
            "rollback_snapshot": {
                "draft_path": _display_path(storage.root, path),
                "publish_gate_report_path": _display_path(storage.root, Path(gate_path)),
                "created_at": utc_now(),
            },
            "os_envelope_id": os_envelope.get("envelope_id", ""),
            "created_at": utc_now(),
        },
        metadata={
            "workflow": "release-package",
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "created_at": utc_now(),
            "risk_level": "low" if status == "ready" else "high",
            **envelope_asset_metadata(os_envelope),
        },
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), _dedupe([target.id, _asset_id(gate)])),
    )
    with AgentExecutionContext(
        storage,
        agent_key="publishing",
        operation="create-release-package",
        input_assets=[path, gate_path],
        output_types=["release_package"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_release_package", "release_package")
        output = storage.write_asset("publishing", asset)
        run.succeed(output_assets=[_display_path(storage.root, output)])
        return output


def _release_platform_rules(context: dict[str, Any], channel: str) -> dict[str, Any]:
    project = context.get("project", {}) if isinstance(context.get("project", {}), dict) else {}
    config = project.get("project_config", {}) if isinstance(project.get("project_config", {}), dict) else {}
    return {
        "channel": channel,
        "target_platform": config.get("target_platform", channel),
        "require_chapter_audit": True,
        "require_originality_pass": True,
        "require_publish_gate_ready": True,
        "title_candidate_count": 3,
        "min_hook_score": config.get("publish_min_hook_score", 0.7),
        "max_risk_level": config.get("publish_max_risk_level", "medium"),
    }


def _publish_source_policy(source_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = dict(source_policy or {})
    policy.update({
        "raw_source_text_allowed": False,
        "source_chunk_raw_text_allowed": False,
        "runtime_assets_in_generation_rag_allowed": False,
        "generation_rag_allowed": True,
        "exclude_raw_sources": True,
    })
    return policy


def _assert_publish_envelope_before_side_effect(
    storage: LocalStorage,
    *,
    envelope: dict[str, Any] | None,
    environment: str,
    project_id: str,
    asset_type: str,
    source_policy: dict[str, Any],
    operation: str,
) -> None:
    runtime_request = normalize_runtime_request_policy(
        envelope_payload=envelope,
        environment=environment,
        source_policy=source_policy,
        operation=operation,
    )
    if not runtime_request["production"]:
        return
    enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation=operation,
        project_id=project_id,
        task_type="publish",
        asset_type=asset_type,
        actor_type="publishing_service",
        source="audit.production_preflight",
        source_policy=source_policy,
        environment=str(runtime_request["environment"]),
        require_for_production=True,
        record_trace=False,
    )


def _mkaos_risk_summary(storage: LocalStorage, project_id: str) -> dict[str, Any]:
    rows = list_risk_knowledge(storage, project_id=project_id or None, limit=200)
    blocking_rows = [
        row
        for row in rows
        if str((row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}).get("risk_level") or (row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}).get("risk_level") or "").lower()
        in {"high", "critical"}
    ]
    issues = [
        {
            "dimension": "mkaos_risk",
            "severity": str((row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}).get("risk_level") or (row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}).get("risk_level") or "high"),
            "message": f"MKAOS risky knowledge requires review before publish: {row.get('title') or row.get('id')}",
            "recommendation": "resolve, deprecate, or lower-risk the knowledge card before building a release package",
            "knowledge_id": row.get("id", ""),
            "path": row.get("path", ""),
        }
        for row in blocking_rows
    ]
    return {
        "risk_count": len(rows),
        "blocking": bool(blocking_rows),
        "blocking_count": len(blocking_rows),
        "blocking_issues": issues,
        "risk_items": [
            {
                "id": row.get("id", ""),
                "path": row.get("path", ""),
                "title": row.get("title", ""),
                "risk_reasons": row.get("risk_reasons", []),
            }
            for row in rows[:20]
        ],
    }


def _evaluation_gate_summary(storage: LocalStorage, target: dict[str, Any], target_path: str, *, project_id: str, required: bool) -> dict[str, Any]:
    gate = _latest_governance_asset(
        storage,
        "evaluation_gate",
        project_id=project_id,
        target_asset_id=str(target.get("id", "")),
        target_asset_path=target_path,
    )
    if not gate:
        issues = []
        if required:
            issues.append(
                {
                    "dimension": "evaluation_gate",
                    "severity": "high",
                    "message": "production publish requires a passing EvaluationGate",
                    "recommendation": "run /product/evaluation/evaluation-gate for the draft before publishing",
                }
            )
        return {"status": "missing", "required": required, "blocking": bool(issues), "path": "", "blocking_issues": issues}
    content = gate.get("content", {}) if isinstance(gate.get("content", {}), dict) else {}
    status = str(content.get("status") or "unknown")
    blocking = bool(content.get("blocking")) or status == "blocked"
    issues = []
    if blocking:
        issues.append(
            {
                "dimension": "evaluation_gate",
                "severity": "critical",
                "message": f"EvaluationGate blocked publish: score {content.get('overall_score', 'unknown')}",
                "recommendation": "resolve evaluation findings or rerun evaluation after revision",
                "evaluation_gate_path": gate.get("path", ""),
            }
        )
    return {
        "status": status,
        "required": required,
        "blocking": blocking,
        "path": gate.get("path", ""),
        "overall_score": content.get("overall_score", 0),
        "minimum_score": content.get("minimum_score", 0),
        "blocking_issues": issues,
    }


def _provider_runtime_gate_summary(storage: LocalStorage, *, project_id: str, workspace_path: str, required: bool) -> dict[str, Any]:
    report = provider_hard_stop_evidence_report(storage, project_id=project_id or None, workspace_path=workspace_path or None)
    status = str(report.get("status") or "missing")
    summary = report.get("summary", {}) if isinstance(report.get("summary", {}), dict) else {}
    blocking = bool(required and status != "passed")
    issues = []
    if blocking:
        failed_count = int(summary.get("failed_provider_guard_count", 0) or 0)
        issues.append(
            {
                "dimension": "provider_runtime_gate",
                "severity": "critical" if failed_count else "high",
                "message": f"production publish requires provider runtime hard-stop evidence; current status is {status}",
                "recommendation": "run provider runtime guard/evaluation before publish gate, or record an approved fallback with ReviewIssue evidence",
                "provider_runtime_status": status,
                "missing_dimensions": summary.get("missing_dimensions", []),
            }
        )
    return {
        "status": status,
        "required": required,
        "blocking": blocking,
        "summary": summary,
        "provider_guard_gate_count": summary.get("provider_guard_gate_count", 0),
        "failed_provider_guard_count": summary.get("failed_provider_guard_count", 0),
        "missing_dimensions": summary.get("missing_dimensions", []),
        "blocking_issues": issues,
    }


def _platform_strategy_gate_summary(storage: LocalStorage, context: dict[str, Any], *, project_id: str, required: bool) -> dict[str, Any]:
    project = context.get("project", {}) if isinstance(context.get("project", {}), dict) else {}
    config = project.get("project_config", {}) if isinstance(project.get("project_config", {}), dict) else {}
    platform_id = str(config.get("target_platform") or "").strip()
    pack = _latest_governance_asset(storage, "platform_strategy_pack", project_id=project_id)
    retention = _latest_governance_asset(storage, "platform_retention_risk", project_id=project_id)
    retention_content = retention.get("content", {}) if isinstance(retention.get("content", {}), dict) else {}
    risk_level = str(retention_content.get("risk_level") or "unknown").lower()
    issues = []
    if required and not pack:
        issues.append(
            {
                "dimension": "platform_strategy_gate",
                "severity": "high",
                "message": "production publish requires a PlatformStrategyPack",
                "recommendation": "build platform strategy pack before publish gate",
            }
        )
    if risk_level in {"high", "critical"}:
        issues.append(
            {
                "dimension": "platform_retention_risk",
                "severity": "critical" if risk_level == "critical" else "high",
                "message": f"platform retention risk is {risk_level}",
                "recommendation": "revise chapter strategy or resolve retention risk before release",
                "platform_retention_risk_path": retention.get("path", ""),
            }
        )
    return {
        "status": "blocked" if issues else "passed" if pack or not required else "missing",
        "required": required,
        "target_platform": platform_id,
        "platform_strategy_pack_path": pack.get("path", "") if pack else "",
        "platform_retention_risk_path": retention.get("path", "") if retention else "",
        "risk_level": risk_level,
        "blocking": bool(issues),
        "blocking_issues": issues,
    }


def _latest_governance_asset(
    storage: LocalStorage,
    asset_type: str,
    *,
    project_id: str,
    target_asset_id: str = "",
    target_asset_path: str = "",
) -> dict[str, Any]:
    rows = []
    for category in ["runs", "platforms", "publishing"]:
        for path in storage.list_json(category):
            data = _read_json_safe(storage, path)
            if data.get("type") != asset_type:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            row_project = str(metadata.get("project_id") or content.get("project_id") or "")
            if project_id and row_project and row_project != project_id:
                continue
            if target_asset_id and str(content.get("target_asset_id") or "") != target_asset_id:
                continue
            if target_asset_path and str(content.get("target_asset_path") or "") not in {"", target_asset_path}:
                continue
            data["path"] = _display_path(storage.root, path)
            rows.append(data)
    return sorted(rows, key=lambda row: str(row.get("updated_at") or row.get("created_at") or row.get("content", {}).get("created_at", "")))[-1] if rows else {}


def _gate_has_mkaos_blocker(gate: dict[str, Any]) -> bool:
    content = gate.get("content", {}) if isinstance(gate.get("content", {}), dict) else {}
    mkaos_risk = content.get("mkaos_risk", {}) if isinstance(content.get("mkaos_risk", {}), dict) else {}
    return bool(mkaos_risk.get("blocking"))


def _related_review_issue_asset_ids(asset: dict[str, Any]) -> list[str]:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return _dedupe(
        [
            str(asset.get("source") or ""),
            str(metadata.get("previous_draft_id") or ""),
            str(content.get("source_draft_id") or ""),
            str(content.get("target_draft_id") or ""),
        ]
    )


def _candidate_source_assets(storage: LocalStorage, target: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[str] = [str(target.get("source", ""))]
    if isinstance(target.get("references", []), list):
        values.extend(str(item) for item in target.get("references", []) if str(item).strip())
    if isinstance(context.get("profile_references", []), list):
        values.extend(str(item) for item in context.get("profile_references", []) if str(item).strip())
    values = _dedupe(values)
    results: list[dict[str, Any]] = []
    for value in values:
        payload = _asset_by_reference(storage, value)
        if payload and payload.get("id") != target.get("id"):
            results.append(payload)
    return _dedupe_assets(results)


def _reference_library_scan(storage: LocalStorage, target: dict[str, Any], context: dict[str, Any], *, limit: int = 500) -> dict[str, Any]:
    project_id = str(context.get("project", {}).get("project_id", "") if isinstance(context.get("project", {}), dict) else "")
    target_id = str(target.get("id", ""))
    target_type = str(target.get("type", ""))
    allowed_types = {
        "source_document",
        "decomposition_report",
        "common_novel_analysis_report",
        "web_fiction_business_analysis_report",
        "published_fiction_analysis_report",
        "classic_literary_analysis_report",
        "analysis_conversion_report",
        "material_card",
        "knowledge_card",
        "style_decomposition_report",
        "writing_template",
        "craft_template",
        "draft_chapter",
        "draft_version",
    }
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    scan_errors: list[dict[str, str]] = []
    scanned = 0
    for category in DATA_DIRS:
        for path in reversed(storage.list_json(category)):
            if len(included) >= limit:
                break
            try:
                data = storage.read_json(path)
            except Exception as exc:
                require_recoverable_asset_scan_error(exc, context=f"reference library scan: {path}")
                scan_errors.append(recoverable_asset_scan_error(exc, path=_display_path(storage.root, path)))
                continue
            if not isinstance(data, dict):
                continue
            scanned += 1
            asset_id = str(data.get("id", ""))
            asset_type = str(data.get("type", ""))
            if asset_id == target_id or asset_type == target_type == "draft_version":
                continue
            if asset_type not in allowed_types:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            row_project = str(metadata.get("project_id", ""))
            if project_id and row_project and row_project != project_id:
                excluded.append({"path": _display_path(storage.root, path), "reason": "cross_project_reference"})
                continue
            rights = metadata.get("rights", {}) if isinstance(metadata.get("rights", {}), dict) else {}
            authorization = str(rights.get("authorization") or metadata.get("rights_authorization") or "").lower()
            risk = str(metadata.get("risk_level") or metadata.get("copyright_risk") or "").lower()
            if asset_type in {"source_document", "draft_chapter", "draft_version"} and authorization in {"restricted", "unknown"}:
                excluded.append({"path": _display_path(storage.root, path), "reason": f"high_raw_text_risk:{authorization or risk or 'unknown'}"})
                continue
            item = dict(data)
            item["_scan_path"] = _display_path(storage.root, path)
            included.append(item)
        if len(included) >= limit:
            break
    return {
        "included_assets": _dedupe_assets(included),
        "excluded": excluded,
        "scan_errors": scan_errors[:50],
        "scan_error_count": len(scan_errors),
        "scanned_count": scanned,
        "scope": {"project_id": project_id, "limit": limit, "allowed_types": sorted(allowed_types)},
    }


def _model_assisted_originality_review(
    checks: list[dict[str, Any]],
    skeleton_checks: list[dict[str, Any]],
    role_checks: list[dict[str, Any]],
    forbidden_hits: list[dict[str, Any]],
    library_scan: dict[str, Any],
) -> dict[str, Any]:
    high = [
        *[item for item in checks if item.get("risk") == "high"],
        *[item for item in skeleton_checks if item.get("risk") == "high"],
        *[item for item in role_checks if item.get("risk") == "high"],
    ]
    medium = [
        *[item for item in checks if item.get("risk") == "medium"],
        *[item for item in skeleton_checks if item.get("risk") == "medium"],
        *[item for item in role_checks if item.get("risk") == "medium"],
    ]
    recommendation = "pass"
    if high or any(item.get("kind") == "license_risk" and item.get("element") == "restricted" for item in forbidden_hits):
        recommendation = "block_publish"
    elif medium or forbidden_hits:
        recommendation = "human_review"
    return {
        "provider": "local-rules-review",
        "model_name": "deterministic-originality-reviewer",
        "recommendation": recommendation,
        "rationale": [
            f"reference library scan included {len(library_scan.get('included_assets', []))} assets and excluded {len(library_scan.get('excluded', []))}",
            f"high risk structural hits: {len(high)}",
            f"medium risk structural hits: {len(medium)}",
            f"forbidden/license hits: {len(forbidden_hits)}",
        ],
        "next_action": "rewrite and rerun originality gate" if recommendation == "block_publish" else "human review required before release" if recommendation == "human_review" else "safe to continue through publish gate",
    }


def _structure_similarity_matrix(
    checks: list[dict[str, Any]],
    skeleton_checks: list[dict[str, Any]],
    role_checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_source: dict[str, dict[str, Any]] = {}
    for label, rows in [("text", checks), ("plot_skeleton", skeleton_checks), ("role_configuration", role_checks)]:
        for item in rows:
            source_id = str(item.get("source_asset_id", ""))
            if not source_id:
                continue
            row = by_source.setdefault(
                source_id,
                {
                    "source_asset_id": source_id,
                    "source_asset_type": item.get("source_asset_type", ""),
                    "source_title": item.get("source_title", ""),
                    "text": 0.0,
                    "plot_skeleton": 0.0,
                    "role_configuration": 0.0,
                    "max_risk": "low",
                    "matched_terms": [],
                },
            )
            row[label] = max(float(row.get(label, 0) or 0), float(item.get("similarity", 0) or 0))
            row["max_risk"] = _max_risk([str(row.get("max_risk", "low")), str(item.get("risk", "low"))])
            terms = item.get("matched_terms", []) if isinstance(item.get("matched_terms", []), list) else []
            row["matched_terms"] = _dedupe([*row.get("matched_terms", []), *[str(term) for term in terms]])[:24]
    rows = list(by_source.values())
    rows.sort(key=lambda item: ({"high": 3, "medium": 2, "low": 1}.get(str(item.get("max_risk", "low")), 0), float(item.get("plot_skeleton", 0) or 0), float(item.get("role_configuration", 0) or 0)), reverse=True)
    return rows[:50]


def _originality_risk_explanations(
    checks: list[dict[str, Any]],
    skeleton_checks: list[dict[str, Any]],
    role_checks: list[dict[str, Any]],
    forbidden_hits: list[dict[str, Any]],
    risk_scores: dict[str, str],
    library_scan: dict[str, Any],
) -> list[dict[str, str]]:
    explanations: list[dict[str, str]] = []
    for key, risk in risk_scores.items():
        if risk in {"medium", "high"}:
            explanations.append(
                {
                    "dimension": key,
                    "severity": risk,
                    "reason": _risk_reason(key, checks, skeleton_checks, role_checks, forbidden_hits),
                    "evidence": f"scanned={library_scan.get('scanned_count', 0)}, included={len(library_scan.get('included_assets', []))}, excluded={len(library_scan.get('excluded', []))}",
                }
            )
    if not explanations:
        explanations.append({"dimension": "overall", "severity": "low", "reason": "no high-overlap text, plot skeleton, role setup, or source license signal crossed thresholds", "evidence": "reference library scan completed"})
    return explanations


def _risk_reason(
    dimension: str,
    checks: list[dict[str, Any]],
    skeleton_checks: list[dict[str, Any]],
    role_checks: list[dict[str, Any]],
    forbidden_hits: list[dict[str, Any]],
) -> str:
    if dimension == "plot_skeleton_risk":
        top = max([*checks, *skeleton_checks], key=lambda item: float(item.get("similarity", 0) or 0), default={})
        return f"plot/text overlap near {top.get('source_title', top.get('source_asset_id', 'reference asset'))}: similarity={top.get('similarity', 0)}"
    if dimension == "character_setup_risk":
        top = max(role_checks, key=lambda item: float(item.get("similarity", 0) or 0), default={})
        return f"role configuration overlap near {top.get('source_title', top.get('source_asset_id', 'reference asset'))}: similarity={top.get('similarity', 0)}"
    if dimension == "style_expression_risk":
        return "style profile or expression boundary requires human confirmation; avoid author imitation and signature phrase reuse"
    if dimension == "source_license_risk":
        return f"license/forbidden source signals present: {len(forbidden_hits)}"
    return "risk threshold crossed"


def _originality_remediation_plan(risk_level: str, explanations: list[dict[str, str]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for item in explanations:
        dimension = item.get("dimension", "")
        if dimension == "plot_skeleton_risk":
            actions.append({"action": "rebuild_plot_spine", "priority": item.get("severity", "medium"), "instruction": "change causal order, core dilemma, payoff timing, and scene function while preserving only abstract project goals"})
        elif dimension == "character_setup_risk":
            actions.append({"action": "reconfigure_roles", "priority": item.get("severity", "medium"), "instruction": "alter role triangle, motives, constraints, relationship polarity, and decision cost"})
        elif dimension == "style_expression_risk":
            actions.append({"action": "neutralize_style", "priority": item.get("severity", "medium"), "instruction": "rewrite with project style_profile parameters; remove any signature phrasing or author-specific rhythm"})
        elif dimension == "source_license_risk":
            actions.append({"action": "remove_restricted_source_dependency", "priority": "high", "instruction": "remove raw source dependency from generation context and convert only abstract notes if license allows"})
    if not actions and risk_level == "low":
        actions.append({"action": "keep_evidence", "priority": "low", "instruction": "keep report attached to publish gate as originality evidence"})
    return actions


def _similarity_check(target_text: str, source: dict[str, Any]) -> dict[str, Any]:
    source_text = _asset_text(source)
    target_ngrams = _ngrams(target_text)
    source_ngrams = _ngrams(source_text)
    overlap = target_ngrams & source_ngrams
    denominator = max(len(target_ngrams | source_ngrams), 1)
    similarity = round(len(overlap) / denominator, 4)
    return {
        "source_asset_id": str(source.get("id", "")),
        "source_asset_type": str(source.get("type", "")),
        "source_title": str(source.get("title") or source.get("name") or ""),
        "similarity": similarity,
        "matched_shingle_count": len(overlap),
        "risk": "high" if similarity >= 0.45 else ("medium" if similarity >= 0.25 else "low"),
    }


def _plot_skeleton_check(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    target_signature = _plot_signature(target)
    source_signature = _plot_signature(source)
    similarity = _jaccard(target_signature, source_signature)
    return {
        "source_asset_id": str(source.get("id", "")),
        "source_asset_type": str(source.get("type", "")),
        "source_title": str(source.get("title") or source.get("name") or ""),
        "similarity": similarity,
        "matched_terms": sorted(target_signature & source_signature)[:24],
        "risk": "high" if similarity >= 0.5 else ("medium" if similarity >= 0.3 else "low"),
    }


def _role_configuration_check(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    target_signature = _role_signature(target)
    source_signature = _role_signature(source)
    similarity = _jaccard(target_signature, source_signature)
    return {
        "source_asset_id": str(source.get("id", "")),
        "source_asset_type": str(source.get("type", "")),
        "source_title": str(source.get("title") or source.get("name") or ""),
        "similarity": similarity,
        "matched_terms": sorted(target_signature & source_signature)[:24],
        "risk": "high" if similarity >= 0.55 else ("medium" if similarity >= 0.35 else "low"),
    }


def _forbidden_element_hits(target_text: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lowered = target_text.lower()
    hits: list[dict[str, Any]] = []
    for source in sources:
        title = str(source.get("title") or source.get("name") or "").strip()
        if title and len(title) >= 4 and title.lower() in lowered:
            hits.append({"source_asset_id": str(source.get("id", "")), "element": title, "kind": "source_title"})
        metadata = source.get("metadata", {}) if isinstance(source.get("metadata", {}), dict) else {}
        rights = metadata.get("rights", {}) if isinstance(metadata.get("rights", {}), dict) else {}
        authorization = str(rights.get("authorization") or metadata.get("rights_authorization") or "").lower()
        if authorization in {"unknown", "noncommercial", "restricted"}:
            hits.append(
                {
                    "source_asset_id": str(source.get("id", "")),
                    "element": authorization,
                    "kind": "license_risk",
                }
            )
    return hits


def _originality_risks(
    checks: list[dict[str, Any]],
    skeleton_checks: list[dict[str, Any]],
    role_checks: list[dict[str, Any]],
    forbidden_hits: list[dict[str, Any]],
    context: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, str]:
    max_similarity = max((float(item.get("similarity", 0)) for item in checks), default=0.0)
    max_skeleton_similarity = max((float(item.get("similarity", 0)) for item in skeleton_checks), default=0.0)
    max_role_similarity = max((float(item.get("similarity", 0)) for item in role_checks), default=0.0)
    plot_signal = max(max_similarity, max_skeleton_similarity)
    plot = "high" if plot_signal >= 0.45 else ("medium" if plot_signal >= 0.25 else "low")
    character = "high" if max_role_similarity >= 0.55 else ("medium" if max_role_similarity >= 0.35 or any(item.get("kind") == "source_title" for item in forbidden_hits) else "low")
    style = "medium" if _profile_risk(context, "style_profile") in {"medium", "high"} else "low"
    source_license = "high" if any(item.get("kind") == "license_risk" and item.get("element") in {"restricted"} for item in forbidden_hits) else (
        "medium" if any(item.get("kind") == "license_risk" for item in forbidden_hits) else "low"
    )
    boundary = str(target.get("content", {}).get("copyright_boundary", "") if isinstance(target.get("content", {}), dict) else "").lower()
    if not boundary:
        source_license = _max_risk([source_license, "medium"])
    return {
        "plot_skeleton_risk": plot,
        "character_setup_risk": character,
        "style_expression_risk": style,
        "source_license_risk": source_license,
    }


def _chapter_dimension_scores(
    quality: dict[str, Any],
    style: dict[str, Any],
    originality: dict[str, Any],
    context: dict[str, Any],
    runtime_gate_evidence: dict[str, Any],
    platform_compliance: dict[str, Any],
    semantic_review: dict[str, Any],
) -> dict[str, float]:
    quality_content = quality.get("content", {}) if isinstance(quality.get("content", {}), dict) else {}
    style_content = style.get("content", {}) if isinstance(style.get("content", {}), dict) else {}
    originality_content = originality.get("content", {}) if isinstance(originality.get("content", {}), dict) else {}
    scores = dict(quality_content.get("scores", {}) if isinstance(quality_content.get("scores", {}), dict) else {})
    scores["style_consistency"] = float(style_content.get("style_match_score", scores.get("style_consistency", 75)) or 0)
    scores["originality_safety"] = _risk_score(str(originality_content.get("risk_level", "unknown")))
    scores["production_preflight"] = 100.0 if context.get("preflight", {}).get("ready") else 60.0
    scores["rag_context_quality"] = float(runtime_gate_evidence.get("rag_quality_score", 0) or 0)
    scores["long_form_stability"] = 100.0 if runtime_gate_evidence.get("stability_gate_passed") else 45.0
    scores["platform_compliance"] = float(platform_compliance.get("score", 0) or 0)
    motivation = semantic_review.get("character_motivation_drift", {}) if isinstance(semantic_review.get("character_motivation_drift", {}), dict) else {}
    power = semantic_review.get("power_scale_conflicts", {}) if isinstance(semantic_review.get("power_scale_conflicts", {}), dict) else {}
    chapter = semantic_review.get("chapter_pleasure_toxicity", {}) if isinstance(semantic_review.get("chapter_pleasure_toxicity", {}), dict) else {}
    platform = semantic_review.get("platform_adaptation_review", {}) if isinstance(semantic_review.get("platform_adaptation_review", {}), dict) else {}
    scores["character_motivation_alignment"] = float(motivation.get("score", 75.0) or 0)
    scores["power_scale_consistency"] = float(power.get("score", 100.0) or 0)
    scores["chapter_pleasure_score"] = float(chapter.get("pleasure_score", 0.0) or 0)
    scores["toxicity_safety"] = max(0.0, 100.0 - float(chapter.get("toxicity_score", 0.0) or 0))
    scores["platform_semantic_fit"] = float(platform.get("score", 75.0) or 0)
    return {str(key): float(value) for key, value in scores.items() if isinstance(value, (int, float))}


def _chapter_gate_results(
    dimension_scores: dict[str, float],
    quality: dict[str, Any],
    style: dict[str, Any],
    originality: dict[str, Any],
    context: dict[str, Any],
    runtime_gate_evidence: dict[str, Any],
    platform_compliance: dict[str, Any],
    semantic_review: dict[str, Any],
) -> tuple[dict[str, bool], list[dict[str, Any]]]:
    quality_content = quality.get("content", {}) if isinstance(quality.get("content", {}), dict) else {}
    style_content = style.get("content", {}) if isinstance(style.get("content", {}), dict) else {}
    originality_content = originality.get("content", {}) if isinstance(originality.get("content", {}), dict) else {}
    gate_results: dict[str, bool] = {
        **(quality_content.get("gate_results", {}) if isinstance(quality_content.get("gate_results", {}), dict) else {}),
        "style_match_passed": float(style_content.get("style_match_score", 0) or 0) >= 70,
        "originality_passed": originality_content.get("risk_level") == "low",
        "production_context_ready": bool(context.get("preflight", {}).get("ready")),
        "rag_quality_gate_passed": bool(runtime_gate_evidence.get("rag_quality_gate_passed")),
        "stability_preflight_passed": bool(runtime_gate_evidence.get("stability_gate_passed")),
        "platform_compliance_passed": bool(platform_compliance.get("passed")),
        "semantic_review_passed": semantic_review.get("recommendation") != "block",
        "motivation_drift_passed": str((semantic_review.get("character_motivation_drift", {}) if isinstance(semantic_review.get("character_motivation_drift", {}), dict) else {}).get("status", "")) != "blocked",
        "power_scale_semantic_passed": str((semantic_review.get("power_scale_conflicts", {}) if isinstance(semantic_review.get("power_scale_conflicts", {}), dict) else {}).get("status", "")) != "blocked",
        "platform_semantic_fit_passed": bool((semantic_review.get("platform_adaptation_review", {}) if isinstance(semantic_review.get("platform_adaptation_review", {}), dict) else {}).get("passed", True)),
    }
    issues: list[dict[str, Any]] = []
    for name, score in dimension_scores.items():
        if score < 60:
            issues.append({"dimension": name, "severity": "high", "message": f"{name} score is below publish floor", "recommendation": "block publish until fixed"})
        elif score < 75:
            issues.append({"dimension": name, "severity": "medium", "message": f"{name} needs revision", "recommendation": "revise before publishing"})
    if style_content.get("copyright_style_risk") in {"medium", "high"}:
        issues.append({"dimension": "style_consistency", "severity": "medium", "message": "style drift or AI taste detected", "recommendation": "apply style revision"})
    if originality_content.get("risk_level") == "high":
        issues.append({"dimension": "originality_safety", "severity": "high", "message": "originality risk is high", "recommendation": "rewrite and rerun originality gate"})
    elif originality_content.get("risk_level") == "medium":
        issues.append({"dimension": "originality_safety", "severity": "medium", "message": "originality risk requires human gate", "recommendation": "revise or confirm safe abstraction"})
    for missing in context.get("preflight", {}).get("missing", []):
        issues.append({"dimension": "production_context", "severity": "high", "message": f"missing required profile: {missing}", "recommendation": "bind project profile before publishing"})
    for issue in runtime_gate_evidence.get("issues", []) if isinstance(runtime_gate_evidence.get("issues", []), list) else []:
        issues.append(issue)
    for issue in platform_compliance.get("issues", []) if isinstance(platform_compliance.get("issues", []), list) else []:
        issues.append(issue)
    for issue in semantic_review.get("issues", []) if isinstance(semantic_review.get("issues", []), list) else []:
        issues.append(issue)
    return gate_results, issues


def _publish_gates(audit: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    audit_content = audit.get("content", {}) if isinstance(audit.get("content", {}), dict) else {}
    chapter_recommendation = str(audit_content.get("recommendation", "block_publish"))
    linked = audit_content.get("linked_reports", {}) if isinstance(audit_content.get("linked_reports", {}), dict) else {}
    runtime = audit_content.get("runtime_gate_evidence", {}) if isinstance(audit_content.get("runtime_gate_evidence", {}), dict) else {}
    platform = audit_content.get("platform_compliance", {}) if isinstance(audit_content.get("platform_compliance", {}), dict) else {}
    semantic = audit_content.get("semantic_review", {}) if isinstance(audit_content.get("semantic_review", {}), dict) else {}
    gates = {
        "chapter_audit_passed": chapter_recommendation == "pass",
        "quality_report_present": bool(linked.get("quality_score_report_path")),
        "style_report_present": bool(linked.get("style_review_report_path")),
        "originality_report_present": bool(linked.get("originality_report_path")),
        "rag_quality_report_present": bool(linked.get("rag_quality_report_path")),
        "rag_quality_gate_passed": bool(runtime.get("rag_quality_gate_passed")),
        "stability_preflight_present": bool(linked.get("stability_preflight_path")),
        "stability_preflight_passed": bool(runtime.get("stability_gate_passed")),
        "platform_compliance_passed": bool(platform.get("passed")),
        "semantic_review_passed": semantic.get("recommendation") != "block",
        "platform_profile_bound": bool(context.get("profiles", {}).get("platform_profile")) if isinstance(context.get("profiles", {}), dict) else False,
        "genre_market_profile_bound": bool(context.get("profiles", {}).get("genre_market_profile")) if isinstance(context.get("profiles", {}), dict) else False,
        "creative_strategy_profile_bound": bool(context.get("profiles", {}).get("creative_strategy_profile")) if isinstance(context.get("profiles", {}), dict) else False,
        "quality_standard_profile_bound": bool(context.get("profiles", {}).get("quality_standard_profile")) if isinstance(context.get("profiles", {}), dict) else False,
        "style_profile_bound": bool(context.get("profiles", {}).get("style_profile")) if isinstance(context.get("profiles", {}), dict) else False,
        "continuity_bible_bound": bool(context.get("profiles", {}).get("continuity_bible")) if isinstance(context.get("profiles", {}), dict) else False,
    }
    blocking = list(audit_content.get("issues", []) if isinstance(audit_content.get("issues", []), list) else [])
    for key, passed in gates.items():
        if not passed:
            severity = "high" if key.endswith("_bound") or key in {"chapter_audit_passed", "semantic_review_passed"} else "medium"
            blocking.append({"dimension": key, "severity": severity, "message": f"publish gate failed: {key}", "recommendation": "complete required gate"})
    return {"gates": gates, "blocking_issues": blocking}


def _draft_runtime_gate_evidence(target: dict[str, Any]) -> dict[str, Any]:
    content = target.get("content", {}) if isinstance(target.get("content", {}), dict) else {}
    metadata = target.get("metadata", {}) if isinstance(target.get("metadata", {}), dict) else {}
    rag_gate = content.get("rag_quality_gate", {}) if isinstance(content.get("rag_quality_gate", {}), dict) else {}
    rag_report_path = str(metadata.get("rag_quality_report_path") or content.get("rag_quality_report_path") or rag_gate.get("report_path") or "")
    rag_recommendation = str(metadata.get("rag_quality_recommendation") or content.get("rag_quality_recommendation") or rag_gate.get("recommendation") or "")
    rag_score = 0.0
    budget = rag_gate.get("context_budget_score", {}) if isinstance(rag_gate.get("context_budget_score", {}), dict) else {}
    if isinstance(budget.get("score"), (int, float)):
        rag_score = float(budget.get("score"))
    stability_path = str(metadata.get("stability_preflight_path") or content.get("stability_preflight_path") or "")
    stability_recommendation = str(metadata.get("stability_preflight_recommendation") or content.get("stability_preflight", {}).get("recommendation", "") if isinstance(content.get("stability_preflight", {}), dict) else metadata.get("stability_preflight_recommendation") or "")
    stability_status = str(metadata.get("stability_preflight_gate_status") or content.get("stability_preflight", {}).get("gate_status", "") if isinstance(content.get("stability_preflight", {}), dict) else metadata.get("stability_preflight_gate_status") or "")
    issues: list[dict[str, Any]] = []
    rag_passed = bool(rag_report_path) and rag_recommendation not in {"", "block"}
    stability_passed = bool(stability_path) and stability_recommendation != "block" and stability_status != "blocked"
    if not rag_report_path:
        issues.append({"dimension": "rag_context_quality", "severity": "high", "message": "draft is missing RAG quality report", "recommendation": "rerun context builder before review/publish"})
    elif not rag_passed:
        issues.append({"dimension": "rag_context_quality", "severity": "high", "message": f"RAG quality gate is {rag_recommendation or 'unknown'}", "recommendation": "repair context assets before publishing"})
    if not stability_path:
        issues.append({"dimension": "long_form_stability", "severity": "high", "message": "draft is missing long-form stability preflight", "recommendation": "rerun chapter stability preflight"})
    elif not stability_passed:
        issues.append({"dimension": "long_form_stability", "severity": "high", "message": f"stability preflight is {stability_recommendation or stability_status}", "recommendation": "repair continuity before publishing"})
    return {
        "rag_quality_report_path": rag_report_path,
        "rag_quality_recommendation": rag_recommendation,
        "rag_quality_score": rag_score,
        "rag_quality_gate_passed": rag_passed,
        "stability_preflight_path": stability_path,
        "stability_preflight_recommendation": stability_recommendation,
        "stability_gate_status": stability_status,
        "stability_gate_passed": stability_passed,
        "issues": issues,
    }


def _platform_compliance(target: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    text = _asset_text(target)
    char_count = len(re.sub(r"\s+", "", text))
    profiles = context.get("profiles", {}) if isinstance(context.get("profiles", {}), dict) else {}
    platform = profiles.get("platform_profile", {}) if isinstance(profiles.get("platform_profile", {}), dict) else {}
    content = platform.get("content", {}) if isinstance(platform.get("content", {}), dict) else {}
    length = content.get("chapter_length_range") if isinstance(content.get("chapter_length_range"), dict) else content.get("chapter_length", {}) if isinstance(content.get("chapter_length", {}), dict) else {}
    min_len = int(length.get("min", 0) or 0) if isinstance(length, dict) else 0
    max_len = int(length.get("max", 0) or 0) if isinstance(length, dict) else 0
    issues: list[dict[str, Any]] = []
    if min_len and char_count < min_len:
        issues.append(
            {
                "dimension": "platform_compliance",
                "severity": "medium",
                "message": f"chapter length {char_count} is below platform minimum {min_len}",
                "recommendation": "expand the chapter or mark this draft as internal-only before publishing",
            }
        )
    if max_len and char_count > max_len:
        issues.append(
            {
                "dimension": "platform_compliance",
                "severity": "medium",
                "message": f"chapter length {char_count} exceeds platform maximum {max_len}",
                "recommendation": "split or tighten the chapter before publishing",
            }
        )
    review_risks = content.get("review_risks", []) if isinstance(content.get("review_risks", []), list) else []
    lowered = text.lower()
    for risk in review_risks:
        risk_text = str(risk).strip().lower()
        if risk_text and risk_text in lowered:
            issues.append({"dimension": "platform_compliance", "severity": "medium", "message": f"platform review risk appears in draft: {risk}", "recommendation": "revise platform-sensitive wording"})
    score = 100.0
    if issues:
        score = max(55.0, 100.0 - 18.0 * len(issues))
    return {
        "passed": not any(issue.get("severity") == "high" for issue in issues),
        "score": score,
        "char_count": char_count,
        "chapter_length_range": length,
        "issues": issues,
    }


def _asset_by_reference(storage: LocalStorage, reference: str) -> dict[str, Any] | None:
    if not reference:
        return None
    candidate = resolve_path(storage.root, reference)
    if candidate.exists() and candidate.is_file():
        data = read_json_for_scan(storage, candidate, context="audit asset reference direct lookup")
        if isinstance(data, dict):
            return data
    for category in DATA_DIRS:
        for path in reversed(storage.list_json(category)):
            data = read_json_for_scan(storage, path, context="audit asset reference scan")
            if not data:
                continue
            if not isinstance(data, dict):
                continue
            if reference in {str(data.get("id", "")), _display_path(storage.root, path), str(path)}:
                return data
    return None


def _read_asset_dict(storage: LocalStorage, path: str | Path) -> dict[str, Any]:
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"asset JSON must be an object: {path}")
    return data


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception as exc:
        require_recoverable_asset_scan_error(exc, context=f"audit JSON scan: {path}")
        return {}
    return data if isinstance(data, dict) else {}


def _asset_text(asset: Any) -> str:
    data = asset.to_dict() if hasattr(asset, "to_dict") else asset
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
    for key in ["text", "summary", "logline"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if isinstance(content, dict):
        return " ".join(str(value) for value in content.values() if isinstance(value, str))
    return str(data.get("title", "") if isinstance(data, dict) else "")


def _plot_signature(data: dict[str, Any]) -> set[str]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    fields = [
        content.get("objective"),
        content.get("beats"),
        content.get("hook"),
        content.get("conflict"),
        content.get("information_points"),
        content.get("acts"),
        content.get("structure_map"),
        content.get("plot_points"),
        content.get("chapter_trends"),
    ]
    return _semantic_terms(json.dumps(fields, ensure_ascii=False, sort_keys=True))


def _role_signature(data: dict[str, Any]) -> set[str]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    fields = [
        content.get("name"),
        content.get("role"),
        content.get("external_goal"),
        content.get("internal_need"),
        content.get("desire"),
        content.get("motivation_chain"),
        content.get("relationships"),
        content.get("character_map"),
        content.get("characters"),
    ]
    return _semantic_terms(json.dumps(fields, ensure_ascii=False, sort_keys=True))


def _semantic_terms(text: str) -> set[str]:
    tokens = set()
    for token in re.split(r"[\s,，。；;:：\"'{}\[\]()/\\|]+", str(text).lower()):
        cleaned = token.strip()
        if len(cleaned) >= 2 and cleaned not in {"none", "null", "true", "false"}:
            tokens.add(cleaned[:40])
    compact = re.sub(r"\s+", "", str(text).lower())
    if len(compact) >= 8:
        for index in range(0, max(len(compact) - 8, 0), 4):
            tokens.add(compact[index : index + 8])
            if len(tokens) >= 160:
                break
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return round(len(left & right) / max(len(left | right), 1), 4)


def _ngrams(text: str, size: int = 18) -> set[str]:
    compact = re.sub(r"\s+", "", text.lower())
    if len(compact) <= size:
        return {compact} if compact else set()
    return {compact[index : index + size] for index in range(0, len(compact) - size + 1)}


def _risk_score(risk: str) -> float:
    return {"low": 95.0, "medium": 70.0, "high": 40.0}.get(risk, 60.0)


def _max_risk(risks: list[str]) -> str:
    rank = {"low": 0, "unknown": 1, "medium": 2, "high": 3}
    return max(risks or ["unknown"], key=lambda item: rank.get(item, 1))


def _profile_risk(context: dict[str, Any], asset_type: str) -> str:
    profiles = context.get("profiles", {}) if isinstance(context.get("profiles", {}), dict) else {}
    profile = profiles.get(asset_type)
    if not isinstance(profile, dict):
        return "unknown"
    metadata = profile.get("metadata", {}) if isinstance(profile.get("metadata", {}), dict) else {}
    content = profile.get("content", {}) if isinstance(profile.get("content", {}), dict) else {}
    source_boundary = content.get("source_boundary", {}) if isinstance(content.get("source_boundary", {}), dict) else {}
    return str(source_boundary.get("copyright_risk") or metadata.get("risk_level") or "unknown")


def _asset_id(data: dict[str, Any]) -> str:
    return str(data.get("id", ""))


def _title_candidates(title: str, context: dict[str, Any]) -> list[str]:
    project_title = str(context.get("project", {}).get("title", "") if isinstance(context.get("project", {}), dict) else "")
    base = title or project_title or "Untitled Chapter"
    return _dedupe([base, f"{base} - publish draft", f"{project_title} {base}".strip()])


def _summary(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:220] if compact else "No draft text available."


def _release_tags(context: dict[str, Any], target: Any) -> list[str]:
    tags = ["release"]
    data = target.to_dict() if hasattr(target, "to_dict") else target
    if isinstance(data, dict):
        tags.extend(str(item) for item in data.get("tags", []) if str(item).strip())
    config = context.get("project_config", {}) if isinstance(context.get("project_config", {}), dict) else {}
    for key in ["genre", "target_platform"]:
        if config.get(key):
            tags.append(str(config[key]))
    return _dedupe(tags)


def _publishing_metadata_optimization(title: str, text: str, context: dict[str, Any]) -> dict[str, Any]:
    config = context.get("project_config", {}) if isinstance(context.get("project_config", {}), dict) else {}
    genre = str(config.get("genre") or "")
    target_platform = str(config.get("target_platform") or "")
    hook = _summary(text)[:80]
    base = title or str(context.get("project", {}).get("title", "Untitled") if isinstance(context.get("project", {}), dict) else "Untitled")
    title_candidates = _dedupe(
        [
            base,
            f"{base}: {hook[:18]}",
            f"{genre}新章 - {base}".strip(" -"),
        ]
    )
    synopsis = _summary(text)
    return {
        "title_candidates": title_candidates[:5],
        "synopsis_candidates": [synopsis, f"{synopsis} 下一章将兑现当前悬念。"],
        "tag_candidates": _dedupe([genre, target_platform, "原创", "连载", "章节钩子"])[:12],
        "hook_check": {"opening_signal": hook, "status": "needs_manual_review" if len(hook) < 12 else "ready"},
        "platform_notes": [
            "标题和简介只做本地建议，不自动提交外部平台。",
            "平台审核反馈需通过 publishing_log 或 adapter payload 回填。",
        ],
    }


def _cover_asset_requirements(context: dict[str, Any], channel: str) -> dict[str, Any]:
    profiles = context.get("profiles", {}) if isinstance(context.get("profiles", {}), dict) else {}
    platform = profiles.get("platform_profile", {}) if isinstance(profiles.get("platform_profile", {}), dict) else {}
    content = platform.get("content", {}) if isinstance(platform.get("content", {}), dict) else {}
    return {
        "required": bool(content.get("cover_required", channel not in {"local", "manual"})),
        "status": "missing",
        "asset_path": "",
        "requirements": content.get("cover_requirements", {"safe_text": True, "no_infringing_source_art": True}),
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedupe_assets(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        asset_id = str(value.get("id", ""))
        if asset_id and asset_id not in seen:
            seen.add(asset_id)
            result.append(value)
    return result


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
