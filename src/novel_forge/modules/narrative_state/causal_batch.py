from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import StoryTime


@dataclass(frozen=True, slots=True)
class CausalBatch:
    ordered: tuple[Mapping[str, Any], ...]
    ancestors: Mapping[str, frozenset[str]]
    event_ids: Mapping[str, str]


def batch_binding(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    payload = (event.get("mutation") or {}).get("payload") or {}
    return payload.get("causal_batch")


def compile_causal_batch(
    events: Sequence[Mapping[str, Any]], *, accepted_ids: frozenset[str]
) -> CausalBatch:
    nodes: dict[str, Mapping[str, Any]] = {}
    dependencies: dict[str, set[str]] = {}
    event_ids: dict[str, str] = {}
    for event in events:
        binding = batch_binding(event)
        if binding is None:
            continue
        if (
            not isinstance(binding, Mapping)
            or set(binding) != {"contract_version", "local_id", "depends_on"}
            or binding.get("contract_version") != "causal-batch-event.v1"
            or not isinstance(binding.get("local_id"), str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", binding["local_id"])
            or not isinstance(binding.get("depends_on"), list)
            or any(not isinstance(ref, str) or not ref for ref in binding["depends_on"])
        ):
            raise KernelError(
                "WORLD_BATCH_CONTRACT_INVALID",
                "batch events require versioned local names and explicit dependencies",
            )
        name = binding["local_id"]
        identity = str(event.get("event_id") or "")
        if (
            name in nodes
            or not identity
            or identity in event_ids.values()
            or identity in accepted_ids
        ):
            raise KernelError(
                "WORLD_BATCH_IDENTITY_COLLISION",
                "batch names and immutable event identities must be unique",
            )
        refs = binding["depends_on"]
        if len(refs) != len(set(refs)):
            raise KernelError(
                "WORLD_BATCH_CONTRACT_INVALID", "batch dependencies must be unique"
            )
        nodes[name] = event
        event_ids[name] = identity
        dependencies[name] = set(refs)
    if len(nodes) > 128:
        raise KernelError(
            "WORLD_BATCH_BOUND_EXCEEDED",
            "one acceptance batch permits at most 128 causal events",
        )
    tagged_keys = {
        (event["state_kind"], event["identity"]["entity_key"])
        for event in nodes.values()
    }
    if any(
        batch_binding(event) is None
        and (event["state_kind"], event["identity"]["entity_key"]) in tagged_keys
        for event in events
    ):
        raise KernelError(
            "WORLD_BATCH_MIXED_WRITE",
            "all writes to a batch identity must declare their causal order",
        )
    for refs in dependencies.values():
        if any(
            ref[6:] not in nodes
            if ref.startswith("local:")
            else ref not in accepted_ids
            for ref in refs
        ):
            raise KernelError(
                "WORLD_BATCH_REFERENCE_UNKNOWN",
                "dependencies must name accepted evidence or a declared local event",
            )
    remaining = {
        key: {ref[6:] for ref in refs if ref.startswith("local:")}
        for key, refs in dependencies.items()
    }
    order: list[str] = []
    ancestors: dict[str, frozenset[str]] = {}
    while remaining:
        ready = sorted(name for name, refs in remaining.items() if not refs)
        if not ready:
            raise KernelError(
                "WORLD_BATCH_CAUSAL_CYCLE",
                "a causal batch cannot depend on its own future",
            )
        for name in ready:
            direct = {ref[6:] for ref in dependencies[name] if ref.startswith("local:")}
            ancestors[name] = frozenset(
                direct.union(*(ancestors[parent] for parent in direct))
            )
            order.append(name)
            del remaining[name]
        for refs in remaining.values():
            refs.difference_update(ready)
    writers: dict[tuple[str, str], list[str]] = {}
    for name in order:
        event = nodes[name]
        time = StoryTime.from_dict(dict(event.get("story_time") or {}))
        if time.precision == "UNSPECIFIED":
            raise KernelError(
                "WORLD_BATCH_TIME_REQUIRED", "causal events require explicit world time"
            )
        for parent in ancestors[name]:
            prior = StoryTime.from_dict(dict(nodes[parent]["story_time"]))
            if (
                prior.timeline_id != time.timeline_id
                or prior.end_ordinal > time.start_ordinal
            ):
                raise KernelError(
                    "WORLD_BATCH_FUTURE_CAUSE",
                    "a cause must finish before its dependent effect",
                )
        key = (
            str(event.get("state_kind") or ""),
            str((event.get("identity") or {}).get("entity_key") or ""),
        )
        if any(prior not in ancestors[name] for prior in writers.get(key, [])):
            raise KernelError(
                "WORLD_BATCH_CONCURRENT_WRITE",
                "writes to one identity require an explicit causal order",
            )
        writers.setdefault(key, []).append(name)
    return CausalBatch(tuple(nodes[name] for name in order), ancestors, event_ids)
