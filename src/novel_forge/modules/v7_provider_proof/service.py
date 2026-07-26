from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.content_quality_loop import run_content_quality_loop
from novel_forge.modules.long_chain_proof import run_long_chain_proof
from novel_forge.modules.model_router import record_external_provider_proof
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata
from novel_forge.modules.production_context import project_scope_from_asset
from novel_forge.modules.production_execution import (
    CandidateKind,
    DomainExecutionPort,
    DomainModelOperation,
    execute_domain_candidate,
)
from novel_forge.modules.production_execution.security import (
    CONTROLLED_EXECUTION_ENVIRONMENTS,
    execution_environment,
)
from novel_forge.modules.quality_eval import build_quality_rubric_pack, run_provider_quality_judge, run_quality_gate
from novel_forge.schemas import DraftChapter, ProjectMetricSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage


def run_v7_provider_proof(
    storage: LocalStorage,
    *,
    provider_adapter: Any,
    execution_port: DomainExecutionPort | None = None,
    project_id: str,
    draft_path: str | Path | None = None,
    genre_strategy_pack_path: str | Path | None = None,
    style_profile_path: str | Path | None = None,
    platform_id: str = "local",
    provider_runtime_guard: dict[str, Any] | None = None,
    require_external_provider_proof: bool = True,
    environment: str = "production",
    envelope: dict[str, Any] | None = None,
    target_chapter_count: int = 50,
) -> dict[str, Any]:
    """Run the V7 P0 provider proof chain through existing governed services.

    The runner proves three things with the same provider/runtime boundary:
    opening_3 provider judge, one provider-generated chapter draft plus content
    quality loop, and a provider-backed 50-chapter long-chain proof.
    """

    if provider_adapter is None and execution_port is None:
        raise ValueError("V7 Provider proof requires an execution port")
    if (
        execution_environment(environment)
        in CONTROLLED_EXECUTION_ENVIRONMENTS
        and execution_port is None
    ):
        raise RuntimeError(
            "legacy direct model adapters are disabled; controlled V7 Provider "
            "proof requires an Authority-bound "
            "ProductionExecutionGateway port"
        )
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="run-v7-provider-proof",
        project_id=project_id,
        task_type="v7_provider_proof",
        asset_type="project_metric_snapshot",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    resolved_draft_path = str(draft_path or "")
    single_generation: dict[str, Any] = {}
    if not resolved_draft_path:
        single = _run_provider_single_chapter_draft(
            storage,
            adapter=provider_adapter,
            execution_port=execution_port,
            project_id=project_id,
            envelope=env,
            provider_runtime_guard=provider_runtime_guard or {},
            require_external_provider_proof=require_external_provider_proof,
        )
        resolved_draft_path = single["draft_path"]
        single_generation = single
    draft_asset = storage.read_asset(resolve_path(storage.root, resolved_draft_path))
    if not single_generation:
        single_generation = _single_generation_evidence_from_draft(storage, resolved_draft_path, draft_asset.to_dict())
    scope = project_scope_from_asset(storage, draft_asset, input_path=resolve_path(storage.root, resolved_draft_path))
    rubric = build_quality_rubric_pack(
        storage,
        genre_id="general",
        platform_id=platform_id,
        style_profile_path=str(style_profile_path or ""),
        scope="opening_3",
        environment=str(env.get("environment") or environment),
        envelope={**env, "task_type": "quality_eval", "asset_type": "quality_rubric_pack"},
    )
    opening = run_provider_quality_judge(
        storage,
        suite_type="opening_3",
        target_paths=[resolved_draft_path],
        rubric_path=rubric["path"],
        adapter=provider_adapter,
        execution_port=execution_port,
        genre_strategy_pack_path=str(genre_strategy_pack_path or ""),
        style_profile_path=str(style_profile_path or ""),
        platform_id=platform_id,
        environment=str(env.get("environment") or environment),
        envelope={**env, "task_type": "quality_judge", "asset_type": "opening_3_report"},
        provider_runtime_guard=provider_runtime_guard or {},
        allow_mock_fixture=False,
        require_external_provider_proof=require_external_provider_proof,
    )
    opening_gate = run_quality_gate(
        storage,
        quality_report_path=opening["path"],
        environment=str(env.get("environment") or environment),
        envelope={**env, "task_type": "quality_gate", "asset_type": "evaluation_gate"},
    )
    single_quality = run_content_quality_loop(
        storage,
        target_path=resolved_draft_path,
        stage="provider_single_chapter",
        suite_type="opening_3",
        genre_strategy_pack_path=genre_strategy_pack_path,
        style_profile_path=style_profile_path,
        platform_id=platform_id,
        provider_adapter=provider_adapter,
        execution_port=execution_port,
        provider_runtime_guard=provider_runtime_guard or {},
        allow_mock_fixture=False,
        require_provider_judge=True,
        require_external_provider_proof=require_external_provider_proof,
        environment=str(env.get("environment") or environment),
        envelope={**env, "task_type": "content_quality_loop", "asset_type": "content_quality_loop_report"},
        persist_issues=True,
    )
    long_chain = run_long_chain_proof(
        storage,
        project_id=project_id,
        mode="provider_50_proof",
        target_chapter_count=target_chapter_count,
        environment=str(env.get("environment") or environment),
        envelope={**env, "task_type": "long_chain_proof", "asset_type": "long_chain_run"},
        opt_in_slow_provider=True,
        provider_adapter=provider_adapter,
        execution_port=execution_port,
        provider_runtime_guard=provider_runtime_guard or {},
        require_external_provider_proof=require_external_provider_proof,
    )
    proof_manifest = _provider_proof_manifest(
        storage,
        opening=opening,
        single_generation=single_generation,
        single_quality=single_quality,
        long_chain=long_chain,
        target_chapter_count=target_chapter_count,
        require_external_provider_proof=require_external_provider_proof,
    )
    checks = [
        _check("opening_3_provider_judge", opening["asset"]["content"].get("recommendation") == "ready", opening["path"]),
        _check("opening_3_quality_gate", opening_gate["asset"]["content"].get("status") == "passed", opening_gate["path"]),
        _check("provider_single_chapter_quality_loop", single_quality.get("status") in {"passed", "passed_with_warnings"}, single_quality.get("path", "")),
        _check("provider_50_long_chain_proof", long_chain["asset"]["content"].get("status") == "ready", long_chain["acceptance_report_path"]),
        _check("provider_proof_manifest", not proof_manifest["blocking"], ""),
    ]
    status = "passed" if all(row["passed"] for row in checks) else "blocked"
    evidence_refs = _dedupe(
        [
            resolved_draft_path,
            rubric["path"],
            opening["path"],
            opening_gate["path"],
            single_quality.get("path", ""),
            long_chain.get("run_path", ""),
            long_chain.get("acceptance_report_path", ""),
            *(opening.get("model_judge_result_paths", []) if isinstance(opening.get("model_judge_result_paths", []), list) else []),
            str((opening.get("external_provider_proof", {}) if isinstance(opening.get("external_provider_proof", {}), dict) else {}).get("path") or ""),
        ]
    )
    snapshot = ProjectMetricSnapshot(
        title="V7 provider proof snapshot",
        tags=["v7-provider-proof", status],
        content={
            "snapshot_id": make_id("project_metric_snapshot", f"v7-provider-proof-{project_id}-{utc_now()}"),
            "snapshot_kind": "v7_provider_proof",
            "snapshot_at": utc_now(),
            "status": status,
            "project_id": project_id or str(scope.get("project_id") or ""),
            "throughput": {"proof_count": len(checks), "passed_count": sum(1 for row in checks if row["passed"])},
            "quality": {"average_review_score": 0.0, "review_pass_rate": 1.0 if status == "passed" else 0.0, "originality_risk_rate": 0.0},
            "task_health": {"failed": 0 if status == "passed" else 1, "running": 0, "waiting_handoff": 0, "dead_letters": 0},
            "agent_health": {"provider_proof": status},
            "storage_health": {"evidence_ref_count": len(evidence_refs)},
            "recommendations": [] if status == "passed" else ["Repair failed V7 provider proof checks before production release."],
            "checks": checks,
            "opening_3": {"report_path": opening["path"], "gate_path": opening_gate["path"], "external_provider_proof": opening.get("external_provider_proof", {})},
            "single_chapter": {"draft_path": resolved_draft_path, "content_quality_loop_path": single_quality.get("path", ""), "status": single_quality.get("status", "")},
            "long_chain_50": {"run_path": long_chain.get("run_path", ""), "acceptance_report_path": long_chain.get("acceptance_report_path", ""), "status": long_chain["asset"]["content"].get("status", "")},
            "provider_proof_manifest": proof_manifest,
            "provider_runtime_guard": provider_runtime_guard or {},
            "external_provider_proof_required": bool(require_external_provider_proof),
            "evidence_refs": evidence_refs,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, **envelope_asset_metadata(env)},
        references=evidence_refs,
    )
    path = _write_asset(storage, snapshot)
    return {"status": status, "path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "evidence_refs": evidence_refs, "envelope": env}


def _provider_proof_manifest(
    storage: LocalStorage,
    *,
    opening: dict[str, Any],
    single_generation: dict[str, Any],
    single_quality: dict[str, Any],
    long_chain: dict[str, Any],
    target_chapter_count: int,
    require_external_provider_proof: bool,
) -> dict[str, Any]:
    opening_proof = opening.get("external_provider_proof", {}) if isinstance(opening.get("external_provider_proof", {}), dict) else {}
    single_proof = single_generation.get("external_provider_proof", {}) if isinstance(single_generation.get("external_provider_proof", {}), dict) else {}
    single_quality_proof = _proof_from_content_quality_loop(storage, single_quality)
    long_chain_report = long_chain.get("asset", {}).get("content", {}) if isinstance(long_chain.get("asset", {}).get("content", {}), dict) else {}
    provider_generation = long_chain_report.get("provider_generation_evidence", {}) if isinstance(long_chain_report.get("provider_generation_evidence", {}), dict) else {}
    long_chain_paths = [str(path) for path in provider_generation.get("external_provider_proof_paths", []) if str(path).strip()] if isinstance(provider_generation.get("external_provider_proof_paths", []), list) else []
    long_chain_statuses = [_proof_status_from_path(storage, path) for path in long_chain_paths]
    segments = {
        "opening_3_provider_judge": _proof_summary(opening_proof, required=require_external_provider_proof),
        "single_chapter_generation": _proof_summary(single_proof, required=require_external_provider_proof),
        "single_chapter_quality_judge": _proof_summary(single_quality_proof, required=require_external_provider_proof),
        "long_chain_50_generation": {
            "status": "passed" if long_chain_statuses and all(item.get("status") == "passed" for item in long_chain_statuses) and len(long_chain_statuses) == target_chapter_count else "not_required" if not require_external_provider_proof else "missing",
            "classification": "external_provider" if long_chain_statuses and all(item.get("status") == "passed" for item in long_chain_statuses) and len(long_chain_statuses) == target_chapter_count else "not_required" if not require_external_provider_proof else "missing",
            "proof_count": len(long_chain_statuses),
            "target_count": target_chapter_count,
            "paths": long_chain_paths[:10],
        },
    }
    blocking: list[dict[str, Any]] = []
    if require_external_provider_proof:
        for segment, summary in segments.items():
            if summary.get("classification") != "external_provider" or summary.get("status") != "passed":
                blocking.append(
                    {
                        "segment": segment,
                        "status": summary.get("status", ""),
                        "classification": summary.get("classification", ""),
                        "message": f"{segment} lacks real external provider proof",
                    }
                )
    return {
        "contract": "provider-proof-harness-v1",
        "external_provider_proof_required": bool(require_external_provider_proof),
        "status": "blocked" if blocking else "passed",
        "blocking": bool(blocking),
        "segments": segments,
        "blocking_issues": blocking,
        "ledger_requirements": ["model_route_resolution", "model_call_log", "runtime_policy", "cost_ledger", "external_provider_proof_report"],
        "credential_boundary": "credential references only; no raw provider secret is persisted",
    }


def _proof_summary(proof: dict[str, Any], *, required: bool) -> dict[str, Any]:
    status = str(proof.get("status") or "")
    path = str(proof.get("path") or "")
    if status == "passed" and path:
        return {"status": "passed", "classification": "external_provider", "path": path}
    if not required:
        return {"status": status or "not_required", "classification": "not_required", "path": path}
    if status == "blocked":
        issues = proof.get("blocking_issues", []) if isinstance(proof.get("blocking_issues", []), list) else []
        if any("fixture" in str(issue.get("dimension", "")).lower() for issue in issues if isinstance(issue, dict)):
            return {"status": "blocked", "classification": "fixture_or_mock", "path": path, "blocking_issues": issues}
        return {"status": "blocked", "classification": "blocked", "path": path, "blocking_issues": issues}
    return {"status": "missing", "classification": "missing", "path": path}


def _proof_status_from_path(storage: LocalStorage, path: str) -> dict[str, Any]:
    try:
        data = storage.read_json(resolve_path(storage.root, path))
    except FileNotFoundError:
        return {"status": "missing", "path": path}
    content = data.get("content", {}) if isinstance(data.get("content"), dict) else {}
    return {"status": str(content.get("status") or ""), "path": path}


def _proof_from_content_quality_loop(storage: LocalStorage, single_quality: dict[str, Any]) -> dict[str, Any]:
    asset = single_quality.get("asset", {}) if isinstance(single_quality.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    steps = content.get("steps", []) if isinstance(content.get("steps", []), list) else []
    for step in steps:
        if not isinstance(step, dict) or step.get("name") != "provider_quality_judge":
            continue
        for path in step.get("paths", []) if isinstance(step.get("paths", []), list) else []:
            try:
                data = storage.read_json(resolve_path(storage.root, path))
            except FileNotFoundError:
                continue
            if data.get("type") != "external_provider_proof_report":
                continue
            status = str((data.get("content", {}) if isinstance(data.get("content"), dict) else {}).get("status") or "")
            return {"status": status, "path": str(path)}
    return {"status": "missing", "path": ""}


def _single_generation_evidence_from_draft(storage: LocalStorage, draft_path: str, draft: dict[str, Any]) -> dict[str, Any]:
    content = draft.get("content", {}) if isinstance(draft.get("content"), dict) else {}
    evidence = content.get("provider_generation_evidence", {}) if isinstance(content.get("provider_generation_evidence", {}), dict) else {}
    proof_path = str(evidence.get("external_provider_proof_path") or "")
    proof = {"status": "missing", "path": "", "blocking": True}
    if proof_path:
        proof = _proof_status_from_path(storage, proof_path) | {"blocking": False}
    return {"draft_path": draft_path, "external_provider_proof": proof}


def _run_provider_single_chapter_draft(
    storage: LocalStorage,
    *,
    adapter: Any,
    execution_port: DomainExecutionPort | None,
    project_id: str,
    envelope: dict[str, Any],
    provider_runtime_guard: dict[str, Any],
    require_external_provider_proof: bool,
) -> dict[str, Any]:
    payload = {
        "task": "v7_provider_single_chapter_draft",
        "project_id": project_id,
        "instruction": "Generate an original single chapter proof candidate with visible genre promise, style controllability, conflict, and hook.",
    }
    candidate = execute_domain_candidate(
        capability="prose.chapter.draft",
        operation=DomainModelOperation.GENERATE,
        candidate_kind=CandidateKind.GENERATION,
        prompt=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        context={
            "environment": envelope.get("environment"),
            "proof": "v7_provider_single_chapter",
            "project_id": project_id,
            "prompt_id": "v7-provider-proof-single-chapter",
            "prompt_version": "v7",
        },
        execution_port=execution_port,
        legacy_model=adapter,
        legacy_model_role="draft",
        environment=str(envelope.get("environment") or ""),
    )
    routed = {
        **dict(candidate.raw_output),
        "production_execution": candidate.evidence.to_dict(),
        "model_route_resolution_path": candidate.evidence.route_snapshot_id,
        "model_gateway_call": {
            "provider": (
                candidate.evidence.provider_id
                or candidate.evidence.backend_id
            ),
            "model": candidate.evidence.model_id,
            "model_call_log_path": candidate.evidence.validation_manifest_ref,
            "runtime_policy_path": candidate.evidence.input_manifest_ref,
            "cost_ledger_path": candidate.evidence.cost_receipt_ref,
            "provider_policy": {
                "status": "passed"
                if execution_port is not None
                else "legacy_development_only",
                "production_execution_gateway_backed": (
                    execution_port is not None
                ),
            },
            "approval_evidence": {
                "approved": execution_port is not None,
                "route_snapshot_id": candidate.evidence.route_snapshot_id,
            },
        },
        "external_provider_evidence": {
            "external_call": candidate.evidence.real_model_call,
            "fixture": candidate.evidence.fixture_protocol_only,
            "provider_response_id": candidate.evidence.provider_request_id,
            "endpoint_host": "",
            "rate_limit_policy": "route-snapshot-bound",
            "credential_ref": "route-snapshot:"
            + candidate.evidence.route_snapshot_id,
        },
    }
    external_proof = (
        record_external_provider_proof(
            storage,
            proof_type="v7_provider_single_chapter_draft",
            routed_result=routed,
            adapter=adapter,
            project_id=project_id,
            environment=str(envelope.get("environment") or ""),
            strict=require_external_provider_proof,
        )
        if require_external_provider_proof
        else {"status": "not_required", "path": "", "blocking": False}
    )
    gateway = routed.get("model_gateway_call", {}) if isinstance(routed.get("model_gateway_call", {}), dict) else {}
    draft = DraftChapter(
        title="V7 provider proof single chapter",
        tags=["v7-provider-proof", "single-chapter", "provider-generated"],
        content={
            "chapter": 1,
            "text": str(routed.get("text") or ""),
            "copyright_boundary": "provider-generated original proof candidate; no reference-source text",
            "provider_generation_evidence": {
                "model_route_resolution_path": str(routed.get("model_route_resolution_path") or ""),
                "model_call_log_path": str(gateway.get("model_call_log_path") or ""),
                "runtime_policy_path": str(gateway.get("runtime_policy_path") or ""),
                "cost_ledger_path": str(gateway.get("cost_ledger_path") or ""),
                "external_provider_proof_path": str(external_proof.get("path") or ""),
            },
        },
        metadata={"project_id": project_id, **envelope_asset_metadata(envelope)},
        references=_dedupe(
            [
                str(routed.get("model_route_resolution_path") or ""),
                str(gateway.get("model_call_log_path") or ""),
                str(gateway.get("runtime_policy_path") or ""),
                str(gateway.get("cost_ledger_path") or ""),
                str(external_proof.get("path") or ""),
            ]
        ),
    )
    path = _write_asset(storage, draft)
    return {"draft_path": path, "external_provider_proof": external_proof}


def _check(name: str, passed: bool, path: str) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "path": str(path or ""), "blocking": True}


def _write_asset(storage: LocalStorage, asset: Any) -> str:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return _display_path(storage.root, storage.write_asset_auto(asset))


def _display_path(root: Path, path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return str(resolved.relative_to(root)) if resolved.is_relative_to(root) else str(resolved)


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
