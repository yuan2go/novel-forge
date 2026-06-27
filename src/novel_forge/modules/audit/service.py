from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import build_production_context, filter_project_safe_references
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
    source_assets = _candidate_source_assets(storage, target.to_dict(), context)
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
            "forbidden_element_hits": forbidden_hits,
            "plot_skeleton_risk": risk_scores["plot_skeleton_risk"],
            "character_setup_risk": risk_scores["character_setup_risk"],
            "style_expression_risk": risk_scores["style_expression_risk"],
            "source_license_risk": risk_scores["source_license_risk"],
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
    dimension_scores = _chapter_dimension_scores(quality, style, originality, context, runtime_gate_evidence, platform_compliance)
    gate_results, issues = _chapter_gate_results(dimension_scores, quality, style, originality, context, runtime_gate_evidence, platform_compliance)
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
) -> Path:
    path = resolve_path(storage.root, draft_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    audit_path = resolve_path(storage.root, chapter_audit_path) if chapter_audit_path else create_chapter_audit_report(storage, path, workspace_path=workspace_path)
    audit = _read_asset_dict(storage, audit_path)
    gate_data = _publish_gates(audit, context)
    blocking = gate_data["blocking_issues"]
    decision = "ready"
    if any(issue.get("severity") == "high" for issue in blocking):
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
            "required_reports": {
                "chapter_audit_report_path": _display_path(storage.root, Path(audit_path)),
                **(audit.get("content", {}).get("linked_reports", {}) if isinstance(audit.get("content", {}), dict) else {}),
            },
            "human_override": bool(human_override),
            "preflight": context.get("preflight", {}),
        },
        metadata={
            "workflow": "publish-gate",
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "created_at": utc_now(),
            "risk_level": "high" if decision == "blocked" else ("medium" if decision == "needs_revision" else "low"),
        },
        references=filter_project_safe_references(
            storage,
            str(project.get("project_id", "")),
            _dedupe([target.id, _asset_id(audit), *context.get("profile_references", [])]),
        ),
    )
    with AgentExecutionContext(
        storage,
        agent_key="publishing",
        operation="create-publish-gate-report",
        input_assets=[path, audit_path],
        output_types=["publish_gate_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_publish_gate_report", "publish_gate_report")
        output = storage.write_asset("publishing", asset)
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
) -> Path:
    path = resolve_path(storage.root, draft_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    gate_path = resolve_path(storage.root, publish_gate_path) if publish_gate_path else create_publish_gate_report(
        storage,
        path,
        workspace_path=workspace_path,
        human_override=human_override,
    )
    gate = _read_asset_dict(storage, gate_path)
    decision = gate.get("content", {}).get("decision", "blocked") if isinstance(gate.get("content", {}), dict) else "blocked"
    status = "ready" if decision == "ready" else "blocked"
    text = _asset_text(target)
    asset = ReleasePackage(
        title=f"Release package for {target.title}",
        source=target.id,
        tags=["release-package", str(channel or "local")],
        content={
            "target_asset_id": target.id,
            "publish_gate_report_id": _asset_id(gate),
            "title_candidates": _title_candidates(target.title, context),
            "summary": _summary(text),
            "tags": _release_tags(context, target),
            "channel": channel or "local",
            "status": status,
            "draft_path": _display_path(storage.root, path),
            "publish_gate_report_path": _display_path(storage.root, Path(gate_path)),
        },
        metadata={
            "workflow": "release-package",
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "created_at": utc_now(),
            "risk_level": "low" if status == "ready" else "high",
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
    return {str(key): float(value) for key, value in scores.items() if isinstance(value, (int, float))}


def _chapter_gate_results(
    dimension_scores: dict[str, float],
    quality: dict[str, Any],
    style: dict[str, Any],
    originality: dict[str, Any],
    context: dict[str, Any],
    runtime_gate_evidence: dict[str, Any],
    platform_compliance: dict[str, Any],
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
    return gate_results, issues


def _publish_gates(audit: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    audit_content = audit.get("content", {}) if isinstance(audit.get("content", {}), dict) else {}
    chapter_recommendation = str(audit_content.get("recommendation", "block_publish"))
    linked = audit_content.get("linked_reports", {}) if isinstance(audit_content.get("linked_reports", {}), dict) else {}
    runtime = audit_content.get("runtime_gate_evidence", {}) if isinstance(audit_content.get("runtime_gate_evidence", {}), dict) else {}
    platform = audit_content.get("platform_compliance", {}) if isinstance(audit_content.get("platform_compliance", {}), dict) else {}
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
            severity = "high" if key.endswith("_bound") or key == "chapter_audit_passed" else "medium"
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
        try:
            data = storage.read_json(candidate)
        except Exception:
            data = None
        if isinstance(data, dict):
            return data
    for category in DATA_DIRS:
        for path in reversed(storage.list_json(category)):
            try:
                data = storage.read_json(path)
            except Exception:
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
