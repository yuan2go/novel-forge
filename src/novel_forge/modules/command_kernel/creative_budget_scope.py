from __future__ import annotations

from copy import deepcopy
from typing import Any

from .creative_budget_contract import _PLANNING_CAPABILITIES, classify_phase
from .errors import KernelError


def _unknown(message: str) -> KernelError:
    return KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_UNKNOWN", message)


def _payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _unknown("frozen operation payload is unavailable")
    payload = value.get("payload", value)
    if not isinstance(payload, dict):
        raise _unknown("frozen business payload is unavailable")
    return payload


def _number(value: Any, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise _unknown("chapter and repair identities require exact non-bool integers")
    return value


def classify_business_scope(identity: dict[str, Any], *, dispatch_generation: int = 1,
                            chapter_ranges: dict[str, list[int]] | None = None) -> dict[str, Any]:
    _number(dispatch_generation, minimum=0)
    request = identity["request_payload"]
    phase = classify_phase(identity["operation_name"], identity["capability"], request, identity["attempt_no"])
    operation = identity["operation_name"]
    stage = request["stage"]
    inputs = request["input"]
    command = _payload(identity["command_payload"])
    metadata = request.get("_production_execution") or {}
    if not isinstance(metadata, dict):
        raise _unknown("Provider execution metadata is invalid")
    sources = []
    numbers = []

    def add_chapter(value: Any, path: str) -> None:
        number = _number(value, minimum=1)
        numbers.append(number)
        sources.append({"path": path, "value": number})

    repair = phase == "REPAIR" or dispatch_generation > 1
    generator = ""
    if phase == "SOURCE":
        origin_phase = "SOURCE"
    else:
        if operation == "story_design.semantic_evaluate":
            origin = identity.get("evaluation_origin")
            if not isinstance(origin, dict) or not origin.get("source_ref"):
                raise _unknown("semantic review requires its exact native generation lineage")
            original = _payload(origin.get("command_payload"))
            generator = original.get("generator_operation_name") if origin.get("definition_name") == "story_planning.generate" else origin.get("definition_name")
            target = inputs.get("evaluation_target")
            if not isinstance(target, dict):
                raise _unknown("semantic review has no frozen target")
            for claimed in (target.get("generator_operation_name"), command.get("generator_operation_name"), metadata.get("generator_operation_name")):
                if claimed is not None and claimed != generator:
                    raise _unknown("semantic review generator differs from its native origin")
            if target.get("generator_operation_name") != generator:
                raise _unknown("semantic review does not bind the native generator")
            sources.append({"path": "native_generation", "value": deepcopy(origin["source_ref"])})
            command = original
        elif operation == "story_planning.generate":
            generator = command.get("generator_operation_name")
            expected = "chapter_plan.generate" if stage in {"world_candidates.generate", "world_candidates.evaluate", "world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2"} else stage
            if generator != expected:
                raise _unknown("Planning Effect and native generator differ")
        if generator:
            if generator not in {*_PLANNING_CAPABILITIES, "book_design.propose"}:
                raise _unknown("native generator has no bounded business classification")
            repair_number = _number(command.get("repair_number", 0), minimum=0)
            sources.append({"path": "operation.repair_number", "value": repair_number})
            repair = repair or repair_number > 0
            if generator == "chapter_plan.generate":
                realization = command.get("narrative_realization")
                if not isinstance(realization, dict):
                    raise _unknown("Chapter Planning has no frozen realization")
                add_chapter(realization.get("chapter_number"), "operation.narrative_realization.chapter_number")
                if operation == "story_planning.generate":
                    if stage in {"world_candidates.generate", "world_candidates.evaluate", "world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2"}:
                        world = inputs.get("world_preparation")
                        frontier = command.get("world_preparation_request")
                        if not isinstance(world, dict) or not isinstance(frontier, dict):
                            raise _unknown("World preparation has no exact frozen frontier")
                        for value, path in ((world.get("accepted_through_chapter"), "request.world_preparation"), (frontier.get("accepted_through_chapter"), "operation.world_preparation_request")):
                            add_chapter(_number(value, minimum=0) + 1, path + ".accepted_through_chapter+1")
                    else:
                        projected = inputs.get("planning_command") or {}
                        projected_realization = projected.get("narrative_realization") or {}
                        add_chapter(projected_realization.get("chapter_number"), "request.planning_command.narrative_realization.chapter_number")
            else:
                origin_phase = "DESIGN"
        elif operation == "longform.prose_review":
            scope = identity.get("native_prose_scope")
            if not isinstance(scope, dict) or not scope.get("spans") or not scope.get("manifest_digest"):
                raise _unknown("longform review requires its verified frozen native window")
            first, last = (_number(scope.get(key), minimum=1) for key in ("chapter_start", "chapter_end"))
            if first > last or type(metadata.get("chapter")) is not int or metadata["chapter"] not in {0, last}:
                raise _unknown("review chapter metadata differs from its frozen range")
            add_chapter(last, "native_prose_window.chapter_end")
            sources.append({"path": "native_prose_window", "value": deepcopy(scope)})
        else:
            for key in ("chapter_number", "chapter"):
                if key in command:
                    add_chapter(command[key], "operation." + key)
            if "chapter" in metadata:
                add_chapter(metadata["chapter"], "request._production_execution.chapter")
            if not numbers:
                raise _unknown("creative Effect has no frozen chapter identity")
        if numbers:
            if len(set(numbers)) != 1:
                raise _unknown("frozen chapter identities disagree")
            chapter = numbers[0]
            ranges = chapter_ranges if chapter_ranges is not None else {"CREATION_EARLY": [1, 6], "CREATION_LATE": [7, 12]}
            matches = [name for name, (first, last) in ranges.items() if first <= chapter <= last]
            if len(matches) != 1:
                raise _unknown("creative Effect is outside the frozen chapter phase ranges")
            origin_phase = matches[0]
    return {
        "phase": "SOURCE" if origin_phase == "SOURCE" else "REPAIR" if repair else origin_phase,
        "origin_phase": origin_phase,
        "chapter_number": numbers[0] if numbers else 0,
        "generator_operation_name": generator,
        "operation_name": operation,
        "capability": identity["capability"],
        "stage": stage,
        "dispatch_generation": dispatch_generation,
        "provider_request_hash": str(identity.get("request_hash") or ""),
        "scope_sources": sources,
    }


def require_business_scope(policy: dict[str, Any], actual: dict[str, Any]) -> None:
    allowed = policy["authorization"]["business_scope"]
    origin = actual["origin_phase"]
    if origin == "SOURCE":
        admitted = allowed["source_allowed"]
    elif origin == "DESIGN":
        admitted = allowed["design_allowed"]
    elif origin in {"CREATION_EARLY", "CREATION_LATE", "PRODUCTION"}:
        chapter = _number(actual["chapter_number"], minimum=1)
        admitted = chapter <= allowed["max_chapter_number"]
    else:
        raise _unknown("actual creative scope has no known origin")
    if not admitted:
        raise KernelError("CREATIVE_BUDGET_BUSINESS_SCOPE_DENIED", "the exact Source/design/chapter scope is outside the frozen authorization")


__all__ = ["classify_business_scope", "require_business_scope"]
