"""Read-only, deterministic scanner for a frozen Legacy JSON snapshot."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


REBUILDABLE_CATEGORIES = frozenset(
    {"indexes", "runs", "backups", "cache", "exports", "task_statuses"}
)


@dataclass(frozen=True, slots=True)
class LegacySnapshotRecord:
    source_ref: str
    category: str
    source_hash: str
    size_bytes: int
    stable_business_key: str
    project_id: str
    workspace_id: str
    source_asset_type: str
    payload: dict[str, Any] | None
    references: tuple[str, ...]
    decision: str
    status: str
    error_code: str = ""
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LegacySnapshotScan:
    root: str
    snapshot_hash: str
    records: tuple[LegacySnapshotRecord, ...]
    counts: dict[str, int]


def scan_legacy_snapshot(
    root: str | Path, *, max_inline_bytes: int = 8 * 1024 * 1024
) -> LegacySnapshotScan:
    snapshot_root = Path(root).resolve()
    data_root = snapshot_root / "data" if (snapshot_root / "data").is_dir() else snapshot_root
    paths = sorted(path for path in data_root.rglob("*.json") if path.is_file())
    records: list[LegacySnapshotRecord] = []
    tree = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(snapshot_root).as_posix()
        raw = path.read_bytes()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        tree.update(relative.encode())
        tree.update(b"\0")
        tree.update(digest.encode())
        category = _category(path, data_root)
        if len(raw) > max_inline_bytes:
            records.append(
                LegacySnapshotRecord(
                    source_ref=relative,
                    category=category,
                    source_hash=digest,
                    size_bytes=len(raw),
                    stable_business_key=relative,
                    project_id="",
                    workspace_id="",
                    source_asset_type="unknown",
                    payload=None,
                    references=(),
                    decision="QUARANTINE",
                    status="QUARANTINED",
                    error_code="OBJECT_STORE_REQUIRED",
                    errors=("content exceeds inline import limit",),
                )
            )
            continue
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("top-level JSON must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            records.append(
                LegacySnapshotRecord(
                    source_ref=relative,
                    category=category,
                    source_hash=digest,
                    size_bytes=len(raw),
                    stable_business_key=relative,
                    project_id="",
                    workspace_id="",
                    source_asset_type="unknown",
                    payload=None,
                    references=(),
                    decision="QUARANTINE",
                    status="QUARANTINED",
                    error_code="MALFORMED_JSON",
                    errors=(str(exc),),
                )
            )
            continue
        content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
        project_id = str(
            payload.get("project_id")
            or content.get("project_id")
            or (payload.get("metadata") or {}).get("project_id")
            or ""
        ).strip()
        workspace_id = str(
            payload.get("workspace_id")
            or content.get("workspace_id")
            or (payload.get("id") if payload.get("type") == "project_workspace_state" else "")
            or ""
        ).strip()
        asset_type = str(payload.get("type") or "unknown").strip().lower()
        business_key = str(payload.get("id") or relative).strip()
        references = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in payload.get("references") or ()
                if str(item).strip()
            )
        )
        decision, status, error = "IMPORT", "VALIDATED", ""
        errors: tuple[str, ...] = ()
        if category in REBUILDABLE_CATEGORIES or asset_type in {"task_status", "run_log"}:
            decision, status = "DISCARD_REBUILDABLE", "SKIPPED_DUPLICATE"
        elif not project_id:
            decision, status, error = "QUARANTINE", "QUARANTINED", "PROJECT_ID_MISSING"
            errors = ("record has no stable project_id",)
        elif _source_is_unauthorized(payload, asset_type):
            decision, status, error = "QUARANTINE", "INELIGIBLE", "SOURCE_RIGHTS_UNVERIFIED"
            errors = ("source rights do not allow downstream production use",)
        records.append(
            LegacySnapshotRecord(
                source_ref=relative,
                category=category,
                source_hash=digest,
                size_bytes=len(raw),
                stable_business_key=business_key,
                project_id=project_id,
                workspace_id=workspace_id,
                source_asset_type=asset_type,
                payload=payload,
                references=references,
                decision=decision,
                status=status,
                error_code=error,
                errors=errors,
            )
        )

    identities = {
        record.stable_business_key: record.project_id
        for record in records
        if record.payload is not None
    }
    seen: dict[tuple[str, str], str] = {}
    resolved: list[LegacySnapshotRecord] = []
    for record in records:
        if record.decision != "IMPORT":
            resolved.append(record)
            continue
        key = (record.project_id, record.stable_business_key)
        previous_hash = seen.get(key)
        if previous_hash == record.source_hash:
            resolved.append(
                replace(record, decision="DISCARD_REBUILDABLE", status="SKIPPED_DUPLICATE")
            )
            continue
        if previous_hash is not None:
            resolved.append(
                replace(
                    record,
                    decision="QUARANTINE",
                    status="QUARANTINED",
                    error_code="BUSINESS_IDENTITY_CONTENT_CONFLICT",
                    errors=("same business identity has different content hashes",),
                )
            )
            continue
        seen[key] = record.source_hash
        cross_project = sorted(
            reference
            for reference in record.references
            if identities.get(reference) not in {None, "", record.project_id}
        )
        missing = sorted(reference for reference in record.references if reference not in identities)
        if cross_project:
            resolved.append(
                replace(
                    record,
                    decision="QUARANTINE",
                    status="QUARANTINED",
                    error_code="CROSS_PROJECT_REFERENCE",
                    errors=(f"cross-project references: {', '.join(cross_project)}",),
                )
            )
        elif missing:
            resolved.append(
                replace(
                    record,
                    decision="QUARANTINE",
                    status="QUARANTINED",
                    error_code="MISSING_REFERENCE",
                    errors=(f"missing references: {', '.join(missing)}",),
                )
            )
        else:
            resolved.append(record)
    counts: dict[str, int] = {"TOTAL": len(resolved)}
    for record in resolved:
        counts[record.status] = counts.get(record.status, 0) + 1
    return LegacySnapshotScan(
        root=str(snapshot_root),
        snapshot_hash="sha256:" + tree.hexdigest(),
        records=tuple(resolved),
        counts=counts,
    )


def _category(path: Path, data_root: Path) -> str:
    relative = path.relative_to(data_root)
    return relative.parts[0] if len(relative.parts) > 1 else "root"


def _source_is_unauthorized(payload: dict[str, Any], asset_type: str) -> bool:
    if asset_type not in {"source_document", "source_chunk", "cleaned_text"}:
        return False
    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    rights = payload.get("rights") if isinstance(payload.get("rights"), dict) else {}
    authorization = str(
        rights.get("authorization")
        or content.get("rights_authorization")
        or payload.get("rights_authorization")
        or "unknown"
    ).lower()
    allowed = bool(
        rights.get("allow_downstream_generation")
        or content.get("allow_downstream_generation")
        or payload.get("allow_downstream_generation")
    )
    return authorization in {"unknown", "denied", "unauthorized"} or not allowed


__all__ = [
    "LegacySnapshotRecord",
    "LegacySnapshotScan",
    "REBUILDABLE_CATEGORIES",
    "scan_legacy_snapshot",
]
