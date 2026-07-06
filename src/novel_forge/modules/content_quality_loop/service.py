from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import ASSET_DIR_BY_TYPE
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.canon_graph import run_canon_graph_plugin
from novel_forge.modules.common import resolve_path
from novel_forge.modules.genre_os import run_genre_risk_gate
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment
from novel_forge.modules.production_context import project_scope_from_asset
from novel_forge.modules.quality_eval import build_quality_rubric_pack, run_provider_quality_judge, run_quality_gate, run_quality_suite
from novel_forge.modules.style_os import run_style_drift_gate
from novel_forge.schemas import ContentQualityLoopReport, validate_common_fields
from novel_forge.storage.local import LocalStorage

GENRE_PLUGIN_BY_ID = {
    "xuanhuan": "fantasy_power_scale_engine",
    "fantasy": "fantasy_power_scale_engine",
    "mystery": "mystery_evidence_chain_engine",
    "romance": "romance_relationship_state_engine",
    "historical": "historical_faction_network_engine",
    "sci_fi": "sci_fi_rule_consistency_engine",
    "horror": "horror_rule_contamination_engine",
}


def run_content_quality_loop(
    storage: LocalStorage,
    *,
    target_path: str | Path,
    stage: str = "draft",
    suite_type: str = "opening_3",
    genre_strategy_pack_path: str | Path | None = None,
    style_profile_path: str | Path | None = None,
    rubric_path: str | Path | None = None,
    platform_id: str = "local",
    canon_plugin: str = "",
    provider_adapter: Any | None = None,
    provider_runtime_guard: dict[str, Any] | None = None,
    allow_mock_fixture: bool = False,
    require_provider_judge: bool | None = None,
    require_external_provider_proof: bool = False,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    persist_issues: bool = True,
    attach_to_target: bool = True,
) -> dict[str, Any]:
    target_file = resolve_path(storage.root, target_path)
    target = storage.read_asset(target_file)
    project = project_scope_from_asset(storage, target, input_path=target_file)
    project_id = str(project.get("project_id") or "")
    workspace_path = str(project.get("workspace_path") or "")
    production = is_production_environment(environment or (envelope or {}).get("environment"))
    provider_required = production if require_provider_judge is None else bool(require_provider_judge)
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="run-content-quality-loop",
        project_id=project_id,
        task_type="content_quality_loop",
        asset_type="content_quality_loop_report",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    genre_path = str(genre_strategy_pack_path or _latest_asset_path(storage, "genre_strategy_pack", project_id=project_id))
    style_path = str(style_profile_path or _latest_asset_path(storage, "style_profile", project_id=project_id))
    steps: list[dict[str, Any]] = []
    evidence_paths: list[str] = []
    review_issue_paths: list[str] = []
    revision_task_paths: list[str] = []
    genre_id = ""

    if genre_path:
        genre_asset = storage.read_json(resolve_path(storage.root, genre_path))
        genre_content = genre_asset.get("content", {}) if isinstance(genre_asset.get("content", {}), dict) else {}
        genre_id = str(genre_content.get("genre_id") or "")
        result = _record_step(
            "genre_risk_gate",
            run_genre_risk_gate(
                storage,
                strategy_pack_path=genre_path,
                target_path=_display_path(storage.root, target_file),
                evidence={
                    "stage": stage,
                    "auto_quality_loop": True,
                    "longform_risk_controls": genre_content.get("longform_risks", []),
                },
                environment=str(env.get("environment") or environment or ""),
                envelope=env,
                persist_issues=persist_issues,
            ),
        )
        steps.append(result)
        evidence_paths.extend(result["paths"])
        review_issue_paths.extend(result["review_issue_paths"])
    else:
        steps.append(_missing_step("genre_risk_gate", required=production, message="genre_strategy_pack is missing"))

    if style_path:
        result = _record_step(
            "style_drift_gate",
            run_style_drift_gate(
                storage,
                style_profile_path=style_path,
                target_path=_display_path(storage.root, target_file),
                environment=str(env.get("environment") or environment or ""),
                envelope=env,
                persist_issues=persist_issues,
            ),
        )
        steps.append(result)
        evidence_paths.extend(result["paths"])
        review_issue_paths.extend(result["review_issue_paths"])
        if result.get("revision_task_path"):
            revision_task_paths.append(str(result["revision_task_path"]))
    else:
        steps.append(_missing_step("style_drift_gate", required=production, message="style_profile is missing"))

    plugin = canon_plugin or GENRE_PLUGIN_BY_ID.get(genre_id, "mystery_evidence_chain_engine")
    result = _record_step(
        "canon_graph_plugin_gate",
        run_canon_graph_plugin(
            storage,
            {
                "plugin": plugin,
                "target_path": _display_path(storage.root, target_file),
                "project_id": project_id,
                "workspace_path": workspace_path,
                "persist_issues": persist_issues,
            },
        ),
    )
    steps.append(result)
    evidence_paths.extend(result["paths"])
    review_issue_paths.extend(result["review_issue_paths"])

    resolved_rubric_path = str(rubric_path or "")
    if not resolved_rubric_path:
        rubric = build_quality_rubric_pack(
            storage,
            genre_id=genre_id or "general",
            platform_id=platform_id,
            style_profile_path=style_path,
            scope="chapter" if stage in {"draft", "revision", "revised_draft"} else stage,
            environment=str(env.get("environment") or environment or ""),
            envelope=env,
        )
        resolved_rubric_path = str(rubric["path"])
        steps.append(_record_step("quality_rubric_pack", rubric))
        evidence_paths.append(resolved_rubric_path)

    suite = run_quality_suite(
        storage,
        suite_type=suite_type,
        target_paths=[_display_path(storage.root, target_file)],
        rubric_path=resolved_rubric_path,
        genre_strategy_pack_path=genre_path,
        style_profile_path=style_path,
        platform_id=platform_id,
        environment=str(env.get("environment") or environment or ""),
        envelope=env,
        persist_issues=persist_issues,
    )
    suite_step = _record_step("quality_suite", suite)
    steps.append(suite_step)
    evidence_paths.extend(suite_step["paths"])
    review_issue_paths.extend(suite_step["review_issue_paths"])
    if suite.get("revision_task_path"):
        revision_task_paths.append(str(suite["revision_task_path"]))

    quality_report_path = str(suite["path"])
    if provider_adapter is not None:
        provider = run_provider_quality_judge(
            storage,
            suite_type=suite_type,
            target_paths=[_display_path(storage.root, target_file)],
            rubric_path=resolved_rubric_path,
            adapter=provider_adapter,
            genre_strategy_pack_path=genre_path,
            style_profile_path=style_path,
            platform_id=platform_id,
            environment=str(env.get("environment") or environment or ""),
            envelope=env,
            provider_runtime_guard=provider_runtime_guard,
            allow_mock_fixture=allow_mock_fixture,
            require_external_provider_proof=require_external_provider_proof,
            persist_issues=persist_issues,
        )
        provider_step = _record_step("provider_quality_judge", provider)
        steps.append(provider_step)
        evidence_paths.extend(provider_step["paths"])
        review_issue_paths.extend(provider_step["review_issue_paths"])
        if provider.get("revision_task_path"):
            revision_task_paths.append(str(provider["revision_task_path"]))
        quality_report_path = str(provider["path"])
    elif provider_required:
        steps.append(_missing_step("provider_quality_judge", required=True, message="provider quality judge adapter is required"))
    else:
        steps.append({"name": "provider_quality_judge", "status": "skipped", "blocking": False, "message": "provider judge not required for this environment", "paths": [], "review_issue_paths": []})

    gate = run_quality_gate(
        storage,
        quality_report_path=quality_report_path,
        environment=str(env.get("environment") or environment or ""),
        envelope=env,
    )
    gate_step = _record_step("quality_gate", gate)
    steps.append(gate_step)
    evidence_paths.extend(gate_step["paths"])

    blocking_issues = _blocking_issues(steps)
    status = "blocked" if blocking_issues else "passed"
    if status == "passed" and any(step["status"] == "skipped" for step in steps):
        status = "passed_with_warnings"
    report = ContentQualityLoopReport(
        title=f"Content quality loop for {target.title or target.id}",
        source=target.id,
        tags=["content-quality-loop", stage, status],
        content={
            "loop_id": make_id("content_quality_loop_report", f"{target.id}-{stage}-{utc_now()}"),
            "target_asset_id": target.id,
            "target_asset_type": target.type,
            "target_asset_path": _display_path(storage.root, target_file),
            "stage": stage,
            "status": status,
            "blocking": bool(blocking_issues),
            "steps": steps,
            "evidence_paths": _dedupe(evidence_paths),
            "review_issue_paths": _dedupe(review_issue_paths),
            "revision_task_paths": _dedupe(revision_task_paths),
            "blocking_issues": blocking_issues,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, **envelope_asset_metadata(env)},
        references=_dedupe([_display_path(storage.root, target_file), *evidence_paths, *review_issue_paths, *revision_task_paths]),
    )
    path = _write_asset(storage, report)
    if attach_to_target:
        _attach_loop_to_target(storage, target_file, path, status=status, blocking=bool(blocking_issues))
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "status": status, "blocking": bool(blocking_issues), "envelope": env}


def _record_step(name: str, result: dict[str, Any]) -> dict[str, Any]:
    asset = result.get("asset", {}) if isinstance(result.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    status = _status_from_result(result, content)
    paths = _paths_from_result(result)
    review_paths = [str(item) for item in result.get("review_issues", []) if str(item).strip()] if isinstance(result.get("review_issues", []), list) else []
    primary_path = str(result.get("path") or (paths[0] if paths else ""))
    return {
        "name": name,
        "status": status,
        "blocking": status in {"blocked", "missing", "failed"} or bool(content.get("blocking")),
        "path": primary_path,
        "paths": paths,
        "review_issue_paths": review_paths,
        "revision_task_path": str(result.get("revision_task_path") or content.get("revision_task_path") or ""),
        "summary": _step_summary(content),
    }


def _status_from_result(result: dict[str, Any], content: dict[str, Any]) -> str:
    if result.get("status"):
        value = str(result.get("status"))
    else:
        value = str(content.get("status") or content.get("recommendation") or "")
    if value in {"ready", "passed", "pass", "accepted", "succeeded"}:
        return "passed"
    if value in {"blocked", "block", "failed"}:
        return "blocked"
    if value in {"needs_revision", "warning", "warn"}:
        return "needs_revision"
    if content.get("blocking") or int(content.get("blocking_issue_count", 0) or 0) > 0:
        return "blocked"
    return value or "passed"


def _paths_from_result(result: dict[str, Any]) -> list[str]:
    keys = ["path", "run_path", "acceptance_report_path", "style_rewrite_task_path", "revision_task_path"]
    values = [str(result.get(key) or "") for key in keys]
    for key in ["model_judge_result_paths", "review_issues"]:
        if isinstance(result.get(key), list):
            values.extend(str(item) for item in result[key])
    external = result.get("external_provider_proof", {}) if isinstance(result.get("external_provider_proof", {}), dict) else {}
    values.append(str(external.get("path") or ""))
    return _dedupe(values)


def _missing_step(name: str, *, required: bool, message: str) -> dict[str, Any]:
    return {"name": name, "status": "missing" if required else "skipped", "blocking": bool(required), "message": message, "paths": [], "review_issue_paths": [], "summary": {}}


def _blocking_issues(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    for step in steps:
        if step.get("blocking"):
            issues.append(
                {
                    "dimension": f"content_quality_loop.{step.get('name')}",
                    "severity": "critical" if step.get("name") in {"provider_quality_judge", "quality_gate"} else "high",
                    "message": str(step.get("message") or f"{step.get('name')} status is {step.get('status')}"),
                    "status": str(step.get("status") or ""),
                    "path": str(step.get("path") or ""),
                }
            )
    return issues


def _latest_asset_path(storage: LocalStorage, asset_type: str, *, project_id: str) -> str:
    category = ASSET_DIR_BY_TYPE.get(asset_type)
    if not category:
        return ""
    rows: list[tuple[str, str]] = []
    for path in storage.list_json(category):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or content.get("project_id") or "") not in {project_id, ""}:
            continue
        rows.append((str(data.get("updated_at") or data.get("created_at") or ""), _display_path(storage.root, path)))
    return sorted(rows)[-1][1] if rows else ""


def _step_summary(content: dict[str, Any]) -> dict[str, Any]:
    keys = ["recommendation", "status", "blocking", "blocking_issue_count", "overall_score", "drift_level", "state_machine_status"]
    return {key: content.get(key) for key in keys if key in content}


def _attach_loop_to_target(storage: LocalStorage, target_file: Path, report_path: str, *, status: str, blocking: bool) -> None:
    data = storage.read_json(target_file)
    if not isinstance(data, dict):
        return
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata["content_quality_loop_path"] = report_path
    metadata["content_quality_loop_status"] = status
    metadata["content_quality_loop_blocking"] = blocking
    content["content_quality_loop"] = {"path": report_path, "status": status, "blocking": blocking}
    data["metadata"] = metadata
    data["content"] = content
    storage.write_json(target_file, data)


def _write_asset(storage: LocalStorage, asset: Any) -> str:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return _display_path(storage.root, storage.write_asset_auto(asset))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _display_path(root: Path, path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return str(resolved.relative_to(root)) if resolved.is_relative_to(root) else str(resolved)
