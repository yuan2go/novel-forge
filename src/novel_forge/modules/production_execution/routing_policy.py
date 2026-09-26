from __future__ import annotations

import math
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import _validate_json_schema
from novel_forge.modules.command_kernel.routing_bootstrap import (
    SOURCE_BOOTSTRAP_TASKS,
    CHAPTER_BOOTSTRAP_TASKS,
    WORLD_SAMPLE_TASKS,
    validate_bootstrap_authorization,
    validate_bootstrap_history,
)

from .cost_routing import task_policy


OWNER = "PROVIDER_ROUTING"
POLICY_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["policy_version", "reason", "task_overrides"],
    "properties": {
        "policy_version": {"type": "string", "minLength": 1},
        "reason": {"type": "string", "minLength": 1},
        "bootstrap_authorizations": {"type": "array", "items": {"type": "object"}},
        "task_overrides": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["work_id", "task_type", "risk", "quality_floor"],
                "properties": {
                    "work_id": {"type": "string", "minLength": 1},
                    "task_type": {"type": "string", "minLength": 1},
                    "risk": {"enum": ["LOW", "MEDIUM", "HIGH"]},
                    "quality_floor": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 1,
                    },
                    "chapter": {"type": "integer", "minimum": 1},
                    "latency_sla_seconds": {"type": "number", "exclusiveMinimum": 0},
                    "escalation_reason": {"type": "string"},
                },
            },
        },
    },
}


def validate_routing_policy(content: Mapping[str, Any]) -> None:
    try:
        _validate_json_schema(POLICY_SCHEMA, dict(content))
        if not all(content[key].strip() for key in ("policy_version", "reason")):
            raise ValueError("policy identity and reason are required")
        authorization_ids = set()
        for grant in content.get("bootstrap_authorizations", []):
            validate_bootstrap_authorization(grant)
            task_policy(grant["task_type"])
            if (
                not (grant["task_type"].endswith(".generate")
                     or grant["task_type"] == "narrative_semantic_evaluation"
                     or grant["task_type"] == "longform_prose_review"
                     or grant["task_type"] in SOURCE_BOOTSTRAP_TASKS.values()
                     or grant["task_type"] in CHAPTER_BOOTSTRAP_TASKS.values()
                     or grant["task_type"] in WORLD_SAMPLE_TASKS)
                or grant["authorization_id"] in authorization_ids
            ):
                raise ValueError(
                    "bootstrap authorization must identify one supported native sampling task"
                )
            authorization_ids.add(grant["authorization_id"])
        validate_bootstrap_history(list(content.get("bootstrap_authorizations", [])), [])
        for item in content["task_overrides"]:
            _validate_json_schema(
                POLICY_SCHEMA["properties"]["task_overrides"]["items"], item
            )
            if not all(item[key].strip() for key in ("work_id", "task_type")):
                raise ValueError("work and task identity are required")
            if item["risk"] not in ("LOW", "MEDIUM", "HIGH"):
                raise ValueError("risk is invalid")
            for key in ("quality_floor", "latency_sla_seconds"):
                if key in item and (
                    isinstance(item[key], bool)
                    or not math.isfinite(item[key])
                    or item[key] <= 0
                ):
                    raise ValueError(key + " must be positive and finite")
            if item["quality_floor"] > 1:
                raise ValueError("quality floor exceeds one")
            if "chapter" in item and (
                type(item["chapter"]) is not int or item["chapter"] <= 0
            ):
                raise ValueError("chapter must be a positive integer")
    except (KernelError, ValueError, TypeError, ArithmeticError) as exc:
        raise KernelError(
            "ROUTING_POLICY_SCHEMA_INVALID", "routing policy violates its contract"
        ) from exc
    seen = set()
    for item in content["task_overrides"]:
        identity = (item["work_id"], item["task_type"], item.get("chapter"))
        if identity in seen:
            raise ValueError("ROUTING_DUPLICATE_TASK_OVERRIDE")
        seen.add(identity)
        baseline = task_policy(item["task_type"], item["risk"])
        if float(item["quality_floor"]) < baseline.quality_floor:
            raise ValueError("ROUTING_QUALITY_DOWNGRADE_FORBIDDEN")


def task_requirements(
    content: Mapping[str, Any], *, work_id: str, task_type: str, chapter: int = 0
) -> dict[str, Any]:
    validate_routing_policy(content)
    matches = [
        row
        for row in content["task_overrides"]
        if row["work_id"] == work_id
        and row["task_type"] == task_type
        and ("chapter" not in row or row["chapter"] == chapter)
    ]
    result: dict[str, Any] = {}
    for row in sorted(matches, key=lambda item: "chapter" in item):
        prior = dict(result)
        result.update(
            {
                key: value
                for key, value in row.items()
                if key not in {"work_id", "task_type", "chapter"}
            }
        )
        ranks = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        result["risk"] = max(
            (prior.get("risk", "LOW"), row["risk"]), key=ranks.__getitem__
        )
        result["quality_floor"] = max(
            prior.get("quality_floor", 0), row["quality_floor"]
        )
    return result
