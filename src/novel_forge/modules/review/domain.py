from __future__ import annotations

import hashlib
from typing import Any

from .prose_window import coverage_report

from novel_forge.modules.command_kernel.errors import KernelError


def evaluate_review_result(
    *,
    project_id: str,
    target_asset_version_id: str,
    context_bundle_version_id: str,
    chapter: int,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    prose_text: str | None = None,
    knowledge_targets: list[dict[str, Any]] | None = None,
    cross_chapter_window: dict[str, Any] | None = None,
    prior_review: dict[str, Any] | None = None,
    craft_targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not project_id or not target_asset_version_id or not context_bundle_version_id:
        raise KernelError("REVIEW_INPUT_INVALID", "project, target and context versions are required")
    decision = str(result.get("decision") or "").upper()
    if decision not in {"PASSED", "NEEDS_REVISION", "BLOCKED"}:
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review decision is unsupported")
    score = result.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= 100:
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review score must be between 0 and 100")
    issues = result.get("issues")
    if not isinstance(issues, list) or any(not isinstance(item, dict) for item in issues):
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review issues must be objects")
    from .diagnostics import DIAGNOSTIC_CONTRACT, prose_hash, validate_diagnosis
    actionable = result.get("diagnostic_contract_version") == DIAGNOSTIC_CONTRACT
    if cross_chapter_window is not None:
        from .prose_window import validate_window
        validate_window(cross_chapter_window)
        if not actionable:
            raise KernelError("REVIEW_DIAGNOSIS_INCOMPLETE", "cross-chapter review requires actionable diagnostics")
    if craft_targets and not actionable:
        raise KernelError("CRAFT_REVIEW_DIAGNOSIS_REQUIRED", "Craft review requires actionable diagnostics")
    if actionable and prose_text is None:
        raise KernelError("REVIEW_SOURCE_REQUIRED", "actionable review requires exact candidate prose")
    normalized: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    code_bindings: dict[str, list[str]] = {}
    for ordinal, item in enumerate(issues, start=1):
        code = str(item.get("code") or "").strip()
        severity = str(item.get("severity") or "").lower()
        message = str(item.get("message") or "").strip()
        if not code or severity not in {"blocking", "major", "minor"} or not message:
            raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review issue is incomplete")
        provider_code = code
        diagnosis = validate_diagnosis(item, str(prose_text)) if actionable and cross_chapter_window is None else {}
        if cross_chapter_window is not None:
            target = item.get("evidence") or {}
            if target.get("asset_version_id") != target_asset_version_id or target.get("text_hash") != prose_hash(str(prose_text)):
                raise KernelError("REVIEW_EVIDENCE_INVALID", "target evidence must bind the exact candidate version and hash")
            from .cross_chapter import paired_diagnosis
            diagnosis = paired_diagnosis(item, text=str(prose_text), window=cross_chapter_window, prior=prior_review)
            code = diagnosis.get("code", code)
        if code in seen_codes:
            raise KernelError("REVIEW_ISSUE_IDENTITY_INVALID", "review issue codes must be unique so distinct diagnoses survive revision")
        seen_codes.add(code)
        code_bindings.setdefault(provider_code, []).append(code)
        evidence = item.get("evidence", {}) if isinstance(item.get("evidence"), dict) else {}
        fingerprint = f"{project_id}:{target_asset_version_id}:{code}:{ordinal}".encode()
        normalized.append(
            {
                "review_issue_id": "review-issue:" + hashlib.sha256(fingerprint).hexdigest()[:24],
                "code": code,
                "severity": severity,
                "message": message,
                "status": "OPEN",
                "qualification": "ELIGIBLE",
                "target_asset_version_id": target_asset_version_id,
                "context_bundle_version_id": context_bundle_version_id,
                "evidence_locator": {
                    "chapter": chapter,
                    "start": evidence.get("start"),
                    "end": evidence.get("end"),
                    "excerpt_digest": str(evidence.get("excerpt_digest") or ""),
                },
                "revision_strategy": str(item.get("revision_strategy") or message),
                **diagnosis,
                **({"target_text_hash": prose_hash(str(prose_text))} if actionable else {}),
            }
        )
    blocking_count = sum(item["severity"] == "blocking" for item in normalized)
    if decision == "PASSED" and blocking_count:
        raise KernelError("REVIEW_DECISION_CONFLICT", "PASSED review cannot contain blocking issues")
    from .knowledge import validate_knowledge_checks
    def bind_issue_references(value: Any) -> Any:
        if isinstance(value, list):
            return [bind_issue_references(item) for item in value]
        if isinstance(value, dict):
            return {key: list(dict.fromkeys(bound for code in item for bound in code_bindings.get(code, [code]))) if key == "issue_codes" and isinstance(item, list)
                    else bind_issue_references(item) for key, item in value.items()}
        return value
    targets = list(knowledge_targets or [])
    knowledge_checks = validate_knowledge_checks(
        checks=bind_issue_references(result.get("knowledge_checks", [])), targets=targets, issues=normalized,
        text=str(prose_text or ""), target_asset_version_id=target_asset_version_id,
        real_model_call=provider_evidence.get("real_model_call") is True,
    )
    if any(item["status"] == "MISAPPLIED" for item in knowledge_checks) and decision == "PASSED":
        decision = "NEEDS_REVISION"
    from .craft import CRAFT_REVIEW_CONTRACT, validate_craft_checks
    craft_checks = validate_craft_checks(
        checks=bind_issue_references(result.get("craft_checks", [])), targets=list(craft_targets or []), issues=normalized,
        text=str(prose_text or ""), target_asset_version_id=target_asset_version_id,
        real_model_call=provider_evidence.get("real_model_call") is True,
    )
    return {
        **({"craft_review_contract": CRAFT_REVIEW_CONTRACT, "craft_targets": craft_targets, "craft_checks": craft_checks} if craft_targets else {}),
        **({"cross_chapter_window": cross_chapter_window,
            "cross_chapter_coverage": coverage_report(cross_chapter_window)} if cross_chapter_window is not None else {}),
        "report_type": "ReviewReport",
        "project_id": project_id,
        "chapter": chapter,
        "target_asset_version_id": target_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "decision": decision,
        "score": float(score),
        "issues": normalized,
        "blocking_issue_count": blocking_count,
        "provider_evidence": dict(provider_evidence),
        "review_contract_version": "review-domain-v2",
        "knowledge_targets": targets,
        "knowledge_checks": knowledge_checks,
        "knowledge_target_text_hash": prose_hash(str(prose_text or "")),
        **({"diagnostic_contract_version": DIAGNOSTIC_CONTRACT, "target_text_hash": prose_hash(str(prose_text))} if actionable else {}),
    }


def evaluate_rereview_result(
    *,
    project_id: str,
    original_draft_version_id: str,
    initial_review_version_id: str,
    revision_version_id: str,
    context_bundle_version_id: str,
    initial_review: dict[str, Any],
    revision: dict[str, Any],
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    knowledge_targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from .craft import craft_review_targets, same_frozen_targets
    current_craft_targets = craft_review_targets(revision)
    if not same_frozen_targets(current_craft_targets, initial_review.get("craft_targets") or []):
        raise KernelError("CRAFT_REVISION_SELECTION_CHANGED", "rereview cannot replace frozen Craft targets")
    reviewed = evaluate_review_result(
        project_id=project_id,
        target_asset_version_id=revision_version_id,
        context_bundle_version_id=context_bundle_version_id,
        chapter=int(revision["chapter"]),
        result=result,
        provider_evidence=provider_evidence,
        prose_text=str(revision.get("text") or ""),
        knowledge_targets=(knowledge_targets if knowledge_targets is not None else initial_review.get("knowledge_targets", [])),
        cross_chapter_window=initial_review.get("cross_chapter_window"),
        prior_review=initial_review,
        craft_targets=current_craft_targets,
    )
    from .craft import craft_rereview_preservation
    craft_preservation = craft_rereview_preservation(result, initial_review, reviewed, str(revision.get("text") or ""))
    if craft_preservation.get("craft_preservation_status", "PRESERVED") != "PRESERVED":
        result = {**result, "resolution_checks": [{**check, "preservation": craft_preservation["craft_preservation_status"]} for check in result["resolution_checks"]]}
    if initial_review.get("cross_chapter_window"):
        from .cross_chapter import resolution_checks
        result = {**result, "resolution_checks": resolution_checks(result, initial_review, str(revision.get("text") or ""))}
    claimed = set(revision.get("resolution_claimed_issue_codes", []))
    from .diagnostics import open_diagnoses, require_review_score
    initial_by_code = {str(item["code"]): item for item in open_diagnoses(initial_review)}
    current_codes = {str(item.get("code")) for item in reviewed["issues"]}
    verified = {str(item) for item in result.get("resolved_issue_codes", [])}
    if initial_review.get("diagnostic_contract_version") == "actionable-diagnostics.v1":
        from .diagnostics import verified_resolutions
        verified = verified_resolutions(result, initial_review, str(revision.get("text") or ""))
    elif reviewed["decision"] == "PASSED":
        verified.update(claimed - current_codes)
    issue_lineage: list[dict[str, Any]] = []
    remaining: list[str] = []
    resolved: list[str] = []
    regressions: list[str] = []
    for code, issue in initial_by_code.items():
        if code in verified and code not in current_codes:
            status = "RESOLVED"
            resolved.append(code)
        elif code in current_codes:
            status = "REOPENED" if code in claimed else "OPEN"
            remaining.append(code)
        else:
            status = "RESOLUTION_CLAIMED" if code in claimed else "OPEN"
            remaining.append(code)
        issue_lineage.append(
            {
                "review_issue_id": issue.get("review_issue_id", ""),
                "code": code,
                "from_status": issue.get("status", "OPEN"),
                "revision_claimed": code in claimed,
                "verified_by_rereview": status == "RESOLVED",
                "to_status": status,
            }
        )
    new_issues = []
    for issue in reviewed["issues"]:
        code = str(issue["code"])
        if code not in initial_by_code:
            new_issues.append(issue)
            regressions.append(code)
    blocking_remaining = sum(
        initial_by_code[code].get("severity") == "blocking" for code in remaining
    ) + sum(item.get("severity") == "blocking" for item in new_issues)
    decision = reviewed["decision"]
    if blocking_remaining and decision == "PASSED":
        decision = "NEEDS_REVISION"
    from novel_forge.modules.revision.domain import validate_quality_resolution_checks
    quality_checks = validate_quality_resolution_checks(revision=revision, revision_asset_version_id=revision_version_id, result=result)
    if any(row["status"] != "SATISFIED" or row["preservation"] != "PRESERVED" for row in quality_checks):
        decision = "NEEDS_REVISION"
    before_score = require_review_score(initial_review)
    after_score = float(reviewed["score"])
    from .diagnostics import validate_location
    relocated = {check["code"]: validate_location(dict(check["evidence"]), str(revision.get("text") or ""))
                 for check in result.get("resolution_checks", []) if check.get("evidence")}
    return {
        **reviewed,
        **craft_preservation,
        "report_type": "ReReviewReport",
        "decision": decision,
        "original_draft_version_id": original_draft_version_id,
        "initial_review_version_id": initial_review_version_id,
        "revision_version_id": revision_version_id,
        "issue_lineage": issue_lineage,
        "resolution_checks": list(result.get("resolution_checks") or []),
        **({"quality_resolution_checks": quality_checks,
            "prior_review_evidence": {"asset_version_id": initial_review_version_id,
                "target_asset_version_id": initial_review.get("target_asset_version_id"),
                "target_text_hash": initial_review.get("target_text_hash"),
                "resolved_issue_codes": list(initial_review.get("resolved_issue_codes") or []),
                "issue_lineage": list(initial_review.get("issue_lineage") or []),
                "prior_review_evidence": initial_review.get("prior_review_evidence")}}
           if quality_checks else {}),
        **({"preservation_checks": result["preservation_checks"]} if initial_review.get("cross_chapter_window") else {}),
        "resolved_issue_codes": sorted(resolved),
        "remaining_issue_codes": sorted(remaining),
        "unresolved_issues": [
            {**initial_by_code[code], "status": "OPEN", "evidence_scope": "CURRENT_CANDIDATE" if code in relocated else "PRIOR_CANDIDATE",
             **({"evidence_locator": relocated[code], "target_asset_version_id": revision_version_id,
                 "target_text_hash": reviewed["target_text_hash"],
                 "origin_evidence_locator": initial_by_code[code].get("origin_evidence_locator", initial_by_code[code]["evidence_locator"]),
                 "origin_target_asset_version_id": initial_by_code[code].get("origin_target_asset_version_id", initial_by_code[code]["target_asset_version_id"])} if code in relocated else {}),
             "origin_review_issue_id": initial_by_code[code].get("origin_review_issue_id", initial_by_code[code].get("review_issue_id"))}
            for code in sorted(remaining)
        ],
        "new_issues": new_issues,
        "regression_issue_codes": sorted(regressions),
        "blocking_issue_count": blocking_remaining,
        "revision_quality_delta": {
            "before_score": before_score,
            "after_score": after_score,
            "score_delta": after_score - before_score,
            "resolved_issue_count": len(resolved),
            "remaining_issue_count": len(remaining),
            "new_issue_count": len(new_issues),
            "regression_count": len(regressions),
            "content_hash_before": str(initial_review.get("target_content_hash", "")),
            "content_hash_after": str(result.get("target_content_hash", "")),
        },
        "review_contract_version": "re-review-domain-v1",
    }


__all__ = ["evaluate_rereview_result", "evaluate_review_result"]
