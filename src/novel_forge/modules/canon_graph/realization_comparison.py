from __future__ import annotations

from copy import deepcopy
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

CONTRACT = "realization-intent-comparison.v1"
DIMENSIONS = {"causality": "CAUSALITY_DRIFT", "required_state": "STATE_DELTA_DRIFT",
              "knowledge_boundary": "KNOWLEDGE_BOUNDARY_DRIFT"}
VERDICTS = ("EQUIVALENT", "DEVIATED", "UNCERTAIN")


def comparison_input(*, planned: dict[str, Any], extraction: dict[str, Any], text: str) -> dict[str, Any]:
    from novel_forge.modules.hierarchical_planning.realization_domain import realization_hash

    events = {str(item["event_id"]): dict(item) for item in planned.get("events") or []}
    observed = [dict(item) for item in extraction.get("realization_evidence") or []
                if item.get("observation_status") == "OBSERVED"]
    if any(str(item.get("planned_event_id") or "") not in events for item in observed):
        raise KernelError("CANON_REALIZATION_EVIDENCE_INVALID", "Observation is outside the exact frozen realization slice")
    if (len({item["planned_event_id"] for item in observed}) != len(observed)
        or any(not item.get("grounded_claim_id") for item in observed)):
        raise KernelError("CANON_REALIZATION_EVIDENCE_INVALID", "Observation requires unique events and exact grounded claim identities")
    quotes = {str(item.get("evidence_quote")) for values in extraction.values()
              if isinstance(values, list) for item in values
              if isinstance(item, dict) and item.get("grounded_claim_id") and item.get("evidence_quote")}
    if observed and not quotes:
        raise KernelError("REALIZATION_COMPARISON_EVIDENCE_INVALID", "Observed events require exact final-candidate quotations before independent comparison")
    return {"contract_version": CONTRACT,
            "events": [{"planned_event_id": item["planned_event_id"],
                        "planned_event_hash": realization_hash(events[str(item["planned_event_id"])]),
                        "planned_intent": events[str(item["planned_event_id"])],
                        "observed_claim_id": item["grounded_claim_id"],
                        "observation": item} for item in observed],
            "evidence_quotes": sorted(quotes), "prose_length": len(text)}


def comparison_schema(schema: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    if inputs.get("contract_version") != CONTRACT:
        raise KernelError("REALIZATION_COMPARISON_CONTRACT_INVALID", "Unknown intent comparison contract")
    result = deepcopy(schema)
    identities = [str(item["planned_event_id"]) for item in inputs["events"]]
    properties = {"planned_event_id": {"type": "string", **({"enum": identities} if identities else {})},
                  **{key: {"type": "string", "enum": list(VERDICTS)} for key in DIMENSIONS},
                  "reason": {"type": "string", "minLength": 1, "maxLength": 4000},
                  "evidence_quotes": {"type": "array", "minItems": 1, "maxItems": 8,
                      "items": {"type": "string", **({"enum": inputs["evidence_quotes"]} if inputs["evidence_quotes"] else {})}}}
    result["properties"]["realization_comparisons"] = {"type": "array", "minItems": len(identities),
        "maxItems": len(identities), "items": {"type": "object", "properties": properties,
                                                "required": list(properties), "additionalProperties": False}}
    result["required"] = [*result["required"], "realization_comparisons"]
    return result


def validate_comparisons(*, inputs: dict[str, Any], result: dict[str, Any],
                         revision_asset_version_id: str, text: str) -> list[dict[str, Any]]:
    from novel_forge.modules.review.diagnostics import validate_location
    from .grounding import text_hash

    expected = {str(item["planned_event_id"]): item for item in inputs["events"]}
    supplied = result.get("realization_comparisons")
    if (not isinstance(supplied, list) or len(supplied) != len(expected)
        or any(not isinstance(item, dict) for item in supplied)
        or {item.get("planned_event_id") for item in supplied} != set(expected)):
        raise KernelError("REALIZATION_COMPARISON_COVERAGE_INVALID", "Independent support must compare every observed event exactly once")
    validated = []
    for item in supplied:
        source = expected[str(item["planned_event_id"])]
        quotes = item.get("evidence_quotes")
        if (any(item.get(key) not in VERDICTS for key in DIMENSIONS)
            or not str(item.get("reason") or "").strip() or not isinstance(quotes, list) or not quotes
            or any(quote not in inputs["evidence_quotes"] for quote in quotes)):
            raise KernelError("REALIZATION_COMPARISON_EVIDENCE_INVALID", "Comparison requires typed judgments and exact final-prose evidence")
        locations = [validate_location({"quote": quote}, text) for quote in quotes]
        validated.append({"contract_version": CONTRACT, "planned_event_id": item["planned_event_id"],
            "planned_event_hash": source["planned_event_hash"], "observed_claim_id": source["observed_claim_id"],
            "candidate_asset_version_id": revision_asset_version_id, "candidate_text_hash": text_hash(text),
            "judgments": {key: item[key] for key in DIMENSIONS}, "reason": item["reason"],
            "evidence_locations": locations, "evidence_class": "MODEL_SEMANTIC_SUPPORT"})
    return validated


def bind_comparisons(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    grounding = dict(extraction.get("grounding") or {})
    comparisons = grounding.get("realization_comparisons")
    evidence = [dict(item) for item in extraction.get("realization_evidence") or []]
    if comparisons is None:
        return evidence
    if grounding.get("semantic_status") != "SUPPORTED_CANDIDATE":
        raise KernelError("CANON_GROUNDING_SUPPORT_REQUIRED", "Comparison cannot bypass independent claim support")
    by_id = {item["planned_event_id"]: dict(item) for item in comparisons}
    for item in evidence:
        if item.get("observation_status") != "OBSERVED":
            continue
        compared = by_id.get(item.get("planned_event_id"))
        if (not compared or compared["observed_claim_id"] != item.get("grounded_claim_id")
            or compared["candidate_asset_version_id"] != grounding["candidate_asset_version_id"]
            or compared["candidate_text_hash"] != grounding["text_hash"]):
            raise KernelError("REALIZATION_COMPARISON_SOURCE_INVALID", "Comparison belongs to a different claim or adopted candidate")
        item["semantic_comparison"] = compared
    return evidence
