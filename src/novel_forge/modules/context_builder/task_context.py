from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash

SYSTEM_CONTEXT_WINDOW_TOKENS = 512_000
TASK_CONTEXT_POLICY_VERSION = "task-scoped-context.v1"
DRAFT_TASK_PROFILE = "draft-context-profile-v4"

_REFERENCE_FIELDS = frozenset({
    "cause_refs", "required_event_ids", "required_fact_ids", "required_long_distance_fact_ids",
    "source_event_id", "event_id", "fact_id", "proposition_id", "obligation_id",
    "obligation_refs", "required_obligation_ids", "rule_id", "world_rule_refs",
    "character_id", "character_ids", "actor_id", "entity_id", "entity_ids",
    "entity_key", "relationship_id", "thread_id", "arc_id", "arc_refs",
    "arc_plan_version_id", "accessible_knowledge", "known_fact_ids", "belief_refs",
    "fact_refs", "state_entity_refs", "required_event_refs", "required_source_event_ids",
})
_BOOKKEEPING_PREDICATES = frozenset({"accepted_revision_digest"})
_CORE_KINDS = frozenset({"world_rule", "reader_promise"})


def serialized_token_upper_bound(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def task_references(value: Any) -> set[str]:
    references: set[str] = set()

    def visit(item: Any, field: str = "") -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, str(key))
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child, field)
        elif field in _REFERENCE_FIELDS and isinstance(item, str) and item:
            references.add(item)
            if field == "entity_key":
                references.update(part.partition("=")[2] for part in item.split("|") if "=" in part)

    visit(value)
    return references


def source_identity(entry: Mapping[str, Any]) -> str:
    return str(entry.get("source_event_id") or entry.get("source_identity") or "")


def fact_aliases(fact: Mapping[str, Any]) -> set[str]:
    state = fact.get("state") or {}
    return {str(value) for value in (
        source_identity(fact), fact.get("fact_id"), fact.get("proposition_id"),
        state.get("fact_id"), state.get("proposition_id"),
        *(part.partition("=")[2] for part in str(fact.get("entity_key") or "").split("|") if part.partition("=")[0] in {"fact_id", "proposition_id"}),
    ) if value}


def task_reality_workset(
    reality: Mapping[str, Any], *, task: Mapping[str, Any], role_kinds: tuple[str, ...],
    required_event_ids: tuple[str, ...] = (), auxiliary_limit: int = 12,
) -> tuple[list[tuple[str, str, dict[str, Any], str]], dict[str, Any]]:
    boundary = int(reality["chapter_number"])
    chapter = int(task.get("chapter") or boundary + 1)
    selectors = task_references(task)
    events = {str(event["event_id"]): event for event in reality.get("events", [])}
    selected: dict[str, tuple[str, str, dict[str, Any], str]] = {}
    required = set(required_event_ids)
    auxiliary = []
    for kind, entries in sorted(reality["current_state"].items()):
        if kind not in role_kinds:
            continue
        for entry in entries:
            entry = deepcopy(dict(entry))
            event_id = source_identity(entry)
            if not event_id:
                initial_source = next((source for source in reality.get("initial_state_sources", ()) if source["state_kind"] == kind and source["entity_key"] == entry["entity_key"] and source["state_hash"] == narrative_hash(entry.get("state") or {})), None)
                if initial_source is None and reality.get("baseline_kind") != "APPROVED_FOUNDATION":
                    raise KernelError("TASK_CONTEXT_SOURCE_IDENTITY_REQUIRED", "state requires an accepted event or exact frozen initial source binding")
                entry["source_binding"] = deepcopy(initial_source["source_binding"] if initial_source else reality.get("initial_state_binding") or {"reality_revision_id": reality["revision_id"]})
                entry["source_identity"] = "initial:" + narrative_hash({"binding": entry["source_binding"], "kind": kind, "entity_key": entry["entity_key"]})
                event_id = entry["source_identity"]
            state = entry.get("state") or {}
            if kind == "canon_fact" and state.get("predicate") in _BOOKKEEPING_PREDICATES:
                continue
            refs = task_references({"entity_key": entry["entity_key"], "state": state})
            window = state.get("target_window") or {}
            due = kind == "narrative_obligation" and state.get("status") not in {"FULFILLED", "CANCELLED"} and (
                state.get("priority") in {"HIGH", "CRITICAL"}
                or (window.get("status") == "SCHEDULED" and int(window.get("to_chapter") or 0) <= chapter)
            )
            row = (kind, entry["entity_key"], deepcopy(dict(entry)), "CURRENT_STATE" if entry.get("source_event_id") else "FROZEN_INITIAL_STATE")
            if event_id in required or kind in _CORE_KINDS or due or selectors.intersection(refs):
                selected[event_id] = row
                required.add(event_id)
            else:
                auxiliary.append(row)
    obligation_ids = {row[2]["state"].get("obligation_id") for row in selected.values() if row[0] == "narrative_obligation"}
    for obligation_id in sorted(value for value in obligation_ids if value):
        history = [event for event in events.values() if event["state_kind"] == "narrative_obligation" and event["mutation"]["payload"].get("obligation_id") == obligation_id and int(event["coordinate"]["source_chapter"]) <= boundary]
        history.sort(key=lambda event: (int(event["coordinate"]["source_chapter"]), event["event_id"]))
        for event in history[:1] + history[-1:]:
            event_id = event["event_id"]
            selected.setdefault(event_id, (event["state_kind"], event["identity"]["entity_key"], {"source_event_id": event_id, "state": deepcopy(event["mutation"]["payload"])}, "OBLIGATION_PLANTING_OR_ADVANCE"))
            required.add(event_id)
    pending = sorted(required | (selectors & set(events)))
    for event_id in pending:
        required.add(event_id)
    visited: set[str] = set()
    while pending:
        event_id = pending.pop(0)
        if event_id in visited:
            continue
        visited.add(event_id)
        event = events.get(event_id)
        if event is None:
            if event_id in selected:
                continue
            raise KernelError("TASK_CONTEXT_DEPENDENCY_UNAVAILABLE", "a required accepted event is unavailable at the frozen boundary")
        if int(event["coordinate"]["source_chapter"]) > boundary:
            raise KernelError("TASK_CONTEXT_FUTURE_DEPENDENCY", "required event exceeds the accepted boundary")
        if event["state_kind"] not in role_kinds:
            raise KernelError("TASK_CONTEXT_DEPENDENCY_DENIED", "required dependency is outside the role read scope")
        selected.setdefault(event_id, (event["state_kind"], event["identity"]["entity_key"], {
            "source_event_id": event_id, "state": deepcopy(event["mutation"]["payload"]),
        }, "ACCEPTED_HISTORICAL_EVENT"))
        transition = event["mutation"]["payload"].get("world_transition") or {}
        for dependency in sorted(set(transition.get("cause_refs") or ())):
            if dependency in events:
                required.add(dependency)
                pending.append(dependency)
            elif dependency not in reality.get("foundation_cause_refs", []):
                raise KernelError("TASK_CONTEXT_DEPENDENCY_UNAVAILABLE", "causal predecessor is absent from the frozen accepted source")
    auxiliary.sort(key=lambda row: (-int((events.get(source_identity(row[2])) or {}).get("coordinate", {}).get("source_chapter") or 0), row[0], row[1]))
    for row in auxiliary[:auxiliary_limit]:
        selected.setdefault(source_identity(row[2]), row)
    rows = sorted(selected.values(), key=lambda row: (source_identity(row[2]) not in required, row[0], row[1], source_identity(row[2])))
    receipt = {
        "policy_version": TASK_CONTEXT_POLICY_VERSION, "role_scope": list(role_kinds),
        "task_hash": narrative_hash(task), "source_revision": reality["revision_id"],
        "source_hash": narrative_hash(reality), "accepted_through_chapter": boundary,
        "required_event_ids": sorted(required), "selectors": sorted(selectors),
        "selected_event_ids": [row[2]["source_event_id"] for row in rows if row[2].get("source_event_id")],
        "selected_source_ids": [source_identity(row[2]) for row in rows],
        "initial_source_ids": [source_identity(row[2]) for row in rows if not row[2].get("source_event_id")],
        "auxiliary_limit": auxiliary_limit, "candidate_count": len(rows),
        "full_current_state_count": sum(len(entries) for entries in reality["current_state"].values()),
        "compression": "LOSSLESS_TASK_PROJECTION", "fact_mutation_allowed": False,
    }
    return rows, {**receipt, "receipt_hash": narrative_hash(receipt)}


def project_task_state_facts(
    facts: list[dict[str, Any]], *, projection: Mapping[str, Any], chapter: int,
) -> list[dict[str, Any]]:
    from novel_forge.modules.chapter_authority.provider_views import _selectors, _state_fact_relevant

    selectors = _selectors(projection, {})
    explicit = set(projection.get("required_event_refs") or ())
    materialized = [fact for fact in facts if (fact.get("state") or {}).get("predicate") not in _BOOKKEEPING_PREDICATES]
    by_id = {alias: fact for fact in materialized for alias in (fact_aliases(fact) or {"projection:" + narrative_hash(fact)})}
    selected = {
        event_id: fact for event_id, fact in by_id.items()
        if event_id in explicit
        or fact.get("state_kind") in _CORE_KINDS
        or _state_fact_relevant(fact, selectors, chapter)
    }
    pending = list(selected)
    while pending:
        fact = selected[pending.pop(0)]
        for ref in (fact.get("state") or {}).get("world_transition", {}).get("cause_refs", ()):
            if ref in by_id and ref not in selected:
                selected[ref] = by_id[ref]
                pending.append(ref)
    unique = {narrative_hash(fact): fact for fact in selected.values()}
    return [deepcopy(unique[digest]) for digest in sorted(unique)]
