from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.modules.worldbuilding.dynamics import state_index
from .task_context import SYSTEM_CONTEXT_WINDOW_TOKENS, serialized_token_upper_bound, source_identity, task_reality_workset
from .governance import (
    ContextBudgetLimits,
    ContextPolicySnapshot,
    PolicyIdentity,
    compile_effective_context_policy,
)


_WORLD = (
    "world_state",
    "world_rule",
    "resource_state",
    "power_state",
    "faction_state",
    "location_state",
    "timeline_event",
    "consequence_state",
    "conflict_state",
)
_CHARACTER = (
    "character_state",
    "relationship_state",
    "character_knowledge",
    "character_belief",
    "character_arc",
)
_READER = (
    "reader_knowledge",
    "disclosure_event",
    "reader_promise",
    "narrative_obligation",
)
ROLE_STATE_KINDS = {
    "WORLD_REASONER": _WORLD + _CHARACTER + ("narrative_obligation",),
    "DIRECTOR": _WORLD + _CHARACTER + _READER + ("arc_state", "canon_fact"),
    "CHARACTER_REASONER": _CHARACTER,
    "SCENE_PLANNER": _WORLD + _CHARACTER + _READER + ("canon_fact",),
    "DIALOGUE_WRITER": _CHARACTER,
    "ACTION_WRITER": _WORLD
    + ("character_state", "character_knowledge", "character_belief"),
    "CONTINUITY_JUDGE": _WORLD + _CHARACTER + _READER + ("canon_fact",),
    "QUALITY_JUDGE": _WORLD + _CHARACTER + _READER + ("canon_fact", "arc_state"),
    "OBSERVER": _WORLD + _CHARACTER + _READER + ("canon_fact",),
}


def project_role_context(
    *,
    reality: Mapping[str, Any],
    role: str,
    token_budget: int,
    character_ids: tuple[str, ...] = (),
    entity_keys: tuple[str, ...] = (),
    required_event_ids: tuple[str, ...] = (),
    task: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    task_scoped = task is not None
    maximum = SYSTEM_CONTEXT_WINDOW_TOKENS if task_scoped else 32768
    if (
        role not in ROLE_STATE_KINDS
        or type(token_budget) is not int
        or not 0 < token_budget <= maximum
    ):
        raise KernelError(
            "REALITY_CONTEXT_POLICY_INVALID",
            "role Context requires a known role and bounded token budget",
        )
    if (
        role in {"CHARACTER_REASONER", "DIALOGUE_WRITER", "ACTION_WRITER"}
        and not character_ids
    ):
        raise KernelError(
            "REALITY_CONTEXT_ACTOR_REQUIRED",
            "character-local Context requires an explicit cast scope",
        )
    kinds = ROLE_STATE_KINDS[role]
    policy_body = {
        "role": role,
        "allowed_kinds": list(kinds),
        "maximum_tokens" if task_scoped else "maximum_bytes": maximum,
        "version": "reality-role-policy.v2" if task_scoped else "reality-role-policy.v1",
    }
    role_policy = ContextPolicySnapshot(
        identity=PolicyIdentity(
            f"reality-role:{role}",
            "context-policy-v1",
            narrative_hash(policy_body),
            policy_body["version"],
        ),
        allowed_logical_kinds=kinds,
        allowed_physical_types=("story_state_snapshot",),
        limits=ContextBudgetLimits(total=maximum),
        permitted_truncation_strategies=(),
    )
    caller_policy = ContextPolicySnapshot(
        identity=PolicyIdentity(
            "reality-role:caller",
            "caller-context-limit-v1",
            narrative_hash({"token_budget": token_budget}),
            str(reality["revision_id"]),
        ),
        allowed_logical_kinds=kinds,
        limits=ContextBudgetLimits(total=token_budget),
        permitted_truncation_strategies=(),
    )
    policy = compile_effective_context_policy(
        (role_policy, caller_policy)
    ).effective_policy
    candidates = []
    rejected = []
    scoped_entries = [
        (kind, key, entry, "CURRENT_STATE")
        for (kind, key), entry in sorted(state_index(reality).items())
    ]
    workset = None
    if task_scoped:
        scoped_entries, workset = task_reality_workset(reality, task=task, role_kinds=kinds, required_event_ids=required_event_ids)
        required_event_ids = tuple(workset["required_event_ids"])
    current_event_ids = {
        str(entry.get("source_event_id") or "") for _, _, entry, _ in scoped_entries
    }
    for event in reality.get("events", []):
        if (
            not task_scoped
            and event.get("event_id") in required_event_ids
            and event["event_id"] not in current_event_ids
        ):
            scoped_entries.append(
                (
                    event["state_kind"],
                    event["identity"]["entity_key"],
                    {
                        "source_event_id": event["event_id"],
                        "state": event["mutation"]["payload"],
                    },
                    "ACCEPTED_HISTORICAL_EVENT",
                )
            )
    for kind, key, entry, evidence_role in scoped_entries:
        event_id = source_identity(entry) if task_scoped else str(entry.get("source_event_id") or "")
        state = dict(entry.get("state") or {})
        reason = ""
        if kind not in policy.allowed_logical_kinds:
            reason = "ROLE_KIND_DENIED"
        elif (
            kind
            in {
                "character_knowledge",
                "character_belief",
                "character_state",
                "character_arc",
            }
            and character_ids
            and state.get("character_id") not in character_ids
        ):
            reason = "ACTOR_SCOPE_DENIED"
        elif (
            kind == "relationship_state"
            and character_ids
            and not {state.get("source_id"), state.get("target_id")}.intersection(
                character_ids
            )
        ):
            reason = "ACTOR_SCOPE_DENIED"
        elif (
            entity_keys
            and key not in entity_keys
            and state.get("character_id") not in character_ids
        ):
            reason = "ENTITY_SCOPE_DENIED"
        if reason:
            rejected.append({"source_event_id": event_id, "reason": reason})
            continue
        candidates.append(
            {
                "state_kind": kind,
                "entity_key": key,
                "source_event_id": str(entry.get("source_event_id") or ""),
                **({"source_identity": event_id, "source_binding": entry["source_binding"]} if task_scoped and evidence_role == "FROZEN_INITIAL_STATE" else {}),
                "state": state,
                "evidence_role": evidence_role,
            }
        )
    candidates.sort(
        key=lambda c: (
            source_identity(c) not in required_event_ids,
            c["state_kind"],
            c["entity_key"],
        )
    )
    selected = []
    seen = set()
    consumed = 0
    for candidate in candidates:
        digest = narrative_hash(candidate)
        if digest in seen:
            continue
        seen.add(digest)
        amount = serialized_token_upper_bound(candidate)
        if consumed + amount > policy.limits.total:
            rejected.append(
                {
                    "source_event_id": candidate["source_event_id"],
                    "reason": "CONTEXT_BUDGET_EXCEEDED",
                }
            )
            continue
        selected.append(candidate)
        consumed += amount
    if not set(required_event_ids).issubset(
        {source_identity(item) for item in selected}
    ):
        raise KernelError(
            "REALITY_CONTEXT_REQUIRED_SOURCE_UNAVAILABLE",
            "required causal evidence cannot be omitted or truncated",
        )
    body = {
        "contract_version": "narrative-role-context.v2" if task_scoped else "narrative-role-context.v1",
        "project_id": reality["project_id"],
        "book_id": reality["book_id"],
        "reality_revision_id": reality["revision_id"],
        "accepted_through_chapter": reality["chapter_number"],
        "role": role,
        "character_ids": list(character_ids),
        "entity_keys": list(entity_keys),
        "policy": policy.to_dict(),
        **({"task_workset": workset} if workset is not None else {}),
        "selection": selected,
        "rejections": rejected,
        "estimated_tokens": consumed,
        "token_accounting": "utf8-byte-upper-bound.v1",
        "provider_admission": "REQUIRED_AT_EXISTING_EXTERNAL_EFFECT_BOUNDARY",
        "fact_mutation_allowed": False,
    }
    return {**body, "context_digest": narrative_hash(body)}
