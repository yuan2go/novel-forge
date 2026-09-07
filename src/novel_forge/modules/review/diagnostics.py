from __future__ import annotations

import hashlib
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


DIAGNOSTIC_CONTRACT = "actionable-diagnostics.v1"


def prose_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def validate_location(location: dict[str, Any], text: str) -> dict[str, Any]:
    start, end = location.get("start"), location.get("end")
    if (type(start) is not int or type(end) is not int
        or not 0 <= start < end <= len(text) or location.get("quote") != text[start:end]):
        raise KernelError("REVIEW_EVIDENCE_INVALID", "diagnosis requires a literal Unicode code-point span in its exact candidate")
    return {**location, "excerpt_digest": prose_hash(text[start:end]), "offset_unit": "UNICODE_CODE_POINT"}


def validate_diagnosis(issue: dict[str, Any], text: str) -> dict[str, Any]:
    required = ("category", "judgment_kind", "violated_constraint", "revision_goal")
    if any(not isinstance(issue.get(key), str) or not issue[key].strip() for key in required):
        raise KernelError("REVIEW_DIAGNOSIS_INCOMPLETE", "diagnosis requires category, judgment, constraint and revision goal")
    for key in ("preserve", "acceptance_criteria"):
        values = issue.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(x, str) or not x.strip() for x in values):
            raise KernelError("REVIEW_DIAGNOSIS_INCOMPLETE", "diagnosis requires explicit preservation and acceptance criteria")
    if issue["judgment_kind"] not in {"SEMANTIC_CONFLICT", "AESTHETIC_SUGGESTION", "UNCERTAIN"}:
        raise KernelError("REVIEW_JUDGMENT_INVALID", "Provider judgment cannot declare deterministic proof")
    if issue["judgment_kind"] == "AESTHETIC_SUGGESTION" and issue.get("severity") != "minor":
        raise KernelError("REVIEW_JUDGMENT_INVALID", "an aesthetic preference alone cannot block acceptance")
    return {**{key: issue[key] for key in (*required, "preserve", "acceptance_criteria")},
            "evidence_locator": validate_location(dict(issue.get("evidence") or {}), text),
            "revision_strategy": issue["revision_goal"]}


def verified_resolutions(result: dict[str, Any], initial: dict[str, Any], text: str) -> set[str]:
    checks = result.get("resolution_checks")
    if not isinstance(checks, list):
        raise KernelError("REVIEW_RESOLUTION_CHECKS_REQUIRED", "rereview requires explicit per-diagnosis checks")
    issues = {item["code"]: item for item in initial.get("issues", [])}
    seen: set[str] = set()
    verified: set[str] = set()
    for check in checks:
        code = check.get("code")
        if code not in issues or code in seen:
            raise KernelError("REVIEW_RESOLUTION_INVALID", "resolution checks must identify unique original diagnoses")
        seen.add(code)
        validate_location(dict(check.get("evidence") or {}), text)
        if check.get("status") == "SATISFIED" and check.get("preservation") == "PRESERVED":
            if not str(check.get("reason") or "").strip():
                raise KernelError("REVIEW_RESOLUTION_INVALID", "resolution needs an explanation tied to the repair criteria")
            verified.add(code)
    return verified


def review_covers_candidate(review: dict[str, Any], *, text: str, source_id: str) -> bool:
    if review.get("selection_review_contract") == "immutable-review-projection.v1":
        return (
            review.get("report_type") in {"ReviewReport", "ReReviewReport"}
            and bool(review.get("selection_review_source_asset_version_id"))
            and bool(source_id)
            and review.get("revision_version_id") == source_id
            and review.get("target_text_hash") == prose_hash(text)
        )
    return review.get("report_type") == "ReReviewReport"
