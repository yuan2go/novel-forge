from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping, Sequence
from novel_forge.modules.command_kernel.errors import KernelError

PROSE_REVIEW_DEFINITION = "longform.prose_review"
PROSE_REVIEW_SCHEMA = "longform-prose-review.v1"
PROSE_DIMENSIONS = (
    "structure_conflict_repetition",
    "goals_relationships",
    "setup_progress_payoff",
    "voice_expression",
    "arc_pacing",
    "motivation_cost",
)


def completion_digest(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def prose_review_output_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}

    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    citation = obj(
        {
            "asset_version_id": text,
            "text_hash": text,
            "start": {"type": "integer", "minimum": 0},
            "end": {"type": "integer", "minimum": 1},
            "quote": text,
        }
    )
    finding = obj(
        {
            "lineage_id": text,
            "dimension": {"type": "string", "enum": list(PROSE_DIMENSIONS)},
            "judgment": {
                "type": "string",
                "enum": ["ISSUE", "INTENTIONAL", "INSUFFICIENT_EVIDENCE"],
            },
            "severity": {
                "type": "string",
                "enum": ["BLOCKING", "MAJOR", "MINOR", "NONE"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "claim": text,
            "rationale": text,
            "evidence": {"type": "array", "items": citation, "minItems": 1},
        }
    )
    issue = deepcopy(finding)
    issue["properties"]["judgment"]["enum"] = ["ISSUE"]
    issue["properties"]["severity"]["enum"] = ["BLOCKING", "MAJOR", "MINOR"]
    observation = deepcopy(finding)
    observation["properties"]["judgment"]["enum"] = [
        "INTENTIONAL",
        "INSUFFICIENT_EVIDENCE",
    ]
    observation["properties"]["severity"]["enum"] = ["NONE"]
    finding = {"anyOf": [issue, observation]}
    return obj(
        {
            "schema_version": {"type": "string", "enum": [PROSE_REVIEW_SCHEMA]},
            "manifest_digest": text,
            "window_id": text,
            "reviewed_dimensions": {
                "type": "array",
                "items": {"type": "string", "enum": list(PROSE_DIMENSIONS)},
                "uniqueItems": True,
                "minItems": len(PROSE_DIMENSIONS),
                "maxItems": len(PROSE_DIMENSIONS),
            },
            "findings": {"type": "array", "items": finding},
        }
    )


def normalize_prose_review_output(raw: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(raw))
    from novel_forge.modules.chapter_authority.provider_output_contracts import (
        validate_chapter_provider_output_against_schema,
    )

    validate_chapter_provider_output_against_schema(
        "longform_prose_review",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **prose_review_output_schema(),
        },
        result,
    )
    for finding in result["findings"]:
        if (finding["judgment"] == "ISSUE") != (finding["severity"] != "NONE"):
            raise KernelError(
                "LONGFORM_PROSE_JUDGMENT_INVALID",
                "only an issue can carry issue severity",
            )
    return result


def freeze_manifest(
    *,
    project_id: str,
    workspace_id: str,
    book_run_id: str,
    sources: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    work_intent: bool = True,
) -> dict[str, Any]:
    required = {
        "policy_version",
        "window_codepoints",
        "overlap_codepoints",
        "context_token_budget",
        "maximum_windows",
    }
    optional = {"execution_mode", "relation_window_limit", "follow_acceptance", "relation_retrieval_version"}
    if (
        not required <= set(policy)
        or set(policy) - required - optional
        or not str(policy["policy_version"]).strip()
    ):
        raise KernelError(
            "LONGFORM_PROSE_POLICY_INVALID",
            "an explicit versioned window and token policy is required",
        )
    if any(
        type(policy[key]) is not int or policy[key] <= 0
        for key in required - {"policy_version", "overlap_codepoints"}
    ):
        raise KernelError(
            "LONGFORM_PROSE_POLICY_INVALID",
            "window limits and request token cap must be positive integers",
        )
    if (
        type(policy["overlap_codepoints"]) is not int
        or not 0 <= policy["overlap_codepoints"] < policy["window_codepoints"]
    ):
        raise KernelError(
            "LONGFORM_PROSE_POLICY_INVALID", "overlap must be smaller than the window"
        )
    if (
        policy.get("execution_mode", "MANUAL") not in {"MANUAL", "AUTOMATIC"}
        or type(policy.get("relation_window_limit", 0)) is not int
        or not 0 <= policy.get("relation_window_limit", 0) <= policy["maximum_windows"]
        or type(policy.get("follow_acceptance", False)) is not bool
        or (
            policy.get("follow_acceptance")
            and policy.get("execution_mode") != "AUTOMATIC"
        )
    ):
        raise KernelError(
            "LONGFORM_PROSE_POLICY_INVALID",
            "automatic review and bounded relation retrieval require explicit policy",
        )
    if policy.get("relation_retrieval_version", "lexical.v1") not in {"lexical.v1", "accepted-state-relations.v2"}:
        raise KernelError("LONGFORM_PROSE_POLICY_INVALID", "Unknown explicit relation retrieval version")
    records, windows = [], []
    previous_tail = None
    for source in sources:
        text = source.get("text")
        if not isinstance(text, str) or not text:
            raise KernelError(
                "LONGFORM_PROSE_SOURCE_EMPTY",
                "accepted exact prose is required; a recap cannot substitute",
            )
        record = {
            key: source[key]
            for key in (
                "chapter_number",
                "acceptance_id",
                "asset_version_id",
                "asset_hash",
            )
        }
        record.update(text_hash=text_digest(text), codepoints=len(text))
        if work_intent:
            from novel_forge.modules.chapter_authority.chapter_plan_views import (
                validate_creative_baseline,
            )
            baseline = source.get("creative_baseline")
            record["creative_baseline"] = validate_creative_baseline(baseline) if baseline is not None else None
            if baseline is not None and baseline["chapter"] != record["chapter_number"]:
                raise KernelError(
                    "LONGFORM_PROSE_SOURCE_BASELINE_DRIFT",
                    "Accepted prose and its creative baseline must identify the same chapter",
                )
            record["work_intent_status"] = "FROZEN_CANDIDATE_BASELINE" if baseline is not None else "UNKNOWN_LEGACY_BASELINE"
        if policy.get("relation_retrieval_version") == "accepted-state-relations.v2":
            record["relation_evidence_digest"] = completion_digest(source.get("relation_evidence", []))
        records.append(record)
        start = 0
        while start < len(text):
            prefix = [previous_tail] if start == 0 and previous_tail else []
            allowance = policy["window_codepoints"] - sum(
                len(item["text"]) for item in prefix
            )
            end = min(len(text), start + allowance)
            span = {**record, "start": start, "end": end, "text": text[start:end]}
            spans = [*prefix, span]
            windows.append(
                {
                    "window_id": completion_digest(
                        {"spans": spans, "policy": dict(policy)}
                    ),
                    "spans": spans,
                }
            )
            if end == len(text):
                break
            start = max(start + 1, end - policy["overlap_codepoints"])
        previous_tail = (
            {
                **record,
                "start": max(0, len(text) - policy["overlap_codepoints"]),
                "end": len(text),
                "text": text[max(0, len(text) - policy["overlap_codepoints"]) :],
            }
            if policy["overlap_codepoints"]
            else None
        )
    if not records or len({row["chapter_number"] for row in records}) != len(records):
        raise KernelError(
            "LONGFORM_PROSE_MANIFEST_INVALID",
            "manifest needs distinct accepted chapters",
        )
    body = {
        "schema_version": "longform-prose-manifest.v2" if work_intent else "longform-prose-manifest.v1",
        "project_id": project_id,
        "workspace_id": workspace_id,
        "book_run_id": book_run_id,
        "sources": records,
        "policy": dict(policy),
        "windows": windows,
    }
    if policy.get("relation_window_limit"):
        from .prose_relations import relation_windows

        if policy.get("relation_retrieval_version") == "accepted-state-relations.v2":
            from .prose_semantic_relations import structured_relation_windows
            relations, coverage = structured_relation_windows(sources, records, policy)
        else:
            relations, coverage = relation_windows(sources, records, policy)
        body["windows"].extend(relations)
        body["relation_retrieval"] = coverage
    return {**body, "manifest_digest": completion_digest(body)}


def validate_window_report(
    report: Mapping[str, Any], *, manifest: Mapping[str, Any], window: Mapping[str, Any]
) -> dict[str, Any]:
    report = normalize_prose_review_output(report)
    if (
        report["manifest_digest"] != manifest["manifest_digest"]
        or report["window_id"] != window["window_id"]
    ):
        raise KernelError(
            "LONGFORM_PROSE_REPORT_STALE",
            "review must bind the frozen manuscript and actual window",
        )
    if set(report["reviewed_dimensions"]) != set(PROSE_DIMENSIONS):
        raise KernelError(
            "LONGFORM_PROSE_DIMENSIONS_MISSING",
            "all dimensions must be assessed, including insufficient evidence",
        )
    for finding in report["findings"]:
        for citation in finding["evidence"]:
            matches = [
                span
                for span in window["spans"]
                if span["asset_version_id"] == citation["asset_version_id"]
                and span["text_hash"] == citation["text_hash"]
                and span["start"] <= citation["start"] < citation["end"] <= span["end"]
            ]
            if not matches or not any(
                span["text"][
                    citation["start"] - span["start"] : citation["end"] - span["start"]
                ]
                == citation["quote"]
                for span in matches
            ):
                raise KernelError(
                    "LONGFORM_PROSE_CITATION_INVALID",
                    "finding must quote exact provided Unicode codepoint ranges",
                )
        if (
            window.get("relation_hypothesis")
            and finding["judgment"] != "INSUFFICIENT_EVIDENCE"
        ):
            if not all(
                any(
                    citation["asset_version_id"] == span["asset_version_id"]
                    and span["start"]
                    <= citation["start"]
                    < citation["end"]
                    <= span["end"]
                    for citation in finding["evidence"]
                )
                for span in window["spans"]
            ):
                raise KernelError(
                    "LONGFORM_PROSE_RELATION_EVIDENCE_INCOMPLETE",
                    "a relation judgment must locate evidence in both retrieved passages",
                )
    return report


def aggregate_reports(
    manifest: Mapping[str, Any], reports: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    windows = {row["window_id"]: row for row in manifest["windows"]}
    groups: dict[str, list[dict[str, Any]]] = {}
    covered: dict[str, list[tuple[int, int]]] = {}
    completed = set()
    for report in reports:
        window = windows.get(report["window_id"])
        if window is None:
            raise KernelError(
                "LONGFORM_PROSE_WINDOW_UNKNOWN",
                "report window is outside this manifest",
            )
        validate_window_report(report, manifest=manifest, window=window)
        if report["window_id"] in completed:
            continue
        completed.add(report["window_id"])
        for span in window["spans"]:
            covered.setdefault(span["asset_version_id"], []).append(
                (span["start"], span["end"])
            )
        for finding in report["findings"]:
            groups.setdefault(finding["lineage_id"], []).append(
                dict(finding, window_id=report["window_id"])
            )
    exclusions = []
    for source in manifest["sources"]:
        cursor = 0
        for start, end in sorted(covered.get(source["asset_version_id"], [])):
            if start > cursor:
                exclusions.append(
                    {
                        "asset_version_id": source["asset_version_id"],
                        "start": cursor,
                        "end": start,
                    }
                )
            cursor = max(cursor, end)
        if cursor < source["codepoints"]:
            exclusions.append(
                {
                    "asset_version_id": source["asset_version_id"],
                    "start": cursor,
                    "end": source["codepoints"],
                }
            )
    findings = []
    for lineage, members in sorted(groups.items()):
        dimensions = {item["dimension"] for item in members}
        judgments = {item["judgment"] for item in members}
        evidence_sets = [
            {
                (e["asset_version_id"], e["text_hash"], e["start"], e["end"])
                for e in item["evidence"]
            }
            for item in members
        ]
        connected = set(evidence_sets[0])
        pending = list(evidence_sets[1:])
        while pending:
            linked = next((item for item in pending if item & connected), None)
            if linked is None:
                break
            connected |= linked
            pending.remove(linked)
        findings.append(
            {
                "lineage_id": lineage,
                "status": "CONFLICT_REQUIRES_REVIEW"
                if len(dimensions) > 1 or len(judgments) > 1 or pending
                else "OPEN"
                if "ISSUE" in judgments
                else "OBSERVATION",
                "members": members,
                "required_consumer": "VERSION_BOUND_EDITORIAL_PENDING",
            }
        )
    return {
        "manifest_digest": manifest["manifest_digest"],
        "completed_window_ids": sorted(completed),
        "total_windows": len(windows),
        "uncovered_ranges": exclusions,
        "coverage_complete": not exclusions,
        "review_complete": len(completed) == len(windows),
        "findings": findings,
        "relation_verification": {
            "retrieval": manifest.get(
                "relation_retrieval", {"status": "NOT_REQUESTED"}
            ),
            "completed_hypothesis_ids": [
                window["relation_hypothesis"]["hypothesis_id"]
                for identity, window in windows.items()
                if identity in completed and window.get("relation_hypothesis")
            ],
            "paired_evidence_hypothesis_ids": sorted(
                {
                    windows[report["window_id"]]["relation_hypothesis"]["hypothesis_id"]
                    for report in reports
                    if windows[report["window_id"]].get("relation_hypothesis")
                    and any(
                        finding["judgment"] != "INSUFFICIENT_EVIDENCE"
                        for finding in report["findings"]
                    )
                }
            ),
            "global_relationships_verified": False,
        },
        "quality_absence_proven": False,
        "independent_human_review": "NOT_RUN",
    }
