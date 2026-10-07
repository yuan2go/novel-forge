from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.realization_composition import (
    derive_targeted_revision_slots, prose_from_output, reconcile_revision_composition,
)


def _materialize_targeted_result(
    source: dict[str, Any], review: dict[str, Any], result: dict[str, Any], range_policy: str = "INTERSECTION_V1",
) -> tuple[dict[str, Any], dict[str, Any]]:
    from novel_forge.modules.review.cross_chapter import apply_targeted_edits
    targeted = apply_targeted_edits(draft=source, review=review, result=result, range_policy=range_policy)
    if "scene_artifacts" not in result:
        slots = derive_targeted_revision_slots(source, targeted["targeted_edits"])
        result = {**result, "scene_artifacts": slots}
    text = prose_from_output(result, separators=source.get("scene_separators"))
    if text != targeted["repaired_text"]:
        raise KernelError("REVISION_TARGETED_EDIT_INVALID", "derived Slot prose differs from bounded edits")
    return result, {key: value for key, value in targeted.items() if key != "repaired_text"}


def apply_revision_result(
    *,
    project_id: str,
    draft: dict[str, Any],
    review: dict[str, Any],
    draft_asset_version_id: str,
    review_asset_version_id: str,
    context_bundle_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    length_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not all((project_id, draft_asset_version_id, review_asset_version_id, context_bundle_version_id)):
        raise KernelError("REVISION_INPUT_INVALID", "versioned revision lineage is required")
    from novel_forge.modules.review.diagnostics import open_diagnoses

    diagnoses = open_diagnoses(review)
    repair_diagnoses = diagnoses
    if "creative_baseline" in draft:
        from novel_forge.modules.chapter_authority.chapter_plan_views import (
            validate_creative_baseline,
        )

        if (
            review.get("creative_baseline_digest")
            != validate_creative_baseline(draft["creative_baseline"])["baseline_digest"]
        ):
            raise KernelError(
                "REVISION_CREATIVE_BASELINE_DRIFT",
                "Revision diagnoses must use the exact candidate creative baseline",
            )
        from novel_forge.modules.review.diagnostics import prose_repair_diagnoses
        repair_diagnoses = prose_repair_diagnoses(review, work_requirements=True)
        allowed_codes = {item["code"] for item in repair_diagnoses}
        if set(result.get("resolved_issue_codes") or []) - allowed_codes or any(set(edit.get("issue_codes") or []) - allowed_codes for edit in result.get("edits") or []):
            raise KernelError("REVISION_UNAUTHORIZED_DIAGNOSIS", "Evidence reassessment and aesthetic advice cannot be claimed as prose repairs")
    if review.get("diagnostic_contract_version") == "actionable-diagnostics.v1":
        from novel_forge.modules.review.diagnostics import prose_hash
        if (review.get("target_asset_version_id") != draft_asset_version_id
            or review.get("context_bundle_version_id") != context_bundle_version_id
            or review.get("target_text_hash") != prose_hash(str(draft.get("text") or ""))):
            raise KernelError("REVISION_DIAGNOSIS_STALE", "revision must consume diagnostics for its exact source candidate and Context")
    targeted = {}
    if review.get("cross_chapter_window") or review.get("craft_targets"):
        result, targeted = _materialize_targeted_result(draft, review, result)
    text = prose_from_output(result, separators=draft.get("scene_separators"))
    if length_scope is not None:
        validate_chapter_length_scope(length_scope, draft, text, source_asset_version_id=draft_asset_version_id,
            context_asset_version_id=context_bundle_version_id)
    if "creative_baseline" in draft:
        from novel_forge.modules.review.diagnostics import validate_prose_repair_scope
        validate_prose_repair_scope(draft, repair_diagnoses, text, length_scope=length_scope)
    if review.get("craft_targets"):
        from novel_forge.modules.review.craft import craft_revision_contract
        targeted["craft_revision_contract"] = craft_revision_contract(draft, review)
    resolved = sorted({str(item) for item in result.get("resolved_issue_codes", []) if str(item).strip()})
    open_blocking = {
        str(item.get("code") or "")
        for item in diagnoses
        if item.get("severity") == "blocking"
        and item.get("status", "OPEN") == "OPEN"
        and item.get("qualification", "ELIGIBLE") == "ELIGIBLE"
    }
    if not text.strip() or not open_blocking.issubset(set(resolved)):
        raise KernelError(
            "CHAPTER_REVISION_INCOMPLETE",
            "revision must provide text and resolve every eligible blocking issue",
        )
    resolutions = [
        {
            "code": str(item.get("code") or ""),
            "review_issue_id": str(item.get("review_issue_id") or ""),
            "from_status": item.get("status", "OPEN"),
            "to_status": (
                "RESOLUTION_CLAIMED"
                if item.get("code") in resolved
                else item.get("status", "OPEN")
            ),
        }
        for item in diagnoses
    ]
    assertions = result.get("canon_assertions", [])
    if not isinstance(assertions, list) or any(not isinstance(item, dict) for item in assertions):
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "canon_assertions must be objects")
    return {
        **reconcile_revision_composition(draft, result),
        **targeted,
        "project_id": project_id,
        "chapter": draft["chapter"],
        "title": draft["title"],
        "text": text,
        "source_draft_version_id": draft_asset_version_id,
        "creative_execution": dict(draft.get("creative_execution") or {}),
        **(
            {"creative_baseline": dict(draft["creative_baseline"])}
            if "creative_baseline" in draft
            else {}
        ),
        **(
            {"author_design_guidance": dict(draft["author_design_guidance"])}
            if draft.get("author_design_guidance")
            else {}
        ),
        "review_version_id": review_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "resolved_issue_codes": resolved,
        "resolution_claimed_issue_codes": resolved,
        "issue_resolutions": resolutions,
        "canon_assertions": assertions,
        "provider_evidence": dict(provider_evidence),
        **({"chapter_length_repair_scope": {**length_scope, "revised_han_characters": han_characters(text)}} if length_scope is not None else {}),
        "revision_contract_version": "revision-domain-v4" if "creative_baseline" in draft else "revision-domain-v3",
    }


def apply_quality_revision_result(
    *,
    project_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
    revision_tasks: tuple[dict[str, Any], ...],
    revision_task_asset_version_ids: tuple[str, ...],
    context_bundle_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    range_policy: str = "INTERSECTION_V1",
) -> dict[str, Any]:
    if not all(
        (
            project_id,
            revision_asset_version_id,
            quality_asset_version_id,
            context_bundle_version_id,
        )
    ) or not revision_tasks or len(revision_tasks) != len(
        revision_task_asset_version_ids
    ):
        raise KernelError(
            "QUALITY_REVISION_INPUT_INVALID",
            "Quality correction requires versioned target, decision, task, and context lineage",
        )
    scope = quality_edit_contract(revision=revision, revision_asset_version_id=revision_asset_version_id, revision_tasks=revision_tasks, range_policy=range_policy)
    targeted = {}
    if scope is not None:
        result, targeted = _materialize_targeted_result(
            revision,
            {"target_text_hash": scope["target_text_hash"], "issues": scope["permitted_ranges"]},
            result,
            range_policy=range_policy,
        )
    text = prose_from_output(result, separators=revision.get("scene_separators"))
    if not text.strip():
        raise KernelError(
            "QUALITY_REVISION_INCOMPLETE", "Quality correction produced no revised text"
        )
    if range_policy == 'NAMED_DIAGNOSIS_UNION_V1':
        admission = quality.get('internal_admission') or {}
        if (admission.get('version') not in {'creative-quality-admission.v2', 'creative-quality-admission.v3'} or admission.get('status') != 'BLOCKED'
            or admission.get('strict_certification_eligible') is not False
            or admission.get('target_asset_version_id') != revision_asset_version_id):
            raise KernelError('QUALITY_INTERNAL_DISPOSITION_REQUIRED','A source-bound blocked internal disposition is required')
        required_actions = list(quality.get('internal_required_actions') or [])
    else:
        required_actions = list(quality.get('required_actions') or [])
    expected = {
        str(item.get("observation") or item.get("issue", {}).get("code") or "")
        for item in required_actions
    }
    frozen = {
        str(item.get("observation") or item.get("issue", {}).get("code") or "")
        for item in revision_tasks
    }
    expected.discard("")
    frozen.discard("")
    if not expected or not frozen or not frozen.issubset(expected) or any(
        str(item.get("status") or "OPEN") != "OPEN" for item in revision_tasks
    ):
        raise KernelError(
            "QUALITY_REVISION_TASK_CONFLICT",
            "frozen RevisionTasks are not active aggregate Quality required actions",
        )
    if str(quality.get("project_id") or "") != project_id or any(
        str(item.get("project_id") or "") != project_id
        or str(item.get("target_revision_asset_version_id") or "")
        != revision_asset_version_id
        for item in revision_tasks
    ):
        raise KernelError(
            "QUALITY_REVISION_LINEAGE_CONFLICT",
            "Quality correction task scope does not match its frozen target revision",
        )
    source_text = str(revision.get("text") or "")
    minimum_preserved_ratio = 0.6
    if (
        len(source_text) >= 500
        and "chapter_length" not in frozen
        and len(text) < len(source_text) * minimum_preserved_ratio
    ):
        raise KernelError(
            "QUALITY_REVISION_SCOPE_INVALID",
            "bounded Quality correction cannot replace a complete chapter with a "
            "truncated summary or excerpt",
        )
    return {
        **revision,
        **reconcile_revision_composition(revision, result),
        **targeted,
        **({"quality_edit_contract": scope} if scope is not None else {}),
        "text": text,
        "source_revision_asset_version_id": revision_asset_version_id,
        "source_quality_asset_version_id": quality_asset_version_id,
        "quality_revision_task_asset_version_ids": list(
            revision_task_asset_version_ids
        ),
        "quality_action_observations": sorted(frozen),
        "context_bundle_version_id": context_bundle_version_id,
        "provider_evidence": dict(provider_evidence),
        "revision_contract_version": "quality-corrective-revision-v3" if "creative_baseline" in revision else "quality-corrective-revision-v2",
    }


__all__ = ["apply_quality_revision_result", "apply_revision_result"]


def freeze_quality_edit_scope(*, revision: dict[str, Any], revision_asset_version_id: str,
                            quality: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.review.diagnostics import prose_hash
    text = str(revision.get("text") or "")
    observation = str(action.get("observation") or "")
    locations = []
    for report in quality.get("evidence_reports", []):
        if (report.get("dimension") != observation or report.get("target_asset_version_id") != revision_asset_version_id
            or (report.get("gate_status") != "FAILED" and not (action.get("disposition_contract") == "creative-quality-disposition.v2" and report.get("semantic_verdict") == "FAILED"))):
            continue
        for location in report.get("evidence_locations", []):
            start, end = location.get("start"), location.get("end")
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                continue
            item = {"start": start, "end": end, "quote": text[start:end]}
            if item not in locations:
                locations.append(item)
    locations.sort(key=lambda item: (item["start"], item["end"]))
    merged = []
    for location in locations:
        if merged and location["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], location["end"])
            merged[-1]["quote"] = text[merged[-1]["start"]:merged[-1]["end"]]
        else:
            merged.append(dict(location))
    bounded = bool(merged) and sum(item["end"] - item["start"] for item in merged) < len(text)
    return {"contract_version": "quality-located-edit-scope.v1", "policy": "EXACT_NATIVE_EVIDENCE_RANGES_ONLY",
            "target_asset_version_id": revision_asset_version_id, "text_hash": prose_hash(text),
            "observation": observation, "status": "LOCATED" if bounded else "REQUIRES_LOCATED_EVIDENCE",
            "permitted_ranges": merged if bounded else [], "diagnostic_ranges": locations,
            "semantic_evidence": "MODEL_OR_RULE_CLAIM_REQUIRES_REVIEW", "whole_chapter_edit_authorized": False}


def quality_edit_contract(*, revision: dict[str, Any], revision_asset_version_id: str,
                          revision_tasks: tuple[dict[str, Any], ...], range_policy: str = "INTERSECTION_V1") -> dict[str, Any] | None:
    from novel_forge.modules.review.diagnostics import prose_hash, validate_location
    if not any(task.get("bounded_edit_scope") or task.get("contract_version") == "governed-revision-task-v2" for task in revision_tasks):
        return None
    text = str(revision.get("text") or "")
    ranges = []
    for task_index, task in enumerate(revision_tasks, start=1):
        scope = task.get("bounded_edit_scope") or {}
        if (scope.get("contract_version") != "quality-located-edit-scope.v1"
            or scope.get("status") != "LOCATED" or not scope.get("permitted_ranges")):
            raise KernelError("QUALITY_REVISION_LOCATION_REQUIRED", "Quality correction requires located native evidence; request an author decision instead of expanding to the whole chapter")
        if scope.get("target_asset_version_id") != revision_asset_version_id or scope.get("text_hash") != prose_hash(text):
            raise KernelError("QUALITY_REVISION_SCOPE_STALE", "Quality correction scope must bind the exact selected candidate")
        for index, location in enumerate(scope["permitted_ranges"]):
            located = validate_location(location, text)
            if located["start"] == 0 and located["end"] == len(text):
                raise KernelError("QUALITY_REVISION_SCOPE_INVALID", "Model evidence does not authorize whole-chapter edits")
            ranges.append({"code": str(task["issue"]["code"]) + f":task:{task_index}:range:{index + 1}",
                           "observation": task["observation"], "evidence_locator": located,
                           "status": "OPEN", "severity": "blocking", "qualification": "ELIGIBLE"})
    combined = []
    for item in sorted((row["evidence_locator"] for row in ranges), key=lambda row: (row["start"], row["end"])):
        if combined and item["start"] <= combined[-1][1]:
            combined[-1][1] = max(combined[-1][1], item["end"])
        else:
            combined.append([item["start"], item["end"]])
    if sum(end - start for start, end in combined) >= len(text):
        raise KernelError("QUALITY_REVISION_SCOPE_INVALID", "Combined task evidence cannot authorize a whole-chapter rewrite")
    if range_policy == "NAMED_DIAGNOSIS_UNION_V1" and any(task.get("disposition_contract") != "creative-quality-disposition.v2" for task in revision_tasks):
        raise KernelError("QUALITY_RANGE_POLICY_SCOPE_INVALID", "The union successor requires exact creative internal disposition tasks")
    return {"contract_version": "quality-targeted-repair.v2" if range_policy == "NAMED_DIAGNOSIS_UNION_V1" else "quality-targeted-repair.v1", **({"range_policy": range_policy} if range_policy == "NAMED_DIAGNOSIS_UNION_V1" else {}), "target_asset_version_id": revision_asset_version_id,
            "target_text_hash": prose_hash(text), "permitted_ranges": ranges,
            "instructions": ("For each edit, every named range must intersect it and their connected union must cover the edit, without gaps. " if range_policy == "NAMED_DIAGNOSIS_UNION_V1" else "") + "Return exact ordered non-overlapping edits, naming the permitted range code in issue_codes. Edit only inside those frozen ranges. Keep every other Unicode code point unchanged, including whitespace. Preserve adopted Craft, facts and accepted history. Updated scene artifacts must reconstruct the same resulting text. Unresolved or unlocated evidence requires author review, never wider edits."}


def extend_quality_rereview_schema(schema: dict[str, Any], *, legacy_contract: bool = False) -> dict[str, Any]:
    from copy import deepcopy
    result = deepcopy(schema)
    fields = {
        "observation": {"type": "string", "minLength": 1},
        "status": {"type": "string", "enum": ["SATISFIED", "UNRESOLVED", "UNCERTAIN"]},
        "preservation": {"type": "string", "enum": ["PRESERVED", "REGRESSED", "UNCERTAIN"]},
        "evidence": {"type": "object", "properties": {
            **({"start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1}} if legacy_contract else {}),
            "quote": {"type": "string", "minLength": 1}}, "required": (["start", "end", "quote"] if legacy_contract else ["quote"]), "additionalProperties": False},
        "reason": {"type": "string", "minLength": 1},
    }
    result["properties"]["quality_resolution_checks"] = {"type": "array", "minItems": 1,
        "items": {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}}
    result["required"].append("quality_resolution_checks")
    return result


def validate_quality_resolution_checks(*, revision: dict[str, Any], revision_asset_version_id: str,
                                       result: dict[str, Any]) -> list[dict[str, Any]]:
    from novel_forge.modules.review.diagnostics import prose_hash, validate_location
    scope = revision.get("quality_edit_contract")
    if not scope:
        return []
    expected = set(revision.get("quality_action_observations") or [])
    rows = result.get("quality_resolution_checks")
    if (not isinstance(rows, list) or not expected or len(rows) != len(expected)
        or {row.get("observation") for row in rows if isinstance(row, dict)} != expected):
        raise KernelError("QUALITY_REREVIEW_CHECKS_REQUIRED", "ReReview must explicitly disposition every frozen Quality action separately from Review diagnoses")
    normalized = []
    for row in rows:
        if (row.get("status") not in {"SATISFIED", "UNRESOLVED", "UNCERTAIN"}
            or row.get("preservation") not in {"PRESERVED", "REGRESSED", "UNCERTAIN"}
            or not str(row.get("reason") or "").strip()):
            raise KernelError("QUALITY_REREVIEW_CHECKS_INVALID", "Quality action check requires explicit status, preservation and evidence reasoning")
        evidence = validate_location(dict(row.get("evidence") or {}), str(revision["text"]))
        normalized.append({**row, "evidence": evidence, "target_asset_version_id": revision_asset_version_id,
            "target_text_hash": prose_hash(revision["text"]), "source_asset_version_id": scope["target_asset_version_id"],
            "source_text_hash": scope["target_text_hash"],
            "source_quality_asset_version_id": revision["source_quality_asset_version_id"],
            "evidence_class": "MODEL_REVIEW_PROPOSAL_REQUIRES_QUALITY_REEVALUATION"})
    return normalized


def han_characters(text: str) -> int:
    import unicodedata
    return sum(unicodedata.name(char, '').startswith(('CJK UNIFIED IDEOGRAPH-', 'CJK COMPATIBILITY IDEOGRAPH-')) for char in text)


def freeze_chapter_length_scope(source: dict[str, Any], *, source_asset_version_id: str,
                                context: dict[str, Any], context_asset_version_id: str) -> dict[str, Any] | None:
    from novel_forge.modules.chapter_quality_authority.context_views import compile_platform_policy
    from novel_forge.modules.review.diagnostics import prose_hash
    profiles = []
    for segment in context.get('context_segments', []):
        if segment.get('asset_type') != 'platform_profile':
            continue
        profile_id = segment['asset_version_id']
        rules = compile_platform_policy(profile_asset_version_id=profile_id, segment=segment).chapter_length_rules
        if rules.get('unit') == 'HAN_CHARACTERS_V1':
            profiles.append((segment, rules))
    if not profiles:
        return None
    if len(profiles) != 1:
        raise KernelError('CHAPTER_LENGTH_SCOPE_PROFILE_CONFLICT', 'Length correction requires one exact frozen Platform profile')
    segment, rules = profiles[0]
    minimum, maximum = rules.get('minimum'), rules.get('maximum')
    if type(minimum) is not int or type(maximum) is not int or not 0 < minimum <= maximum:
        raise KernelError('CHAPTER_LENGTH_POLICY_INVALID', 'Frozen length bounds must be positive ordered integers')
    text = str(source.get('text') or '')
    observed = han_characters(text)
    if minimum <= observed <= maximum:
        return None
    return {'contract_version':'chapter-length-repair.v1', 'scope':'WHOLE_CHAPTER_LENGTH_CORRECTION',
        'source_asset_version_id':source_asset_version_id, 'source_text_hash':prose_hash(text),
        'context_asset_version_id':context_asset_version_id, 'platform_profile_asset_version_id':segment['asset_version_id'],
        'platform_profile_content_hash':segment.get('content_digest'), 'unit':'HAN_CHARACTERS_V1',
        'minimum':minimum, 'maximum':maximum, 'source_han_characters':observed,
        'preservation':'FROZEN_SCENES_FACTS_VOICE_QUALITY_AND_REVIEW_REQUIRED'}


def validate_chapter_length_scope(scope: dict[str, Any], source: dict[str, Any], text: str, *,
                                  source_asset_version_id: str, context_asset_version_id: str) -> None:
    from novel_forge.modules.review.diagnostics import prose_hash
    original = str(source.get('text') or '')
    minimum, maximum = scope.get('minimum'), scope.get('maximum')
    if (scope.get('contract_version') != 'chapter-length-repair.v1' or scope.get('unit') != 'HAN_CHARACTERS_V1'
        or scope.get('scope') != 'WHOLE_CHAPTER_LENGTH_CORRECTION'
        or scope.get('source_asset_version_id') != source_asset_version_id or scope.get('context_asset_version_id') != context_asset_version_id
        or scope.get('source_text_hash') != prose_hash(original) or scope.get('source_han_characters') != han_characters(original)
        or type(minimum) is not int or type(maximum) is not int or not 0 < minimum <= maximum
        or minimum <= han_characters(original) <= maximum):
        raise KernelError('CHAPTER_LENGTH_SCOPE_INVALID', 'Only an exact out-of-bounds frozen candidate authorizes whole-chapter length repair')
    if not minimum <= han_characters(text) <= maximum:
        raise KernelError('CHAPTER_LENGTH_REPAIR_INCOMPLETE', f'Actual HAN_CHARACTERS_V1 count {han_characters(text)} is outside frozen bounds {minimum}–{maximum}; repair the full candidate without padding')


def retain_reviewed_draft(*, draft, draft_id, draft_hash, review, review_id, review_hash, context_id, context_hash):
    from copy import deepcopy
    from novel_forge.modules.review.diagnostics import open_diagnoses, prose_hash, require_review_score
    if review.get("review_decision_contract") != "work-review-decision.v1" or review.get("decision") != "PASSED" or open_diagnoses(review):
        return None
    require_review_score(review)
    if (review.get("target_asset_version_id") != draft_id or review.get("context_bundle_version_id") != context_id
        or review.get("target_text_hash") != prose_hash(draft.get("text", ""))):
        raise KernelError("REVISION_DIAGNOSIS_STALE", "Retention requires the exact reviewed draft and Context")
    if "creative_baseline" in draft:
        from novel_forge.modules.chapter_authority.chapter_plan_views import validate_creative_baseline
        if review.get("creative_baseline_digest") != validate_creative_baseline(draft["creative_baseline"])["baseline_digest"]:
            raise KernelError("REVISION_CREATIVE_BASELINE_DRIFT", "Retention cannot reuse a different work contract")
    proof = {"contract_version": "unchanged-reviewed-prose.v1", "decision": "NO_REPAIR_REQUIRED",
        "source_draft_asset_version_id": draft_id, "source_draft_content_hash": draft_hash,
        "source_review_asset_version_id": review_id, "source_review_content_hash": review_hash,
        "context_bundle_asset_version_id": context_id, "context_bundle_content_hash": context_hash,
        "target_text_hash": review["target_text_hash"], "provider_dispatches": 0, "improvement_claimed": False}
    return {**deepcopy(draft), "source_draft_version_id": draft_id, "review_version_id": review_id,
        "context_bundle_version_id": context_id, "resolved_issue_codes": [], "resolution_claimed_issue_codes": [],
        "issue_resolutions": [], "revision_execution_decision": proof,
        "provider_evidence": {"evidence_class": "NATIVE_RETENTION", "source_review_asset_version_id": review_id}}


def reuse_unchanged_review(*, draft, draft_id, draft_hash, review, review_id, review_hash, revision, revision_id, context_id, context_hash):
    from copy import deepcopy
    expected = retain_reviewed_draft(draft=draft, draft_id=draft_id, draft_hash=draft_hash,
        review=review, review_id=review_id, review_hash=review_hash, context_id=context_id, context_hash=context_hash)
    if expected is None or not revision.get("revision_execution_decision"):
        return None
    if revision != expected:
        raise KernelError("REREVIEW_RETENTION_DRIFT", "A changed candidate cannot reuse the original Review")
    score = review["score"]
    return {**deepcopy(review), "report_type": "ReReviewReport", "target_asset_version_id": revision_id,
        "revision_version_id": revision_id, "original_draft_version_id": draft_id, "initial_review_version_id": review_id,
        "issue_lineage": [], "resolution_checks": [], "resolved_issue_codes": [], "remaining_issue_codes": [],
        "unresolved_issues": [], "new_issues": [], "regression_issue_codes": [],
        "revision_quality_delta": {"before_score": score, "after_score": score, "score_delta": 0,
            "resolved_issue_count": 0, "remaining_issue_count": 0, "new_issue_count": 0, "regression_count": 0},
        "review_reuse_evidence": {**expected["revision_execution_decision"], "decision": "REUSED_EXACT_REVIEW",
            "target_revision_asset_version_id": revision_id}, "provider_evidence": {
            "evidence_class": "NATIVE_REVIEW_REUSE", "source_review_asset_version_id": review_id,
            "source_review_provider_evidence": deepcopy(review.get("provider_evidence") or {})}}
