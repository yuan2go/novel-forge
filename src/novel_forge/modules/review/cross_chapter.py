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
    support = validate_support(issue.get("supporting_evidence"), window)
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
        "window": window["source_window_hash"],
    }
    code = "CC-" + str(category) + "-" + digest(identity).split(":")[1][:20].upper()
    lineage = issue.get("lineage_code")
    if lineage:
        original = next(
            (
                item
                for item in open_diagnoses(prior or {"issues": []})
                if item["code"] == lineage
            ),
            None,
        )
        if (
            original is None
            or original.get("category") != category
            or _source_locations(original.get("supporting_evidence", []))
            != _source_locations(support)
        ):
            raise KernelError(
                "REVIEW_ISSUE_LINEAGE_INVALID",
                "repair lineage must retain the original problem and source locations",
            )
        code = str(lineage)
    return {
        **base,
        "code": code,
        "diagnosis_identity": code,
        "judgment_kind": judgment,
        "confidence": issue["confidence"],
        "interpretation": intentional,
        "supporting_evidence": support,
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
            if _source_locations(support) != _source_locations(
                prior["supporting_evidence"]
            ):
                raise KernelError(
                    "REVIEW_RESOLUTION_INVALID",
                    "rereview must check the original accepted evidence",
                )
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
    *, draft: dict[str, Any], review: dict[str, Any], result: dict[str, Any]
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
            "cross-chapter repair requires located edits",
        )
    previous_end, pieces = 0, []
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
        pieces.extend((text[previous_end : location["start"]], edit["replacement"]))
        previous_end = location["end"]
    pieces.append(text[previous_end:])
    repaired = "".join(pieces)
    if result.get("text") != repaired:
        raise KernelError(
            "REVISION_TARGETED_EDIT_INVALID",
            "returned prose differs from exact diagnosed edits",
        )
    return {
        "targeted_edits": deepcopy(edits),
        "source_window_hash": review["cross_chapter_window"]["source_window_hash"],
        "preservation_requirements": deepcopy(
            review["cross_chapter_window"]["preservation_requirements"]
        ),
    }


def extend_provider_schema(schema: dict[str, Any], stage: str) -> dict[str, Any]:
    result = deepcopy(schema)
    text = {"type": "string", "minLength": 1}
    location = {
        "start": {"type": "integer", "minimum": 0},
        "end": {"type": "integer", "minimum": 1},
        "quote": text,
    }

    def obj(fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": fields,
            "required": list(fields),
            "additionalProperties": False,
        }

    if stage == "revision":
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
                "chapter_number": {"type": "integer", "minimum": 1},
                "asset_version_id": text,
                "content_hash": text,
                "text_hash": text,
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
    return result
