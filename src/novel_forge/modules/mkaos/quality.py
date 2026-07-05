from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.mkaos.asset_index import find_asset, list_assets
from novel_forge.storage.local import LocalStorage


def knowledge_quality_history(storage: LocalStorage, knowledge_ref: str | Path, *, limit: int = 200) -> dict[str, Any]:
    knowledge_id = str(knowledge_ref)
    try:
        _, knowledge = find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
        knowledge_id = str(knowledge.get("id") or knowledge_id)
    except FileNotFoundError:
        pass
    rows = [
        row
        for row in list_assets(storage, "knowledge", "knowledge_quality_score", limit=limit)
        if str(row.get("content", {}).get("knowledge_id") or "") == knowledge_id
    ]
    return {"knowledge_id": knowledge_id, "count": len(rows), "items": rows}


def list_low_quality_knowledge(
    storage: LocalStorage,
    *,
    threshold: float = 0.45,
    project_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    rows = list_assets(storage, "knowledge", "knowledge_card", project_id=project_id, mkaos_only=False, limit=limit)
    return [row for row in rows if _float(row.get("content", {}).get("overall_quality_score", row.get("content", {}).get("quality_score", 0.7)), 0.7) < threshold]


def list_high_copyright_risk_knowledge(
    storage: LocalStorage,
    *,
    threshold: float = 0.7,
    project_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    rows = list_assets(storage, "knowledge", "knowledge_card", project_id=project_id, mkaos_only=False, limit=limit)
    return [
        row
        for row in rows
        if _float((row.get("content", {}).get("quality_dimensions") or {}).get("copyright_risk_score"), 0.0) >= threshold
        or str(row.get("content", {}).get("risk_level") or row.get("metadata", {}).get("risk_level") or "") in {"high", "critical"}
    ]


def _float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
