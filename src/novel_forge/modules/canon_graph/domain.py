"""Storage-free canon extraction, conflict detection, and state reduction."""
from __future__ import annotations

import hashlib
from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError


STATE_ASSET_TYPES = (
    "canon_snapshot", "character_state", "relationship_state", "timeline_snapshot",
    "foreshadow_state", "reader_promise", "reward_ledger", "world_rule", "power_state",
)


def extract_canon_candidates(
    *,
    project_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    context_bundle_version_id: str,
) -> dict[str, Any]:
    """Produce deterministic candidates independently of revision-provider metadata."""
    if not all((project_id, revision_asset_version_id, context_bundle_version_id)):
        raise KernelError("CANON_EXTRACTION_INPUT_INVALID", "versioned extraction lineage is required")
    text = str(revision.get("text") or "").strip()
    if not text:
        raise KernelError("CANON_EXTRACTION_INPUT_INVALID", "accepted revision text is required")
    assertions = list(revision.get("canon_assertions", []))
    # Every accepted chapter has a deterministic event assertion, so a real-provider
    # path never silently produces an empty Canon update when optional structured
    # assertions are absent.
    assertions.append(
        {
            "subject": f"chapter:{revision['chapter']}",
            "predicate": "accepted_revision_digest",
            "object": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "effective_chapter": int(revision["chapter"]),
            "evidence_source": "deterministic_revision_digest",
        }
    )
    for item in assertions:
        if not all(str(item.get(key) or "").strip() for key in ("subject", "predicate", "object")):
            raise KernelError("CANON_ASSERTION_INVALID", "canon assertion requires subject/predicate/object")
    return {
        "project_id": project_id,
        "chapter": int(revision["chapter"]),
        "revision_asset_version_id": revision_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "canon_assertion_candidates": assertions,
        "character_state_changes": list(revision.get("character_state_changes", [])),
        "relationship_changes": list(revision.get("relationship_changes", [])),
        "timeline_event_candidates": list(revision.get("timeline_events", [])),
        "foreshadow_changes": list(revision.get("foreshadow_changes", [])),
        "promise_changes": list(revision.get("promise_changes", [])),
        "reward_changes": list(revision.get("reward_changes", [])),
        "world_rule_usages": list(revision.get("world_rule_usages", [])),
        "power_state_changes": list(revision.get("power_state_changes", [])),
        "extraction_source": "deterministic_extractor",
        "provider_assertions_optional": True,
        "canon_extraction_contract_version": "canon-extraction-v1",
    }


def build_canon_update(
    *,
    project_id: str,
    revision: dict[str, Any] | None = None,
    revision_asset_version_id: str,
    context_bundle_version_id: str,
    existing_facts: Iterable[dict[str, Any]] = (),
    extraction: dict[str, Any] | None = None,
    historical_state: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if not all((project_id, revision_asset_version_id, context_bundle_version_id)):
        raise KernelError("CANON_INPUT_INVALID", "versioned canon lineage is required")
    if extraction is None:
        if revision is None:
            raise KernelError("CANON_EXTRACTION_REQUIRED", "Canon reduction requires extraction")
        extraction = extract_canon_candidates(
            project_id=project_id,
            revision=revision,
            revision_asset_version_id=revision_asset_version_id,
            context_bundle_version_id=context_bundle_version_id,
        )
    if extraction.get("project_id") != project_id:
        raise KernelError("CROSS_PROJECT_REFERENCE", "Canon extraction belongs to another project")
    chapter = int(extraction["chapter"])
    state = {key: list(values) for key, values in (historical_state or {}).items()}
    previous = [*existing_facts, *state.get("canon_snapshot", [])]
    facts = [_normalize_fact(item, chapter, revision_asset_version_id) for item in extraction.get("canon_assertion_candidates", [])]
    conflicts = _fact_conflicts(previous, facts)
    conflicts.extend(_typed_state_conflicts(chapter, state, extraction))
    return {
        "project_id": project_id,
        "chapter": chapter,
        "source_asset_version_id": revision_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "facts": facts,
        "conflicts": conflicts,
        "gate": "BLOCKED" if any(item["severity"] == "blocking" for item in conflicts) else "PASSED",
        "historical_input_version_ids": sorted(
            {
                str(item.get("asset_version_id"))
                for values in state.values() for item in values
                if item.get("asset_version_id")
            }
        ),
        "snapshot_candidates": _snapshot_candidates(chapter, state, extraction, facts),
        "rebuildable": True,
        "rollback_aware": True,
        "canon_contract_version": "canon-update-domain-v3",
    }


def _normalize_fact(item: dict[str, Any], chapter: int, source: str) -> dict[str, Any]:
    subject = str(item.get("subject") or "").strip()
    predicate = str(item.get("predicate") or "").strip()
    object_value = str(item.get("object") or "").strip()
    if not all((subject, predicate, object_value)):
        raise KernelError("CANON_ASSERTION_INVALID", "canon assertion requires subject/predicate/object")
    return {
        "subject": subject, "predicate": predicate, "object": object_value,
        "effective_chapter": int(item.get("effective_chapter") or chapter),
        "source_asset_version_id": source,
        "supersedes_version_id": str(item.get("supersedes_version_id") or ""),
    }


def _conflict(code: str, existing: Any, candidate: Any, recommendation: str, *, approval: bool = True) -> dict[str, Any]:
    return {
        "conflict_code": code,
        "severity": "blocking",
        "existing_version": existing,
        "candidate_version": candidate,
        "evidence": {"existing": existing, "candidate": candidate},
        "recommended_resolution": recommendation,
        "approval_requirement": "REQUIRED" if approval else "NONE",
    }


def _fact_conflicts(previous: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts = []
    for fact in facts:
        for old in previous:
            if old.get("subject") == fact["subject"] and old.get("predicate") == fact["predicate"] and old.get("object") != fact["object"] and not fact["supersedes_version_id"]:
                conflicts.append(_conflict("FACT_CONTRADICTION", old, fact, "supersede explicitly or revise the chapter"))
    return conflicts


def _typed_state_conflicts(chapter: int, state: dict[str, list[dict[str, Any]]], extraction: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for event in extraction.get("timeline_event_candidates", []):
        if int(event.get("chapter", chapter)) < max([int(item.get("chapter", 0)) for item in state.get("timeline_snapshot", [])] or [0]):
            conflicts.append(_conflict("TEMPORAL_CONTRADICTION", state.get("timeline_snapshot", []), event, "place the event after the latest frozen timeline boundary"))
    for change in extraction.get("character_state_changes", []):
        existing = next((item for item in state.get("character_state", []) if item.get("character_id") == change.get("character_id")), None)
        if existing and existing.get("canonical_name") and change.get("canonical_name") and existing["canonical_name"] != change["canonical_name"]:
            conflicts.append(_conflict("CHARACTER_IDENTITY_CONTRADICTION", existing, change, "create an alias/merge proposal instead of changing identity"))
    for change in extraction.get("relationship_changes", []):
        if change.get("trust_state") == "trusted" and change.get("betrayal_unresolved"):
            conflicts.append(_conflict("RELATIONSHIP_CONTRADICTION", state.get("relationship_state", []), change, "add reconciliation evidence or preserve distrust"))
    for usage in extraction.get("world_rule_usages", []):
        if usage.get("exception") and not usage.get("cost"):
            conflicts.append(_conflict("WORLD_RULE_CONTRADICTION", state.get("world_rule", []), usage, "pay the rule exception cost"))
    for change in extraction.get("power_state_changes", []):
        if change.get("tier_increase") and not change.get("change_reasons"):
            conflicts.append(_conflict("POWER_PROGRESSION_CONTRADICTION", state.get("power_state", []), change, "supply training, equipment, condition, or cost evidence"))
    for change in extraction.get("foreshadow_changes", []):
        if change.get("status") == "PAID" and not change.get("payoff_evidence"):
            conflicts.append(_conflict("FORESHADOW_LIFECYCLE_CONTRADICTION", state.get("foreshadow_state", []), change, "add causal payoff evidence"))
    for change in extraction.get("promise_changes", []):
        if change.get("status") == "PAID" and not change.get("payoff_evidence"):
            conflicts.append(_conflict("PROMISE_LIFECYCLE_CONTRADICTION", state.get("reader_promise", []), change, "add reader-visible fulfillment evidence"))
    return conflicts


def _snapshot_candidates(chapter: int, state: dict[str, list[dict[str, Any]]], extraction: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes = {
        "canon_snapshot": facts,
        "character_state": extraction.get("character_state_changes", []),
        "relationship_state": extraction.get("relationship_changes", []),
        "timeline_snapshot": extraction.get("timeline_event_candidates", []),
        "foreshadow_state": extraction.get("foreshadow_changes", []),
        "reader_promise": extraction.get("promise_changes", []),
        "reward_ledger": extraction.get("reward_changes", []),
        "world_rule": extraction.get("world_rule_usages", []),
        "power_state": extraction.get("power_state_changes", []),
    }
    return [
        {
            "asset_type": asset_type,
            "chapter": chapter,
            "previous_asset_version_ids": [str(item.get("asset_version_id")) for item in state.get(asset_type, []) if item.get("asset_version_id")],
            "changes": list(changes[asset_type]),
            "append_only": True,
        }
        for asset_type in STATE_ASSET_TYPES
    ]


__all__ = ["STATE_ASSET_TYPES", "build_canon_update", "extract_canon_candidates"]
