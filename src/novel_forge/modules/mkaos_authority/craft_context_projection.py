from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


_HISTORY_FIELDS = ("recent_usage", "accepted_usage_history", "realization_cautions")
_HISTORY_POINTER = "/narrative_intelligence/need/recent_craft_usage"


def project_planning_craft_histories(selection: dict[str, Any]) -> dict[str, Any]:
    from .craft_selection import _hash

    if selection.get("craft_policy", {}).get("schema_version") != "narrative-craft-budget.v4":
        return selection
    history = selection.get("need", {}).get("recent_craft_usage")
    if not isinstance(history, list) or not history:
        return selection
    result = deepcopy(selection)
    by_hash = {_hash(row): index for index, row in enumerate(history)}
    changed = False
    for card in [*result.get("selected", []), *result.get("rejected", [])]:
        budget = card.get("craft_assessment", {}).get("budget_assessment", {})
        for field in _HISTORY_FIELDS:
            rows = budget.get(field)
            if not isinstance(rows, list) or not rows:
                continue
            indices = [by_hash.get(_hash(row)) for row in rows]
            if any(index is None or history[index] != row for row, index in zip(rows, indices)):
                continue
            reference = {"contract_version": "planning-craft-history-reference.v1",
                "json_pointer": _HISTORY_POINTER, "indices": indices, "content_hash": _hash(rows)}
            if len(json.dumps(reference, ensure_ascii=False)) >= len(json.dumps(rows, ensure_ascii=False)):
                continue
            del budget[field]
            budget[field + "_reference"] = reference
            changed = True
    if not changed:
        return selection
    result["planning_history_projection"] = {
        "contract_version": "planning-craft-history-projection.v1",
        "source_selection_digest": selection["selection_digest"],
        "source_view_hash": _hash(selection),
        "instruction": "Each *_reference replaces only an identical accepted-history list. Read its zero-based indices at json_pointer in this same task view, in order. The full observations, evidence, phases and predecessors remain there; no observation is omitted or upgraded.",
    }
    if resolve_planning_craft_histories(result) != selection:
        raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Planning references must reconstruct the complete frozen selection")
    return result if len(json.dumps(result, ensure_ascii=False)) < len(json.dumps(selection, ensure_ascii=False)) else selection


def resolve_planning_craft_histories(selection: dict[str, Any]) -> dict[str, Any]:
    from .craft_selection import _hash

    result = deepcopy(selection)
    receipt = result.pop("planning_history_projection", None)
    history = result.get("need", {}).get("recent_craft_usage")
    if (not isinstance(receipt, dict) or receipt.get("contract_version") != "planning-craft-history-projection.v1"
        or receipt.get("source_selection_digest") != result.get("selection_digest") or not isinstance(history, list)):
        raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Planning history projection has no exact source identity")
    for card in [*result.get("selected", []), *result.get("rejected", [])]:
        budget = card.get("craft_assessment", {}).get("budget_assessment", {})
        for field in _HISTORY_FIELDS:
            reference = budget.pop(field + "_reference", None)
            if reference is None:
                continue
            if (field in budget or not isinstance(reference, dict)
                or set(reference) != {"contract_version", "json_pointer", "indices", "content_hash"}
                or reference["contract_version"] != "planning-craft-history-reference.v1"
                or reference["json_pointer"] != _HISTORY_POINTER or not isinstance(reference["indices"], list)
                or not reference["indices"] or any(type(index) is not int or not 0 <= index < len(history) for index in reference["indices"])):
                raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Planning history reference differs from its bounded in-request source")
            rows = [deepcopy(history[index]) for index in reference["indices"]]
            if _hash(rows) != reference["content_hash"]:
                raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Planning history reference has changed observations")
            budget[field] = rows
    if receipt.get("source_view_hash") != _hash(result):
        raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Planning history references changed the complete source view")
    return result


def reference_duplicate_craft_uses(candidates, *, intent: dict[str, Any], intent_asset_version_id: str):
    strategy = intent.get("craft_strategy") or {}
    if strategy.get("schema_version") != "narrative-craft-strategy.v3":
        return candidates
    output = []
    for candidate in candidates:
        if candidate.asset_type != "knowledge_card":
            output.append(candidate)
            continue
        summary = json.loads(candidate.safe_summary)
        uses = summary.get("craft_uses")
        expected = [use for use in strategy["uses"] if use["knowledge_card_asset_version_id"] == candidate.asset_version_id]
        if not uses:
            output.append(candidate)
            continue
        if uses != expected or summary.get("craft_strategy_digest") != strategy["strategy_digest"]:
            raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "A duplicate projection must match the protected exact execution strategy")
        summary.pop("craft_uses")
        summary["craft_uses_reference"] = {"contract_version": "protected-craft-uses-reference.v1",
            "asset_version_id": intent_asset_version_id, "json_pointer": "/craft_strategy/uses",
            "strategy_digest": strategy["strategy_digest"], "use_ids": [use["use_id"] for use in expected]}
        rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        output.append(replace(candidate, safe_summary=rendered,
            estimated_tokens=max(1, candidate.estimated_tokens - max(0, len(candidate.safe_summary) - len(rendered)) // 4)))
    return output


def resolve_projected_craft_uses(summary: dict[str, Any], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reference = summary.get("craft_uses_reference")
    if reference is None:
        return summary.get("craft_uses") or []
    if reference.get("contract_version") != "protected-craft-uses-reference.v1" or reference.get("json_pointer") != "/craft_strategy/uses":
        raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Unknown Craft projection cannot establish a delivered use")
    for segment in segments:
        if segment.get("asset_version_id") != reference["asset_version_id"]:
            continue
        content = segment.get("safe_summary")
        content = json.loads(content) if isinstance(content, str) else content
        strategy = (content or {}).get("craft_strategy") or {}
        if strategy.get("strategy_digest") == reference["strategy_digest"]:
            uses = [use for use in strategy["uses"] if use["use_id"] in reference["use_ids"]]
            if [use["use_id"] for use in uses] == reference["use_ids"]:
                return uses
    raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "The exact protected strategy is missing from the frozen Context")
