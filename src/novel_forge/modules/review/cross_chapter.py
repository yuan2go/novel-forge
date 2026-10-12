from __future__ import annotations

from copy import deepcopy
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from .diagnostics import (
    open_diagnoses,
    prose_hash,
    validate_diagnosis,
    validate_location,
)
from .prose_window import (
    CROSS_CHAPTER_CATEGORIES,
    PRESERVATION_DIMENSIONS,
    digest,
    validate_support,
)


JUDGMENTS = (
    "HARD_CONTRACT_VIOLATION",
    "SEMANTIC_CONTRADICTION",
    "LIKELY_CONTINUITY_PROBLEM",
    "AESTHETIC_SUGGESTION",
    "UNCERTAIN",
)


def _source_locations(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: item[key]
            for key in (
                "asset_version_id",
                "content_hash",
                "text_hash",
                "chapter_number",
                "start",
                "end",
                "quote",
            )
        }
        for item in evidence
    ]


def paired_diagnosis(
    issue: dict[str, Any],
    *,
    text: str,
    window: dict[str, Any],
    prior: dict[str, Any] | None = None,
    target_asset_version_id: str = "",
) -> dict[str, Any]:
    category, judgment = issue.get("category"), issue.get("judgment_kind")
    if (
        judgment in {"UNCERTAIN", "AESTHETIC_SUGGESTION"}
        and issue.get("severity") == "blocking"
    ):
        raise KernelError(
            "REVIEW_JUDGMENT_INVALID", "uncertain or aesthetic judgments cannot block"
        )
    if category not in CROSS_CHAPTER_CATEGORIES:
        return validate_diagnosis(issue, text)
    if judgment not in JUDGMENTS or issue.get("confidence") not in {
        "HIGH",
        "MEDIUM",
        "LOW",
    }:
        raise KernelError(
            "REVIEW_JUDGMENT_INVALID", "cross-chapter judgment and confidence required"
        )
    current_id = target_asset_version_id or window.get("target_candidate_asset_version_id")
    supplied = issue.get("supporting_evidence")
    if not isinstance(supplied, list) or not supplied:
        support = validate_support(supplied, window)
        candidate_support = []
    else:
        candidate_support = []
        earlier_support = []
        for item in supplied:
            if not isinstance(item, dict) or item.get("asset_version_id") != current_id:
                earlier_support.append(item)
                continue
            if (not str(item.get("relation_to_issue") or "").strip()
                or item.get("text_hash", prose_hash(text)) != prose_hash(text)
                or item.get("chapter_number", window.get("target_chapter_number")) != window.get("target_chapter_number")
                or "content_hash" in item):
                raise KernelError("REVIEW_EVIDENCE_INVALID", "current support requires exact candidate prose identity")
            candidate_support.append({**validate_location(item, text),
                "asset_version_id": current_id, "text_hash": prose_hash(text),
                "chapter_number": window.get("target_chapter_number"),
                "relation_to_issue": item["relation_to_issue"], "evidence_scope": "CURRENT_CANDIDATE"})
        support = validate_support(earlier_support, window) if earlier_support else []
    location = validate_location(dict(issue.get("evidence") or {}), text)
    intentional = issue.get("interpretation")
    if intentional not in {
        "CONTINUITY_PROBLEM",
        "INTENTIONAL_RECAP",
        "MOTIF",
        "REINTERPRETATION",
        "NEW_POV",
        "INFORMATION_UPGRADE",
        "DRAMATIC_REPETITION",
        "MOTIVATED_CHANGE",
        "UNCERTAIN",
    }:
        raise KernelError(
            "REVIEW_JUDGMENT_INVALID",
            "diagnosis must distinguish intentional narrative variation",
        )
    blocking = issue.get("severity") == "blocking"
    if blocking and (
        judgment not in {"HARD_CONTRACT_VIOLATION", "SEMANTIC_CONTRADICTION"}
        or issue["confidence"] != "HIGH"
        or intentional != "CONTINUITY_PROBLEM"
    ):
        raise KernelError(
            "REVIEW_JUDGMENT_INVALID",
            "uncertain, aesthetic or intentional variation cannot block",
        )
    if judgment == "HARD_CONTRACT_VIOLATION" and issue.get(
        "violated_constraint"
    ) not in window["preservation_requirements"].get("approved_hard_constraints", []):
        raise KernelError(
            "REVIEW_JUDGMENT_INVALID",
            "hard violation must identify an approved frozen constraint",
        )
    base = validate_diagnosis(
        {
            **issue,
            "judgment_kind": judgment
            if judgment in {"AESTHETIC_SUGGESTION", "UNCERTAIN"}
            else "SEMANTIC_CONFLICT",
        },
        text,
    )
    identity = {
        "category": category,
        "target": {k: location[k] for k in ("start", "end", "quote")},
        "support": [
            {k: value[k] for k in ("asset_version_id", "start", "end")}
            for value in support
        ],
        "candidate_support": [{k: value[k] for k in ("asset_version_id", "start", "end")}
                              for value in candidate_support],
        "window": window["source_window_hash"],
    }
    code = "CC-" + str(category) + "-" + digest(identity).split(":")[1][:20].upper()
    lineage = issue.get("lineage_code")
    reassessment = {}
    if lineage:
        original = next(
            (
                item
                for item in open_diagnoses(prior or {"issues": []})
                if item["code"] == lineage
            ),
            None,
        )
        frozen_support = original.get("supporting_evidence", []) if original else []
        anchors = _source_locations(frozen_support)
        if (original is not None and original.get("category") == category and _source_locations(support) == anchors
                and all(original.get(key) == issue.get(key) for key in ("judgment_kind", "severity", "confidence", "interpretation"))
                and all((original.get("repair") or {}).get(key) == (issue.get("repair") or {}).get(key)
                    for key in ("problem_owner", "root_cause"))):
            code = str(lineage)
            reassessment = {"reassessment_supporting_evidence": support}
            support = deepcopy(frozen_support)
        else:
            code = "CC-" + str(category) + "-" + digest({"identity": identity, "unverified_lineage": lineage,
                "judgment_kind": judgment, "severity": issue.get("severity"), "interpretation": intentional}).split(":")[1][:20].upper()
            reassessment = {"unverified_lineage_code": str(lineage), "lineage_status": "UNVERIFIED"}
    return {
        **base,
        "code": code,
        "diagnosis_identity": code,
        "judgment_kind": judgment,
        "confidence": issue["confidence"],
        "interpretation": intentional,
        "supporting_evidence": support,
        **reassessment,
        **({"candidate_supporting_evidence": candidate_support} if candidate_support else {}),
        "source_window_hash": window["source_window_hash"],
    }


def resolution_checks(
    result: dict[str, Any], initial: dict[str, Any], text: str
) -> list[dict[str, Any]]:
    issues = {issue["code"]: issue for issue in open_diagnoses(initial)}
    checks = result.get("resolution_checks")
    if (
        not isinstance(checks, list)
        or len(checks) != len(issues)
        or {check.get("code") for check in checks} != set(issues)
    ):
        raise KernelError(
            "REVIEW_RESOLUTION_CHECKS_REQUIRED",
            "every prior diagnosis needs an explicit unique disposition",
        )
    normalized = []
    for check in checks:
        if check.get("status") not in {
            "RESOLVED",
            "PARTIALLY_RESOLVED",
            "UNRESOLVED",
            "REGRESSED",
            "NOT_APPLICABLE",
        }:
            raise KernelError(
                "REVIEW_RESOLUTION_INVALID",
                "explicit cross-chapter resolution status required",
            )
        validate_location(dict(check.get("evidence") or {}), text)
        prior = issues[check["code"]]
        if prior.get("supporting_evidence"):
            support = validate_support(
                check.get("supporting_evidence"), initial["cross_chapter_window"]
            )
            if _source_locations(support) != _source_locations(prior["supporting_evidence"]):
                check = {**check, "reassessment_supporting_evidence": support,
                    "supporting_evidence": deepcopy(prior["supporting_evidence"]),
                    "claimed_resolution_status": check["status"], "resolution_evidence_status": "INCOMPLETE_ORIGINAL_SUPPORT",
                    "status": "UNRESOLVED" if check["status"] == "RESOLVED" else check["status"]}
        normalized.append(
            {
                **check,
                "resolution_status": check["status"],
                "status": "SATISFIED"
                if check["status"] == "RESOLVED"
                else check["status"],
            }
        )
    preservation = result.get("preservation_checks")
    if (
        not isinstance(preservation, list)
        or len(preservation) != len(PRESERVATION_DIMENSIONS)
        or {check.get("dimension") for check in preservation}
        != set(PRESERVATION_DIMENSIONS)
    ):
        raise KernelError(
            "REVIEW_PRESERVATION_REQUIRED",
            "rereview must explicitly assess all frozen preservation dimensions",
        )
    for check in preservation:
        if (
            check.get("status") not in {"PRESERVED", "REGRESSED", "UNCERTAIN"}
            or not str(check.get("reason") or "").strip()
        ):
            raise KernelError(
                "REVIEW_PRESERVATION_REQUIRED",
                "preservation requires status and evidence reasoning",
            )
        validate_location(dict(check.get("evidence") or {}), text)
    return normalized


def apply_targeted_edits(
    *, draft: dict[str, Any], review: dict[str, Any], result: dict[str, Any], range_policy: str = "INTERSECTION_V1"
) -> dict[str, Any]:
    text = str(draft.get("text") or "")
    if review.get("target_text_hash") != prose_hash(text):
        raise KernelError(
            "REVISION_DIAGNOSIS_STALE", "targeted repair source has changed"
        )
    diagnoses = {item["code"]: item for item in open_diagnoses(review)}
    edits = result.get("edits")
    if not isinstance(edits, list):
        raise KernelError(
            "REVISION_TARGETED_EDITS_REQUIRED",
            "targeted repair requires located edits",
        )
    previous_end, pieces = 0, []
    located_edits: list[dict[str, Any]] = []
    for edit in edits:
        location = validate_location(edit, text)
        codes = edit.get("issue_codes")
        if (
            not isinstance(codes, list)
            or not codes
            or set(codes) - set(diagnoses)
            or location["start"] < previous_end
            or not isinstance(edit.get("replacement"), str)
        ):
            raise KernelError(
                "REVISION_TARGETED_EDIT_INVALID",
                "ordered non-overlapping edits must name existing diagnoses",
            )
        if range_policy == 'NAMED_DIAGNOSIS_UNION_V1':
            ranges = sorted((diagnoses[code]['evidence_locator']['start'],diagnoses[code]['evidence_locator']['end']) for code in codes)
            merged = []
            for low,high in ranges:
                if max(low,location['start']) >= min(high,location['end']):
                    raise KernelError('REVISION_TARGETED_EDIT_INVALID','Every named finding must intersect its edit')
                if merged and low <= merged[-1][1]:
                    merged[-1][1] = max(high,merged[-1][1])
                else:
                    merged.append([low,high])
            if not any(low <= location['start'] < location['end'] <= high for low,high in merged):
                raise KernelError('REVISION_TARGETED_EDIT_INVALID','Every changed code point must remain in the connected named frozen scope')
        elif range_policy == 'INTERSECTION_V1':
            for code in codes:
                target = diagnoses[code]["evidence_locator"]
                if (
                    not target["start"]
                    <= location["start"]
                    < location["end"]
                    <= target["end"]
                ):
                    raise KernelError(
                        "REVISION_TARGETED_EDIT_INVALID",
                        "repair cannot change prose outside diagnosed locations",
                    )
        else:
            raise KernelError('REVISION_RANGE_POLICY_INVALID','An explicit supported range policy is required')
        pieces.extend((text[previous_end : location["start"]], edit["replacement"]))
        located_edits.append({**edit, "start": location["start"], "end": location["end"]})
        previous_end = location["end"]
    pieces.append(text[previous_end:])
    repaired = "".join(pieces)
    if "text" in result and result["text"] != repaired:
        raise KernelError(
            "REVISION_TARGETED_EDIT_INVALID",
            "returned prose differs from exact diagnosed edits",
        )
    return {
        "targeted_edits": located_edits,
        "repaired_text": repaired,
        **({"source_window_hash": review["cross_chapter_window"]["source_window_hash"],
            "preservation_requirements": deepcopy(review["cross_chapter_window"]["preservation_requirements"])}
           if review.get("cross_chapter_window") else {}),
    }


def extend_provider_schema(schema: dict[str, Any], stage: str, *, legacy_contract: bool = False) -> dict[str, Any]:
    result = deepcopy(schema)
    text = {"type": "string", "minLength": 1}
    location = {**({"start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1}} if legacy_contract else {}), "quote": text}

    def obj(fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": fields,
            "required": list(fields),
            "additionalProperties": False,
        }

    if stage == "revision":
        if "edits" in result["properties"]:
            return result
        result["properties"]["edits"] = {
            "type": "array",
            "items": obj(
                {
                    **location,
                    "replacement": {"type": "string"},
                    "issue_codes": {"type": "array", "minItems": 1, "items": text},
                }
            ),
        }
        result["required"].append("edits")
        return result
    support = {
        "type": "array",
        "items": obj(
            {
                **location,
                **({"chapter_number": {"type": "integer", "minimum": 1}} if legacy_contract else {}),
                "asset_version_id": text,
                **({"content_hash": text, "text_hash": text} if legacy_contract else {}),
                "relation_to_issue": text,
            }
        ),
    }
    issue = result["properties"]["issues"]["items"]
    issue["properties"]["judgment_kind"]["enum"] = [*JUDGMENTS, "SEMANTIC_CONFLICT"]
    additions = {
        "supporting_evidence": support,
        "lineage_code": {"type": ["string", "null"]},
        "confidence": {"enum": ["HIGH", "MEDIUM", "LOW"]},
        "interpretation": {
            "enum": [
                "CONTINUITY_PROBLEM",
                "INTENTIONAL_RECAP",
                "MOTIF",
                "REINTERPRETATION",
                "NEW_POV",
                "INFORMATION_UPGRADE",
                "DRAMATIC_REPETITION",
                "MOTIVATED_CHANGE",
                "UNCERTAIN",
            ]
        },
    }
    issue["properties"].update(additions)
    issue["required"].extend(additions)
    if legacy_contract:
        target = issue["properties"]["evidence"]
        target["properties"].update({"asset_version_id": text, "text_hash": text})
        target["required"].extend(["asset_version_id", "text_hash"])
    check = result["properties"]["resolution_checks"]["items"]
    check["properties"]["status"]["enum"] = [
        "RESOLVED",
        "PARTIALLY_RESOLVED",
        "UNRESOLVED",
        "REGRESSED",
        "NOT_APPLICABLE",
    ]
    check["properties"]["supporting_evidence"] = support
    check["required"].append("supporting_evidence")
    result["properties"]["preservation_checks"] = {
        "type": "array",
        "items": obj(
            {
                "dimension": {"enum": list(PRESERVATION_DIMENSIONS)},
                "status": {"enum": ["PRESERVED", "REGRESSED", "UNCERTAIN"]},
                "evidence": obj(location),
                "reason": text,
            }
        ),
    }
    result["required"].append("preservation_checks")
    from .diagnostics import constrain_diagnosis_schema
    result["properties"]["issues"]["items"] = constrain_diagnosis_schema(issue, cross_categories=tuple(sorted(CROSS_CHAPTER_CATEGORIES)))
    return result
