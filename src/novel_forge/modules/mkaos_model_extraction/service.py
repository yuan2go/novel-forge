from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.mkaos_ingestion import create_creative_knowledge_card
from novel_forge.modules.mkaos_ingestion.source_type_extractors import (
    classical_text_extractor,
    mystery_extractor,
    professional_book_extractor,
    webnovel_extractor,
)
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

from .candidate_validator import validate_candidate_payload
from .confidence_scoring import score_extraction_candidate
from .extraction_prompt_registry import create_prompt_version, ensure_default_prompt_versions, list_prompt_versions
from .provider_output_sanitizer import sanitize_provider_output
from .provider_runner import run_provider


MODEL_EXTRACTION_TYPES = {
    "mkaos_model_extraction_job": "runs",
    "mkaos_model_extraction_candidate": "knowledge",
    "mkaos_model_extraction_review": "runs",
    "mkaos_extraction_provider_evidence": "runs",
    "mkaos_extraction_benchmark_case": "runs",
    "mkaos_extraction_benchmark_run": "runs",
    "mkaos_extraction_regression_report": "runs",
}


def create_model_extraction_job(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "local-system")
    source_type = str(payload.get("source_type") or "professional_book")
    content = {
        "job_id": "",
        "project_id": project_id,
        "source_type": source_type,
        "status": "pending",
        "provider_mode": str(payload.get("provider_mode") or "disabled"),
        "input_summary": str(payload.get("input_summary") or payload.get("summary") or payload.get("text") or "")[:1600],
        "source_refs": _strings(payload.get("source_refs") or payload.get("source_document_ids") or payload.get("source_chunk_ids")),
        "evidence_refs": _strings(payload.get("evidence_refs") or payload.get("source_chunk_ids") or payload.get("source_refs")),
        "runtime_policy": payload.get("runtime_policy") if isinstance(payload.get("runtime_policy"), dict) else {},
        "source_policy": _source_policy(),
        "source_isolation": _source_isolation(),
        "created_at": utc_now(),
    }
    job_id = make_id("mkaos_model_extraction_job", f"{project_id} {source_type} {content['created_at']}")
    content["job_id"] = job_id
    asset = _asset("mkaos_model_extraction_job", job_id, f"MKAOS model extraction {source_type}", "mkaos-model-extraction", content, _metadata(project_id, payload), references=content["evidence_refs"])
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path), "id": job_id}


def run_model_extraction_job(storage: LocalStorage, job_ref: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    path, job = _find(storage, job_ref, "mkaos_model_extraction_job")
    content = job.get("content", {}) if isinstance(job.get("content"), dict) else {}
    project_id = str(content.get("project_id") or payload.get("project_id") or "local-system")
    source_type = str(payload.get("source_type") or content.get("source_type") or "professional_book")
    run_payload = {**content, **payload, "project_id": project_id, "source_type": source_type}
    _update_job(storage, path, {"status": "running", "started_at": utc_now()})
    prompts = ensure_default_prompt_versions(storage, project_id=project_id)
    prompt = _active_prompt(prompts, source_type)
    deterministic = _deterministic_candidates(source_type, run_payload)
    provider = run_provider(run_payload, prompt.get("content", prompt))
    sanitizer = sanitize_provider_output(provider.get("output", {}))
    provider_evidence = _write_provider_evidence(storage, project_id, provider, sanitizer, run_payload)
    provider_runtime_gate = provider.get("provider_runtime_gate", {}) if isinstance(provider.get("provider_runtime_gate", {}), dict) else {}
    if _is_production(run_payload) and provider_runtime_gate.get("status") == "blocked":
        _update_job(
            storage,
            path,
            {
                "status": "blocked",
                "completed_at": utc_now(),
                "candidate_count": 0,
                "review_count": 0,
                "provider_evidence_path": provider_evidence.get("path", ""),
                "review_issue_count": 0,
            },
        )
        raise ValueError(f"MKAOS model extraction blocked production provider runtime gate: {provider_runtime_gate.get('reason', 'blocked')}")
    raw_candidates = _provider_candidates(sanitizer["sanitized"])
    if not raw_candidates:
        raw_candidates = deterministic
    candidates: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_candidates):
        seed = deterministic[index % len(deterministic)] if deterministic else {}
        normalized = _normalize_candidate({**seed, **(raw if isinstance(raw, dict) else {})}, run_payload)
        candidate_sanitizer = sanitize_provider_output(normalized)
        candidate_payload = candidate_sanitizer["sanitized"]
        validation = validate_candidate_payload(candidate_payload)
        score = score_extraction_candidate(candidate_payload, validation, candidate_sanitizer, deterministic)
        if candidate_sanitizer["forbidden_field_count"]:
            score["quality_dimensions"]["originality_safety_score"] = min(score["quality_dimensions"]["originality_safety_score"], 0.55)
        candidate = _write_candidate(storage, project_id, job, candidate_payload, validation, score, candidate_sanitizer, provider_evidence, run_payload)
        review = _write_review(storage, project_id, candidate["asset"], score, validation, candidate_sanitizer, run_payload)
        candidates.append(candidate)
        reviews.append(review)
        if candidate_sanitizer["forbidden_field_count"] or not validation["valid"]:
            issue = _persist_candidate_issue(storage, project_id, candidate["asset"], validation, candidate_sanitizer, production=_is_production(run_payload))
            if issue:
                issues.append(issue)
    status = "blocked" if issues and _is_production(run_payload) else "succeeded"
    _update_job(
        storage,
        path,
        {
            "status": status,
            "completed_at": utc_now(),
            "candidate_count": len(candidates),
            "review_count": len(reviews),
            "provider_evidence_path": provider_evidence.get("path", ""),
            "review_issue_count": len(issues),
        },
    )
    if _is_production(run_payload) and issues:
        raise ValueError("MKAOS model extraction blocked production due to sanitizer or schema issues")
    return {
        "job": storage.read_json(path),
        "candidates": candidates,
        "reviews": reviews,
        "provider_evidence": provider_evidence,
        "issues": issues,
        "candidate_count": len(candidates),
        "status": status,
        "source_isolation": _source_isolation(),
    }


def list_model_extraction_jobs(storage: LocalStorage, *, project_id: str | None = None, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = _list(storage, "mkaos_model_extraction_job", project_id=project_id, limit=limit)
    if status:
        rows = [row for row in rows if str(row.get("content", {}).get("status") or "") == status]
    return rows


def get_model_extraction_job(storage: LocalStorage, job_ref: str) -> dict[str, Any]:
    path, data = _find(storage, job_ref, "mkaos_model_extraction_job")
    return _row(storage, path, data)


def cancel_model_extraction_job(storage: LocalStorage, job_ref: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    path, _ = _find(storage, job_ref, "mkaos_model_extraction_job")
    _update_job(storage, path, {"status": "cancelled", "cancelled_at": utc_now(), "cancel_reason": str(payload.get("reason") or "operator_cancelled")})
    return {"job": storage.read_json(path)}


def list_review_queue(storage: LocalStorage, *, project_id: str | None = None, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = _list(storage, "mkaos_model_extraction_review", project_id=project_id, limit=limit)
    if status:
        rows = [row for row in rows if str(row.get("content", {}).get("status") or "") == status]
    return rows


def approve_candidate(storage: LocalStorage, candidate_ref: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    path, candidate = _find(storage, candidate_ref, "mkaos_model_extraction_candidate")
    content = candidate.get("content", {}) if isinstance(candidate.get("content"), dict) else {}
    card = create_creative_knowledge_card(storage, {**content.get("candidate_payload", {}), "project_id": content.get("project_id") or payload.get("project_id") or "local-system", "source": candidate.get("id", ""), "evidence_refs": content.get("evidence_refs", [])})
    content["status"] = "approved"
    content["approved_at"] = utc_now()
    content["approved_knowledge_card_id"] = card["asset"]["id"]
    candidate["content"] = content
    candidate["updated_at"] = utc_now()
    storage.write_json(path, candidate)
    _update_reviews_for_candidate(storage, str(candidate.get("id") or ""), "approved", payload)
    return {"candidate": storage.read_json(path), "knowledge_card": card}


def reject_candidate(storage: LocalStorage, candidate_ref: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    path, candidate = _find(storage, candidate_ref, "mkaos_model_extraction_candidate")
    content = candidate.get("content", {}) if isinstance(candidate.get("content"), dict) else {}
    content["status"] = "rejected"
    content["rejected_at"] = utc_now()
    content["reject_reason"] = str(payload.get("reason") or "operator_rejected")
    candidate["content"] = content
    candidate["updated_at"] = utc_now()
    storage.write_json(path, candidate)
    _update_reviews_for_candidate(storage, str(candidate.get("id") or ""), "rejected", payload)
    return {"candidate": storage.read_json(path)}


def run_benchmark(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    cases = _benchmark_cases(payload)
    results = []
    for case in cases:
        job = create_model_extraction_job(storage, {**case, "project_id": project_id, "provider_mode": payload.get("provider_mode", "disabled")})
        run = run_model_extraction_job(storage, job["id"], {**case, "provider_mode": payload.get("provider_mode", "disabled")})
        results.append(_benchmark_case_result(case, run))
    score = round(sum(item["score"] for item in results) / len(results), 4) if results else 0
    asset = _asset(
        "mkaos_extraction_benchmark_run",
        make_id("mkaos_extraction_benchmark_run", f"{project_id} {utc_now()}"),
        "MKAOS extraction benchmark",
        "mkaos-model-extraction",
        {"project_id": project_id, "benchmark_score": score, "case_count": len(results), "results": results, "source_policy": _source_policy(), "source_isolation": _source_isolation(), "created_at": utc_now()},
        _metadata(project_id, payload),
    )
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path), "benchmark_score": score, "results": results}


def run_regression(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    benchmark = run_benchmark(storage, payload)
    regressions = [item for item in benchmark["results"] if not item["passed"]]
    project_id = str(payload.get("project_id") or "local-system")
    asset = _asset(
        "mkaos_extraction_regression_report",
        make_id("mkaos_extraction_regression_report", f"{project_id} {utc_now()}"),
        "MKAOS extraction regression",
        "mkaos-model-extraction",
        {"project_id": project_id, "passed": not regressions, "regression_count": len(regressions), "benchmark_score": benchmark["benchmark_score"], "regressions": regressions, "source_policy": _source_policy(), "source_isolation": _source_isolation(), "created_at": utc_now()},
        _metadata(project_id, payload),
        references=[benchmark["asset"]["id"]],
    )
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path), "passed": not regressions, "regression_count": len(regressions)}


def create_prompt_version_public(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    return create_prompt_version(storage, payload)


def _deterministic_candidates(source_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if source_type == "classical_text":
        return classical_text_extractor(payload)
    if source_type == "webnovel_analysis":
        return webnovel_extractor(payload)
    if source_type == "mystery":
        return mystery_extractor(payload)
    return professional_book_extractor(payload)


def _active_prompt(prompts: list[dict[str, Any]], source_type: str) -> dict[str, Any]:
    for row in prompts:
        content = row.get("content", {}) if isinstance(row.get("content"), dict) else {}
        if content.get("source_type") == source_type and content.get("status") == "active":
            return row
    for row in prompts:
        content = row.get("content", {}) if isinstance(row.get("content"), dict) else {}
        if content.get("source_type") == source_type:
            return row
    return prompts[0] if prompts else {"content": {}}


def _provider_candidates(output: Any) -> list[dict[str, Any]]:
    if isinstance(output, dict) and isinstance(output.get("candidates"), list):
        return [item for item in output["candidates"] if isinstance(item, dict)]
    return []


def _normalize_candidate(candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    source_type = str(candidate.get("source_type") or payload.get("source_type") or "professional_book")
    quality = candidate.get("quality_dimensions") if isinstance(candidate.get("quality_dimensions"), dict) else {}
    return {
        "concept_name": str(candidate.get("concept_name") or f"{source_type} creative mechanism"),
        "source_type": source_type,
        "discipline": str(candidate.get("discipline") or "creative_knowledge"),
        "knowledge_type": str(candidate.get("knowledge_type") or "mechanism"),
        "abstraction_level": str(candidate.get("abstraction_level") or "mechanism"),
        "core_explanation": str(candidate.get("core_explanation") or candidate.get("creative_principle") or "abstract creative mechanism"),
        "creative_principle": str(candidate.get("creative_principle") or "turn source-derived abstraction into choice, conflict, action, and cost"),
        "narrative_function": str(candidate.get("narrative_function") or "drive plot through pressure and consequence"),
        "conflict_function": str(candidate.get("conflict_function") or "make competing incentives visible"),
        "character_function": str(candidate.get("character_function") or "reveal desire, wound, pressure, and cost"),
        "worldbuilding_function": str(candidate.get("worldbuilding_function") or "define reusable world constraint"),
        "prose_function": str(candidate.get("prose_function") or "show through scene action rather than exposition"),
        "review_function": str(candidate.get("review_function") or "check whether knowledge changes action, conflict, or consequence"),
        "positive_usage": candidate.get("positive_usage") if isinstance(candidate.get("positive_usage"), list) else ["use as abstract mechanism"],
        "negative_usage": candidate.get("negative_usage") if isinstance(candidate.get("negative_usage"), list) else ["do not copy source expression"],
        "anti_patterns": candidate.get("anti_patterns") if isinstance(candidate.get("anti_patterns"), list) else ["百科化", "原文复用"],
        "applicable_flows": candidate.get("applicable_flows") if isinstance(candidate.get("applicable_flows"), list) and candidate.get("applicable_flows") else ["outline", "chapter_outline", "prose", "review"],
        "applicable_genres": candidate.get("applicable_genres") if isinstance(candidate.get("applicable_genres"), list) else [],
        "applicable_platforms": candidate.get("applicable_platforms") if isinstance(candidate.get("applicable_platforms"), list) else [],
        "originality_boundary": str(candidate.get("originality_boundary") or "abstract mechanism only; no source wording, characters, scenes, or source-specific sequence"),
        "evidence_refs": _strings(candidate.get("evidence_refs") or payload.get("evidence_refs") or payload.get("source_refs")),
        "confidence": float(candidate.get("confidence", 0.7) or 0.7),
        "risk_level": str(candidate.get("risk_level") or "low"),
        "quality_dimensions": {
            "abstraction_score": float(quality.get("abstraction_score", 0.76)),
            "creative_usability_score": float(quality.get("creative_usability_score", 0.76)),
            "flow_binding_score": float(quality.get("flow_binding_score", 0.76)),
            "originality_safety_score": float(quality.get("originality_safety_score", 0.82)),
            "review_pass_score": float(quality.get("review_pass_score", 0.66)),
        },
        "metadata": candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {},
    }


def _write_provider_evidence(storage: LocalStorage, project_id: str, provider: dict[str, Any], sanitizer: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    content = {
        "project_id": project_id,
        "provider_mode": provider.get("provider_mode", ""),
        "model": provider.get("model", ""),
        "provider_output_hash": provider.get("provider_output_hash") or sanitizer.get("provider_output_hash", ""),
        "sanitizer_events": sanitizer.get("sanitizer_events", []),
        "forbidden_field_count": sanitizer.get("forbidden_field_count", 0),
        "source_policy": _source_policy(),
        "source_isolation": _source_isolation(),
        "provider_approval_evidence": provider.get("provider_approval_evidence", {}) if isinstance(provider.get("provider_approval_evidence", {}), dict) else {},
        "provider_runtime_gate": provider.get("provider_runtime_gate", {}) if isinstance(provider.get("provider_runtime_gate", {}), dict) else {},
        "warnings": provider.get("warnings", []) if isinstance(provider.get("warnings"), list) else [],
        "created_at": utc_now(),
    }
    asset = _asset("mkaos_extraction_provider_evidence", make_id("mkaos_extraction_provider_evidence", content["provider_output_hash"] or utc_now()), "MKAOS extraction provider evidence", "mkaos-model-extraction", content, _metadata(project_id, payload), references=_strings(payload.get("evidence_refs")))
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path)}


def _write_candidate(storage: LocalStorage, project_id: str, job: dict[str, Any], candidate_payload: dict[str, Any], validation: dict[str, Any], score: dict[str, Any], sanitizer: dict[str, Any], provider_evidence: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    status = "pending_review"
    if sanitizer.get("forbidden_field_count"):
        status = "blocked_source_leakage"
    elif score["approval_recommendation"] == "approve":
        status = "auto_approved"
    elif score["approval_recommendation"] == "reject":
        status = "auto_rejected"
    content = {
        "candidate_id": "",
        "project_id": project_id,
        "job_id": job.get("id", ""),
        "candidate_payload": candidate_payload,
        "status": status,
        "confidence": score["confidence"],
        "quality_dimensions": score["quality_dimensions"],
        "approval_recommendation": score["approval_recommendation"],
        "validation": validation,
        "sanitizer": {key: sanitizer.get(key) for key in ["forbidden_field_hits", "forbidden_field_count", "sanitizer_events", "source_isolation", "provider_output_hash"]},
        "source_policy": _source_policy(),
        "source_isolation": _source_isolation(),
        "evidence_refs": _strings(candidate_payload.get("evidence_refs")),
        "created_at": utc_now(),
    }
    candidate_id = make_id("mkaos_model_extraction_candidate", f"{job.get('id')} {candidate_payload.get('concept_name')}")
    content["candidate_id"] = candidate_id
    asset = _asset("mkaos_model_extraction_candidate", candidate_id, str(candidate_payload.get("concept_name") or "MKAOS candidate"), "mkaos-model-extraction", content, _metadata(project_id, payload), references=_strings([job.get("id", ""), provider_evidence.get("asset", {}).get("id", ""), *content["evidence_refs"]]))
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path)}


def _write_review(storage: LocalStorage, project_id: str, candidate: dict[str, Any], score: dict[str, Any], validation: dict[str, Any], sanitizer: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    status = "pending"
    if sanitizer.get("forbidden_field_count"):
        status = "auto_rejected"
    elif score["confidence"] >= 0.85 and validation.get("valid"):
        status = "auto_approved"
    elif score["confidence"] < 0.65:
        status = "auto_rejected"
    content = {
        "review_id": "",
        "project_id": project_id,
        "candidate_id": candidate.get("id", ""),
        "status": status,
        "confidence": score["confidence"],
        "approval_recommendation": score["approval_recommendation"],
        "validation": validation,
        "sanitizer": sanitizer,
        "source_policy": _source_policy(),
        "source_isolation": _source_isolation(),
        "created_at": utc_now(),
    }
    review_id = make_id("mkaos_model_extraction_review", f"{candidate.get('id')} {status}")
    content["review_id"] = review_id
    asset = _asset("mkaos_model_extraction_review", review_id, f"Review {candidate.get('title')}", "mkaos-model-extraction", content, _metadata(project_id, payload), references=[str(candidate.get("id") or "")])
    path = _write(storage, asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path)}


def _persist_candidate_issue(storage: LocalStorage, project_id: str, candidate: dict[str, Any], validation: dict[str, Any], sanitizer: dict[str, Any], *, production: bool) -> dict[str, Any] | None:
    if not production and not sanitizer.get("forbidden_field_count"):
        return None
    issue_type = "source_leakage" if sanitizer.get("forbidden_field_count") else "mkaos_conflict"
    severity = "critical" if sanitizer.get("forbidden_field_count") else "high"
    return create_review_issue(
        storage,
        {
            "project_id": project_id,
            "issue_type": issue_type,
            "severity": severity,
            "blocking": True,
            "message": "MKAOS model extraction candidate failed sanitizer or schema validation",
            "target_asset_id": candidate.get("id", ""),
            "target_asset_type": "mkaos_model_extraction_candidate",
            "evidence_refs": [candidate.get("id", "")],
            "source_system": "mkaos.model_extraction",
            "source_issue": {"validation": validation, "sanitizer": sanitizer},
        },
    )


def _benchmark_cases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    if cases:
        return [case for case in cases if isinstance(case, dict)]
    return [
        {"case_id": "classical-basic", "source_type": "classical_text", "input_summary": "礼法和名分造成角色选择压力。", "expected_knowledge_types": ["world_rule"], "expected_flows": ["outline", "review"], "expected_min_scores": {"confidence": 0.65}},
        {"case_id": "professional-basic", "source_type": "professional_book", "input_summary": "专业方法差异会改变资源配置和风险后果。", "expected_knowledge_types": ["review_rule"], "expected_flows": ["review"], "expected_min_scores": {"confidence": 0.65}},
        {"case_id": "mystery-basic", "source_type": "mystery", "input_summary": "证据、误导和嫌疑人动机构成公平线索链。", "expected_knowledge_types": ["conflict_pattern"], "expected_flows": ["review"], "expected_min_scores": {"confidence": 0.65}},
    ]


def _benchmark_case_result(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    candidates = [row["asset"]["content"] for row in run.get("candidates", [])]
    confidence = max([float(item.get("confidence", 0)) for item in candidates] or [0])
    expected_min = float(case.get("expected_min_scores", {}).get("confidence", 0.65) if isinstance(case.get("expected_min_scores"), dict) else 0.65)
    selected_flows = {flow for item in candidates for flow in item.get("candidate_payload", {}).get("applicable_flows", [])}
    expected_flows = {str(item) for item in case.get("expected_flows") or []}
    passed = confidence >= expected_min and bool(selected_flows & expected_flows or not expected_flows)
    return {"case_id": case.get("case_id", ""), "score": confidence, "passed": passed, "selected_flows": sorted(selected_flows), "expected_flows": sorted(expected_flows)}


def _update_job(storage: LocalStorage, path: Path, updates: dict[str, Any]) -> None:
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data.get("content"), dict) else {}
    content.update(updates)
    content["status_history"] = [*(content.get("status_history") if isinstance(content.get("status_history"), list) else []), {"status": content.get("status", ""), "at": utc_now()}]
    data["content"] = content
    data["updated_at"] = utc_now()
    storage.write_json(path, data)


def _update_reviews_for_candidate(storage: LocalStorage, candidate_id: str, status: str, payload: dict[str, Any]) -> None:
    for row in _list(storage, "mkaos_model_extraction_review", limit=1000):
        if str(row.get("content", {}).get("candidate_id") or "") != candidate_id:
            continue
        path = resolve_path(storage.root, row["path"])
        data = storage.read_json(path)
        content = data.get("content", {}) if isinstance(data.get("content"), dict) else {}
        content["status"] = status
        content["operator_note"] = str(payload.get("note") or payload.get("reason") or "")
        content["updated_at"] = utc_now()
        data["content"] = content
        data["updated_at"] = utc_now()
        storage.write_json(path, data)


def _list(storage: LocalStorage, asset_type: str, *, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    category = MODEL_EXTRACTION_TYPES.get(asset_type, "runs")
    for path in reversed(storage.list_json(category)):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        content = data.get("content", {}) if isinstance(data.get("content"), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
        if project_id and str(content.get("project_id") or metadata.get("project_id") or "") != project_id:
            continue
        rows.append(_row(storage, path, data))
    return rows


def _find(storage: LocalStorage, ref: str, asset_type: str) -> tuple[Path, dict[str, Any]]:
    value = str(ref)
    category = MODEL_EXTRACTION_TYPES.get(asset_type, "runs")
    if "/" in value or value.endswith(".json"):
        path = resolve_path(storage.root, value)
        data = storage.read_json(path)
        if data.get("type") == asset_type:
            return path, data
    for path in reversed(storage.list_json(category)):
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") == asset_type and value in {str(data.get("id") or ""), str(path.relative_to(storage.root))}:
            return path, data
    raise FileNotFoundError(ref)


def _row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return {"path": _display_path(storage, path), "id": data.get("id", ""), "type": data.get("type", ""), "title": data.get("title", ""), "content": data.get("content", {}), "metadata": data.get("metadata", {}), "references": data.get("references", []), "asset": data, "updated_at": data.get("updated_at", "")}


def _asset(asset_type: str, asset_id: str, title: str, source: str, content: dict[str, Any], metadata: dict[str, Any], references: list[str] | None = None) -> BaseAsset:
    return BaseAsset(id=asset_id, type=asset_type, title=title, source=source, tags=["mkaos", "model-extraction", asset_type], content=content, metadata=metadata, references=references or [])


def _write(storage: LocalStorage, asset: BaseAsset) -> Path:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return storage.write_asset(MODEL_EXTRACTION_TYPES.get(asset.type, "runs"), asset)


def _metadata(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "mkaos": True,
        "use_in_generation_rag": False,
        "trace_id": str(payload.get("trace_id") or ""),
        "os_envelope": payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else {},
        "run_metadata": run_metadata("mkaos.model_extraction", BaseAsset(title="mkaos-model-extraction", content={})),
        "source_policy": _source_policy(),
        "source_isolation": _source_isolation(),
    }


def _source_policy() -> dict[str, bool]:
    return {"raw_source_text_allowed": False, "source_chunk_raw_text_allowed": False, "parallel_pair_text_allowed": False, "provider_raw_output_allowed": False, "generation_rag_allowed": False}


def _source_isolation() -> dict[str, bool]:
    return {"raw_text_included": False, "clean_text_included": False, "source_text_included": False, "target_text_included": False, "provider_raw_output_included": False}


def _is_production(payload: dict[str, Any]) -> bool:
    return str(payload.get("environment") or "").strip().lower() in {"production", "strict", "operating_system"}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _display_path(storage: LocalStorage, path: str | Path) -> str:
    p = Path(path)
    return str(p.relative_to(storage.root)) if p.is_absolute() and p.is_relative_to(storage.root) else str(p)
