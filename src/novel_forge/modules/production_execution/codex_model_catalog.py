from __future__ import annotations

import json
from typing import Any, Mapping

from .cost_routing import ModelCandidate, PricingSnapshot, TASK_TAXONOMY, snapshot_hash


CATALOG_VERSION = "codex-router-models.v1"


def parse_codex_model_catalog(raw: str) -> tuple[dict[str, Any], ...]:
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {"contract_version", "models"}
        or value["contract_version"] != CATALOG_VERSION
        or not isinstance(value["models"], list) or not value["models"]):
        raise ValueError("CODEX_MODEL_CATALOG_INVALID")
    entries = []
    identities = set()
    for entry in value["models"]:
        if (not isinstance(entry, dict) or set(entry) != {
            "model", "reasoning", "role", "tasks", "context_limit", "output_limit"}
            or not isinstance(entry["model"], str) or not entry["model"].strip()
            or entry["reasoning"] not in {"low", "medium", "high", "xhigh", "max"}
            or entry["role"] not in {"PRIMARY", "REFERENCE", "ESCALATION"}
            or not isinstance(entry["tasks"], list) or not entry["tasks"]
            or any(not isinstance(task, str) or task not in TASK_TAXONOMY for task in entry["tasks"])
            or len(set(entry["tasks"])) != len(entry["tasks"])
            or any(type(entry[key]) is not int or entry[key] <= 0 for key in ("context_limit", "output_limit"))
            or entry["output_limit"] > entry["context_limit"]):
            raise ValueError("CODEX_MODEL_CATALOG_ENTRY_INVALID")
        identity = (entry["model"], entry["reasoning"])
        if identity in identities:
            raise ValueError("CODEX_MODEL_CATALOG_DUPLICATE")
        identities.add(identity)
        entries.append({**entry, "tasks": sorted(entry["tasks"])})
    return tuple(entries)


def codex_catalog_candidates(entries: tuple[dict[str, Any], ...], *,
    entitlement: Mapping[str, Any], quota: int | None, valid_from: str, valid_until: str,
) -> tuple[ModelCandidate, ...]:
    price = PricingSnapshot(version=entitlement["configuration_ref"],
        effective_from=valid_from, effective_until=valid_until,
        input_miss_per_million="0", input_hit_per_million="0", output_per_million="0",
        currency="UNKNOWN", source=entitlement["authorization_ref"], accounting_basis="ACCOUNT_ENTITLEMENT")
    return tuple(ModelCandidate(
        candidate_id=f"codex-cli:{entry['model']}:{entry['reasoning']}",
        provider="codex-cli", model=entry["model"], reasoning=entry["reasoning"],
        tier=entry["role"].lower(), capabilities=("structured_output", "text"),
        context_limit=entry["context_limit"], output_limit=entry["output_limit"], pricing=price,
        capability_version=entitlement["configuration_ref"],
        model_revision=f"{entitlement['configuration_ref']}:{CATALOG_VERSION}:{snapshot_hash(entry)}",
        escalation_only=entry["role"] == "ESCALATION",
        entitlement_role=entry["role"] if entry["role"] != "ESCALATION" else "",
        authorized_tasks=tuple(entry["tasks"]), quota_remaining=quota,
        authorization_ref=entitlement["authorization_ref"],
    ) for entry in entries)
