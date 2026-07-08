from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

DO_NOT_SELECT_STATES = {"quarantined", "deprecated", "do_not_select", "rejected", "superseded_by_lifecycle_rollback"}


def refresh_mkaos_selector_governance(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "")
    max_assets = max(1, int(payload.get("max_assets") or 1000))
    adjustments: dict[str, dict[str, Any]] = {}
    exclusions: dict[str, dict[str, Any]] = {}
    scanned = 0
    for path in storage.list_json("knowledge"):
        if scanned >= max_assets:
            break
        try:
            data = storage.read_json(path)
        except (OSError, TypeError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("type") != "knowledge_card":
            continue
        if project_id and _asset_project_id(data) not in {"", project_id}:
            continue
        scanned += 1
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        knowledge_id = str(data.get("id") or "")
        if not knowledge_id:
            continue
        base_weight = _float(content.get("weight", metadata.get("weight", 1.0)), 1.0)
        delta = _float(metadata.get("mkaos_governance_weight_delta", metadata.get("selector_governance_weight_delta", 0.0)), 0.0)
        state = str(content.get("status") or metadata.get("asset_status") or "")
        lifecycle_state = str(metadata.get("mkaos_lifecycle_state") or "")
        excluded, reason = _selector_exclusion(metadata, state=state, lifecycle_state=lifecycle_state)
        evidence_refs = _evidence_refs(metadata)
        if delta != 0.0 or metadata.get("mkaos_governance_application_status") or metadata.get("mkaos_lifecycle_state"):
            adjustments[knowledge_id] = {
                "knowledge_id": knowledge_id,
                "path": _display_path(storage.root, path),
                "base_weight": base_weight,
                "weight_delta": delta,
                "effective_weight": max(0.0, base_weight + delta),
                "governance_action": str(metadata.get("mkaos_governance_action") or ""),
                "lifecycle_state": lifecycle_state,
                "evidence_refs": evidence_refs,
                "content_weight_mutated": False,
            }
        if excluded:
            exclusions[knowledge_id] = {
                "knowledge_id": knowledge_id,
                "path": _display_path(storage.root, path),
                "reason": reason,
                "state": state,
                "lifecycle_state": lifecycle_state,
                "evidence_refs": evidence_refs,
            }
    report_id = make_id("mkaos_selector_governance_report", f"{project_id or 'all'}-{utc_now()}")
    content = {
        "selector_governance_report_id": report_id,
        "project_id": project_id,
        "scanned_knowledge_count": scanned,
        "adjustments": adjustments,
        "exclusions": exclusions,
        "selector_policy_patch": {
            "weight_overrides": {knowledge_id: item["effective_weight"] for knowledge_id, item in adjustments.items()},
            "excluded_knowledge_ids": sorted(exclusions),
            "evidence_by_knowledge_id": {knowledge_id: item.get("evidence_refs", []) for knowledge_id, item in {**adjustments, **exclusions}.items()},
        },
        "refresh_contract": {
            "contract_version": "mkaos-selector-governance-refresh-v1",
            "content_weight_mutation_allowed": False,
            "selector_application_requires_explicit_report_ref": True,
            "raw_source_text_included": False,
            "prose_mutation_included": False,
        },
        "generated_at": utc_now(),
    }
    asset = BaseAsset(
        id=report_id,
        type="mkaos_selector_governance_report",
        title="MKAOS selector governance refresh",
        source="mkaos-selector-governance",
        tags=["mkaos", "selector-governance", "refresh"],
        content=content,
        metadata={"project_id": project_id, "asset_status": "active", "use_in_generation_rag": False, "selector_governance_report": True},
        references=sorted({ref for item in [*adjustments.values(), *exclusions.values()] for ref in item.get("evidence_refs", []) if ref}),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset("runs", asset)
    return {"status": "refreshed", "path": _display_path(storage.root, path), "asset": storage.read_json(path), "adjustment_count": len(adjustments), "exclusion_count": len(exclusions)}


def load_selector_governance_policy(storage: LocalStorage, payload: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    ref = str(payload.get("selector_governance_report_path") or payload.get("selector_governance_report_ref") or "").strip()
    if not ref and bool(payload.get("use_latest_selector_governance")):
        latest = _latest_selector_governance_report(storage, project_id=project_id)
        ref = latest.get("path", "")
    if not ref:
        return {}
    path, data = _resolve_selector_report(storage, ref)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "report_id": str(data.get("id") or content.get("selector_governance_report_id") or ""),
        "report_path": _display_path(storage.root, path),
        "weight_overrides": content.get("selector_policy_patch", {}).get("weight_overrides", {}) if isinstance(content.get("selector_policy_patch", {}), dict) else {},
        "excluded_knowledge_ids": content.get("selector_policy_patch", {}).get("excluded_knowledge_ids", []) if isinstance(content.get("selector_policy_patch", {}), dict) else [],
        "evidence_by_knowledge_id": content.get("selector_policy_patch", {}).get("evidence_by_knowledge_id", {}) if isinstance(content.get("selector_policy_patch", {}), dict) else {},
        "adjustments": content.get("adjustments", {}) if isinstance(content.get("adjustments", {}), dict) else {},
        "exclusions": content.get("exclusions", {}) if isinstance(content.get("exclusions", {}), dict) else {},
    }


def _resolve_selector_report(storage: LocalStorage, ref: str) -> tuple[Path, dict[str, Any]]:
    path, data = _resolve_asset_by_ref(storage, ref)
    if not isinstance(data, dict) or data.get("type") != "mkaos_selector_governance_report":
        raise ValueError("selector_governance_report_path must point to a mkaos_selector_governance_report")
    return path, data


def _latest_selector_governance_report(storage: LocalStorage, *, project_id: str) -> dict[str, Any]:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except (OSError, TypeError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("type") != "mkaos_selector_governance_report":
            continue
        if project_id and _asset_project_id(data) not in {"", project_id}:
            continue
        return {"path": _display_path(storage.root, path), "asset": data}
    return {}


def _selector_exclusion(metadata: dict[str, Any], *, state: str, lifecycle_state: str) -> tuple[bool, str]:
    normalized_state = str(lifecycle_state or state or "").strip()
    if normalized_state in DO_NOT_SELECT_STATES:
        return True, f"state:{normalized_state}"
    governance_action = str(metadata.get("mkaos_governance_action") or metadata.get("selector_governance_action") or "")
    if governance_action in {"quarantine", "deprecate", "do_not_select", "reject"}:
        return True, f"governance_action:{governance_action}"
    if metadata.get("selector_governance_excluded") is True:
        return True, "selector_governance_excluded"
    return False, ""


def _evidence_refs(metadata: dict[str, Any]) -> list[str]:
    refs = [
        str(metadata.get("mkaos_governance_report_path") or ""),
        str(metadata.get("mkaos_governance_approval_request_path") or ""),
        str(metadata.get("mkaos_lifecycle_approval_request_path") or ""),
    ]
    return [ref for ref in refs if ref]


def _resolve_asset_by_ref(storage: LocalStorage, ref: str) -> tuple[Path, dict[str, Any]]:
    text = str(ref or "").strip()
    if not text:
        raise ValueError("asset reference must not be empty")
    try:
        direct = resolve_path(storage.root, text)
        data = storage.read_json(direct)
        if isinstance(data, dict):
            return direct, data
    except (OSError, TypeError, ValueError):
        pass
    for category in DATA_DIRS:
        for path in reversed(storage.list_json(category)):
            try:
                data = storage.read_json(path)
            except (OSError, TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            if text in {str(data.get("id") or ""), str(content.get("selector_governance_report_id") or ""), _display_path(storage.root, path)}:
                return path, data
    raise ValueError(f"asset not found: {text}")


def _asset_project_id(asset: dict[str, Any]) -> str:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
