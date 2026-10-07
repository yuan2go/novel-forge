from __future__ import annotations

import json
from copy import deepcopy
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
    frozen_reality: Mapping[str, Any] | None = None,
    reader_observation_lineage: bool = False,
) -> list[dict[str, Any]]:
    if frozen_reality is not None:
        from .domain import _narrative_state_changes, _bind_narrative_entity_versions
        from novel_forge.modules.narrative_state.contracts import events_from_canon_patch
        changes = _narrative_state_changes(dict(extraction), [])
        try:
            bind_world_event_lineage(changes, reader_observation_lineage=reader_observation_lineage)
            _bind_narrative_entity_versions(changes, dict(historical_state))
            events = events_from_canon_patch(
                project_id=str(extraction["project_id"]), book_id=str(frozen_reality["book_id"]),
                source_chapter=int(extraction["chapter"]), chapter_outcome_id="reconciliation-preview",
                canon_patch_asset_version_id="reconciliation-preview", accepted_draft_asset_version_id=str(extraction["revision_asset_version_id"]),
                source_operation_id="reconciliation-preview", trace_id="reconciliation-preview", canon_patch={"state_changes": changes},
            )
            validate_actual_world_events(previous_reality=frozen_reality, chapter_outcome={"state_events": [event.to_dict() for event in events]})
            return []
        except KernelError as exc:
            return [{"conflict_code": exc.code, "severity": "blocking", "existing_version": frozen_reality["revision_id"], "candidate_version": extraction, "evidence": {"message": str(exc)}, "recommended_resolution": "revise the causal batch against its frozen source", "approval_requirement": "NONE"}]
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


def bind_world_event_lineage(changes: dict[str, list[dict[str, Any]]], *, reader_observation_lineage: bool = False) -> None:
    for kind, items in changes.items():
        for change in items:
            if not change.get("world_transition") and kind not in {value[0] for value in WORLD_CHANGE_IDENTITIES.values()}:
                if reader_observation_lineage and kind == "disclosure_event" and change.get("story_time") and not change.get("causal_batch"):
                    evidence = change.get("extraction_evidence") or {}
                    span = evidence.get("span") or {}
                    source = evidence.get("source_revision_asset_version_id")
                    if not source or not evidence.get("excerpt_digest") or type(span.get("start")) is not int or type(span.get("end")) is not int or not 0 <= span["start"] < span["end"]:
                        raise KernelError("READER_DISCLOSURE_SOURCE_REQUIRED", "Timed disclosure must bind its exact supported candidate span")
                    change["reader_observation_lineage"] = {"contract_version": "reader-disclosure-observation.v1", "source_revision_asset_version_id": source}
                    change["causality"] = {"cause_refs": [f"observed:{source}:{span['start']}:{span['end']}"],
                        "participant_ids": [change["character_id"]] if change.get("character_id") else [],
                        "precondition_refs": [], "effect_kinds": ["DISCLOSURE"]}
                if change.get("causal_batch"):
                    evidence = change.get("extraction_evidence") or {}
                    span = evidence.get("span") or {}
                    observed_ref = f"observed:{evidence.get('source_revision_asset_version_id', '')}:{span.get('start')}:{span.get('end')}"
                    change["causality"] = {"cause_refs": list(change["causal_batch"]["depends_on"]) or [observed_ref], "participant_ids": [change["character_id"]] if change.get("character_id") else [], "precondition_refs": [], "effect_kinds": ["STATE"]}
                continue
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
    if previous_reality.get("world_dynamics_contract") == "world-dynamics.v2":
        known_causes.update(previous_reality.get("foundation_cause_refs", []))
    from novel_forge.modules.narrative_state.causal_batch import (
        batch_binding,
        compile_causal_batch,
    )

    events = chapter_outcome.get("state_events", [])
    if any(batch_binding(event) is not None for event in events):
        batch = compile_causal_batch(events, accepted_ids=frozenset(known_causes))
        validated: dict[str, Mapping[str, Any]] = {}
        for event in batch.ordered:
            binding = batch_binding(event)
            name = str(binding["local_id"])
            working = deepcopy(previous_reality)
            working["world_dynamics_contract"] = "world-dynamics.v2"
            ancestors = batch.ancestors[name]
            from novel_forge.modules.narrative_state.contracts import (
                NarrativeStateEvent,
            )
            from novel_forge.modules.narrative_state.reducers import (
                preview_state_events,
            )

            prior_events = [
                prior
                for prior_name, prior in validated.items()
                if prior_name in ancestors
            ]
            working["current_state"] = preview_state_events(
                previous=dict(previous_reality),
                events=[
                    NarrativeStateEvent.from_dict(dict(prior)) for prior in prior_events
                ],
            )
            for entries in working["current_state"].values():
                for entry in entries:
                    local = next(
                        (
                            name
                            for name, identity in batch.event_ids.items()
                            if identity == entry["source_event_id"]
                        ),
                        None,
                    )
                    if local is not None:
                        entry["source_event_id"] = f"local:{local}"
            working.setdefault("events", []).extend(prior_events)
            _validate_world_actual(
                event,
                working,
                known_causes | {f"local:{parent}" for parent in ancestors},
            )
            validated[name] = event
        remaining = [event for event in events if batch_binding(event) is None]
        for event in remaining:
            _validate_world_actual(event, previous_reality, known_causes)
        from novel_forge.modules.worldbuilding.dynamics import state_index, validate_world_state_rules

        current = preview_state_events(
            previous=dict(previous_reality),
            events=[NarrativeStateEvent.from_dict(dict(event)) for event in [*remaining, *batch.ordered]],
        )
        validate_world_state_rules(
            reality=previous_reality, state=state_index({"current_state": current}),
            affected_kinds={event["state_kind"] for event in events},
        )
        return
    for event in events:
        _validate_world_actual(event, previous_reality, known_causes)


def _validate_world_actual(
    event: Mapping[str, Any],
    previous_reality: Mapping[str, Any],
    known_causes: set[str],
) -> None:
    payload = dict((event.get("mutation") or {}).get("payload") or {})
    observed_disclosure = payload.get("reader_observation_lineage")
    if observed_disclosure and (event.get("state_kind") != "disclosure_event" or observed_disclosure.get("contract_version") != "reader-disclosure-observation.v1"):
        raise KernelError("READER_DISCLOSURE_SCOPE_INVALID", "Reader observation cannot authorize character or world actions")
    if payload.get("causal_batch") or observed_disclosure:
        evidence = event.get("evidence") or {}
        span = evidence.get("span") or {}
        draft = (event.get("provenance") or {}).get("accepted_draft_asset_version_id")
        expected_observation = f"observed:{draft}:{span.get('start')}:{span.get('end')}"
        for cause in (event.get("causality") or {}).get("cause_refs", []):
            if cause.startswith("observed:"):
                if cause != expected_observation or evidence.get("source_revision_asset_version_id") != draft or not evidence.get("excerpt_digest") or type(span.get("start")) is not int or type(span.get("end")) is not int or not 0 <= span["start"] < span["end"]:
                    raise KernelError("WORLD_OBSERVED_ROOT_UNVERIFIED", "an observed root must bind its exact accepted draft and validated evidence span")
            elif observed_disclosure or cause not in known_causes:
                raise KernelError("WORLD_ACTUAL_CAUSE_UNRESOLVED", "batch causes must resolve to accepted evidence or verified ancestors")
    if event.get("state_kind") not in {
        kind for kind, _ in WORLD_CHANGE_IDENTITIES.values()
    } and not payload.get("world_transition"):
        return
    transition = observed_world_transition(payload)
    if (
        event.get("state_kind") != transition.state_kind.value
        or (event.get("identity") or {}).get("entity_key") != transition.entity_key
        or any(payload.get(key) != value for key, value in transition.changes.items())
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
