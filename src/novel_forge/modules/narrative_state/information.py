from copy import deepcopy
from typing import Any, Mapping


def disclosed_fact_projection(entry: Mapping[str, Any]) -> dict[str, Any]:
    projected = deepcopy(dict(entry))
    state = projected.get("state") or {}
    if state.get("preparation_lineage") or (state.get("fact_origin") or {}).get(
        "kind"
    ) in {
        "GOVERNED_BACKGROUND",
        "GOVERNED_PREPARATION",
    }:
        projected["state"] = {
            key: value
            for key, value in state.items()
            if key
            not in {
                "fact_origin",
                "world_transition",
                "causal_batch",
                "causality",
                "approval_resolution",
                "preparation_schedule",
                "dependencies",
                "expected_payoff",
                "causal_requirement",
                "retirement_evidence",
                "target_retirement_evidence",
                "preparation_lineage",
                "actor_step_execution",
            }
        }
    return projected


def accepted_event_projection(
    reality: Mapping[str, Any], event_id: str
) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.errors import KernelError

    event = next(
        (
            event
            for event in reality.get("events", [])
            if event.get("event_id") == event_id
        ),
        None,
    )
    if event is not None and event.get("mutation") is not None:
        scope = event.get("scope") or {}
        chapter = (event.get("coordinate") or {}).get("source_chapter")
        if (
            (scope.get("project_id"), scope.get("book_id"))
            != (reality["project_id"], reality["book_id"])
            or type(chapter) is not int
            or not 0 < chapter <= reality["chapter_number"]
        ):
            raise KernelError(
                "WORLD_DISCLOSURE_SOURCE_SCOPE_INVALID",
                "disclosure must resolve an event in this Book's exact accepted frontier",
            )
        return disclosed_fact_projection(
            {
                "source_event_id": event_id,
                "state_kind": event["state_kind"],
                "entity_key": event["identity"]["entity_key"],
                "state": event["mutation"]["payload"],
                "accepted_chapter": chapter,
                "evidence_role": "ACCEPTED_HISTORICAL_OCCURRENCE",
                "current_assertion": any(
                    entry.get("source_event_id") == event_id
                    for entry in reality["current_state"].get(event["state_kind"], [])
                ),
            }
        )
    entry = next(
        (
            entry
            for entries in reality["current_state"].values()
            for entry in entries
            if entry.get("source_event_id") == event_id
        ),
        None,
    )
    if entry is None:
        raise KernelError(
            "WORLD_DISCLOSURE_SOURCE_UNKNOWN",
            "planned disclosure requires an exact accepted event in the frozen scope",
        )
    return disclosed_fact_projection(entry)


_DISCLOSURE_PRIVATE_FIELDS = frozenset(
    {
        "fact_origin",
        "world_transition",
        "causal_batch",
        "causality",
        "preparation_lineage",
        "actor_step_execution",
        "preparation_schedule",
        "dependencies",
        "expected_payoff",
        "causal_requirement",
        "retirement_evidence",
        "target_retirement_evidence",
        "approval_resolution",
        "extraction_evidence",
        "provenance",
        "reason",
        "rationale",
        "action",
        "safe_summary",
        "summary",
    }
)


def project_disclosure(
    reality: Mapping[str, Any], disclosure: Mapping[str, Any]
) -> dict[str, Any]:
    return _project_disclosure(reality, disclosure)


def project_candidate_disclosure(
    reality: Mapping[str, Any],
    disclosure: Mapping[str, Any],
    *,
    transitions: list[dict[str, Any]],
    chapter_number: int,
    path_id: str,
) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.worldbuilding.working_state import (
        validate_preparation_batch,
    )

    if (
        reality.get("epistemic_contract") != "world-agency.v2"
        or chapter_number != reality["chapter_number"] + 1
    ):
        raise KernelError(
            "WORLD_DISCLOSURE_SOURCE_SCOPE_INVALID",
            "candidate disclosure must belong to the next chapter of the frozen agency contract",
        )
    _, preview = validate_preparation_batch(
        reality=reality,
        transitions=transitions,
        chapter_number=chapter_number,
        path_id=path_id,
    )
    event = next(
        (
            row
            for row in preview["events"]
            if row.get("event_id") == disclosure.get("event_id")
            and row.get("coverage") == "PRIVATE_PREPARATION_SIMULATION"
        ),
        None,
    )
    if event is None:
        raise KernelError(
            "WORLD_DISCLOSURE_SOURCE_UNKNOWN",
            "candidate disclosure must resolve an occurrence in the selected validated local path",
        )
    entry = {
        "state": event["mutation"]["payload"],
        "evidence_role": "PLANNED_LOCAL_OCCURRENCE",
        "current_assertion": any(
            row.get("source_event_id") == event["event_id"]
            for row in preview["current_state"].get(event["state_kind"], [])
        ),
    }
    return _project_disclosure(reality, disclosure, entry)


def _project_disclosure(
    reality: Mapping[str, Any],
    disclosure: Mapping[str, Any],
    entry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.worldbuilding.dynamics import (
        require_contract_fields,
        require_text_fields,
    )

    require_contract_fields(
        disclosure,
        required={
            "disclosure_id",
            "event_id",
            "audience",
            "mode",
            "fields",
            "presentation_channel",
            "claim_kind",
        },
    )
    require_text_fields(
        disclosure,
        (
            "disclosure_id",
            "event_id",
            "audience",
            "mode",
            "presentation_channel",
            "claim_kind",
        ),
    )
    audience = disclosure["audience"]
    mode = disclosure["mode"]
    fields = disclosure["fields"]
    characters = set(reality.get("approved_character_ids", [])) | {
        entry["state"]["character_id"]
        for entry in reality["current_state"].get("character_state", [])
        if entry["state"].get("character_id")
    }
    if audience != "READER" and audience not in characters:
        raise KernelError(
            "WORLD_DISCLOSURE_AUDIENCE_INVALID",
            "each disclosure targets Reader or one exact approved character; mixed audiences require separate records",
        )
    if (
        mode not in {"HINT", "PARTIAL", "MISDIRECT", "CONFIRM", "WITHHOLD"}
        or disclosure["claim_kind"]
        not in {"CURRENT_ASSERTION", "HISTORICAL_OCCURRENCE"}
        or not isinstance(fields, list)
        or any(not isinstance(key, str) or not key for key in fields)
        or len(fields) != len(set(fields))
        or bool(fields) == (mode == "WITHHOLD")
    ):
        raise KernelError(
            "WORLD_DISCLOSURE_POLICY_INVALID",
            "disclosure requires an explicit mode, claim semantics and field scope",
        )
    if entry is None:
        entry = accepted_event_projection(reality, disclosure["event_id"])
    if (
        disclosure["claim_kind"] == "CURRENT_ASSERTION"
        and entry.get("current_assertion") is False
    ):
        raise KernelError(
            "WORLD_DISCLOSURE_ASSERTION_STALE",
            "an earlier occurrence cannot be presented as the current assertion after its state changed",
        )
    state = entry.get("state") or {}
    if set(fields).intersection(_DISCLOSURE_PRIVATE_FIELDS) or any(
        key not in state
        or not isinstance(state[key], (str, int, float, bool, type(None)))
        for key in fields
    ):
        raise KernelError(
            "WORLD_DISCLOSURE_FIELDS_INVALID",
            "presentation fields must select scalar accepted content and cannot expose private decision metadata",
        )
    return {
        "disclosure_id": disclosure["disclosure_id"],
        "fact_id": disclosure["event_id"],
        "audience": audience,
        "mode": mode,
        "presentation_channel": disclosure["presentation_channel"],
        "claim_kind": disclosure["claim_kind"],
        "permitted_fields": list(fields),
        "source": {
            "source_event_id": disclosure["event_id"],
            "state": {key: state[key] for key in fields}
            if audience == "READER" and mode != "WITHHOLD"
            else {},
            "evidence_role": entry.get("evidence_role", "ACCEPTED_CURRENT_STATE"),
        },
    }
