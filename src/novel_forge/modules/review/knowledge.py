from __future__ import annotations

import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from .diagnostics import prose_hash, validate_location


def knowledge_review_targets(context: dict[str, Any]) -> list[dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    manifest = context.get("context_manifest", {})
    inputs = {item["asset_version_id"]: item for item in manifest.get("selected_inputs", [])}
    segments = {item["asset_version_id"]: item for item in context.get("context_segments", [])}
    for item in manifest.get("knowledge_usage", []):
        asset_id = str(item.get("asset_version_id") or item.get("knowledge_card_asset_version_id") or "")
        ids = ([asset_id] if item.get("asset_type") != "knowledge_pack" else
               inputs.get(asset_id, {}).get("provenance", {}).get("knowledge_card_asset_version_ids", []))
        if not ids or any(not isinstance(identity, str) or not identity for identity in ids):
            raise KernelError("REVIEW_KNOWLEDGE_TARGET_INVALID", "knowledge requires exact card versions, including Pack members")
        pack_roles: dict[str, str] = {}
        if item.get("asset_type") == "knowledge_pack":
            usages = inputs.get(asset_id, {}).get("provenance", {}).get("knowledge_card_usages")
            if not isinstance(usages, list) or len(usages) != len(ids):
                raise KernelError("REVIEW_KNOWLEDGE_TARGET_INVALID", "rebuild Context with exact frozen Pack member roles before review")
            for usage in usages:
                if (not isinstance(usage, dict)
                    or usage.get("knowledge_card_asset_version_id") not in ids
                    or usage.get("knowledge_card_asset_version_id") in pack_roles
                    or usage.get("usage_role") not in {"PRINCIPLE", "CONSTRAINT", "CHECK", "REFERENCE"}):
                    raise KernelError("REVIEW_KNOWLEDGE_TARGET_INVALID", "Pack member roles must match the frozen Card versions")
                pack_roles[usage["knowledge_card_asset_version_id"]] = usage["usage_role"]
        projected: dict[str, Any] = {}
        if item.get("asset_type") == "knowledge_card":
            try:
                value = json.loads(segments.get(asset_id, {}).get("safe_summary") or "{}")
                if isinstance(value, dict):
                    projected = value
            except (ValueError, TypeError):
                projected = {}
        for identity in ids:
            target = {"knowledge_card_asset_version_id": identity, "usage_role": pack_roles.get(identity, item.get("usage_role", "REFERENCE"))}
            if projected:
                target.update({key: projected[key] for key in (
                    "concept_name", "mechanism", "preconditions", "applicability", "exceptions",
                    "failure_conditions", "misuse_risks", "review_checks", "translation", "craft_mechanism",
                ) if key in projected})
                translation = projected.get("translation") or {}
                if translation and translation.get("knowledge_card_asset_version_id") != identity:
                    raise KernelError("REVIEW_KNOWLEDGE_TARGET_INVALID", "translation and delivered Card differ")
                target["usage_role"] = translation.get("usage_role", target["usage_role"])
            previous = targets.get(identity)
            if previous is not None and not projected:
                target = {**previous, **target}
            if previous is not None and previous.get("usage_role") == "CONSTRAINT":
                target["usage_role"] = "CONSTRAINT"
            if previous is None or projected or target["usage_role"] == "CONSTRAINT":
                targets[identity] = target
    return [targets[key] for key in sorted(targets)]


def validate_knowledge_checks(
    *, checks: Any, targets: list[dict[str, Any]], issues: list[dict[str, Any]],
    text: str, target_asset_version_id: str, real_model_call: bool = False,
) -> list[dict[str, Any]]:
    expected = {item["knowledge_card_asset_version_id"]: item for item in targets}
    if not isinstance(checks, list):
        raise KernelError("REVIEW_KNOWLEDGE_CHECK_REQUIRED", "review requires explicit knowledge checks")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    by_code = {item["code"]: item for item in issues}
    for check in checks:
        if not isinstance(check, dict):
            raise KernelError("REVIEW_KNOWLEDGE_CHECK_INVALID", "knowledge check must be an object")
        identity = check.get("knowledge_card_asset_version_id")
        status = check.get("status")
        if identity not in expected or identity in seen or status not in {
            "VERIFIED_IN_PROSE", "MISAPPLIED", "NOT_OBSERVED", "NOT_USED", "UNKNOWN"
        }:
            raise KernelError("REVIEW_KNOWLEDGE_CHECK_INVALID", "knowledge check requires a unique delivered card and valid status")
        seen.add(identity)
        if not str(check.get("reason") or "").strip():
            raise KernelError("REVIEW_KNOWLEDGE_CHECK_INVALID", "knowledge judgment requires its reason")
        for field in ("conditions_checked", "exceptions_checked", "issue_codes"):
            values = check.get(field)
            if not isinstance(values, list) or any(not isinstance(x, str) or not x.strip() for x in values):
                raise KernelError("REVIEW_KNOWLEDGE_CHECK_INVALID", "knowledge checks require condition, exception and issue evidence")
        linked = check["issue_codes"]
        if set(linked) - set(by_code):
            raise KernelError("REVIEW_KNOWLEDGE_CHECK_INVALID", "knowledge diagnosis must resolve to an actual review issue")
        location = check.get("evidence")
        if status in {"VERIFIED_IN_PROSE", "MISAPPLIED"} or location is not None:
            location = validate_location(dict(location or {}), text)
        if status == "VERIFIED_IN_PROSE" and not check["conditions_checked"]:
            raise KernelError("REVIEW_KNOWLEDGE_CHECK_INVALID", "verified knowledge requires explicit mechanism conditions")
        hard = expected[identity].get("usage_role") == "CONSTRAINT"
        promised = (expected[identity].get("usage_role") == "MECHANISM"
                    and not expected[identity].get("craft_mechanism")
                    and bool(expected[identity].get("translation", {}).get("use_sites")))
        if status == "MISAPPLIED" or ((hard or promised) and status in {"NOT_OBSERVED", "NOT_USED", "UNKNOWN"}):
            severities = {by_code[code]["severity"] for code in linked}
            permitted = {"blocking"} if hard else {"blocking", "major", "minor"} if expected[identity].get("craft_mechanism") else {"blocking", "major"}
            if not severities & permitted:
                raise KernelError("REVIEW_KNOWLEDGE_DIAGNOSIS_REQUIRED", "misapplied knowledge or unresolved promised mechanism/constraint requires a located diagnosis")
        result.append({
            **check, "evidence": location,
            "usage_role": expected[identity].get("usage_role", "REFERENCE"),
            "target_asset_version_id": target_asset_version_id,
            "target_text_hash": prose_hash(text),
            "evidence_class": "MODEL_SEMANTIC_REVIEW" if real_model_call else "FIXTURE_SEMANTIC_REVIEW",
            "formal_proof": False,
            "human_approved": False,
        })
    if seen != set(expected):
        raise KernelError("REVIEW_KNOWLEDGE_CHECK_REQUIRED", "review omitted delivered knowledge; omission cannot establish correct use")
    return result
