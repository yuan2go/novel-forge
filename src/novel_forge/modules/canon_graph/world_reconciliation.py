from __future__ import annotations

import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.contracts import NarrativeStateKind
from novel_forge.modules.worldbuilding.dynamics import (
    WorldTransition,
    validate_world_transition,
)


WORLD_CHANGE_IDENTITIES = {
    "world_state_changes": ("world_state", "world_state_id"),
    "faction_state_changes": ("faction_state", "faction_id"),
    "location_state_changes": ("location_state", "location_id"),
    "consequence_changes": ("consequence_state", "consequence_id"),
    "conflict_state_changes": ("conflict_state", "conflict_id"),
}


def observed_world_transition(value: Mapping[str, Any]) -> WorldTransition:
    envelope = value.get("world_transition")
    try:
        if not isinstance(envelope, dict) or not isinstance(
            envelope.get("payload_json"), str
        ):
            raise ValueError("missing typed transition")
        return WorldTransition.from_mapping(json.loads(envelope["payload_json"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelError(
            "WORLD_OBSERVATION_CONTRACT_INVALID",
            "observed world changes require a complete typed transition",
        ) from exc


def validate_observed_world_changes(
    *,
    extraction: Mapping[str, Any],
    historical_state: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    violations = []
    current: dict[str, list[dict[str, Any]]] = {}
    for kind, entries in historical_state.items():
        kind = {
            "canon_snapshot": "canon_fact",
            "timeline_snapshot": "timeline_event",
            "reward_ledger": "reward_event",
        }.get(kind, kind)
        if kind not in {value.value for value in NarrativeStateKind}:
            continue
        current[kind] = []
        for entry in entries:
            state = entry.get("state")
            payload = dict(state) if isinstance(state, dict) else dict(entry)
            key = str(entry.get("entity_key") or "")
            if not key:
                continue
            current[kind].append({**entry, "state": payload})
    reality = {"current_state": current, "events": []}
    known_causes = {
        str(entry.get("source_event_id") or "")
        for entries in current.values()
        for entry in entries
    }
    known_causes.discard("")
    for field, (kind, identity_field) in WORLD_CHANGE_IDENTITIES.items():
        for raw in extraction.get(field, []):
            try:
                transition = observed_world_transition(raw)
                if (
                    transition.state_kind.value != kind
                    or transition.entity_key
                    != f"{identity_field}={raw.get(identity_field, '')}"
                ):
                    raise KernelError(
                        "WORLD_OBSERVATION_IDENTITY_MISMATCH",
                        "observed transition and extracted world identity differ",
                    )
                if not set(transition.cause_refs).issubset(known_causes):
                    raise KernelError(
                        "WORLD_OBSERVATION_CAUSE_UNRESOLVED",
                        "observed causes must resolve to accepted input evidence",
                    )
                if any(
                    key not in raw or raw[key] != value
                    for key, value in transition.changes.items()
                ):
                    raise KernelError(
                        "WORLD_OBSERVATION_DELTA_MISMATCH",
                        "Observer fields must match the transition it asks to reconcile",
                    )
                requirements = validate_world_transition(transition, reality)
                if any(not requirement["satisfied"] for requirement in requirements):
                    raise KernelError(
                        "WORLD_OBSERVATION_CAUSAL_DEBT_OPEN",
                        "unprepared causal conditions block actual acceptance",
                    )
            except KernelError as exc:
                violations.append(
                    {
                        "conflict_code": exc.code,
                        "severity": "blocking",
                        "existing_version": historical_state,
                        "candidate_version": raw,
                        "evidence": {"field": field, "message": str(exc)},
                        "recommended_resolution": "revise the observation or upstream causal preparation",
                        "approval_requirement": "NONE",
                    }
                )
    return violations


def bind_world_event_lineage(changes: dict[str, list[dict[str, Any]]]) -> None:
    for kind, _ in WORLD_CHANGE_IDENTITIES.values():
        for change in changes.get(kind, []):
            transition = observed_world_transition(change)
            change["story_time"] = transition.story_time.to_dict()
            change["causality"] = {
                "cause_refs": list(transition.cause_refs),
                "precondition_refs": [
                    r.requirement_id for r in transition.requirements
                ],
                "participant_ids": [transition.actor_id],
                "effect_kinds": ["STATE"],
            }


def validate_actual_world_events(
    *, previous_reality: Mapping[str, Any], chapter_outcome: Mapping[str, Any]
) -> None:
    known_causes = {
        str(entry.get("source_event_id") or "")
        for entries in (previous_reality.get("current_state") or {}).values()
        for entry in entries
    } | {
        str(event.get("event_id") or "") for event in previous_reality.get("events", [])
    }
    known_causes.discard("")
    for event in chapter_outcome.get("state_events", []):
        if event.get("state_kind") not in {
            kind for kind, _ in WORLD_CHANGE_IDENTITIES.values()
        }:
            continue
        payload = dict((event.get("mutation") or {}).get("payload") or {})
        transition = observed_world_transition(payload)
        if (
            event.get("state_kind") != transition.state_kind.value
            or (event.get("identity") or {}).get("entity_key") != transition.entity_key
            or any(
                payload.get(key) != value for key, value in transition.changes.items()
            )
        ):
            raise KernelError(
                "WORLD_ACTUAL_IDENTITY_MISMATCH",
                "accepted event identity and delta must equal its reconciled transition",
            )
        if not set(transition.cause_refs).issubset(known_causes):
            raise KernelError(
                "WORLD_ACTUAL_CAUSE_UNRESOLVED",
                "Book acceptance cannot commit an unsupported world cause",
            )
        if event.get("story_time") != transition.story_time.to_dict() or event.get(
            "causality", {}
        ).get("cause_refs") != list(transition.cause_refs):
            raise KernelError(
                "WORLD_ACTUAL_LINEAGE_MISMATCH",
                "Actual event time and causes must match its reconciled transition",
            )
        receipts = validate_world_transition(transition, previous_reality)
        if any(not receipt["satisfied"] for receipt in receipts):
            raise KernelError(
                "WORLD_ACTUAL_CAUSAL_DEBT_OPEN",
                "Book acceptance requires causal conditions in the exact preceding Reality",
            )
