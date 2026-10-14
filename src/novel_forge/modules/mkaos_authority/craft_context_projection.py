from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


_HISTORY_FIELDS = ("recent_usage", "accepted_usage_history", "realization_cautions")
_HISTORY_POINTER = "/narrative_intelligence/need/recent_craft_usage"
_BUDGET_HISTORY_FIELDS = (*_HISTORY_FIELDS, "working_allocation_history", "working_coverage_gaps")


def experimental_chapter_method_scope(*, generator, contract_version, selection, policy):
    if (generator != "chapter_plan.generate" or contract_version != "1.21.0"
            or not selection.get("selected") or policy.get("mode") != "ALLOW_ONLY"
            or policy.get("usage_scope") != "EXPERIMENTAL_VALIDATION"
            or policy.get("craft_candidate_review_version") != "explicit-allowlist-craft-review.v1"):
        return {}
    project_chapter_method_scope(selection)
    return {"planning_chapter_method_scope_projection_version": "chapter-method-scope-projection.v1",
            "world_method_scope_projection_version": "world-method-scope-projection.v1",
            "planning_method_scope_activation": "fresh-experimental-method-scope.v1"}


def project_book_method_scope(selection: dict[str, Any]) -> dict[str, Any]:
    policy = selection.get("knowledge_access_policy") or {}
    if policy.get("mode") != "ALLOW_ONLY" or policy.get("usage_scope") != "EXPERIMENTAL_VALIDATION":
        raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Book method scope requires its explicit experimental policy")
    result = project_foundation_method_recall(selection)
    result["recall_query_receipt"]["contract_version"] = "book-method-scope-projection.v1"
    result["recall_query_receipt"]["boundary"] = "RECALL_AND_PRIOR_STAGE_AUDIT_NOT_STORY_FACTS"
    return result


def project_group_method_scope(selection: dict[str, Any]) -> dict[str, Any]:
    from .craft_selection import _hash

    policy = selection.get("knowledge_access_policy") or {}
    if policy.get("mode") != "ALLOW_ONLY" or policy.get("usage_scope") != "EXPERIMENTAL_VALIDATION":
        raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Group method scope requires its explicit experimental policy")
    result = project_foundation_method_recall(selection)
    result["recall_query_receipt"]["contract_version"] = "group-method-scope-projection.v1"
    query = selection["need"].get("hard_constraints")
    assessments = [card.get("applicability_assessment", {}) for card in result["selected"]]
    if (isinstance(query, list) and query and all(
            assessment.get("hard_constraints") == query
            and assessment.get("hard_constraint_semantics") == "UNVERIFIED_EXCEPT_EXPLICIT_TYPED_CHECKS"
            and all(check.get("method") == "SEMANTIC_UNVERIFIED" for check in assessment.get("checks", []))
            for assessment in assessments)):
        result["need"].pop("hard_constraints")
        for assessment in assessments:
            assessment.pop("hard_constraints")
        result["recall_query_receipt"]["flattened_constraint_query"] = {
            "json_pointer": "/narrative_intelligence/need/hard_constraints",
            "content_hash": _hash(query), "item_count": len(query),
            "boundary": "UNVERIFIED_RETRIEVAL_TERMS_NOT_ADDITIONAL_STORY_CONSTRAINTS",
            "preserved": "Every typed plan constraint, current method body, applicability check, prerequisite, exception and UNKNOWN result; no explicit typed constraint check is eligible for this query projection.",
        }
    return result


def project_world_method_scope(selection: dict[str, Any]) -> dict[str, Any]:
    result = project_group_method_scope(selection)
    result["recall_query_receipt"]["contract_version"] = "world-method-scope-projection.v1"
    return result


def project_chapter_method_scope(selection: dict[str, Any]) -> dict[str, Any]:
    result = project_group_method_scope(selection)
    result["recall_query_receipt"]["contract_version"] = "chapter-method-scope-projection.v1"
    return result


def project_foundation_method_recall(selection: dict[str, Any]) -> dict[str, Any]:
    from .craft_selection import _hash

    if (selection.get("knowledge_access_policy", {}).get("craft_candidate_review_version")
            != "explicit-allowlist-craft-review.v1"
            or selection.get("schema_version") != "mkaos-narrative-intelligence-selection.v1"
            or not selection.get("selected")):
        raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Foundation recall projection requires its explicit selected method policy")
    need = selection.get("need")
    if (not isinstance(need, dict) or need.get("need_digest") != _hash({key: value for key, value in need.items() if key != "need_digest"})
            or selection.get("selection_digest") != _hash({key: value for key, value in selection.items() if key != "selection_digest"})):
        raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Recall query must bind the complete immutable selection")
    result = deepcopy(selection)
    fields = ("semantic_families", "theme_tags", "genre_tags", "reader_effect_tags", "conflict_tags",
        "current_state_terms", "desired_transformation_terms", "craft_context", "condition_sources")
    removed = {"/need/"+key: result["need"].pop(key) for key in fields if key in result["need"]}
    for index, card in enumerate(result["selected"]):
        assessment = card.get("craft_assessment", {})
        metrics = {key: assessment.pop(key) for key in ("matching_assessment", "score", "match_reasons",
            "rejection_reason", "selection_reason", "candidate_review_policy_version") if key in assessment}
        budget = assessment.get("budget_assessment")
        if isinstance(budget, dict) and not any(budget.get(key) for key in _BUDGET_HISTORY_FIELDS):
            metrics["budget_assessment"] = assessment.pop("budget_assessment")
        if metrics:
            removed[f"/selected/{index}/craft_assessment"] = metrics
    result["recall_query_receipt"] = {
        "contract_version": "foundation-method-recall-projection.v1",
        "source_selection_digest": selection["selection_digest"], "source_need_digest": need["need_digest"],
        "frozen_context_pointer": "/narrative_intelligence/need",
        "omitted_fields": sorted(removed), "omitted_value_hash": _hash(removed),
        "boundary": "RETRIEVAL_QUERY_ONLY_NOT_AUTHOR_REQUIREMENTS_OR_STORY_FACTS",
        "preserved": "All selected method bodies, applicability checks, prerequisites, exceptions, hard constraints, required versions and histories; narrative inputs remain in their frozen role segments.",
    }
    return result


def approved_method_activation_view(content: dict[str, Any], *, asset_version_id: str, content_hash: str) -> dict[str, Any]:
    policy = content.get("source_policy") or {}
    lineage = content.get("lineage") or {}
    return {"contract_version": "approved-method-activation-view.v1",
        "classification": "CURRENT_RUNTIME_FACT",
        "knowledge_card_asset_version_id": asset_version_id, "content_hash": content_hash,
        "governance_decision_asset_version_id": lineage.get("governance_decision_asset_version_id", ""),
        "approval_class": policy.get("approval_class", ""),
        "approval_policy_version": policy.get("approval_policy_version", ""),
        "review_class": policy.get("review_class", ""),
        "production_context_eligible": policy.get("production_context_eligible", False),
        "experimental_context_eligible": policy.get("experimental_context_eligible", False),
        "instruction": "This current Card approval is the activation evidence for the frozen usage scope. Historical discovery-stage statements about an unapproved candidate, pending gates or absent commits describe the earlier Candidate; they do not override this Card's current scoped approval or require human approval to write an experimental manuscript. Method prerequisites, source restrictions and hypothesis status remain unchanged. Approval permits consideration only: Planning still ADOPT/ADAPT/REJECT at concrete sites; no author acceptance, production eligibility or literary effect is created. Operational provenance is never a duty for fictional people."}


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
            summary.setdefault("context_diagnostics", []).append({
                "code": "CRAFT_CONTEXT_PROJECTION_DRIFT", "status": "DIAGNOSTIC_ONLY",
                "protected_intent_asset_version_id": intent_asset_version_id,
                "instruction": "Independent card guidance differs from the protected intent; no exact reference is established.",
            })
            rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            output.append(replace(candidate, safe_summary=rendered,
                estimated_tokens=candidate.estimated_tokens + max(0, len(rendered) - len(candidate.safe_summary) + 3) // 4))
            continue
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
