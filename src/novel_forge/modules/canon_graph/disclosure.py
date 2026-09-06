from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


def bind_disclosure_policy(
    extraction: Mapping[str, Any], binding: Mapping[str, Any]
) -> dict[str, Any]:
    result = deepcopy(extraction)
    action = binding.get("action") or {}
    if action.get("contract_version") != "world-production-action.v2":
        return result
    planned = {
        row["disclosure_id"]: row
        for row in action["world_plan"].get("disclosure_projection", [])
    }
    reality = binding["frozen_source"]["reality"]
    hidden = {
        entry["source_event_id"]
        for entries in reality["current_state"].values()
        for entry in entries
        if entry["state"].get("fact_origin", {}).get("kind") == "GOVERNED_BACKGROUND"
    }
    hidden.update(
        event["event_id"]
        for event in reality.get("events", [])
        if event.get("mutation", {})
        .get("payload", {})
        .get("fact_origin", {})
        .get("kind")
        == "GOVERNED_BACKGROUND"
    )
    observed = {}
    for disclosure in result.get("disclosure_events", []):
        fact_id = disclosure.get("fact_id")
        authorized = planned.get(disclosure.get("disclosure_id"))
        if authorized is None:
            if fact_id in hidden:
                raise KernelError(
                    "WORLD_DISCLOSURE_UNAUTHORIZED",
                    "an accepted hidden event requires an exact governed audience presentation",
                )
            continue
        if (
            fact_id,
            disclosure.get("audience"),
            disclosure.get("disclosure_mode"),
            disclosure.get("presentation_channel"),
        ) != (
            authorized["fact_id"],
            authorized["audience"],
            authorized["mode"],
            authorized["presentation_channel"],
        ):
            raise KernelError(
                "WORLD_DISCLOSURE_POLICY_DRIFT",
                "Observer cannot expand the approved fact, audience, mode or presentation channel",
            )
        policy = {
            "contract_version": "world-disclosure-acceptance.v1",
            "action_asset_version_id": binding["asset_version_id"],
            "action_content_hash": binding["content_hash"],
            "disclosed_fields": list(authorized["permitted_fields"]),
            "claim_kind": authorized["claim_kind"],
            "presentation_projection": deepcopy(authorized["source"]["state"]),
        }
        disclosure["disclosure_policy"] = policy
        observed[(fact_id, authorized["audience"])] = disclosure
    for knowledge in result.get("reader_knowledge_changes", []):
        disclosure = observed.get((knowledge.get("fact_id"), "READER"))
        if disclosure:
            knowledge["disclosure_policy"] = deepcopy(disclosure["disclosure_policy"])
    known = {
        (entry["state"].get("fact_id"), entry["state"].get("character_id"))
        for entry in reality["current_state"].get("character_knowledge", [])
        if entry["state"].get("status") == "KNOWN"
    }
    for knowledge in result.get("character_knowledge_changes", []):
        key = (knowledge.get("fact_id"), knowledge.get("character_id"))
        if (
            key not in known
            and key in observed
            and observed[key]["disclosure_mode"] in {"MISDIRECT", "WITHHOLD"}
        ):
            raise KernelError(
                "WORLD_KNOWLEDGE_DISCLOSURE_DRIFT",
                "misdirection and withholding cannot grant objective character knowledge",
            )
        if key[0] in hidden and key not in observed and key not in known:
            raise KernelError(
                "WORLD_KNOWLEDGE_DISCLOSURE_REQUIRED",
                "objective hidden history cannot become character knowledge without an accepted audience event",
            )
    for (fact_id, audience), disclosure in observed.items():
        mode = disclosure["disclosure_mode"]
        if audience == "READER" or mode in {"MISDIRECT", "WITHHOLD"}:
            continue
        status = "KNOWN" if mode == "CONFIRM" else "SUSPECTED"
        changes = result.setdefault("character_knowledge_changes", [])
        existing = next(
            (
                row
                for row in changes
                if (row.get("fact_id"), row.get("character_id")) == (fact_id, audience)
            ),
            None,
        )
        if existing is not None and existing.get("status") != status:
            raise KernelError(
                "WORLD_KNOWLEDGE_DISCLOSURE_DRIFT",
                "character knowledge must preserve the disclosure's epistemic strength",
            )
        if existing is None:
            existing = {
                "fact_id": fact_id,
                "character_id": audience,
                "status": status,
                "summary": "Character information projected from an observed audience presentation.",
                "extraction_evidence": deepcopy(
                    disclosure.get("extraction_evidence") or {}
                ),
                "confidence": disclosure.get("confidence", 1.0),
                "coverage": "ACCEPTED_DISCLOSURE_PROJECTION",
            }
            changes.append(existing)
        existing["disclosure_policy"] = deepcopy(disclosure["disclosure_policy"])
    return result


def validate_disclosure_acceptance(
    outcome: Mapping[str, Any], binding: Mapping[str, Any]
) -> None:
    if (
        binding.get("action", {}).get("contract_version")
        != "world-production-action.v2"
    ):
        return
    fields = {
        "disclosure_event": "disclosure_events",
        "reader_knowledge": "reader_knowledge_changes",
        "character_knowledge": "character_knowledge_changes",
    }
    extracted = {field: [] for field in fields.values()}
    for event in outcome.get("state_events", []):
        if event["state_kind"] in fields:
            extracted[fields[event["state_kind"]]].append(event["mutation"]["payload"])
    expected = bind_disclosure_policy(extracted, binding)
    for field in fields.values():
        if len(expected[field]) != len(extracted[field]):
            raise KernelError(
                "WORLD_DISCLOSURE_PROJECTION_MISSING",
                "accepted audience projections must be complete",
            )
        for actual, projected in zip(extracted[field], expected[field], strict=True):
            if actual.get("disclosure_policy") != projected.get("disclosure_policy"):
                raise KernelError(
                    "WORLD_DISCLOSURE_ACCEPTANCE_DRIFT",
                    "accepted disclosure fields must match the exact governed presentation policy",
                )
