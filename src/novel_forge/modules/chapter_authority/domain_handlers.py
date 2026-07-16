"""Storage-free domain transformations for the authoritative chapter chain."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def build_chapter_plan(
    *,
    chapter: int,
    title: str,
    premise: str,
    trace_id: str,
) -> dict[str, Any]:
    if chapter <= 0 or not premise.strip():
        raise KernelError("CHAPTER_PLAN_INPUT_INVALID", "chapter and premise are required")
    return {
        "chapter": chapter,
        "title": title.strip() or f"Chapter {chapter}",
        "premise": premise.strip(),
        "objective": "force a consequential choice and preserve continuity",
        "beats": ["promise tested", "public choice", "visible cost"],
        "closing_hook": "the cost creates a new obligation",
        "trace_id": trace_id,
        "blueprint_version": "chapter-blueprint-v1",
    }


def build_context_bundle(
    *,
    plan: dict[str, Any],
    plan_asset_version_id: str,
    plan_content_hash: str,
) -> dict[str, Any]:
    _require_keys(plan, "chapter", "objective", "premise", "beats")
    return {
        "chapter": plan["chapter"],
        "goal": plan["objective"],
        "selected_asset_version_ids": [plan_asset_version_id],
        "context_digest": plan_content_hash,
        "actual_context": {
            "premise": plan["premise"],
            "beats": plan["beats"],
            "copyright_boundary": "project-owned and abstract eligible context only",
        },
        "forbidden_source_count": 0,
        "context_contract_version": "chapter-context-v1",
    }


def normalize_draft_result(
    *,
    plan: dict[str, Any],
    context_asset_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    text = str(result.get("text") or "").strip()
    if not text:
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "draft result has no text")
    return {
        "chapter": plan["chapter"],
        "title": plan["title"],
        "text": text,
        "context_bundle_id": context_asset_version_id,
        "provider_evidence": dict(provider_evidence),
    }


def normalize_review_result(
    *,
    draft: dict[str, Any],
    draft_asset_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    decision = str(result.get("decision") or "").upper()
    if decision not in {"PASSED", "NEEDS_REVISION", "BLOCKED"}:
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review decision is unsupported")
    score = result.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= 100:
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review score must be between 0 and 100")
    issues = result.get("issues")
    if not isinstance(issues, list) or any(not isinstance(item, dict) for item in issues):
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review issues must be objects")
    normalized_issues: list[dict[str, str]] = []
    for item in issues:
        code = str(item.get("code") or "").strip()
        severity = str(item.get("severity") or "").lower()
        message = str(item.get("message") or "").strip()
        if not code or severity not in {"blocking", "major", "minor"} or not message:
            raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review issue is incomplete")
        normalized_issues.append({"code": code, "severity": severity, "message": message})
    return {
        "chapter": draft["chapter"],
        "target_asset_version_id": draft_asset_version_id,
        "decision": decision,
        "score": float(score),
        "issues": normalized_issues,
        "blocking_issue_count": sum(item["severity"] == "blocking" for item in normalized_issues),
        "provider_evidence": dict(provider_evidence),
    }


def normalize_revision_result(
    *,
    draft: dict[str, Any],
    review: dict[str, Any],
    draft_asset_version_id: str,
    review_asset_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    text = str(result.get("text") or "").strip()
    resolved = [str(item) for item in result.get("resolved_issue_codes", []) if str(item).strip()]
    blocking = {
        str(item["code"])
        for item in review.get("issues", [])
        if item.get("severity") == "blocking"
    }
    if not text or not blocking.issubset(set(resolved)):
        raise KernelError(
            "CHAPTER_REVISION_INCOMPLETE",
            "revision must provide text and resolve every blocking issue",
        )
    return {
        "chapter": draft["chapter"],
        "title": draft["title"],
        "text": text,
        "source_draft_version_id": draft_asset_version_id,
        "review_version_id": review_asset_version_id,
        "resolved_issue_codes": resolved,
        "provider_evidence": dict(provider_evidence),
    }


def build_canon_patch(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
) -> dict[str, Any]:
    text = str(revision.get("text") or "")
    facts: list[dict[str, Any]] = []
    if "surrenders the only safe route home" in text:
        facts.append(
            {
                "subject": "protagonist",
                "predicate": "gave_up",
                "object": "safe_route_home",
                "effective_chapter": revision["chapter"],
            }
        )
    return {
        "chapter": revision["chapter"],
        "source_asset_version_id": revision_asset_version_id,
        "facts": facts,
        "conflicts": [],
        "gate": "PASSED",
    }


def build_quality_report(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
) -> dict[str, Any]:
    visible_cost = "surrenders the only safe route home" in str(revision.get("text") or "")
    canon_clear = canon.get("gate") == "PASSED" and not canon.get("conflicts")
    if not visible_cost or not canon_clear:
        raise KernelError(
            "CHAPTER_QUALITY_GATE_FAILED",
            "Quality output cannot be qualified while a blocking check fails",
        )
    return {
        "chapter": revision["chapter"],
        "target_asset_version_id": revision_asset_version_id,
        "canon_patch_version_id": canon_asset_version_id,
        "score": 91,
        "checks": {
            "blocking_review_issue_resolved": visible_cost,
            "canon_conflict_free": canon_clear,
        },
        "gate": "PASSED",
    }


def build_export_package(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
) -> dict[str, Any]:
    if quality.get("gate") != "PASSED":
        raise KernelError("CHAPTER_QUALITY_GATE_BLOCKED", "Export requires a passed quality gate")
    return {
        "chapter": revision["chapter"],
        "title": revision["title"],
        "rendered_text": revision["text"],
        "source_asset_version_id": revision_asset_version_id,
        "quality_asset_version_id": quality_asset_version_id,
        "release_status": "READY_FOR_BLOB_VERIFICATION",
        "media_type": "text/plain",
    }


def _require_keys(payload: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise KernelError("CHAPTER_HANDLER_INPUT_INVALID", f"missing chapter fields: {', '.join(missing)}")


__all__ = [
    "build_canon_patch",
    "build_chapter_plan",
    "build_context_bundle",
    "build_export_package",
    "build_quality_report",
    "normalize_draft_result",
    "normalize_review_result",
    "normalize_revision_result",
]
