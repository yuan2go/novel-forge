"""Storage-free canon assertion validation and conflict detection."""
from __future__ import annotations

from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError


def build_canon_update(
    *,
    project_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    context_bundle_version_id: str,
    existing_facts: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    if not all((project_id, revision_asset_version_id, context_bundle_version_id)):
        raise KernelError("CANON_INPUT_INVALID", "versioned canon lineage is required")
    facts: list[dict[str, Any]] = []
    for item in revision.get("canon_assertions", []):
        subject = str(item.get("subject") or "").strip()
        predicate = str(item.get("predicate") or "").strip()
        object_value = str(item.get("object") or "").strip()
        if not subject or not predicate or not object_value:
            raise KernelError("CANON_ASSERTION_INVALID", "canon assertion requires subject/predicate/object")
        facts.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": object_value,
                "effective_chapter": int(item.get("effective_chapter") or revision["chapter"]),
                "source_asset_version_id": revision_asset_version_id,
            }
        )
    previous = list(existing_facts)
    conflicts: list[dict[str, Any]] = []
    for fact in facts:
        for old in previous:
            if (
                old.get("subject") == fact["subject"]
                and old.get("predicate") == fact["predicate"]
                and old.get("object") != fact["object"]
                and not fact.get("supersedes")
            ):
                conflicts.append({"kind": "fact_conflict", "existing": old, "candidate": fact})
    return {
        "project_id": project_id,
        "chapter": revision["chapter"],
        "source_asset_version_id": revision_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "facts": facts,
        "conflicts": conflicts,
        "gate": "BLOCKED" if conflicts else "PASSED",
        "canon_contract_version": "canon-update-domain-v2",
    }


__all__ = ["build_canon_update"]
