from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


DIAGNOSTIC_CONTRACT = "actionable-diagnostics.v1"


def constrain_diagnosis_schema(schema: dict[str, Any], *, cross_categories: tuple[str, ...] = ()) -> dict[str, Any]:
    base = {key: deepcopy(value) for key, value in schema.items() if key != "anyOf"}
    variants = []

    def variant(judgments: list[str], severities: list[str], *, cross: bool = False, blocking: bool = False) -> None:
        item = deepcopy(base)
        fields = item["properties"]
        fields["judgment_kind"] = {"type": "string", "enum": judgments}
        fields["severity"] = {"type": "string", "enum": severities}
        if cross_categories:
            fields["category"] = ({"type": "string", "enum": list(cross_categories)} if cross else
                                  {**fields["category"], "pattern": "^(?!(?:" + "|".join(cross_categories) + ")$).+"})
        if cross:
            fields["supporting_evidence"]["minItems"] = 1
            if blocking:
                fields["confidence"] = {"type": "string", "enum": ["HIGH"]}
                fields["interpretation"] = {"type": "string", "enum": ["CONTINUITY_PROBLEM"]}
        variants.append(item)

    variant(["SEMANTIC_CONFLICT"], ["blocking", "major", "minor"])
    variant(["AESTHETIC_SUGGESTION"], ["minor"])
    variant(["UNCERTAIN"], ["major", "minor"])
    if cross_categories:
        variant(["HARD_CONTRACT_VIOLATION", "SEMANTIC_CONTRADICTION"], ["blocking"], cross=True, blocking=True)
        variant(["HARD_CONTRACT_VIOLATION", "SEMANTIC_CONTRADICTION", "LIKELY_CONTINUITY_PROBLEM", "UNCERTAIN"], ["major", "minor"], cross=True)
        variant(["AESTHETIC_SUGGESTION"], ["minor"], cross=True)
    return {**base, "anyOf": variants}


def require_review_score(review: dict[str, Any]) -> float:
    value = review.get("score")
    if (type(value) not in {int, float} or not math.isfinite(value)
        or not 0 <= value <= 100):
        raise KernelError("REVIEW_EVIDENCE_REQUIRED", "candidate review requires an explicit finite score")
    return float(value)


def open_diagnoses(review: dict[str, Any]) -> list[dict[str, Any]]:
    current, carried = review.get("issues"), review.get("unresolved_issues", [])
    if not isinstance(current, list) or not isinstance(carried, list):
        raise KernelError("REVIEW_EVIDENCE_REQUIRED", "review requires an explicit diagnosis ledger")
    result: dict[str, dict[str, Any]] = {}
    for item in [*carried, *current]:
        if not isinstance(item, dict) or not item.get("code") or not item.get("severity"):
            raise KernelError("REVIEW_EVIDENCE_REQUIRED", "diagnosis identity and severity are required")
        code = str(item["code"])
        previous = result.get(code)
        merged = dict(item)
        if previous is not None:
            merged["origin_review_issue_id"] = previous.get("origin_review_issue_id", previous.get("review_issue_id"))
            if previous["severity"] == "blocking":
                merged["severity"] = "blocking"
            for field in ("preserve", "acceptance_criteria"):
                if field in previous or field in merged:
                    merged[field] = list(dict.fromkeys([*previous.get(field, []), *merged.get(field, [])]))
        result[code] = merged
    if set(review.get("remaining_issue_codes", [])) - set(result):
        raise KernelError("REVIEW_EVIDENCE_REQUIRED", "unresolved issue codes require their immutable diagnoses")
    return list(result.values())


def prose_repair_diagnoses(review: dict[str, Any], *, work_requirements: bool = False) -> list[dict[str, Any]]:
    diagnoses = open_diagnoses(review)
    if not work_requirements:
        return diagnoses
    requested = review.get("working_revision_request") or {}
    aesthetic_requested = (requested.get("contract_version") == "chapter-working-revision.v1"
        and requested.get("aesthetic_revision_requested") is True
        and requested.get("source_asset_version_id") == review.get("target_asset_version_id"))
    return [item for item in diagnoses if (item.get("judgment_kind") in {
        "SEMANTIC_CONFLICT", "HARD_CONTRACT_VIOLATION", "SEMANTIC_CONTRADICTION", "LIKELY_CONTINUITY_PROBLEM"
    } or aesthetic_requested and item.get("judgment_kind") == "AESTHETIC_SUGGESTION")
        and item.get("status", "OPEN") == "OPEN"]


def validate_prose_repair_scope(source: dict[str, Any], diagnoses: list[dict[str, Any]], text: str, *, length_scope: dict[str, Any] | None = None) -> None:
    from difflib import SequenceMatcher
    original = str(source.get("text") or "")
    if structural_repair_scope(diagnoses) == "CHAPTER_REVISION":
        for issue in diagnoses:
            validate_location(dict(issue.get("evidence_locator") or {}), original)
        return
    scopes = []
    artifacts = source.get("scene_artifacts") or []
    separators = source.get("scene_separators") or ["\n\n"] * max(0, len(artifacts) - 1)
    scene_ranges = []
    position = 0
    for index, artifact in enumerate(artifacts):
        position += len(separators[index - 1]) if index else 0
        end = position + len(artifact["text"])
        scene_ranges.append((position, end))
        position = end
    for issue in diagnoses:
        location = validate_location(dict(issue.get("evidence_locator") or {}), original)
        if scene_ranges:
            matched = [bounds for bounds in scene_ranges if bounds[0] < location["end"] and bounds[1] > location["start"]]
            if not matched:
                raise KernelError("REVISION_DIAGNOSIS_SCOPE_INVALID", "Diagnosis does not locate a prose Scene")
            scopes.append((matched[0][0], matched[-1][1]))
        else:
            scopes.append((original.rfind("\n\n", 0, location["start"]) + 2 if "\n\n" in original[:location["start"]] else 0,
                original.find("\n\n", location["end"]) if "\n\n" in original[location["end"]:] else len(original)))
    if length_scope is not None:
        from novel_forge.modules.revision.domain import validate_chapter_length_scope
        validate_chapter_length_scope(length_scope, source, text, source_asset_version_id=length_scope["source_asset_version_id"],
            context_asset_version_id=length_scope["context_asset_version_id"])
        scopes.append((0, len(original)))
    for tag, start, end, _, _ in SequenceMatcher(None, original, text, autojunk=False).get_opcodes():
        if tag != "equal" and not any(low <= start <= end <= high for low, high in scopes):
            raise KernelError("REVISION_OUTSIDE_DIAGNOSIS_SCOPE", "Revision changed an unaffected Scene or paragraph; evidence uncertainty and aesthetic advice do not authorize prose changes")


def blocking_diagnosis_codes(review: dict[str, Any]) -> tuple[str, ...]:
    codes = tuple(sorted({str(item["code"]) for item in open_diagnoses(review)
                          if item["severity"] in {"blocking", "blocker", "critical", "high"}}))
    if (review.get("blocking_issue_count", 0) and not codes) or (review.get("decision") == "BLOCKED" and not codes):
        raise KernelError("REVIEW_EVIDENCE_REQUIRED", "blocking review requires retained blocking diagnoses")
    return codes


def major_contradiction_codes(review: dict[str, Any], *, text: str, source_id: str) -> tuple[str, ...]:
    if (review.get("target_asset_version_id") != source_id and review.get("revision_version_id") != source_id
            or review.get("target_text_hash") != prose_hash(text)):
        return ()
    return tuple(sorted({str(item["code"]) for item in open_diagnoses(review)
        if item.get("judgment_kind") in {"HARD_CONTRACT_VIOLATION", "SEMANTIC_CONTRADICTION", "SEMANTIC_CONFLICT"}
        and item.get("status", "OPEN") == "OPEN"
        and item.get("severity") in {"blocking", "blocker", "critical", "high", "major"}}))


def prose_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def validate_location(location: dict[str, Any], text: str) -> dict[str, Any]:
    start, end = location.get("start"), location.get("end")
    quote = location.get("quote")
    if start is None and end is None:
        if not isinstance(quote, str) or not quote:
            raise KernelError("REVIEW_EVIDENCE_INVALID", "evidence quote is required")
        start = text.find(quote)
        if start < 0:
            raise KernelError("REVIEW_EVIDENCE_INVALID", "evidence quote is absent from its exact candidate")
        if text.find(quote, start + 1) >= 0:
            raise KernelError("REVIEW_EVIDENCE_AMBIGUOUS", "evidence quote occurs more than once in its exact candidate")
        end = start + len(quote)
    if (type(start) is not int or type(end) is not int
        or not 0 <= start < end <= len(text) or quote != text[start:end]):
        raise KernelError("REVIEW_EVIDENCE_INVALID", "diagnosis requires a literal Unicode code-point span in its exact candidate")
    return {**location, "start": start, "end": end, "excerpt_digest": prose_hash(text[start:end]), "offset_unit": "UNICODE_CODE_POINT"}


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
    if issue["judgment_kind"] == "UNCERTAIN" and issue.get("severity") == "blocking":
        raise KernelError("REVIEW_JUDGMENT_INVALID", "uncertain evidence cannot block acceptance")
    repair = issue.get("repair")
    if repair is not None:
        from .repair_scope import validate_repair
        validate_repair(repair)
    return {**{key: issue[key] for key in (*required, "preserve", "acceptance_criteria")},
            **({"repair": dict(repair)} if repair is not None else {}),
            "evidence_locator": validate_location(dict(issue.get("evidence") or {}), text),
            "revision_strategy": issue["revision_goal"]}


def structural_repair_scope(diagnoses):
    from .repair_scope import validate_repair
    scopes = []
    for issue in diagnoses:
        repair = issue.get("repair")
        if repair is None:
            continue
        validate_repair(repair)
        if (repair["problem_owner"] == "PROSE" and issue.get("status", "OPEN") == "OPEN"
                and issue.get("judgment_kind") not in {"UNCERTAIN", "AESTHETIC_SUGGESTION"}):
            scopes.append(repair["repair_scope"])
    return "CHAPTER_REVISION" if "CHAPTER_REVISION" in scopes else "SCENE_REVISION" if "SCENE_REVISION" in scopes else "LOCAL_PROSE"


def verified_resolutions(result: dict[str, Any], initial: dict[str, Any], text: str) -> set[str]:
    checks = result.get("resolution_checks")
    if not isinstance(checks, list):
        raise KernelError("REVIEW_RESOLUTION_CHECKS_REQUIRED", "rereview requires explicit per-diagnosis checks")
    issues = {item["code"]: item for item in open_diagnoses(initial)}
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
