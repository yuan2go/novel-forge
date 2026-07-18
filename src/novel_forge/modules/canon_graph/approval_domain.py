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
    fingerprints: dict[str, str] = {}
    for field in SEMANTIC_CHANGE_FIELDS:
        for raw in extraction.get(field, []):
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
            span = dict(evidence.get("span") or {})
            if approval_required and not _valid_span(span):
                raise KernelError("CANON_HIGH_IMPACT_EVIDENCE_SPAN_INVALID", "high-impact Canon changes require a valid evidence span")
            entity_id = str(
                item.get("entity_id")
                or item.get("character_id")
                or item.get("relationship_id")
                or item.get("world_rule_id")
                or item.get("foreshadow_id")
                or item.get("promise_id")
                or item.get("subject")
                or ""
            )
            if approval_required and not entity_id:
                raise KernelError("CANON_HIGH_IMPACT_ENTITY_REQUIRED", "high-impact Canon changes require a resolved entity")
            previous_project = str(evidence.get("previous_state_project_id") or project_id)
            if previous_project != project_id:
                raise KernelError("CROSS_PROJECT_REFERENCE", "previous Canon state belongs to another project")
            semantic_identity = json.dumps(
                {"field": field, "entity_id": entity_id, "impact": impact},
                sort_keys=True,
                separators=(",", ":"),
            )
            proposed_digest = hashlib.sha256(
                json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if semantic_identity in fingerprints:
                if fingerprints[semantic_identity] != proposed_digest:
                    raise KernelError("CANON_EXTRACTION_CONTRADICTION", "extractor proposed contradictory changes for one entity")
                continue
            fingerprints[semantic_identity] = proposed_digest
            identity = json.dumps({"field": field, "entity": entity_id, "item": item}, sort_keys=True, separators=(",", ":"))
            change_id = "canon-change:" + hashlib.sha256(identity.encode()).hexdigest()
            changes.append({
                "change_id": change_id,
                "change_field": field,
                "change_type": impact,
                "state_kind": SEMANTIC_CHANGE_FIELDS[field],
                "entity_id": entity_id,
                "current_state_ref": str(evidence.get("previous_state_reference") or ""),
                "proposed_state": item,
                "source_revision_asset_version_id": extraction["revision_asset_version_id"],
                "evidence_span": span,
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


def _valid_span(span: dict[str, Any]) -> bool:
    try:
        start = int(span["start"])
        end = int(span["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return start >= 0 and end > start


def validate_edited_canon_payload(
    *, project_id: str, change: dict[str, Any], edited_payload: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(edited_payload, dict) or not edited_payload:
        raise KernelError("CANON_EDITED_PAYLOAD_REQUIRED", "edited approval requires a payload")
    original = dict(change.get("proposed_state") or {})
    payload = {**original, **edited_payload}
    entity_keys = (
        "entity_id", "character_id", "relationship_id", "world_rule_id",
        "foreshadow_id", "promise_id", "subject",
    )
    original_entity = str(change.get("entity_id") or "")
    edited_entity = next((str(payload[key]) for key in entity_keys if payload.get(key)), "")
    errors: list[str] = []
    if original_entity and edited_entity != original_entity:
        errors.append("ENTITY_IDENTITY_CHANGED")
    if payload.get("project_id", project_id) != project_id:
        errors.append("CROSS_PROJECT_REFERENCE")
    if str(payload.get("impact_type") or payload.get("change_type") or change.get("change_type")) != str(change.get("change_type")):
        errors.append("CHANGE_TYPE_CHANGED")
    try:
        confidence = float(payload.get("confidence", change.get("confidence", 0)))
    except (TypeError, ValueError):
        confidence = -1
    if not 0 <= confidence <= 1:
        errors.append("CONFIDENCE_INVALID")
    evidence = dict(payload.get("extraction_evidence") or original.get("extraction_evidence") or {})
    if change.get("approval_requirement") == "REQUIRED":
        if not _valid_span(dict(evidence.get("span") or change.get("evidence_span") or {})):
            errors.append("EVIDENCE_SPAN_INVALID")
        if not str(evidence.get("excerpt_digest") or change.get("evidence_digest") or ""):
            errors.append("EVIDENCE_DIGEST_MISSING")
    previous_project = str(evidence.get("previous_state_project_id") or project_id)
    if previous_project != project_id:
        errors.append("PREVIOUS_STATE_CROSS_PROJECT")
    conflict_codes = {
        str(item) for item in (
            payload.get("conflict_codes") or change.get("conflict_codes") or []
        )
    }
    blocking_conflicts = sorted(
        code for code in conflict_codes
        if any(token in code for token in ("WORLD_RULE", "TIMELINE", "POWER", "RELATIONSHIP", "CONTRADICTION"))
    )
    if blocking_conflicts:
        errors.extend(blocking_conflicts)
    if payload.get("duplicate_change") is True:
        errors.append("DUPLICATE_CHANGE")
    if payload.get("contradictory_change") is True:
        errors.append("CONTRADICTORY_CHANGE")
    report = {
        "type": "CanonEditedPayloadValidationReport",
        "project_id": project_id,
        "change_id": change.get("change_id"),
        "valid": not errors,
        "errors": errors,
        "contract_version": "canon-edited-payload-validation-v1",
    }
    if errors:
        raise KernelError(
            "CANON_EDITED_PAYLOAD_INVALID",
            "edited Canon payload failed validation: " + ", ".join(errors),
        )
    return {
        "type": "CanonChangeResolution",
        "project_id": project_id,
        "change_id": change["change_id"],
        "state_kind": change["state_kind"],
        "change_type": change["change_type"],
        "entity_id": original_entity,
        "original_proposed_payload": original,
        "edited_payload": dict(edited_payload),
        "validated_payload": payload,
        "validation_report": report,
        "contract_version": "canon-change-resolution-v1",
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
            resolution = decision.get("change_resolution")
            if not isinstance(resolution, dict) or not resolution.get("validated_payload"):
                raise KernelError(
                    "CANON_EDITED_RESOLUTION_REQUIRED",
                    "edited approval requires a validated CanonChangeResolution",
                )
            payload = dict(resolution["validated_payload"])
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


__all__ = [
    "CANON_DECISIONS", "build_canon_change_proposal", "resolve_canon_extraction",
    "validate_edited_canon_payload",
]
