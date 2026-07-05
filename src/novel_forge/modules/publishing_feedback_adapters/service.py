from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib import request
from urllib.parse import urlparse

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment
from novel_forge.modules.review_issue import persist_issue_candidates
from novel_forge.modules.publishing_feedback_adapters.fallbacks import record_platform_publish_failure
from novel_forge.schemas import (
    ChapterDropoffReport,
    CommentClusterReport,
    FeedbackPlanMutationProposal,
    PlatformCommentBatch,
    PlatformMetricSnapshot,
    PlatformPublishReceipt,
    PlatformReviewStatus,
    PlatformUploadPackage,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token", "access_token", "refresh_token"}


class HttpPlatformClient:
    def __init__(self, *, endpoint: str, token_env: str = "", timeout_seconds: float = 20.0):
        self.endpoint = endpoint
        self.token_env = token_env
        self.timeout_seconds = timeout_seconds

    def publish_upload_package(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if not self.endpoint:
            raise ValueError("platform API endpoint is required")
        headers = {"Content-Type": "application/json"}
        if self.token_env:
            token = os.environ.get(self.token_env, "")
            if not token:
                raise ValueError(f"platform API token env var is not set: {self.token_env}")
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps({"upload_package": payload, "context": _redact(context)}, ensure_ascii=False).encode("utf-8")
        req = request.Request(self.endpoint, data=body, headers=headers, method="POST")
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            data = response.read().decode("utf-8")
        parsed = json.loads(data) if data.strip() else {}
        if not isinstance(parsed, dict):
            raise ValueError("platform API response must be a JSON object")
        return parsed


def build_platform_upload_package(
    storage: LocalStorage,
    *,
    release_package_path: str | Path,
    platform_id: str = "manual",
    book_metadata: dict[str, Any] | None = None,
    chapter_payloads: list[dict[str, Any]] | None = None,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    release_path = resolve_path(storage.root, release_package_path)
    release = storage.read_json(release_path)
    if is_production_environment(environment or (envelope or {}).get("environment")) and release.get("type") != "release_package":
        raise ValueError("release_package_path must point to a release_package in production")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="build-platform-upload-package",
        project_id=str(release.get("metadata", {}).get("project_id") or ""),
        task_type="platform_upload_package",
        asset_type="platform_upload_package",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    metadata = book_metadata or _book_metadata_from_release(release)
    chapters = chapter_payloads or _chapter_payloads_from_release(release)
    asset = PlatformUploadPackage(
        title=f"{platform_id} manual upload package",
        source=str(release.get("id") or ""),
        tags=["publishing-feedback-adapter", "manual-upload", platform_id],
        content={
            "package_id": make_id("platform_upload_package", f"{platform_id}-{release.get('id', '')}"),
            "platform_id": platform_id,
            "release_package_path": _display_path(storage.root, release_path),
            "book_metadata": metadata,
            "chapter_payloads": chapters,
            "manual_upload_steps": [
                "Open the target platform editor manually.",
                "Copy title, synopsis, tags, and chapter payload from this package.",
                "Run the sensitive-word, formatting, and cover checklist before submit.",
                "Record the platform receipt with record-platform-receipt.",
            ],
            "checklist": {
                "title_present": bool(metadata.get("title")),
                "synopsis_present": bool(metadata.get("synopsis") or metadata.get("summary")),
                "chapter_title_present": all(bool(row.get("title")) for row in chapters),
                "chapter_body_present": all(bool(row.get("body") or row.get("text")) for row in chapters),
                "cover_checked": bool(metadata.get("cover_path") or metadata.get("cover_status") == "not_required"),
                "sensitive_word_checked": False,
                "format_checked": False,
            },
            "status": "manual_ready",
        },
        metadata={"project_id": str(release.get("metadata", {}).get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[_display_path(storage.root, release_path)],
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env}


def record_platform_receipt(
    storage: LocalStorage,
    *,
    platform_id: str,
    platform_book_id: str,
    platform_chapter_id: str = "",
    review_status: str = "submitted",
    receipt_raw: dict[str, Any] | None = None,
    operator_note: str = "",
    upload_package_path: str = "",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="record-platform-receipt",
        project_id=str((envelope or {}).get("project_id") or ""),
        task_type="platform_receipt",
        asset_type="platform_publish_receipt",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    receipt = PlatformPublishReceipt(
        title=f"{platform_id} receipt {platform_book_id}",
        source=upload_package_path,
        tags=["publishing-feedback-adapter", "receipt", review_status],
        content={
            "receipt_id": make_id("platform_publish_receipt", f"{platform_id}-{platform_book_id}-{platform_chapter_id}"),
            "platform_id": platform_id,
            "platform_book_id": platform_book_id,
            "platform_chapter_id": platform_chapter_id or "book-level",
            "submitted_at": utc_now(),
            "review_status": review_status,
            "receipt_raw": receipt_raw or {},
            "operator_note": operator_note or "manual receipt recorded",
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[upload_package_path] if upload_package_path else [],
    )
    receipt_path = _write_asset(storage, receipt)
    status = PlatformReviewStatus(
        title=f"{platform_id} review status {review_status}",
        source=receipt.id,
        tags=["publishing-feedback-adapter", "review-status", review_status],
        content={
            "status_id": make_id("platform_review_status", receipt.id),
            "platform_id": platform_id,
            "receipt_id": receipt.content["receipt_id"],
            "review_status": review_status,
            "blocking_reasons": _blocking_reasons(review_status, receipt_raw or {}),
            "updated_at": utc_now(),
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[receipt_path],
    )
    status_path = _write_asset(storage, status)
    return {"receipt_path": receipt_path, "status_path": status_path, "asset": storage.read_json(resolve_path(storage.root, receipt_path)), "envelope": env}


def publish_platform_upload_package(
    storage: LocalStorage,
    *,
    upload_package_path: str | Path,
    platform_client: Any | None = None,
    platform_config: dict[str, Any] | None = None,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    upload_path = resolve_path(storage.root, upload_package_path)
    upload = storage.read_json(upload_path)
    production = is_production_environment(environment or (envelope or {}).get("environment"))
    if production and upload.get("type") != "platform_upload_package":
        raise ValueError("upload_package_path must point to a platform_upload_package in production")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="publish-platform-upload-package",
        project_id=str(upload.get("metadata", {}).get("project_id") or (envelope or {}).get("project_id") or ""),
        task_type="platform_publish",
        asset_type="platform_publish_receipt",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    config = platform_config or {}
    client = platform_client or _platform_client_from_config(config)
    if client is None:
        raise ValueError("platform publish requires platform_client or platform_config.endpoint")
    production_governance = _release_governance_from_upload(storage, upload, required=production)
    platform_id = str(config.get("platform_id") or upload.get("content", {}).get("platform_id") or "external")
    context = {
        "platform_id": platform_id,
        "environment": env.get("environment"),
        "trace_id": env.get("trace_id"),
        "endpoint": _endpoint_evidence(str(config.get("endpoint") or getattr(client, "endpoint", ""))),
        "token_env": str(config.get("token_env") or getattr(client, "token_env", "")),
    }
    try:
        response = client.publish_upload_package(upload.get("content", {}), context)
    except Exception as exc:
        failure = record_platform_publish_failure(
            storage,
            upload_path=_display_path(storage.root, upload_path),
            platform_id=platform_id,
            error_message=str(exc),
            envelope=env,
            environment=environment,
            production_governance_path=production_governance.get("path", ""),
        )
        raise RuntimeError(f"platform API publish failed closed: {failure['redacted_error']}") from exc
    receipt_raw = _redact(response.get("receipt_raw", response) if isinstance(response, dict) else {})
    receipt = record_platform_receipt(
        storage,
        platform_id=platform_id,
        platform_book_id=str(response.get("platform_book_id") or response.get("book_id") or ""),
        platform_chapter_id=str(response.get("platform_chapter_id") or response.get("chapter_id") or ""),
        review_status=str(response.get("review_status") or response.get("status") or "submitted"),
        receipt_raw=receipt_raw,
        operator_note="recorded from platform API adapter",
        upload_package_path=_display_path(storage.root, upload_path),
        environment=str(env.get("environment") or ""),
        envelope=env,
    )
    receipt_path = receipt["receipt_path"]
    receipt_asset = storage.read_json(resolve_path(storage.root, receipt_path))
    receipt_asset["content"]["platform_api_evidence"] = {
        "mode": "api_adapter",
        "client": type(client).__name__,
        "endpoint": context["endpoint"],
        "token_env": context["token_env"],
        "upload_package_path": _display_path(storage.root, upload_path),
        "response_keys": sorted(str(key) for key in response.keys()) if isinstance(response, dict) else [],
        "production_governance": production_governance,
    }
    storage.write_json(resolve_path(storage.root, receipt_path), receipt_asset)
    status_asset = storage.read_json(resolve_path(storage.root, receipt["status_path"]))
    return {
        "receipt_path": receipt_path,
        "status_path": receipt["status_path"],
        "asset": receipt_asset,
        "status_asset": status_asset,
        "platform_api_evidence": receipt_asset["content"]["platform_api_evidence"],
        "envelope": env,
    }


def _release_governance_from_upload(storage: LocalStorage, upload: dict[str, Any], *, required: bool) -> dict[str, Any]:
    content = upload.get("content", {}) if isinstance(upload.get("content", {}), dict) else {}
    release_ref = str(content.get("release_package_path") or "").strip()
    if not release_ref:
        if required:
            raise ValueError("production governance requires upload package to reference a release package")
        return {"status": "skipped", "path": "", "blocking": False}
    release = storage.read_json(resolve_path(storage.root, release_ref))
    release_content = release.get("content", {}) if isinstance(release.get("content", {}), dict) else {}
    governance = release_content.get("production_governance", {}) if isinstance(release_content.get("production_governance", {}), dict) else {}
    status = str(governance.get("status") or "missing")
    path = str(governance.get("path") or "")
    blocking = bool(governance.get("blocking")) or status != "passed" or not path
    if required and blocking:
        raise ValueError(f"production governance must pass before platform publish: {status}")
    return {"status": status, "path": path, "blocking": blocking, "release_package_path": release_ref}


def import_platform_metrics(
    storage: LocalStorage,
    *,
    platform_id: str,
    chapter_metrics: list[dict[str, Any]],
    book_metrics: dict[str, Any] | None = None,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="import-platform-metrics",
        project_id=str((envelope or {}).get("project_id") or ""),
        task_type="platform_metrics",
        asset_type="platform_metric_snapshot",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    snapshot = PlatformMetricSnapshot(
        title=f"{platform_id} metric snapshot",
        tags=["publishing-feedback-adapter", "metrics", platform_id],
        content={
            "snapshot_id": make_id("platform_metric_snapshot", platform_id),
            "platform_id": platform_id,
            "chapter_metrics": chapter_metrics,
            "book_metrics": book_metrics or {},
            "collected_at": utc_now(),
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
    )
    snapshot_path = _write_asset(storage, snapshot)
    dropoff = ChapterDropoffReport(
        title=f"{platform_id} chapter dropoff report",
        source=snapshot.id,
        tags=["publishing-feedback-adapter", "dropoff"],
        content={
            "report_id": make_id("chapter_dropoff_report", snapshot.id),
            "platform_metric_snapshot_id": snapshot.content["snapshot_id"],
            "dropoff_points": _dropoff_points(chapter_metrics),
            "risk_level": _dropoff_risk(chapter_metrics),
            "recommendations": ["Inspect chapter hooks before high dropoff points", "Compare reader comments for matching pain points"],
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[snapshot_path],
    )
    dropoff_path = _write_asset(storage, dropoff)
    return {"snapshot_path": snapshot_path, "dropoff_report_path": dropoff_path, "asset": storage.read_json(resolve_path(storage.root, snapshot_path)), "envelope": env}


def cluster_platform_comments(
    storage: LocalStorage,
    *,
    platform_id: str,
    comments: list[dict[str, Any]],
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    persist_issues: bool = False,
) -> dict[str, Any]:
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="cluster-platform-comments",
        project_id=str((envelope or {}).get("project_id") or ""),
        task_type="comment_cluster",
        asset_type="comment_cluster_report",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    batch = PlatformCommentBatch(
        title=f"{platform_id} comment batch",
        tags=["publishing-feedback-adapter", "comments", platform_id],
        content={
            "batch_id": make_id("platform_comment_batch", platform_id),
            "platform_id": platform_id,
            "comments": comments,
            "imported_at": utc_now(),
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
    )
    batch_path = _write_asset(storage, batch)
    clusters = _cluster_comments(comments)
    report = CommentClusterReport(
        title=f"{platform_id} comment cluster report",
        source=batch.id,
        tags=["publishing-feedback-adapter", "comment-cluster"],
        content={
            "report_id": make_id("comment_cluster_report", batch.id),
            "source_comment_batch_id": batch.content["batch_id"],
            "clusters": clusters,
            "pain_points": clusters.get("pain_points", []),
            "pleasure_points": clusters.get("pleasure_points", []),
            "character_heat": clusters.get("character_heat", []),
            "dropoff_reasons": clusters.get("dropoff_reasons", []),
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[batch_path],
    )
    report_path = _write_asset(storage, report)
    issue_paths = []
    if persist_issues and clusters.get("pain_points"):
        issue_paths = persist_issue_candidates(
            storage,
            [
                {
                    "issue_type": "feedback_mutation_risk",
                    "severity": "medium",
                    "blocking": False,
                    "target_asset_id": report.id,
                    "target_asset_type": "comment_cluster_report",
                    "target_asset_path": report_path,
                    "project_id": str(env.get("project_id") or ""),
                    "message": f"reader pain points detected: {', '.join(clusters.get('pain_points', [])[:3])}",
                    "fix_suggestion": "Create a human-gated mutation proposal; do not mutate outline silently.",
                    "evidence_refs": [report_path],
                }
            ],
            source_system="publishing_feedback.comment_cluster",
        ).get("issue_paths", [])
    return {"batch_path": batch_path, "report_path": report_path, "asset": storage.read_json(resolve_path(storage.root, report_path)), "review_issues": issue_paths, "envelope": env}


def create_feedback_mutation_proposal(
    storage: LocalStorage,
    *,
    source_feedback_paths: list[str | Path],
    target_assets: list[dict[str, Any]],
    proposed_changes: list[dict[str, Any]],
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not source_feedback_paths:
        raise ValueError("source_feedback_paths is required")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="create-feedback-mutation-proposal",
        project_id=str((envelope or {}).get("project_id") or ""),
        task_type="feedback_mutation",
        asset_type="feedback_plan_mutation_proposal",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    proposal = FeedbackPlanMutationProposal(
        title="Human-gated feedback mutation proposal",
        tags=["publishing-feedback-adapter", "mutation-proposal", "human-gated"],
        content={
            "proposal_id": make_id("feedback_plan_mutation_proposal", ",".join(str(path) for path in source_feedback_paths)),
            "source_feedback_paths": [str(path) for path in source_feedback_paths],
            "target_assets": target_assets,
            "proposed_changes": proposed_changes,
            "risk_assessment": {
                "silent_mutation_allowed": False,
                "requires_human_approval": True,
                "affected_domains": _affected_domains(target_assets, proposed_changes),
            },
            "human_gate": {"required": True, "status": "pending", "approved_by": "", "decided_at": ""},
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[str(path) for path in source_feedback_paths],
    )
    path = _write_asset(storage, proposal)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env}


def resolve_feedback_mutation_proposal(
    storage: LocalStorage,
    *,
    proposal_ref: str | Path,
    approved: bool,
    actor: str = "operator",
    decision_note: str = "",
    create_application_chain: bool = True,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposal_path = _resolve_feedback_proposal(storage, proposal_ref)
    proposal = storage.read_json(proposal_path)
    if proposal.get("type") != "feedback_plan_mutation_proposal":
        raise ValueError("proposal_ref must point to a feedback_plan_mutation_proposal")
    content = proposal.get("content", {}) if isinstance(proposal.get("content", {}), dict) else {}
    metadata = proposal.get("metadata", {}) if isinstance(proposal.get("metadata", {}), dict) else {}
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="resolve-feedback-mutation-proposal",
        project_id=str(metadata.get("project_id") or (envelope or {}).get("project_id") or ""),
        task_type="feedback_mutation_resolution",
        asset_type="feedback_plan_mutation_proposal",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    human_gate = content.get("human_gate", {}) if isinstance(content.get("human_gate", {}), dict) else {}
    human_gate.update(
        {
            "required": True,
            "status": "approved" if approved else "rejected",
            "approved_by": actor if approved else "",
            "rejected_by": "" if approved else actor,
            "decided_at": utc_now(),
            "decision_note": decision_note,
        }
    )
    updated_content = {
        **content,
        "proposal_id": make_id("feedback_plan_mutation_proposal", f"{content.get('proposal_id', proposal.get('id', 'proposal'))}:resolution:{utc_now()}"),
        "supersedes_proposal_id": content.get("proposal_id", proposal.get("id", "")),
        "source_proposal_path": _display_path(storage.root, proposal_path),
        "human_gate": human_gate,
        "application_status": "planned" if approved and create_application_chain else "rejected" if not approved else "approved_waiting_application_plan",
    }
    if approved and create_application_chain:
        updated_content["application_chain"] = _feedback_application_chain(updated_content)
    resolved = FeedbackPlanMutationProposal(
        title=f"Resolved {proposal.get('title') or 'feedback mutation proposal'}",
        source=str(proposal.get("id") or ""),
        tags=["publishing-feedback-adapter", "mutation-proposal", "human-gated", "approved" if approved else "rejected"],
        content=updated_content,
        metadata={
            **metadata,
            "project_id": str(metadata.get("project_id") or env.get("project_id") or ""),
            "feedback_resolution_status": human_gate["status"],
            **envelope_asset_metadata(env),
        },
        references=_dedupe([_display_path(storage.root, proposal_path), *[str(path) for path in proposal.get("references", []) if str(path).strip()]]),
    )
    path = _write_asset(storage, resolved)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env}


def _book_metadata_from_release(release: dict[str, Any]) -> dict[str, Any]:
    content = release.get("content", {}) if isinstance(release.get("content"), dict) else {}
    return {
        "title": content.get("title") or release.get("title") or "Untitled",
        "synopsis": content.get("synopsis") or content.get("summary") or "",
        "tags": content.get("tags", []),
        "cover_status": "not_required",
    }


def _chapter_payloads_from_release(release: dict[str, Any]) -> list[dict[str, Any]]:
    content = release.get("content", {}) if isinstance(release.get("content"), dict) else {}
    chapters = content.get("chapters", []) if isinstance(content.get("chapters", []), list) else []
    if chapters:
        return [{"title": str(row.get("title") or f"Chapter {index + 1}"), "body": str(row.get("body") or row.get("text") or "")} for index, row in enumerate(chapters) if isinstance(row, dict)]
    body = str(content.get("body") or content.get("text") or "")
    return [{"title": str(content.get("chapter_title") or "Chapter 1"), "body": body}] if body else []


def _blocking_reasons(status: str, receipt: dict[str, Any]) -> list[str]:
    if status in {"rejected", "blocked", "failed"}:
        reasons = receipt.get("reasons", []) if isinstance(receipt.get("reasons", []), list) else []
        return [str(item) for item in reasons] or ["platform review status blocks publishing"]
    return []


def _dropoff_points(chapter_metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points = []
    previous_retention: float | None = None
    for row in chapter_metrics:
        retention = _float(row.get("retention") or row.get("completion_rate") or row.get("read_through"))
        chapter = row.get("chapter_no") or row.get("chapter") or ""
        if previous_retention is not None and previous_retention - retention >= 0.15:
            points.append({"chapter_no": chapter, "previous_retention": previous_retention, "retention": retention, "drop": round(previous_retention - retention, 3)})
        previous_retention = retention
    return points


def _dropoff_risk(chapter_metrics: list[dict[str, Any]]) -> str:
    points = _dropoff_points(chapter_metrics)
    if len(points) >= 3:
        return "high"
    if points:
        return "medium"
    return "low"


def _feedback_application_chain(content: dict[str, Any]) -> dict[str, Any]:
    target_assets = content.get("target_assets", []) if isinstance(content.get("target_assets", []), list) else []
    proposed_changes = content.get("proposed_changes", []) if isinstance(content.get("proposed_changes", []), list) else []
    domains = _affected_domains(target_assets, proposed_changes)
    patch_plan = {
        "outline_patch": _patch_step("outline", target_assets, proposed_changes),
        "chapter_plan_patch": _patch_step("chapter_plan", target_assets, proposed_changes),
        "style_policy_update": _patch_step("style", target_assets, proposed_changes),
        "genre_strategy_update": _patch_step("genre", target_assets, proposed_changes),
        "mkaos_weight_governance": _patch_step("mkaos", target_assets, proposed_changes),
    }
    return {
        "status": "planned",
        "human_approved": True,
        "silent_mutation_allowed": False,
        "patch_plan": patch_plan,
        "impact_analysis": {
            "affected_domains": domains,
            "target_asset_count": len(target_assets),
            "requires_downstream_invalidation": True,
            "requires_re_review": True,
            "risk_level": "high" if any(domain in {"outline", "chapter_plan", "genre", "style"} for domain in domains) else "medium",
        },
        "downstream_invalidation": {
            "apply": False,
            "status": "needs_workflow_execution",
            "targets": _dedupe([str(row.get("path") or row.get("asset_id") or row.get("asset_type") or "") for row in target_assets if isinstance(row, dict)]),
            "invalidate_asset_types": ["outline", "chapter_plan", "draft_chapter", "review_report", "release_package"],
        },
        "regeneration_task": {
            "status": "planned",
            "task_type": "regenerate_after_feedback_mutation",
            "requires_review_issue_link": True,
            "requires_revision_task": True,
            "requires_re_review": True,
            "requires_publish_gate_rerun": True,
        },
    }


def _patch_step(domain: str, target_assets: list[dict[str, Any]], proposed_changes: list[dict[str, Any]]) -> dict[str, Any]:
    changes = [row for row in proposed_changes if isinstance(row, dict) and str(row.get("domain") or row.get("target_domain") or "").lower() in {domain, domain.replace("_", "-")}]
    targets = [row for row in target_assets if isinstance(row, dict) and str(row.get("asset_type") or row.get("domain") or "").lower() in {domain, domain.replace("_", "-")}]
    return {
        "status": "needs_review" if changes or targets else "not_applicable",
        "domain": domain,
        "target_assets": targets,
        "proposed_changes": changes,
        "apply_mode": "human_gated_workflow_only",
    }


def _cluster_comments(comments: list[dict[str, Any]]) -> dict[str, list[Any]]:
    pain_markers = ["毒", "水", "崩", "看不懂", "弃", "无聊", "慢"]
    pleasure_markers = ["爽", "好看", "刺激", "期待", "喜欢", "反转"]
    dropoff_markers = ["弃书", "不追", "太慢", "看不下去"]
    pain: list[str] = []
    pleasure: list[str] = []
    dropoff: list[str] = []
    heat: dict[str, int] = {}
    for comment in comments:
        text = str(comment.get("text") or comment.get("comment") or "")
        if any(marker in text for marker in pain_markers):
            pain.append(text)
        if any(marker in text for marker in pleasure_markers):
            pleasure.append(text)
        if any(marker in text for marker in dropoff_markers):
            dropoff.append(text)
        for role in comment.get("characters", []) if isinstance(comment.get("characters", []), list) else []:
            heat[str(role)] = heat.get(str(role), 0) + 1
    return {
        "pain_points": pain[:20],
        "pleasure_points": pleasure[:20],
        "character_heat": [{"character": key, "mentions": value} for key, value in sorted(heat.items(), key=lambda item: item[1], reverse=True)],
        "dropoff_reasons": dropoff[:20],
        "clusters": [
            {"name": "toxic_points", "count": len(pain)},
            {"name": "pleasure_points", "count": len(pleasure)},
            {"name": "dropoff_reasons", "count": len(dropoff)},
        ],
    }


def _affected_domains(target_assets: list[dict[str, Any]], proposed_changes: list[dict[str, Any]]) -> list[str]:
    domains = []
    for row in [*target_assets, *proposed_changes]:
        value = str(row.get("domain") or row.get("asset_type") or row.get("target") or "").strip()
        if value:
            domains.append(value)
    return sorted(set(domains))


def _resolve_feedback_proposal(storage: LocalStorage, proposal_ref: str | Path) -> Path:
    direct = resolve_path(storage.root, proposal_ref)
    if direct.exists():
        return direct
    ref = str(proposal_ref)
    for path in reversed(storage.list_json("feedback")):
        data = storage.read_json(path)
        if data.get("type") != "feedback_plan_mutation_proposal":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if ref in {str(data.get("id", "")), str(content.get("proposal_id", "")), _display_path(storage.root, path)}:
            return path
    raise FileNotFoundError(f"feedback mutation proposal not found: {proposal_ref}")


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _platform_client_from_config(config: dict[str, Any]) -> HttpPlatformClient | None:
    endpoint = str(config.get("endpoint") or "").strip()
    if not endpoint:
        return None
    return HttpPlatformClient(
        endpoint=endpoint,
        token_env=str(config.get("token_env") or ""),
        timeout_seconds=_float(config.get("timeout_seconds") or 20.0),
    )


def _endpoint_evidence(endpoint: str) -> dict[str, str]:
    parsed = urlparse(endpoint)
    return {"scheme": parsed.scheme, "host": parsed.netloc, "path": parsed.path}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[redacted]" if str(key).lower() in SENSITIVE_KEYS else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
