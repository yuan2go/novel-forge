from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.exception_policy import require_recoverable_asset_scan_error
from novel_forge.core.ids import utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.context_builder import build_flow_context_bundle, knowledge_context_contract_from_result, knowledge_context_contract_metadata
from novel_forge.modules.content_intelligence_governance import platform_upload_checklist_for_release, release_content_intelligence_gate
from novel_forge.modules.longform_stability import create_revision_task_from_gate, evaluate_longform_stability_gate
from novel_forge.modules.mkaos import list_risk_knowledge
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment, normalize_runtime_request_policy
from novel_forge.modules.production_context import build_production_context, filter_project_safe_references
from novel_forge.modules.production_governance import build_production_governance_report
from novel_forge.modules.review_issue import blocking_review_issues, review_issues_to_gate_issues
from novel_forge.modules.runtime_policy import provider_hard_stop_evidence_report
from novel_forge.schemas import PublishGateReport
from novel_forge.storage.local import LocalStorage


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
    from novel_forge.modules.audit import create_chapter_audit_report

    path = resolve_path(storage.root, draft_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    runtime_request = normalize_runtime_request_policy(
        envelope_payload=envelope,
        environment=environment,
        source_policy=publish_source_policy(source_policy),
        operation="publishing.publish_gate",
    )
    environment = str(runtime_request["environment"])
    envelope = runtime_request["envelope"] if runtime_request.get("envelope") else None
    resolved_source_policy = publish_source_policy(runtime_request["source_policy"])
    assert_publish_envelope_before_side_effect(
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
        source="publishing.create_publish_gate_report",
        context_bundle_id=context_bundle_id,
        source_policy=resolved_source_policy,
        environment=environment,
        bypass_reason="publish gate local compatibility path",
        require_for_production=True,
    )
    audit_path = resolve_path(storage.root, chapter_audit_path) if chapter_audit_path else create_chapter_audit_report(storage, path, workspace_path=workspace_path)
    audit = read_asset_dict(storage, audit_path)
    gate_data = publish_gate_data(audit, context)
    mkaos_risk = mkaos_risk_summary(storage, str(project.get("project_id", "")))
    gate_data["gates"]["mkaos_risk_clear"] = not mkaos_risk["blocking"]
    gate_data["blocking_issues"].extend(mkaos_risk["blocking_issues"])
    longform_gate = evaluate_longform_stability_gate(storage, path, workspace_path=workspace_path)
    gate_data["gates"]["longform_stability_passed"] = bool(longform_gate.get("passed"))
    for key, value in longform_gate.get("gates", {}).items():
        gate_data["gates"][f"longform_{key}"] = bool(value)
    gate_data["blocking_issues"].extend(longform_gate.get("blocking_issues", []))
    related_asset_ids = related_review_issue_asset_ids(target.to_dict())
    review_issue_rows = blocking_review_issues(storage, target_asset_id=target.id, project_id=str(project.get("project_id", "")) or None, related_asset_ids=related_asset_ids)
    gate_data["blocking_issues"].extend(review_issues_to_gate_issues(review_issue_rows))
    gate_data["gates"]["review_issue_blocking_clear"] = not review_issue_rows
    production_policy = is_production_environment(environment)
    evaluation_gate = evaluation_gate_summary(storage, target.to_dict(), display_path(storage.root, path), project_id=str(project.get("project_id", "")), required=production_policy)
    gate_data["gates"]["evaluation_gate_passed"] = not evaluation_gate["blocking"]
    gate_data["blocking_issues"].extend(evaluation_gate["blocking_issues"])
    provider_runtime_gate = provider_runtime_gate_summary(storage, project_id=str(project.get("project_id", "")), workspace_path=str(project.get("workspace_path", "")), required=production_policy)
    gate_data["gates"]["provider_runtime_gate_passed"] = not provider_runtime_gate["blocking"]
    gate_data["blocking_issues"].extend(provider_runtime_gate["blocking_issues"])
    platform_strategy_gate = platform_strategy_gate_summary(storage, context, project_id=str(project.get("project_id", "")), required=production_policy)
    gate_data["gates"]["platform_strategy_gate_passed"] = not platform_strategy_gate["blocking"]
    gate_data["blocking_issues"].extend(platform_strategy_gate["blocking_issues"])
    target_content = target.content if isinstance(target.content, dict) else {}
    project_config = context.get("project_config", {}) if isinstance(context.get("project_config", {}), dict) else {}
    upload_checklist = platform_upload_checklist_for_release(
        title=target.title,
        summary=str(target_content.get("summary") or target_content.get("synopsis") or ""),
        text=str(target_content.get("text") or target_content.get("body") or ""),
        channel=str(project.get("target_platform") or project_config.get("target_platform") or "manual"),
        cover={"required": False},
    )
    content_intelligence_gate = release_content_intelligence_gate(
        storage,
        target_asset_id=target.id,
        target_asset_path=path,
        project_id=str(project.get("project_id", "")),
        workspace_path=str(project.get("workspace_path", "")),
        platform_upload_checklist=upload_checklist,
        required=production_policy,
    )
    gate_data["gates"]["content_intelligence_gate_passed"] = not content_intelligence_gate["blocking"]
    gate_data["blocking_issues"].extend(content_intelligence_gate["blocking_issues"])
    blocking = gate_data["blocking_issues"]
    decision = "ready"
    if any(issue.get("severity") in {"high", "critical"} for issue in blocking):
        decision = "blocked"
    elif blocking:
        decision = "needs_revision"
    if human_override and decision != "blocked":
        decision = "ready"
    production_governance = build_production_governance_report(
        storage,
        operation="publishing.publish_gate",
        environment=environment,
        target_asset_id=target.id,
        target_asset_path=path,
        project_id=str(project.get("project_id", "")),
        workspace_path=str(project.get("workspace_path", "")),
        gate_statuses={
            "os_envelope": {"status": "passed", "path": os_envelope.get("trace_span_path", ""), "blocking": False},
            "context_bundle": {"status": "passed" if publish_context.get("path") else "missing", "path": str(publish_context.get("path", "")), "blocking": not bool(publish_context.get("path"))},
            "source_isolation": {"status": "passed", "blocking": False, "path": str(publish_context.get("path", ""))},
            "mkaos_risk": {"status": "blocked" if mkaos_risk.get("blocking") else "passed", "blocking": bool(mkaos_risk.get("blocking")), "path": ""},
            "review_issue": {"status": "passed" if gate_data["gates"].get("review_issue_blocking_clear") else "blocked", "blocking": not bool(gate_data["gates"].get("review_issue_blocking_clear")), "path": ""},
            "longform_stability": {"status": "passed" if longform_gate.get("passed") else "blocked", "blocking": not bool(longform_gate.get("passed")), "path": ""},
            "evaluation_gate": evaluation_gate,
            "provider_runtime_gate": provider_runtime_gate,
            "platform_strategy_gate": platform_strategy_gate,
            "content_intelligence_gate": {
                "status": content_intelligence_gate["status"],
                "blocking": content_intelligence_gate["blocking"],
                "path": "",
            },
        },
        source_policy=resolved_source_policy,
        evidence_refs=[
            display_path(storage.root, Path(audit_path)),
            str(publish_context.get("path", "")),
            str(evaluation_gate.get("path", "")),
            str(platform_strategy_gate.get("platform_strategy_pack_path", "")),
            *[str(item) for item in content_intelligence_gate.get("evidence_refs", [])],
        ],
        rollback_plan={
            "rollback_action": "do_not_create_release_package",
            "rollback_ref": display_path(storage.root, path),
            "requires_operator_review": True,
        },
        trace={"trace_id": os_envelope.get("trace_id", ""), "span_id": os_envelope.get("trace_id", "")},
    )
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
                "chapter_audit_report_path": display_path(storage.root, Path(audit_path)),
                "longform_stability_reports": longform_gate.get("required_reports", {}),
                **(audit.get("content", {}).get("linked_reports", {}) if isinstance(audit.get("content", {}), dict) else {}),
            },
            "human_override": bool(human_override),
            "preflight": context.get("preflight", {}),
            "longform_stability": longform_gate,
            "evaluation_gate": evaluation_gate,
            "provider_runtime_gate": provider_runtime_gate,
            "platform_strategy_gate": platform_strategy_gate,
            "content_intelligence_gate": content_intelligence_gate,
            "platform_upload_checklist": upload_checklist,
            "production_governance": {
                "status": production_governance["status"],
                "path": production_governance["path"],
                "gate_result_path": production_governance["gate_result_path"],
                "blocking": production_governance["blocking"],
            },
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
                dedupe([target.id, asset_id(audit), str(publish_context.get("path", "")), *content_intelligence_gate.get("evidence_refs", []), *context.get("profile_references", [])]),
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
        run.succeed(output_assets=[display_path(storage.root, output)])
        return output


def publish_source_policy(source_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = dict(source_policy or {})
    policy.update(
        {
            "raw_source_text_allowed": False,
            "source_chunk_raw_text_allowed": False,
            "runtime_assets_in_generation_rag_allowed": False,
            "generation_rag_allowed": True,
            "exclude_raw_sources": True,
        }
    )
    return policy


def assert_publish_envelope_before_side_effect(
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
        source="publishing.production_preflight",
        source_policy=source_policy,
        environment=str(runtime_request["environment"]),
        require_for_production=True,
        record_trace=False,
    )


def mkaos_risk_summary(storage: LocalStorage, project_id: str) -> dict[str, Any]:
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
        "risk_items": [{"id": row.get("id", ""), "path": row.get("path", ""), "title": row.get("title", ""), "risk_reasons": row.get("risk_reasons", [])} for row in rows[:20]],
    }


def evaluation_gate_summary(storage: LocalStorage, target: dict[str, Any], target_path: str, *, project_id: str, required: bool) -> dict[str, Any]:
    gate = latest_governance_asset(storage, "evaluation_gate", project_id=project_id, target_asset_id=str(target.get("id", "")), target_asset_path=target_path)
    if not gate:
        issues = []
        if required:
            issues.append({"dimension": "evaluation_gate", "severity": "high", "message": "production publish requires a passing EvaluationGate", "recommendation": "run /product/evaluation/evaluation-gate for the draft before publishing"})
        return {"status": "missing", "required": required, "blocking": bool(issues), "path": "", "blocking_issues": issues}
    content = gate.get("content", {}) if isinstance(gate.get("content", {}), dict) else {}
    status = str(content.get("status") or "unknown")
    blocking = bool(content.get("blocking")) or status == "blocked"
    issues = []
    if blocking:
        issues.append({"dimension": "evaluation_gate", "severity": "critical", "message": f"EvaluationGate blocked publish: score {content.get('overall_score', 'unknown')}", "recommendation": "resolve evaluation findings or rerun evaluation after revision", "evaluation_gate_path": gate.get("path", "")})
    return {"status": status, "required": required, "blocking": blocking, "path": gate.get("path", ""), "overall_score": content.get("overall_score", 0), "minimum_score": content.get("minimum_score", 0), "blocking_issues": issues}


def provider_runtime_gate_summary(storage: LocalStorage, *, project_id: str, workspace_path: str, required: bool) -> dict[str, Any]:
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


def platform_strategy_gate_summary(storage: LocalStorage, context: dict[str, Any], *, project_id: str, required: bool) -> dict[str, Any]:
    project = context.get("project", {}) if isinstance(context.get("project", {}), dict) else {}
    config = project.get("project_config", {}) if isinstance(project.get("project_config", {}), dict) else {}
    platform_id = str(config.get("target_platform") or "").strip()
    pack = latest_governance_asset(storage, "platform_strategy_pack", project_id=project_id)
    retention = latest_governance_asset(storage, "platform_retention_risk", project_id=project_id)
    retention_content = retention.get("content", {}) if isinstance(retention.get("content", {}), dict) else {}
    risk_level = str(retention_content.get("risk_level") or "unknown").lower()
    issues = []
    if required and not pack:
        issues.append({"dimension": "platform_strategy_gate", "severity": "high", "message": "production publish requires a PlatformStrategyPack", "recommendation": "build platform strategy pack before publish gate"})
    if risk_level in {"high", "critical"}:
        issues.append({"dimension": "platform_retention_risk", "severity": "critical" if risk_level == "critical" else "high", "message": f"platform retention risk is {risk_level}", "recommendation": "revise chapter strategy or resolve retention risk before release", "platform_retention_risk_path": retention.get("path", "")})
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


def latest_governance_asset(storage: LocalStorage, asset_type: str, *, project_id: str, target_asset_id: str = "", target_asset_path: str = "") -> dict[str, Any]:
    rows = []
    for category in ["runs", "platforms", "publishing"]:
        for path in storage.list_json(category):
            data = read_json_safe(storage, path)
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
            data["path"] = display_path(storage.root, path)
            rows.append(data)
    return sorted(rows, key=lambda row: str(row.get("updated_at") or row.get("created_at") or row.get("content", {}).get("created_at", "")))[-1] if rows else {}


def related_review_issue_asset_ids(asset: dict[str, Any]) -> list[str]:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return dedupe([str(asset.get("source") or ""), str(metadata.get("previous_draft_id") or ""), str(content.get("source_draft_id") or ""), str(content.get("target_draft_id") or "")])


def publish_gate_data(audit: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    content = audit.get("content", {}) if isinstance(audit.get("content", {}), dict) else {}
    gate_results = content.get("gate_results", {}) if isinstance(content.get("gate_results", {}), dict) else {}
    issues = content.get("issues", []) if isinstance(content.get("issues", []), list) else []
    blocking: list[dict[str, Any]] = []
    gates: dict[str, bool] = {}
    for key in ["quality_threshold", "style_fit", "originality", "platform_compliance", "semantic_integrity", "rag_runtime", "stability_preflight"]:
        result = gate_results.get(key, {}) if isinstance(gate_results.get(key, {}), dict) else {}
        passed = bool(result.get("passed", True))
        gates[key] = passed
        if not passed:
            severity = "high" if key in {"originality", "semantic_integrity", "rag_runtime", "stability_preflight"} else "medium"
            blocking.append({"dimension": key, "severity": severity, "message": f"publish gate failed: {key}", "recommendation": "complete required gate"})
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("severity", "")).lower() in {"high", "critical"}:
            blocking.append({"dimension": issue.get("dimension", "audit"), "severity": issue.get("severity", "high"), "message": issue.get("message", "audit issue"), "recommendation": issue.get("recommendation", "revise")})
    preflight = context.get("preflight", {}) if isinstance(context.get("preflight", {}), dict) else {}
    if preflight.get("ready") is False:
        for item in preflight.get("missing", []) if isinstance(preflight.get("missing", []), list) else []:
            blocking.append({"dimension": "production_context", "severity": "medium", "message": f"missing production context: {item}", "recommendation": "complete project context"})
    gates["chapter_audit_passed"] = not any(str(issue.get("severity")) in {"high", "critical"} for issue in blocking)
    return {"gates": gates, "blocking_issues": blocking}


def read_asset_dict(storage: LocalStorage, path: str | Path) -> dict[str, Any]:
    data = storage.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"asset JSON must be an object: {path}")
    return data


def read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except Exception as exc:
        require_recoverable_asset_scan_error(exc, context=f"publishing JSON scan: {path}")
        return {}
    return data if isinstance(data, dict) else {}


def asset_id(data: dict[str, Any]) -> str:
    return str(data.get("id", ""))


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
