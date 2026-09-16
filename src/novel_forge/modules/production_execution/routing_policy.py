from __future__ import annotations

from typing import Any, Mapping

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
    from novel_forge.modules.chapter_authority.provider_output_contracts import (
        validate_chapter_provider_output_against_schema,
    )

    validate_chapter_provider_output_against_schema(
        "provider_routing_policy", POLICY_SCHEMA, dict(content)
    )
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
