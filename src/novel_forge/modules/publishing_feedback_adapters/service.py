from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib import request
from urllib.parse import urlparse

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.change_impact import mark_downstream_assets_stale
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment
from novel_forge.modules.review_issue import persist_issue_candidates
from novel_forge.modules.publishing_feedback_adapters.fallbacks import record_platform_publish_failure
from novel_forge.schemas import (
    AgentTask,
    ChapterDropoffReport,
    CommentClusterReport,
    FeedbackMutationApplicationReport,
    FeedbackMutationPatch,
    FeedbackPlanMutationProposal,
    PlatformCommentBatch,
    PlatformMetricSnapshot,
    PlatformPublishReceipt,
    PlatformPublishAdapter,
    PlatformReviewStatus,
    PlatformUploadPackage,
    RevisionTask,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token", "access_token", "refresh_token"}

PLATFORM_UPLOAD_PROFILES = {
    "fanqie": {
        "display_name": "番茄小说",
        "rules_version": "fanqie-manual-2026-07",
        "package_shape": "book_metadata_plus_chapter_text",
        "platform_rules": {
            "rule_source": "manual_profile_not_official_sdk",
            "title_max_chars": 30,
            "synopsis_min_chars": 80,
            "chapter_body_min_chars": 800,
            "chapter_body_max_chars": 6000,
            "sensitive_check_required": True,
            "formatting": ["no_nul_bytes", "normalize_line_endings", "chapter_title_required"],
        },
        "review_status_map": {
            "审核中": "reviewing",
            "待审核": "submitted",
            "已通过": "approved",
            "通过": "approved",
            "已发布": "published",
            "已退回": "rejected",
            "退回": "rejected",
            "拒绝": "rejected",
            "失败": "failed",
        },
        "manual_upload_steps": [
            "Open Fanqie author console and select the target book.",
            "Paste title, synopsis, tags, and chapter body from this package.",
            "Run sensitive-word and formatting checks before submit.",
            "Record Fanqie receipt/status after submission.",
        ],
        "checklist": ["title_present", "synopsis_present", "chapter_title_present", "chapter_body_present", "sensitive_word_checked", "format_checked", "cover_checked"],
        "receipt_fields": ["book_id", "chapter_id", "review_status", "submitted_at"],
        "receipt_parser": {
            "book_id_labels": ["作品ID", "书籍ID", "book_id", "platform_book_id"],
            "chapter_id_labels": ["章节ID", "chapter_id", "platform_chapter_id"],
            "status_labels": ["审核状态", "状态", "review_status", "status"],
            "submitted_at_labels": ["提交时间", "submitted_at"],
        },
        "review_risk_gate": ["sensitive_terms", "chapter_length", "duplicate_title", "formatting"],
    },
    "qidian": {
        "display_name": "起点中文网",
        "rules_version": "qidian-manual-2026-07",
        "package_shape": "volume_chapter_package",
        "platform_rules": {
            "rule_source": "manual_profile_not_official_sdk",
            "title_max_chars": 30,
            "synopsis_min_chars": 80,
            "chapter_body_min_chars": 600,
            "chapter_body_max_chars": 8000,
            "volume_required": True,
            "sensitive_check_required": True,
            "formatting": ["volume_title_required", "chapter_sequence_required", "chapter_title_required"],
        },
        "review_status_map": {
            "审核中": "reviewing",
            "待审核": "submitted",
            "已通过": "approved",
            "通过": "approved",
            "已发布": "published",
            "已退回": "rejected",
            "退回": "rejected",
            "驳回": "rejected",
            "拒绝": "rejected",
            "失败": "failed",
        },
        "manual_upload_steps": [
            "Open Qidian writer console and select volume/chapter editor.",
            "Confirm volume title and chapter sequence before pasting.",
            "Run formatting, sensitive-word, and title checks.",
            "Record Qidian receipt/status after submission.",
        ],
        "checklist": ["title_present", "synopsis_present", "volume_present", "chapter_title_present", "chapter_body_present", "sensitive_word_checked", "format_checked"],
        "receipt_fields": ["book_id", "volume_id", "chapter_id", "review_status", "submitted_at"],
        "receipt_parser": {
            "book_id_labels": ["作品号", "作品ID", "书籍ID", "book_id", "platform_book_id"],
            "volume_id_labels": ["卷号", "分卷ID", "volume_id"],
            "chapter_id_labels": ["章节号", "章节ID", "chapter_id", "platform_chapter_id"],
            "status_labels": ["审核状态", "状态", "review_status", "status"],
            "submitted_at_labels": ["提交时间", "submitted_at"],
        },
        "review_risk_gate": ["volume_sequence", "chapter_title", "sensitive_terms", "formatting"],
    },
}


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
    profile = _platform_upload_profile(platform_id)
    chapter_format = _chapter_format_report(chapters, profile)
    checklist = _platform_upload_checklist(metadata, chapters, profile, chapter_format=chapter_format)
    project_id = str(release.get("metadata", {}).get("project_id") or env.get("project_id") or "")
    publish_adapter = _platform_manual_publish_adapter(profile, project_id=project_id)
    publish_adapter_path = _write_asset(storage, publish_adapter)
    platform_rule_snapshot = _platform_rule_snapshot(profile)
    asset = PlatformUploadPackage(
        title=f"{profile['display_name']} manual upload package",
        source=str(release.get("id") or ""),
        tags=["publishing-feedback-adapter", "manual-upload", platform_id],
        content={
            "package_id": make_id("platform_upload_package", f"{platform_id}-{release.get('id', '')}"),
            "platform_id": platform_id,
            "platform_profile": profile,
            "release_package_path": _display_path(storage.root, release_path),
            "book_metadata": metadata,
            "chapter_payloads": chapters,
            "manual_upload_steps": profile["manual_upload_steps"],
            "checklist": checklist,
            "chapter_format_report": chapter_format,
            "platform_rule_snapshot": platform_rule_snapshot,
            "platform_publish_adapter_path": publish_adapter_path,
            "platform_package_sections": _platform_package_sections(metadata, chapters, profile, chapter_format=chapter_format),
            "feedback_import_contract": _feedback_import_contract(profile),
            "manual_adapter_contract": _manual_adapter_contract(profile),
            "status": "manual_ready",
        },
        metadata={"project_id": project_id, **envelope_asset_metadata(env)},
        references=[_display_path(storage.root, release_path), publish_adapter_path],
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env}


def fanqie_manual_adapter(
    storage: LocalStorage,
    *,
    release_package_path: str | Path,
    book_metadata: dict[str, Any] | None = None,
    chapter_payloads: list[dict[str, Any]] | None = None,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_platform_upload_package(
        storage,
        release_package_path=release_package_path,
        platform_id="fanqie",
        book_metadata=book_metadata,
        chapter_payloads=chapter_payloads,
        environment=environment,
        envelope=envelope,
    )


def qidian_manual_adapter(
    storage: LocalStorage,
    *,
    release_package_path: str | Path,
    book_metadata: dict[str, Any] | None = None,
    chapter_payloads: list[dict[str, Any]] | None = None,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_platform_upload_package(
        storage,
        release_package_path=release_package_path,
        platform_id="qidian",
        book_metadata=book_metadata,
        chapter_payloads=chapter_payloads,
        environment=environment,
        envelope=envelope,
    )


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
    profile = _platform_upload_profile(platform_id)
    parsed_receipt = _normalize_receipt_fields(platform_id, receipt_raw or {})
    redacted_receipt_raw = _redact(receipt_raw or {})
    normalized_status = _normalize_review_status(platform_id, review_status or str(parsed_receipt.get("review_status") or "submitted"))
    status_contract = _platform_review_status_contract(profile, normalized_status, {**redacted_receipt_raw, "reasons": parsed_receipt.get("reasons", [])})
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
        title=f"{platform_id} receipt {platform_book_id or parsed_receipt.get('book_id', '')}",
        source=upload_package_path,
        tags=["publishing-feedback-adapter", "receipt", normalized_status],
        content={
            "receipt_id": make_id("platform_publish_receipt", f"{platform_id}-{platform_book_id or parsed_receipt.get('book_id', '')}-{platform_chapter_id or parsed_receipt.get('chapter_id', '')}"),
            "platform_id": platform_id,
            "platform_book_id": platform_book_id or str(parsed_receipt.get("book_id") or ""),
            "platform_chapter_id": platform_chapter_id or str(parsed_receipt.get("chapter_id") or "book-level"),
            "submitted_at": utc_now(),
            "review_status": normalized_status,
            "receipt_raw": redacted_receipt_raw,
            "parsed_receipt": parsed_receipt,
            "receipt_parser": {
                "platform_id": profile.get("platform_id"),
                "rules_version": profile.get("rules_version"),
                "parsed_fields": parsed_receipt,
                "required_fields": profile.get("receipt_fields", []),
                "missing_required_fields": _missing_receipt_fields(profile, parsed_receipt),
                "parser_confidence": _receipt_parser_confidence(profile, parsed_receipt, receipt_text=str((receipt_raw or {}).get("receipt_text") or "")),
                "redaction_applied": redacted_receipt_raw != (receipt_raw or {}),
            },
            "status_contract": status_contract,
            "operator_note": operator_note or "manual receipt recorded",
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[upload_package_path] if upload_package_path else [],
    )
    receipt_path = _write_asset(storage, receipt)
    status = PlatformReviewStatus(
        title=f"{platform_id} review status {normalized_status}",
        source=receipt.id,
        tags=["publishing-feedback-adapter", "review-status", normalized_status],
        content={
            "status_id": make_id("platform_review_status", receipt.id),
            "platform_id": platform_id,
            "receipt_id": receipt.content["receipt_id"],
            "review_status": normalized_status,
            "status_contract": status_contract,
            "blocking_reasons": _blocking_reasons(normalized_status, {**redacted_receipt_raw, "reasons": parsed_receipt.get("reasons", [])}),
            "updated_at": utc_now(),
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[receipt_path],
    )
    status_path = _write_asset(storage, status)
    return {"receipt_path": receipt_path, "status_path": status_path, "asset": storage.read_json(resolve_path(storage.root, receipt_path)), "envelope": env}


def parse_platform_receipt(
    storage: LocalStorage,
    *,
    platform_id: str,
    receipt_text: str = "",
    receipt_raw: dict[str, Any] | None = None,
    operator_note: str = "",
    upload_package_path: str = "",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = _parse_platform_receipt_payload(platform_id, receipt_text=receipt_text, receipt_raw=receipt_raw or {})
    receipt = record_platform_receipt(
        storage,
        platform_id=platform_id,
        platform_book_id=str(parsed.get("book_id") or ""),
        platform_chapter_id=str(parsed.get("chapter_id") or ""),
        review_status=str(parsed.get("review_status") or "submitted"),
        receipt_raw={
            **(receipt_raw or {}),
            "receipt_text": receipt_text,
            "parsed_fields": parsed,
            "volume_id": parsed.get("volume_id", ""),
            "reasons": parsed.get("reasons", []),
        },
        operator_note=operator_note or "parsed from platform receipt text",
        upload_package_path=upload_package_path,
        environment=environment,
        envelope=envelope,
    )
    asset = receipt["asset"]
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    content["receipt_parser"] = {
        **content.get("receipt_parser", {}),
        "receipt_text_present": bool(receipt_text.strip()),
        "parser_mode": "platform_specific_text_or_json",
        "parsed_fields": parsed,
        "parser_confidence": _receipt_parser_confidence(_platform_upload_profile(platform_id), parsed, receipt_text=receipt_text),
        "missing_required_fields": _missing_receipt_fields(_platform_upload_profile(platform_id), parsed),
    }
    asset["content"] = content
    storage.write_json(resolve_path(storage.root, receipt["receipt_path"]), asset)
    return {**receipt, "asset": asset, "parsed_receipt": parsed}


def run_platform_adapter_gate(
    storage: LocalStorage,
    *,
    upload_package_path: str | Path,
    platform_id: str = "",
    receipt_path: str | Path = "",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    upload_file = resolve_path(storage.root, upload_package_path)
    upload = storage.read_json(upload_file)
    if upload.get("type") != "platform_upload_package":
        raise ValueError("upload_package_path must point to a platform_upload_package")
    content = upload.get("content", {}) if isinstance(upload.get("content", {}), dict) else {}
    resolved_platform_id = platform_id or str(content.get("platform_id") or "manual")
    profile = _platform_upload_profile(resolved_platform_id)
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="run-platform-adapter-gate",
        project_id=str(upload.get("metadata", {}).get("project_id") or (envelope or {}).get("project_id") or ""),
        task_type="platform_adapter_gate",
        asset_type="platform_review_status",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    checklist = content.get("checklist", {}) if isinstance(content.get("checklist", {}), dict) else {}
    chapter_format = content.get("chapter_format_report", {}) if isinstance(content.get("chapter_format_report", {}), dict) else {}
    rule_snapshot = content.get("platform_rule_snapshot", {}) if isinstance(content.get("platform_rule_snapshot", {}), dict) else {}
    missing_checklist = [str(key) for key, passed in checklist.items() if not passed]
    blocking_reasons = [f"missing_checklist:{key}" for key in missing_checklist]
    if profile.get("specific_adapter") and not rule_snapshot:
        blocking_reasons.append("platform_rule_snapshot:missing")
    if rule_snapshot and str(rule_snapshot.get("rules_version") or "") != str(profile.get("rules_version") or ""):
        blocking_reasons.append("platform_rule_snapshot:rules_version_mismatch")
    if profile.get("specific_adapter") and not str(content.get("platform_publish_adapter_path") or "").strip():
        blocking_reasons.append("platform_publish_adapter_path:missing")
    if chapter_format.get("status") == "blocked":
        blocking_reasons.append("chapter_format_report:blocking")
    receipt_status = ""
    receipt_id = str(content.get("package_id") or upload.get("id") or "")
    receipt_ref = ""
    if receipt_path:
        receipt_file = resolve_path(storage.root, receipt_path)
        receipt = storage.read_json(receipt_file)
        receipt_content = receipt.get("content", {}) if isinstance(receipt.get("content", {}), dict) else {}
        receipt_status = str(receipt_content.get("review_status") or "")
        receipt_id = str(receipt_content.get("receipt_id") or receipt.get("id") or receipt_id)
        receipt_ref = _display_path(storage.root, receipt_file)
        if receipt_status in {"rejected", "blocked", "failed"}:
            blocking_reasons.append(f"platform_review_status:{receipt_status}")
    review_status = "blocked" if blocking_reasons else "ready" if not receipt_status else _normalize_review_status(resolved_platform_id, receipt_status)
    gate_contract = {
        "platform_id": profile["platform_id"],
        "specific_adapter": bool(profile.get("specific_adapter")),
        "api_mode": profile.get("api_mode", "manual_first"),
        "rules_version": str(profile.get("rules_version") or ""),
        "package_shape": str(profile.get("package_shape") or ""),
        "platform_rule_snapshot": rule_snapshot,
        "platform_publish_adapter_path": str(content.get("platform_publish_adapter_path") or ""),
        "checklist": checklist,
        "missing_checklist": missing_checklist,
        "chapter_format_report": chapter_format,
        "receipt_status": receipt_status,
        "blocking": bool(blocking_reasons),
        "blocking_reasons": blocking_reasons,
        "manual_operator_required": True,
        "supports_auto_publish": False,
        "next_actions": ["fix_upload_package_and_rerun_gate"] if blocking_reasons else ["manual_submit_or_record_receipt"],
    }
    status = PlatformReviewStatus(
        title=f"{profile['display_name']} adapter gate {review_status}",
        source=str(upload.get("id") or ""),
        tags=["publishing-feedback-adapter", "platform-adapter-gate", profile["platform_id"], review_status],
        content={
            "status_id": make_id("platform_review_status", f"{profile['platform_id']}-{receipt_id}-adapter-gate"),
            "platform_id": profile["platform_id"],
            "receipt_id": receipt_id,
            "review_status": review_status,
            "blocking_reasons": blocking_reasons,
            "adapter_gate": gate_contract,
            "updated_at": utc_now(),
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=_dedupe([_display_path(storage.root, upload_file), receipt_ref]),
    )
    path = _write_asset(storage, status)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "status": review_status, "blocking": bool(blocking_reasons), "envelope": env}


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
            "embedding_clusters": clusters.get("embedding_clusters", []),
            "embedding_mode": clusters.get("embedding_mode", "not_available"),
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
            "human_gate": {"required": True, "status": "pending", "approved_by": "", "decided_at": "", "approval_request_path": "", "approval_request_id": ""},
        },
        metadata={"project_id": str(env.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=[str(path) for path in source_feedback_paths],
    )
    path = _write_asset(storage, proposal)
    approval = _create_feedback_mutation_approval_request(
        storage,
        proposal_path=path,
        source_feedback_paths=[str(item) for item in source_feedback_paths],
        target_assets=target_assets,
        project_id=str(env.get("project_id") or ""),
        environment=str(env.get("environment") or environment or "local"),
    )
    asset = storage.read_json(resolve_path(storage.root, path))
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    human_gate = content.get("human_gate", {}) if isinstance(content.get("human_gate", {}), dict) else {}
    human_gate.update(
        {
            "approval_request_path": approval["path"],
            "approval_request_id": approval["asset"]["content"]["request_id"],
            "permission_center_scope": "feedback",
        }
    )
    risk = content.get("risk_assessment", {}) if isinstance(content.get("risk_assessment", {}), dict) else {}
    risk.update({"approval_request_path": approval["path"], "approval_request_id": approval["asset"]["content"]["request_id"]})
    content["human_gate"] = human_gate
    content["risk_assessment"] = risk
    asset["content"] = content
    storage.write_json(resolve_path(storage.root, path), asset)
    return {"path": path, "asset": asset, "envelope": env, "approval_request": approval}


def resolve_feedback_mutation_proposal(
    storage: LocalStorage,
    *,
    proposal_ref: str | Path,
    approved: bool,
    actor: str = "operator",
    decision_note: str = "",
    create_application_chain: bool = True,
    auto_apply_application_chain: bool = True,
    auto_apply_invalidation: bool = True,
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
    application_result: dict[str, Any] = {}
    if approved and create_application_chain and auto_apply_application_chain:
        application_result = apply_feedback_mutation_application_chain(
            storage,
            proposal_ref=path,
            apply_invalidation=auto_apply_invalidation,
            actor=actor,
            environment=str(env.get("environment") or environment or ""),
            envelope=env,
        )
        _attach_auto_application_result(storage, path, application_result)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env, "application_result": application_result}


def _create_feedback_mutation_approval_request(
    storage: LocalStorage,
    *,
    proposal_path: str,
    source_feedback_paths: list[str],
    target_assets: list[dict[str, Any]],
    project_id: str,
    environment: str,
) -> dict[str, Any]:
    from novel_forge.modules.permission_center import create_approval_request

    effective_project_id = project_id or "feedback-mutation"
    target_refs = _dedupe([proposal_path, *[str(item.get("path", "")) for item in target_assets if isinstance(item, dict)]])
    return create_approval_request(
        storage,
        {
            "project_id": effective_project_id,
            "scope": "feedback",
            "action": "approve_feedback_mutation_proposal",
            "risk_level": "high",
            "environment": environment or "local",
            "blocking": True,
            "target_type": "feedback_plan_mutation_proposal",
            "target_id": proposal_path,
            "target_refs": target_refs,
            "evidence_refs": _dedupe([proposal_path, *source_feedback_paths]),
            "requested_by": "publishing-feedback-adapter",
            "subject_type": "agent",
            "subject_id": "feedback-agent",
            "reason": "feedback mutation can alter outline, chapter plan, style, genre, or release path and must be operator-approved",
            "required_before": ["feedback_mutation_resolution", "patch_generation", "downstream_invalidation", "regeneration_task"],
            "rollback_plan": {
                "automatic_story_asset_mutation": False,
                "rollback_action": "do not resolve or apply feedback mutation until approval request is approved",
                "proposal_path": proposal_path,
            },
        },
    )


def apply_feedback_mutation_application_chain(
    storage: LocalStorage,
    *,
    proposal_ref: str | Path,
    apply_invalidation: bool = True,
    actor: str = "workflow",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposal_path = _resolve_feedback_proposal(storage, proposal_ref)
    proposal = storage.read_json(proposal_path)
    content = proposal.get("content", {}) if isinstance(proposal.get("content", {}), dict) else {}
    metadata = proposal.get("metadata", {}) if isinstance(proposal.get("metadata", {}), dict) else {}
    human_gate = content.get("human_gate", {}) if isinstance(content.get("human_gate", {}), dict) else {}
    if human_gate.get("status") != "approved":
        raise ValueError("feedback mutation application requires approved human_gate")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="apply-feedback-mutation-application-chain",
        project_id=str(metadata.get("project_id") or (envelope or {}).get("project_id") or ""),
        task_type="feedback_mutation_application",
        asset_type="feedback_mutation_application_report",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    chain = content.get("application_chain", {}) if isinstance(content.get("application_chain", {}), dict) else _feedback_application_chain(content)
    target_assets = content.get("target_assets", []) if isinstance(content.get("target_assets", []), list) else []
    proposed_changes = content.get("proposed_changes", []) if isinstance(content.get("proposed_changes", []), list) else []
    invalidations = _apply_feedback_invalidations(storage, target_assets, project_id=str(env.get("project_id") or metadata.get("project_id") or ""), apply_invalidation=apply_invalidation)
    patch_artifacts = _write_feedback_patch_assets(
        storage,
        proposal_id=str(content.get("proposal_id") or proposal.get("id") or ""),
        patch_plan=chain.get("patch_plan", {}) if isinstance(chain.get("patch_plan", {}), dict) else {},
        project_id=str(env.get("project_id") or metadata.get("project_id") or ""),
        envelope=env,
    )
    regeneration_tasks = _write_feedback_regeneration_tasks(
        storage,
        proposal_id=str(content.get("proposal_id") or proposal.get("id") or ""),
        target_assets=target_assets,
        proposed_changes=proposed_changes,
        project_id=str(env.get("project_id") or metadata.get("project_id") or ""),
        envelope=env,
    )
    agent_task_plans = _write_feedback_agent_task_plans(
        storage,
        proposal_id=str(content.get("proposal_id") or proposal.get("id") or ""),
        proposal_path=_display_path(storage.root, proposal_path),
        patch_artifacts=patch_artifacts,
        invalidations=invalidations,
        regeneration_tasks=regeneration_tasks,
        project_id=str(env.get("project_id") or metadata.get("project_id") or ""),
        envelope=env,
    )
    workflow_dispatch_plan = _feedback_workflow_dispatch_plan(
        patch_artifacts=patch_artifacts,
        invalidations=invalidations,
        regeneration_tasks=regeneration_tasks,
        agent_task_plans=agent_task_plans,
    )
    status = "applied" if apply_invalidation else "planned"
    report = FeedbackMutationApplicationReport(
        title="Feedback mutation application chain",
        source=str(proposal.get("id") or ""),
        tags=["publishing-feedback-adapter", "mutation-application", status],
        content={
            "application_id": make_id("feedback_mutation_application_report", f"{content.get('proposal_id', proposal.get('id', 'proposal'))}-{utc_now()}"),
            "proposal_id": str(content.get("proposal_id") or proposal.get("id") or ""),
            "source_proposal_path": _display_path(storage.root, proposal_path),
            "status": status,
            "actor": actor,
            "patch_plan": chain.get("patch_plan", {}),
            "patch_artifacts": patch_artifacts,
            "impact_analysis": chain.get("impact_analysis", {}),
            "invalidation_results": invalidations,
            "regeneration_tasks": regeneration_tasks,
            "agent_task_plans": agent_task_plans,
            "workflow_dispatch_plan": workflow_dispatch_plan,
            "re_review_gate_plan": _feedback_re_review_gate_plan(patch_artifacts, regeneration_tasks, agent_task_plans),
            "publish_gate_rerun_plan": _feedback_publish_gate_rerun_plan(patch_artifacts, invalidations, regeneration_tasks, agent_task_plans),
            "approval_evidence": {
                "actor": actor,
                "human_gate": human_gate,
                "source_proposal_path": _display_path(storage.root, proposal_path),
            },
            "re_review_required": True,
            "publish_gate_rerun_required": True,
            "silent_mutation_allowed": False,
            "mutation_control_contract": {
                "patch_review_required": True,
                "automatic_story_asset_mutation": False,
                "direct_outline_mutation": False,
                "direct_chapter_plan_mutation": False,
                "direct_release_package_mutation": False,
            },
            "created_at": utc_now(),
        },
        metadata={"project_id": str(env.get("project_id") or metadata.get("project_id") or ""), **envelope_asset_metadata(env)},
        references=_dedupe([
            _display_path(storage.root, proposal_path),
            *[str(item.get("path", "")) for item in patch_artifacts if isinstance(item, dict)],
            *[str(item.get("path", "")) for item in invalidations if isinstance(item, dict)],
            *[str(item.get("path", "")) for item in regeneration_tasks if isinstance(item, dict)],
            *[str(item.get("path", "")) for item in agent_task_plans if isinstance(item, dict)],
        ]),
    )
    path = _write_asset(storage, report)
    return {"path": path, "asset": storage.read_json(resolve_path(storage.root, path)), "envelope": env}


def _attach_auto_application_result(storage: LocalStorage, proposal_path: str, application_result: dict[str, Any]) -> None:
    data = storage.read_json(resolve_path(storage.root, proposal_path))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    application_path = str(application_result.get("path") or "")
    content["auto_application"] = {
        "status": str((application_result.get("asset", {}).get("content", {}) if isinstance(application_result.get("asset", {}).get("content", {}), dict) else {}).get("status") or ""),
        "application_report_path": application_path,
        "triggered_at": utc_now(),
        "silent_mutation_allowed": False,
    }
    metadata["auto_application_report_path"] = application_path
    refs = data.get("references", []) if isinstance(data.get("references", []), list) else []
    data["references"] = _dedupe([*refs, application_path])
    data["content"] = content
    data["metadata"] = metadata
    storage.write_json(resolve_path(storage.root, proposal_path), data)


def _book_metadata_from_release(release: dict[str, Any]) -> dict[str, Any]:
    content = release.get("content", {}) if isinstance(release.get("content"), dict) else {}
    return {
        "title": content.get("title") or release.get("title") or "Untitled",
        "synopsis": content.get("synopsis") or content.get("summary") or "",
        "tags": content.get("tags", []),
        "cover_status": "not_required",
    }


def _platform_manual_publish_adapter(profile: dict[str, Any], *, project_id: str = "") -> PlatformPublishAdapter:
    platform_id = str(profile.get("platform_id") or "manual")
    rules = profile.get("platform_rules", {}) if isinstance(profile.get("platform_rules", {}), dict) else {}
    return PlatformPublishAdapter(
        id=make_id("platform_publish_adapter", f"{platform_id}-{profile.get('rules_version', '')}-{project_id or 'global'}-manual"),
        title=f"{profile.get('display_name', platform_id)} manual publish adapter",
        source=str(profile.get("rules_version") or "manual-platform-rules"),
        tags=["publishing-feedback-adapter", "manual-platform-adapter", platform_id],
        content={
            "adapter_id": f"{platform_id}_manual_adapter",
            "platform_id": platform_id,
            "rules_version": str(profile.get("rules_version") or ""),
            "package_rules": {
                "shape": str(profile.get("package_shape") or ""),
                "chapter_body_min_chars": rules.get("chapter_body_min_chars", 1),
                "chapter_body_max_chars": rules.get("chapter_body_max_chars", 0),
                "title_max_chars": rules.get("title_max_chars", 0),
                "synopsis_min_chars": rules.get("synopsis_min_chars", 0),
                "volume_required": bool(rules.get("volume_required", False)),
            },
            "metadata_rules": {
                "required_fields": [field.replace("_present", "") for field in profile.get("checklist", []) if str(field).endswith("_present")],
                "receipt_fields": profile.get("receipt_fields", []),
                "review_status_values": sorted(set(str(value) for value in (profile.get("review_status_map", {}) if isinstance(profile.get("review_status_map", {}), dict) else {}).values())),
            },
            "release_cadence": "manual_operator_controlled",
            "checklist": profile.get("checklist", []),
            "export_contract": {
                "format": str(profile.get("package_shape") or "generic_manual_package"),
                "requires_publish_gate": True,
                "requires_platform_strategy_pack": True,
                "requires_platform_rule_snapshot": True,
                "official_sdk_bound": False,
                "callback_bound": False,
                "rate_limit_policy": "manual_operator_controlled",
            },
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id or "global", "use_in_generation_rag": False, "manual_platform_adapter": True},
    )


def _platform_rule_snapshot(profile: dict[str, Any]) -> dict[str, Any]:
    rules = profile.get("platform_rules", {}) if isinstance(profile.get("platform_rules", {}), dict) else {}
    return {
        "platform_id": str(profile.get("platform_id") or "manual"),
        "display_name": str(profile.get("display_name") or profile.get("platform_id") or "manual"),
        "rules_version": str(profile.get("rules_version") or ""),
        "rule_source": str(rules.get("rule_source") or "manual_profile_not_official_sdk"),
        "package_shape": str(profile.get("package_shape") or ""),
        "upload_constraints": {
            "title_max_chars": rules.get("title_max_chars", 0),
            "synopsis_min_chars": rules.get("synopsis_min_chars", 0),
            "chapter_body_min_chars": rules.get("chapter_body_min_chars", 1),
            "chapter_body_max_chars": rules.get("chapter_body_max_chars", 0),
            "volume_required": bool(rules.get("volume_required", False)),
            "sensitive_check_required": bool(rules.get("sensitive_check_required", False)),
            "formatting": rules.get("formatting", []) if isinstance(rules.get("formatting", []), list) else [],
        },
        "checklist_fields": profile.get("checklist", []),
        "receipt_fields": profile.get("receipt_fields", []),
        "review_risk_gate": profile.get("review_risk_gate", []),
        "review_status_map": profile.get("review_status_map", {}) if isinstance(profile.get("review_status_map", {}), dict) else {},
        "automation_boundary": {
            "manual_upload_only": True,
            "official_sdk_bound": False,
            "callback_bound": False,
            "rate_limit_bound": False,
            "requires_operator_receipt_backfill": True,
        },
    }


def _platform_package_sections(metadata: dict[str, Any], chapters: list[dict[str, Any]], profile: dict[str, Any], *, chapter_format: dict[str, Any]) -> list[dict[str, Any]]:
    platform_id = str(profile.get("platform_id") or "manual")
    common = [
        {
            "section": "book_metadata",
            "copy_order": ["title", "synopsis", "tags", "cover_status"],
            "fields_present": {
                "title": bool(metadata.get("title")),
                "synopsis": bool(metadata.get("synopsis") or metadata.get("summary")),
                "cover_status": bool(metadata.get("cover_path") or metadata.get("cover_status")),
            },
        },
        {
            "section": "chapter_submission",
            "copy_order": ["chapter_title", "chapter_body"],
            "chapter_count": len(chapters),
            "format_status": chapter_format.get("status"),
        },
    ]
    if platform_id == "qidian":
        common.insert(
            1,
            {
                "section": "volume",
                "copy_order": ["volume_title", "chapter_sequence"],
                "fields_present": {"volume_title": bool(metadata.get("volume_title") or metadata.get("volume")), "chapter_sequence": True},
                "operator_note": "Qidian manual package requires an explicit volume before chapter paste.",
            },
        )
    if platform_id == "fanqie":
        common.append({"section": "fanqie_review_check", "copy_order": ["sensitive_word_check", "format_check", "cover_check"], "operator_note": "Fanqie remains manual; record receipt/status after console submission."})
    else:
        common.append({"section": "review_backfill", "copy_order": ["receipt_text", "review_status", "platform_ids"], "operator_note": "Backfill platform receipt/status; no callback is bound."})
    return common


def _feedback_import_contract(profile: dict[str, Any]) -> dict[str, Any]:
    platform_id = str(profile.get("platform_id") or "manual")
    return {
        "platform_id": platform_id,
        "rules_version": str(profile.get("rules_version") or ""),
        "supported_imports": ["chapter_metrics", "book_metrics", "comments"],
        "metric_fields": ["chapter_no", "retention", "completion_rate", "read_through", "follow_read", "new_favorites"],
        "comment_fields": ["text", "chapter_no", "characters", "sentiment", "embedding"],
        "mutation_policy": {
            "silent_mutation_allowed": False,
            "requires_human_gate": True,
            "outputs": ["comment_cluster_report", "chapter_dropoff_report", "feedback_plan_mutation_proposal"],
        },
    }


def _platform_upload_profile(platform_id: str) -> dict[str, Any]:
    key = str(platform_id or "manual").strip().lower()
    profile = PLATFORM_UPLOAD_PROFILES.get(key)
    if profile:
        return {"platform_id": key, **profile, "specific_adapter": True, "api_mode": "manual_first"}
    return {
        "platform_id": key or "manual",
        "display_name": platform_id or "manual",
        "package_shape": "generic_manual_package",
        "manual_upload_steps": [
            "Open the target platform editor manually.",
            "Copy title, synopsis, tags, and chapter payload from this package.",
            "Run the sensitive-word, formatting, and cover checklist before submit.",
            "Record the platform receipt with record-platform-receipt.",
        ],
        "checklist": ["title_present", "synopsis_present", "chapter_title_present", "chapter_body_present", "cover_checked", "sensitive_word_checked", "format_checked"],
        "receipt_fields": ["book_id", "chapter_id", "review_status", "submitted_at"],
        "review_risk_gate": ["sensitive_terms", "formatting"],
        "rules_version": "generic-manual-2026-07",
        "specific_adapter": False,
        "api_mode": "manual_first",
    }


def _platform_upload_checklist(metadata: dict[str, Any], chapters: list[dict[str, Any]], profile: dict[str, Any], *, chapter_format: dict[str, Any]) -> dict[str, bool]:
    rules = profile.get("platform_rules", {}) if isinstance(profile.get("platform_rules", {}), dict) else {}
    volume_present = bool(metadata.get("volume") or metadata.get("volume_title"))
    if not rules.get("volume_required"):
        volume_present = volume_present or len(chapters) <= 1
    values = {
        "title_present": bool(metadata.get("title")),
        "synopsis_present": bool(metadata.get("synopsis") or metadata.get("summary")),
        "volume_present": volume_present,
        "chapter_title_present": all(bool(row.get("title")) for row in chapters),
        "chapter_body_present": all(bool(row.get("body") or row.get("text")) for row in chapters),
        "cover_checked": bool(metadata.get("cover_path") or metadata.get("cover_status") == "not_required"),
        "sensitive_word_checked": bool(metadata.get("sensitive_word_checked") or metadata.get("sensitive_checked")),
        "format_checked": chapter_format.get("status") == "passed",
    }
    return {key: bool(values.get(key, False)) for key in profile.get("checklist", [])}


def _chapter_format_report(chapters: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    rules = profile.get("platform_rules", {}) if isinstance(profile.get("platform_rules", {}), dict) else {}
    min_len = int(rules.get("chapter_body_min_chars") or (600 if profile.get("platform_id") == "qidian" else 800 if profile.get("platform_id") == "fanqie" else 1))
    max_len = int(rules.get("chapter_body_max_chars") or 0)
    title_max = int(rules.get("title_max_chars") or 0)
    for index, chapter in enumerate(chapters, start=1):
        title = str(chapter.get("title") or "")
        body = str(chapter.get("body") or chapter.get("text") or "")
        if not title.strip():
            issues.append({"chapter_index": index, "severity": "high", "message": "chapter title is missing"})
        if title_max and len(title.strip()) > title_max:
            issues.append({"chapter_index": index, "severity": "high", "message": f"chapter title exceeds platform manual guideline: {len(title.strip())} > {title_max}"})
        if len(body.strip()) < min_len:
            issues.append({"chapter_index": index, "severity": "medium", "message": f"chapter body is shorter than platform manual guideline: {len(body.strip())} < {min_len}"})
        if max_len and len(body.strip()) > max_len:
            issues.append({"chapter_index": index, "severity": "medium", "message": f"chapter body is longer than platform manual guideline: {len(body.strip())} > {max_len}"})
        if "\x00" in body:
            issues.append({"chapter_index": index, "severity": "critical", "message": "chapter body contains NUL byte"})
        if "\r\n" in body:
            issues.append({"chapter_index": index, "severity": "low", "message": "chapter body uses CRLF; normalize before paste"})
    return {
        "status": "blocked" if any(issue["severity"] in {"critical", "high"} for issue in issues) else "passed",
        "rules_version": str(profile.get("rules_version") or ""),
        "platform_id": str(profile.get("platform_id") or "manual"),
        "min_body_chars": min_len,
        "max_body_chars": max_len,
        "title_max_chars": title_max,
        "issue_count": len(issues),
        "issues": issues,
    }


def _manual_adapter_contract(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "adapter_id": f"{profile.get('platform_id', 'manual')}_manual_adapter",
        "rules_version": str(profile.get("rules_version") or ""),
        "api_mode": "manual_first",
        "supports": {
            "upload_package": True,
            "chapter_format_check": True,
            "review_status_backfill": True,
            "comment_import": True,
            "follow_read_metric_import": True,
            "automatic_publish": False,
        },
        "production_boundaries": {
            "official_sdk_bound": False,
            "callback_bound": False,
            "rate_limit_bound": False,
            "manual_operator_required": True,
            "does_not_publish_without_external_adapter": True,
        },
        "receipt_fields": profile.get("receipt_fields", []),
        "review_risk_gate": profile.get("review_risk_gate", []),
    }


def _parse_platform_receipt_payload(platform_id: str, *, receipt_text: str, receipt_raw: dict[str, Any]) -> dict[str, Any]:
    profile = _platform_upload_profile(platform_id)
    parser = profile.get("receipt_parser", {}) if isinstance(profile.get("receipt_parser", {}), dict) else {}
    parsed = _normalize_receipt_fields(platform_id, receipt_raw)
    text_values = {
        "book_id": _first_labeled_value(receipt_text, parser.get("book_id_labels", [])),
        "volume_id": _first_labeled_value(receipt_text, parser.get("volume_id_labels", [])),
        "chapter_id": _first_labeled_value(receipt_text, parser.get("chapter_id_labels", [])),
        "review_status": _first_labeled_value(receipt_text, parser.get("status_labels", [])),
        "submitted_at": _first_labeled_value(receipt_text, parser.get("submitted_at_labels", [])),
    }
    parsed.update({key: value for key, value in text_values.items() if value})
    parsed["review_status"] = _normalize_review_status(platform_id, str(parsed.get("review_status") or "submitted"))
    reasons = parsed.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    reason_from_text = _first_labeled_value(receipt_text, ["原因", "退回原因", "reasons", "reason"])
    if reason_from_text:
        reasons.append(reason_from_text)
    parsed["reasons"] = [str(item) for item in reasons if str(item).strip()]
    parsed["platform_id"] = profile.get("platform_id")
    parsed["rules_version"] = profile.get("rules_version")
    return parsed


def _normalize_receipt_fields(platform_id: str, receipt_raw: dict[str, Any]) -> dict[str, Any]:
    raw = receipt_raw if isinstance(receipt_raw, dict) else {}
    nested = raw.get("parsed_fields", {}) if isinstance(raw.get("parsed_fields", {}), dict) else {}
    merged = {**raw, **nested}
    status = str(
        merged.get("review_status")
        or merged.get("status")
        or merged.get("audit_status")
        or merged.get("审核状态")
        or merged.get("状态")
        or "submitted"
    )
    return {
        "book_id": str(merged.get("platform_book_id") or merged.get("book_id") or merged.get("作品ID") or merged.get("作品号") or ""),
        "volume_id": str(merged.get("volume_id") or merged.get("卷号") or merged.get("分卷ID") or ""),
        "chapter_id": str(merged.get("platform_chapter_id") or merged.get("chapter_id") or merged.get("章节ID") or merged.get("章节号") or ""),
        "review_status": _normalize_review_status(platform_id, status),
        "submitted_at": str(merged.get("submitted_at") or merged.get("提交时间") or ""),
        "remote_receipt_id": str(merged.get("remote_receipt_id") or merged.get("receipt_id") or ""),
        "reasons": merged.get("reasons", []) if isinstance(merged.get("reasons", []), list) else [str(merged.get("reason") or merged.get("原因") or "")],
    }


def _normalize_review_status(platform_id: str, status: str) -> str:
    value = str(status or "submitted").strip()
    lowered = value.lower()
    if lowered in {"submitted", "reviewing", "approved", "published", "rejected", "blocked", "failed", "scheduled"}:
        return lowered
    profile = _platform_upload_profile(platform_id)
    status_map = profile.get("review_status_map", {}) if isinstance(profile.get("review_status_map", {}), dict) else {}
    for token, normalized in status_map.items():
        if str(token) and str(token) in value:
            return str(normalized)
    if any(token in value for token in ["退回", "拒", "驳回"]):
        return "rejected"
    if any(token in value for token in ["通过", "发布"]):
        return "approved"
    if any(token in value for token in ["审", "处理中"]):
        return "reviewing"
    if any(token in lowered for token in ["fail", "error", "失败"]):
        return "failed"
    return "submitted"


def _platform_review_status_contract(profile: dict[str, Any], status: str, receipt: dict[str, Any]) -> dict[str, Any]:
    blocking = status in {"rejected", "blocked", "failed"}
    return {
        "platform_id": profile.get("platform_id", ""),
        "rules_version": profile.get("rules_version", ""),
        "status": status,
        "status_category": _review_status_category(status),
        "blocking": blocking,
        "terminal": status in {"approved", "published", "rejected", "blocked", "failed"},
        "next_actions": _platform_review_next_actions(status, receipt),
        "manual_operator_required": status in {"submitted", "reviewing", "rejected", "blocked", "failed"},
        "operator_evidence_required": status in {"submitted", "reviewing", "rejected", "blocked", "failed"},
    }


def _review_status_category(status: str) -> str:
    if status in {"approved", "published"}:
        return "success"
    if status in {"rejected", "blocked", "failed"}:
        return "blocking"
    if status in {"submitted", "reviewing", "scheduled"}:
        return "pending"
    return "unknown"


def _platform_review_next_actions(status: str, receipt: dict[str, Any]) -> list[str]:
    if status in {"approved", "published"}:
        return ["record_publish_receipt", "import_metrics_when_available"]
    if status == "reviewing":
        return ["poll_or_manually_backfill_review_status"]
    if status == "submitted":
        return ["wait_for_platform_review", "backfill_receipt_when_status_changes"]
    if status in {"rejected", "blocked", "failed"}:
        reasons = receipt.get("reasons", []) if isinstance(receipt.get("reasons", []), list) else []
        return ["manual_fix_required", "create_review_issue", "rebuild_platform_upload_package", *[f"reason:{item}" for item in reasons if str(item).strip()][:3]]
    return ["manual_review_required"]


def _missing_receipt_fields(profile: dict[str, Any], parsed: dict[str, Any]) -> list[str]:
    field_map = {"book_id": "book_id", "chapter_id": "chapter_id", "volume_id": "volume_id", "review_status": "review_status", "submitted_at": "submitted_at"}
    missing = []
    for field in profile.get("receipt_fields", []):
        key = field_map.get(str(field), str(field))
        if not parsed.get(key):
            missing.append(str(field))
    return missing


def _receipt_parser_confidence(profile: dict[str, Any], parsed: dict[str, Any], *, receipt_text: str = "") -> dict[str, Any]:
    required = [str(item) for item in profile.get("receipt_fields", [])]
    missing = _missing_receipt_fields(profile, parsed)
    present_required = len(required) - len(missing)
    base = present_required / max(1, len(required))
    if str(parsed.get("review_status") or "") in {"submitted", "reviewing", "approved", "published", "rejected", "blocked", "failed", "scheduled"}:
        base = min(1.0, base + 0.1)
    if receipt_text.strip():
        base = min(1.0, base + 0.05)
    level = "high" if base >= 0.85 else "medium" if base >= 0.55 else "low"
    return {
        "score": round(base, 3),
        "level": level,
        "required_fields": required,
        "missing_required_fields": missing,
        "receipt_text_present": bool(receipt_text.strip()),
    }


def _first_labeled_value(text: str, labels: list[Any]) -> str:
    body = str(text or "")
    if not body.strip():
        return ""
    for label in labels:
        escaped = re.escape(str(label))
        pattern = rf"{escaped}\s*[:：]\s*([^\n\r;；]+)"
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


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
        "review_rule_update": _patch_step("review_rule", target_assets, proposed_changes),
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


def _apply_feedback_invalidations(storage: LocalStorage, target_assets: list[dict[str, Any]], *, project_id: str, apply_invalidation: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for target in target_assets:
        if not isinstance(target, dict):
            continue
        path_ref = str(target.get("path") or "").strip()
        if not path_ref:
            results.append({"status": "skipped", "reason": "target has no path", "target": target})
            continue
        try:
            target_path = resolve_path(storage.root, path_ref)
            if not target_path.exists():
                results.append({"status": "skipped", "reason": "target path does not exist", "path": path_ref, "target": target})
                continue
            result = mark_downstream_assets_stale(
                storage,
                path_ref,
                project_id=project_id or None,
                reason="approved feedback mutation application",
                apply=apply_invalidation,
            )
            results.append({"status": result.get("status", ""), "path": str(result.get("impact_report", {}).get("path", "")), "apply": result.get("apply", False), "updated_assets": result.get("updated_assets", []), "errors": result.get("errors", [])})
        except (FileNotFoundError, ValueError) as exc:
            results.append({"status": "failed", "path": path_ref, "error": str(exc)})
    return results


def _write_feedback_regeneration_tasks(
    storage: LocalStorage,
    *,
    proposal_id: str,
    target_assets: list[dict[str, Any]],
    proposed_changes: list[dict[str, Any]],
    project_id: str,
    envelope: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for target in target_assets:
        if not isinstance(target, dict):
            continue
        asset_type = str(target.get("asset_type") or target.get("domain") or "asset")
        path_ref = str(target.get("path") or "")
        task = RevisionTask(
            title=f"Feedback mutation regeneration for {asset_type}",
            source=proposal_id,
            tags=["feedback-mutation", "regeneration", asset_type, "needs-review"],
            content={
                "task_id": make_id("revision_task", f"{proposal_id}-{asset_type}-{path_ref}"),
                "review_path": proposal_id,
                "source_draft_path": path_ref,
                "target_asset_id": str(target.get("asset_id") or ""),
                "target_asset_type": asset_type,
                "target_asset_path": path_ref,
                "issue_indexes": [0],
                "issues": [
                    {
                        "issue_index": 0,
                        "severity": "medium",
                        "message": "approved reader feedback mutation requires controlled regeneration",
                        "proposed_changes": proposed_changes,
                    }
                ],
                "issue_refs": [],
                "instructions": [
                    "Apply only the approved feedback mutation through workflow execution.",
                    "Regenerate downstream drafts only after invalidation and re-review.",
                    "Do not silently mutate outline, chapter plan, style policy, genre strategy, or release package.",
                ],
                "proposed_changes": proposed_changes,
                "status": "open",
                "created_at": utc_now(),
                "requires_re_review": True,
                "requires_publish_gate_rerun": True,
            },
            metadata={"project_id": project_id, **envelope_asset_metadata(envelope)},
            references=_dedupe([path_ref]),
        )
        path = _write_asset(storage, task)
        tasks.append({"status": "created", "path": path, "target_asset_type": asset_type, "target_asset_path": path_ref})
    return tasks


def _write_feedback_agent_task_plans(
    storage: LocalStorage,
    *,
    proposal_id: str,
    proposal_path: str,
    patch_artifacts: list[dict[str, Any]],
    invalidations: list[dict[str, Any]],
    regeneration_tasks: list[dict[str, Any]],
    project_id: str,
    envelope: dict[str, Any],
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    patch_paths = [str(item.get("path") or "") for item in patch_artifacts if isinstance(item, dict) and str(item.get("path") or "").strip()]
    regeneration_paths = [str(item.get("path") or "") for item in regeneration_tasks if isinstance(item, dict) and str(item.get("path") or "").strip()]
    invalidation_paths = [str(item.get("path") or "") for item in invalidations if isinstance(item, dict) and str(item.get("path") or "").strip()]
    for task in regeneration_tasks:
        if not isinstance(task, dict) or not str(task.get("path") or "").strip():
            continue
        plans.append(
            _write_feedback_agent_task_plan(
                storage,
                proposal_id=proposal_id,
                agent_type="editor",
                operation="run-review-revision-publish-loop",
                input_paths=_dedupe([proposal_path, str(task.get("path") or ""), *patch_paths]),
                output_targets=[
                    {"asset_type": "draft_chapter", "reason": "regenerate downstream draft after approved feedback mutation"},
                    {"asset_type": "review_report", "reason": "re-review regenerated content"},
                    {"asset_type": "publish_gate_report", "reason": "rerun publish gate after feedback-driven regeneration"},
                ],
                project_id=project_id,
                envelope=envelope,
                linked_revision_task_path=str(task.get("path") or ""),
                evidence={"target_asset_type": task.get("target_asset_type", ""), "target_asset_path": task.get("target_asset_path", "")},
            )
        )
    if patch_paths or regeneration_paths:
        plans.append(
            _write_feedback_agent_task_plan(
                storage,
                proposal_id=proposal_id,
                agent_type="quality",
                operation="run-quality-gate",
                input_paths=_dedupe([proposal_path, *patch_paths, *regeneration_paths]),
                output_targets=[{"asset_type": "quality_gate_report", "reason": "verify feedback mutation repair before release"}],
                project_id=project_id,
                envelope=envelope,
                evidence={"requires_re_review": True},
            )
        )
    plans.append(
        _write_feedback_agent_task_plan(
            storage,
            proposal_id=proposal_id,
            agent_type="publishing",
            operation="create-publish-gate-report",
            input_paths=_dedupe([proposal_path, *patch_paths, *regeneration_paths, *invalidation_paths]),
            output_targets=[{"asset_type": "publish_gate_report", "reason": "rerun publish gate after approved feedback mutation"}],
            project_id=project_id,
            envelope=envelope,
            evidence={"requires_release_package_rebuild": True, "requires_platform_gate_rerun": True},
        )
    )
    return plans


def _write_feedback_agent_task_plan(
    storage: LocalStorage,
    *,
    proposal_id: str,
    agent_type: str,
    operation: str,
    input_paths: list[str],
    output_targets: list[dict[str, Any]],
    project_id: str,
    envelope: dict[str, Any],
    linked_revision_task_path: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = AgentTask(
        title=f"Feedback mutation follow-up: {operation}",
        source=proposal_id,
        tags=["feedback-mutation", "agent-task", agent_type, operation, "planned"],
        content={
            "task_id": make_id("agent_task", f"feedback-mutation-{operation}-{proposal_id}-{utc_now()}"),
            "agent_type": agent_type,
            "operation": operation,
            "status": "planned",
            "input_assets": [{"path": path, "asset_ref": path} for path in input_paths if str(path).strip()],
            "output_targets": output_targets,
            "linked_loop_run_path": "",
            "linked_context_bundle_path": "",
            "linked_review_issue_path": "",
            "linked_revision_task_path": linked_revision_task_path,
            "agent_run_path": "",
            "dispatch_queue_path": "",
            "evidence": {
                "feedback_mutation_proposal_id": proposal_id,
                "silent_mutation_allowed": False,
                "requires_human_patch_review": True,
                "requires_re_review": True,
                "requires_publish_gate_rerun": True,
                **(evidence or {}),
            },
            "created_at": utc_now(),
            "updated_at": utc_now(),
        },
        metadata={"project_id": project_id, "agent_type": agent_type, "operation": operation, "asset_status": "planned", **envelope_asset_metadata(envelope)},
        references=_dedupe(input_paths),
    )
    path = _write_asset(storage, task)
    return {"status": "planned", "path": path, "agent_type": agent_type, "operation": operation, "linked_revision_task_path": linked_revision_task_path}


def _feedback_workflow_dispatch_plan(
    *,
    patch_artifacts: list[dict[str, Any]],
    invalidations: list[dict[str, Any]],
    regeneration_tasks: list[dict[str, Any]],
    agent_task_plans: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "dispatch_mode": "planned_agent_tasks_and_workflow_nodes",
        "silent_mutation_allowed": False,
        "nodes": [
            {
                "node_id": "patch_review",
                "operation": "human-review-feedback-mutation-patches",
                "status": "planned",
                "input_paths": [str(item.get("path") or "") for item in patch_artifacts if isinstance(item, dict)],
            },
            {
                "node_id": "downstream_invalidation",
                "operation": "mark-downstream-assets-stale",
                "status": "applied" if any(bool(item.get("apply")) for item in invalidations if isinstance(item, dict)) else "planned",
                "evidence_paths": [str(item.get("path") or "") for item in invalidations if isinstance(item, dict)],
            },
            {
                "node_id": "regeneration",
                "operation": "run-review-revision-publish-loop",
                "status": "planned",
                "revision_task_paths": [str(item.get("path") or "") for item in regeneration_tasks if isinstance(item, dict)],
                "agent_task_paths": [str(item.get("path") or "") for item in agent_task_plans if isinstance(item, dict) and item.get("operation") == "run-review-revision-publish-loop"],
            },
            {
                "node_id": "quality_gate",
                "operation": "run-quality-gate",
                "status": "planned",
                "agent_task_paths": [str(item.get("path") or "") for item in agent_task_plans if isinstance(item, dict) and item.get("operation") == "run-quality-gate"],
            },
            {
                "node_id": "publish_gate_rerun",
                "operation": "create-publish-gate-report",
                "status": "planned",
                "agent_task_paths": [str(item.get("path") or "") for item in agent_task_plans if isinstance(item, dict) and item.get("operation") == "create-publish-gate-report"],
            },
        ],
    }


def _feedback_re_review_gate_plan(patch_artifacts: list[dict[str, Any]], regeneration_tasks: list[dict[str, Any]], agent_task_plans: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "required": True,
        "status": "planned",
        "patch_review_required": True,
        "quality_gate_operation": "run-quality-gate",
        "patch_artifact_paths": [str(item.get("path") or "") for item in patch_artifacts if isinstance(item, dict)],
        "regeneration_task_paths": [str(item.get("path") or "") for item in regeneration_tasks if isinstance(item, dict)],
        "agent_task_paths": [str(item.get("path") or "") for item in agent_task_plans if isinstance(item, dict) and item.get("operation") == "run-quality-gate"],
    }


def _feedback_publish_gate_rerun_plan(
    patch_artifacts: list[dict[str, Any]],
    invalidations: list[dict[str, Any]],
    regeneration_tasks: list[dict[str, Any]],
    agent_task_plans: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "required": True,
        "status": "planned",
        "publish_gate_operation": "create-publish-gate-report",
        "release_package_rebuild_required": True,
        "platform_adapter_gate_rerun_required": True,
        "patch_artifact_paths": [str(item.get("path") or "") for item in patch_artifacts if isinstance(item, dict)],
        "invalidation_evidence_paths": [str(item.get("path") or "") for item in invalidations if isinstance(item, dict)],
        "regeneration_task_paths": [str(item.get("path") or "") for item in regeneration_tasks if isinstance(item, dict)],
        "agent_task_paths": [str(item.get("path") or "") for item in agent_task_plans if isinstance(item, dict) and item.get("operation") == "create-publish-gate-report"],
    }


def _write_feedback_patch_assets(
    storage: LocalStorage,
    *,
    proposal_id: str,
    patch_plan: dict[str, Any],
    project_id: str,
    envelope: dict[str, Any],
) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for key, step in patch_plan.items():
        if not isinstance(step, dict):
            continue
        if step.get("status") == "not_applicable":
            continue
        domain = str(step.get("domain") or key)
        patch = FeedbackMutationPatch(
            title=f"Feedback mutation patch: {domain}",
            source=proposal_id,
            tags=["feedback-mutation", "patch", domain, "needs-review"],
            content={
                "patch_id": make_id("feedback_mutation_patch", f"{proposal_id}-{domain}"),
                "proposal_id": proposal_id,
                "domain": domain,
                "status": "needs_review",
                "target_assets": step.get("target_assets", []) if isinstance(step.get("target_assets", []), list) else [],
                "proposed_changes": step.get("proposed_changes", []) if isinstance(step.get("proposed_changes", []), list) else [],
                "apply_mode": "human_gated_workflow_only",
                "human_gate": {"required": True, "status": "approved_upstream_needs_patch_review"},
                "downstream_invalidation_required": domain in {"outline", "chapter_plan", "review_rule", "style", "genre", "mkaos"},
                "regeneration_required": domain in {"outline", "chapter_plan", "style", "genre"},
                "created_at": utc_now(),
            },
            metadata={"project_id": project_id, **envelope_asset_metadata(envelope)},
            references=_dedupe([str(row.get("path", "")) for row in step.get("target_assets", []) if isinstance(row, dict)]),
        )
        path = _write_asset(storage, patch)
        patches.append({"status": "needs_review", "path": path, "domain": domain, "target_count": len(patch.content["target_assets"])})
    return patches


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
        "embedding_clusters": _embedding_comment_clusters(comments),
        "embedding_mode": "provided_embeddings" if any(_comment_embedding(comment) for comment in comments) else "not_available",
        "clusters": [
            {"name": "toxic_points", "count": len(pain)},
            {"name": "pleasure_points", "count": len(pleasure)},
            {"name": "dropoff_reasons", "count": len(dropoff)},
        ],
    }


def _embedding_comment_clusters(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vectors = [(index, _comment_embedding(comment), str(comment.get("text") or comment.get("comment") or "")) for index, comment in enumerate(comments)]
    vectors = [(index, vector, text) for index, vector, text in vectors if vector]
    clusters: list[dict[str, Any]] = []
    assigned: set[int] = set()
    for index, vector, text in vectors:
        if index in assigned:
            continue
        members = [{"index": index, "text": text}]
        assigned.add(index)
        for other_index, other_vector, other_text in vectors:
            if other_index in assigned:
                continue
            if _cosine(vector, other_vector) >= 0.85:
                assigned.add(other_index)
                members.append({"index": other_index, "text": other_text})
        clusters.append({"cluster_id": f"embedding-cluster-{len(clusters) + 1}", "size": len(members), "members": members, "sample_text": members[0]["text"]})
    return clusters


def _comment_embedding(comment: dict[str, Any]) -> list[float]:
    value = comment.get("embedding") if isinstance(comment.get("embedding"), list) else comment.get("vector") if isinstance(comment.get("vector"), list) else []
    result: list[float] = []
    for item in value:
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            return []
    return result


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


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
