from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.applicability import (
    USAGE_ROLES,
    resolve_pointer,
)
from novel_forge.modules.plan_change_authority.domain import SEMANTIC_FIELDS


_CONCRETE_TARGETS = frozenset(SEMANTIC_FIELDS) - {"knowledge_translations"} | {
    "constraints",
    "prohibited_outcomes",
    "target_reader",
    "why_worth_writing",
    "core_desire",
    "core_fear",
    "core_conflict",
    "narrative_engine",
    "differentiation",
    "emotional_contract",
    "serialization_potential",
    "style_profile",
    "thematic_question",
    "opposing_answers",
    "choice_tests",
    "ending_direction",
    "protagonist_cost",
    "unacceptable_shortcuts",
    "setup_progress_payoff",
    "disappointment_risks",
    "rules",
    "dimensions",
    "factions",
    "deferred_dimensions",
    "characters",
    "relationships",
    "candidates",
    "chapter_objective",
    "scene_sequence",
    "world_deltas",
    "relationship_deltas",
}


def add_translation_contract(
    schema: Mapping[str, Any], selection: Mapping[str, Any]
) -> dict[str, Any]:
    selected = list(selection.get("selected") or ())
    if (
        not selected
        or selection.get("policy_version") != "knowledge-grounded-selection-v2"
    ):
        return dict(schema)
    text = {"type": "string", "minLength": 1}
    texts = {"type": "array", "items": text, "minItems": 1}

    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    contract = {
        "type": "array",
        "minItems": len(selected),
        "maxItems": len(selected),
        "description": "Account for every selected exact KnowledgeCard. ADOPT, ADAPT or REJECT it. A non-rejection must locate actual text in this candidate and preserve prerequisites/exception checks; uncertain mechanisms require ADAPT with explicit prerequisite resolution. Card IDs alone are insufficient. This is a planning claim, not prose or Canon proof.",
        "items": obj(
            {
                "knowledge_card_asset_version_id": {
                    "type": "string",
                    "enum": [
                        item["knowledge_card_asset_version_id"] for item in selected
                    ],
                },
                "content_hash": {
                    "type": "string",
                    "enum": [item["content_hash"] for item in selected],
                },
                "decision": {"type": "string", "enum": ["ADOPT", "ADAPT", "REJECT"]},
                "usage_role": {"type": "string", "enum": sorted(USAGE_ROLES)},
                "rationale": text,
                "prerequisite_resolution": text,
                "use_sites": {
                    "type": "array",
                    "items": obj(
                        {
                            "target_pointer": text,
                            "realization_excerpt": {"type": "string", "minLength": 8},
                            "expected_application": text,
                            "preservation_requirements": texts,
                            "verification_checks": texts,
                        }
                    ),
                },
            }
        ),
    }
    result = dict(schema)
    result["properties"] = {
        **dict(schema["properties"]),
        "knowledge_translations": contract,
    }
    result["required"] = [*schema.get("required", ()), "knowledge_translations"]
    return result


def validate_knowledge_translations(
    candidate: Mapping[str, Any], selection: Mapping[str, Any]
) -> list[dict[str, Any]]:
    selected = {
        item["knowledge_card_asset_version_id"]: item
        for item in selection.get("selected") or ()
    }
    translations = candidate.get("knowledge_translations") or []
    if not isinstance(translations, list):
        raise KernelError(
            "PLANNING_KNOWLEDGE_TRANSLATION_INVALID",
            "translation decisions must be a list",
        )
    seen: set[str] = set()
    for item in translations:
        if not isinstance(item, Mapping):
            raise KernelError(
                "PLANNING_KNOWLEDGE_TRANSLATION_INVALID",
                "translation must be an object",
            )
        identity = item.get("knowledge_card_asset_version_id")
        card = selected.get(identity)
        if (
            card is None
            or identity in seen
            or item.get("content_hash") != card["content_hash"]
        ):
            raise KernelError(
                "PLANNING_KNOWLEDGE_TRANSLATION_DRIFT",
                "translation must bind one exact selected Card version and hash",
            )
        seen.add(identity)
        decision, role = item.get("decision"), item.get("usage_role")
        if (
            decision not in {"ADOPT", "ADAPT", "REJECT"}
            or role not in USAGE_ROLES
            or not str(item.get("rationale") or "").strip()
        ):
            raise KernelError(
                "PLANNING_KNOWLEDGE_TRANSLATION_INVALID",
                "translation requires a decision, role and rationale",
            )
        assessment = card.get("applicability_assessment") or {}
        selected_role = assessment.get("usage_role")
        if decision != "REJECT" and (
            (selected_role == "CONSTRAINT" and role != "CONSTRAINT")
            or (
                selected_role == "MECHANISM" and role not in {"MECHANISM", "CONSTRAINT"}
            )
        ):
            raise KernelError(
                "PLANNING_KNOWLEDGE_ROLE_DOWNGRADE",
                "a selected mechanism or hard constraint cannot be relabeled to bypass its applicability checks",
            )
        if decision != "REJECT" and assessment.get("status") == "REJECTED":
            raise KernelError(
                "PLANNING_KNOWLEDGE_HARD_CONFLICT",
                "rejected knowledge cannot enter a plan",
            )
        if (
            decision == "ADOPT"
            and role in {"MECHANISM", "CONSTRAINT"}
            and assessment.get("status") != "APPLICABLE"
        ):
            raise KernelError(
                "PLANNING_KNOWLEDGE_PREREQUISITES_UNRESOLVED",
                "uncertain or unmet prerequisites require explicit adaptation or rejection",
            )
        sites = item.get("use_sites")
        if (
            not isinstance(sites, list)
            or (decision == "REJECT" and sites)
            or (decision != "REJECT" and not sites)
        ):
            raise KernelError(
                "PLANNING_KNOWLEDGE_TRANSLATION_UNLOCATED",
                "adoption/adaptation requires actual candidate locations; rejection has none",
            )
        if (
            decision != "REJECT"
            and not str(item.get("prerequisite_resolution") or "").strip()
        ):
            raise KernelError(
                "PLANNING_KNOWLEDGE_PREREQUISITES_UNRESOLVED",
                "translation must explain prerequisite and exception handling",
            )
        for site in sites:
            if not isinstance(site, Mapping):
                raise KernelError(
                    "PLANNING_KNOWLEDGE_TRANSLATION_UNLOCATED",
                    "translation location must be an object",
                )
            pointer = str(site.get("target_pointer") or "")
            tokens = pointer.split("/")
            found, target = resolve_pointer(candidate, pointer)
            excerpt = str(site.get("realization_excerpt") or "")
            if (
                len(tokens) < 2
                or tokens[1] not in _CONCRETE_TARGETS
                or tokens[-1].endswith(("_id", "_ref", "_version", "_hash"))
                or not found
                or not isinstance(target, str)
                or len(excerpt.strip()) < 8
                or excerpt not in target
            ):
                raise KernelError(
                    "PLANNING_KNOWLEDGE_TRANSLATION_UNLOCATED",
                    "translation excerpt must occur in a concrete candidate field",
                )
            if (
                not isinstance(site.get("expected_application"), str)
                or not site["expected_application"].strip()
            ):
                raise KernelError(
                    "PLANNING_KNOWLEDGE_TRANSLATION_INVALID",
                    "translation requires an expected application at its concrete location",
                )
            for field in ("preservation_requirements", "verification_checks"):
                values = site.get(field)
                if (
                    not isinstance(values, list)
                    or not values
                    or any(
                        not isinstance(value, str) or not value.strip()
                        for value in values
                    )
                ):
                    raise KernelError(
                        "PLANNING_KNOWLEDGE_TRANSLATION_INVALID",
                        "translation requires preservation and subsequent verification checks",
                    )
    if seen != set(selected):
        raise KernelError(
            "PLANNING_KNOWLEDGE_TRANSLATION_MISSING",
            "every selected Card must be explicitly adopted, adapted or rejected",
        )
    return [dict(item) for item in translations]
