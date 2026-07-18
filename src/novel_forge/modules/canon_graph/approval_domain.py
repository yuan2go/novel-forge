"""Storage-free Canon proposal, risk, and decision reduction rules."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError
from .domain import HIGH_IMPACT_CHANGE_TYPES, SEMANTIC_CHANGE_FIELDS

CANON_DECISIONS = frozenset({
    "APPROVE", "REJECT", "EDIT_AND_APPROVE", "DEFER", "REQUEST_REEXTRACTION",
})


def build_canon_change_proposal(*, project_id: str, extraction: dict[str, Any], extraction_asset_version_id: str) -> dict[str, Any]:
    if extraction.get("project_id") != project_id or not extraction_asset_version_id:
        raise KernelError("CANON_PROPOSAL_INPUT_INVALID", "project-scoped extraction is required")
    changes: list[dict[str, Any]] = []
    for field in SEMANTIC_CHANGE_FIELDS:
        for ordinal, raw in enumerate(extraction.get(field, [])):
            item = dict(raw)
            if item.get("predicate") == "accepted_revision_digest":
                continue
            evidence = dict(item.get("extraction_evidence") or {})
            confidence = float(item.get("confidence", 0.0))
            if not 0 <= confidence <= 1:
                raise KernelError("CANON_CHANGE_CONFIDENCE_INVALID", "confidence must be between zero and one")
            impact = str(item.get("impact_type") or item.get("change_type") or field)
            approval_required = item.get("approval_requirement") == "REQUIRED" or impact in HIGH_IMPACT_CHANGE_TYPES
            if approval_required and not str(evidence.get("excerpt_digest") or ""):
                raise KernelError("CANON_HIGH_IMPACT_EVIDENCE_REQUIRED", "high-impact Canon changes require an evidence digest")
            identity = json.dumps({"field": field, "ordinal": ordinal, "item": item}, sort_keys=True, separators=(",", ":"))
            change_id = "canon-change:" + hashlib.sha256(identity.encode()).hexdigest()
            changes.append({
                "change_id": change_id,
                "change_field": field,
                "change_type": impact,
                "state_kind": SEMANTIC_CHANGE_FIELDS[field],
                "entity_id": str(item.get("entity_id") or item.get("subject") or ""),
                "current_state_ref": str(evidence.get("previous_state_reference") or ""),
                "proposed_state": item,
                "source_revision_asset_version_id": extraction["revision_asset_version_id"],
                "evidence_span": dict(evidence.get("span") or {}),
                "evidence_digest": str(evidence.get("excerpt_digest") or ""),
                "confidence": confidence,
                "impact_level": "high" if approval_required else "normal",
                "conflict_codes": list(item.get("conflict_codes") or []),
                "approval_requirement": "REQUIRED" if approval_required else "NONE",
            })
    return {
        "type": "CanonChangeProposal", "project_id": project_id,
        "chapter": int(extraction["chapter"]),
        "extraction_asset_version_id": extraction_asset_version_id,
        "revision_asset_version_id": extraction["revision_asset_version_id"],
        "changes": changes,
        "approval_required_change_ids": [item["change_id"] for item in changes if item["approval_requirement"] == "REQUIRED"],
        "risk_summary": [{"change_id": item["change_id"], "impact_level": item["impact_level"], "change_type": item["change_type"]} for item in changes],
        "contract_version": "canon-change-proposal-v1",
    }


def resolve_canon_extraction(*, extraction: dict[str, Any], proposal: dict[str, Any], decisions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(item["change_id"]): dict(item) for item in decisions}
    resolved = {key: list(extraction.get(key, [])) for key in SEMANTIC_CHANGE_FIELDS}
    proposed_by_field: dict[str, list[dict[str, Any]]] = {key: [] for key in SEMANTIC_CHANGE_FIELDS}
    for change in proposal.get("changes", []):
        field = str(change["change_field"])
        decision = by_id.get(str(change["change_id"]))
        if change.get("approval_requirement") == "REQUIRED" and decision is None:
            raise KernelError("CANON_APPROVAL_INCOMPLETE", "all high-impact changes require a decision")
        action = "APPROVE" if decision is None else str(decision.get("decision"))
        if action not in CANON_DECISIONS:
            raise KernelError("CANON_APPROVAL_DECISION_INVALID", "unsupported Canon decision")
        if action == "REQUEST_REEXTRACTION":
            raise KernelError("CANON_REEXTRACTION_REQUIRED", "Canon extraction must be rerun")
        if action in {"REJECT", "DEFER"}:
            continue
        payload = dict(change["proposed_state"])
        if action == "EDIT_AND_APPROVE":
            edited = decision.get("edited_payload")
            if not isinstance(edited, dict) or not edited:
                raise KernelError("CANON_EDITED_PAYLOAD_REQUIRED", "edited approval requires a payload")
            payload = dict(edited)
        payload["approval_resolution"] = {
            "change_id": change["change_id"], "decision": action,
            "approval_decision_asset_version_id": str((decision or {}).get("asset_version_id") or ""),
        }
        proposed_by_field[field].append(payload)
    # Preserve the digest assertion, then replace proposal-governed semantic items.
    for field, values in proposed_by_field.items():
        if values or any(item.get("change_field") == field for item in proposal.get("changes", [])):
            resolved[field] = [item for item in resolved[field] if item.get("predicate") == "accepted_revision_digest"] + values
    return {
        **extraction,
        **resolved,
        "approval_required_changes": [],
        "canon_change_proposal_asset_version_id": proposal.get("asset_version_id", ""),
        "canon_approval_decision_asset_version_ids": sorted(str(item.get("asset_version_id") or "") for item in decisions),
        "canon_resolution_contract_version": "canon-change-resolution-v1",
    }


__all__ = ["CANON_DECISIONS", "build_canon_change_proposal", "resolve_canon_extraction"]
