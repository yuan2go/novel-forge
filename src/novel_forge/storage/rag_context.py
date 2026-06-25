from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.model_adapters import embedding_provider_health
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.qdrant_index import qdrant_search_assets
from novel_forge.storage.vector_index import vector_search_assets

RAG_CONTEXT_VERSION = "0.1.0"
DEFAULT_RAG_TOP_K = 8
RAG_BACKENDS = {"auto", "local", "qdrant"}

RAG_BUCKETS = {
    "characters": "人物",
    "worldbuilding": "世界观",
    "previous_summaries": "前文摘要",
    "knowledge_cards": "知识卡",
    "foreshadowing": "伏笔",
    "material_cards": "素材卡",
}

TYPE_BUCKETS = {
    "character_card": ["characters"],
    "character_mechanism": ["characters", "material_cards"],
    "world_bible": ["worldbuilding"],
    "project_workspace_state": ["previous_summaries", "foreshadowing"],
    "outline": ["previous_summaries"],
    "chapter_plan": ["previous_summaries"],
    "draft_chapter": ["previous_summaries"],
    "revision_plan": ["previous_summaries"],
    "knowledge_card": ["knowledge_cards"],
    "material_card": ["material_cards"],
    "commercial_pattern": ["material_cards"],
    "narrative_pattern": ["material_cards"],
    "conflict_pattern": ["material_cards"],
    "emotion_curve": ["material_cards"],
    "hook_pattern": ["foreshadowing", "material_cards"],
}

FORESHADOWING_TERMS = ("伏笔", "foreshadow", "hook", "continuity_thread", "continuity_threads", "open_issue", "open_issues")


@dataclass
class RagContextBuilder:
    storage: LocalStorage
    default_top_k: int = DEFAULT_RAG_TOP_K
    backend: str = "auto"
    settings: IndustrialSettings | None = None

    def build(
        self,
        input_asset: BaseAsset,
        input_path: str | Path | None = None,
        query: str | None = None,
        top_k: int | None = None,
        backend: str | None = None,
    ) -> dict[str, Any]:
        requested_top_k = int(top_k or self.default_top_k)
        if requested_top_k < 1:
            raise ValueError("top_k must be greater than zero")
        requested_backend = _normalize_backend(backend or self.backend)
        source_path = _relative_path(self.storage, input_path) if input_path else ""
        query_text = _compact_text(query or _default_query(input_asset), limit=1200) or input_asset.title or input_asset.id
        scope = _project_scope_for_asset(self.storage, input_asset.to_dict(), source_path)
        ranked, actual_backend, backend_attempts = self._ranked_candidates(
            query_text,
            limit=max(requested_top_k * 8, 40),
            backend=requested_backend,
        )
        items = self._select_items(ranked, input_asset, source_path, scope, requested_top_k)
        if len(items) < requested_top_k:
            items = self._fill_from_project_scan(items, input_asset, source_path, scope, requested_top_k)
        buckets = {name: [] for name in RAG_BUCKETS}
        for item in items:
            for bucket in item["categories"]:
                buckets.setdefault(bucket, []).append(item)
        source_asset_ids = _dedupe([str(item["asset_id"]) for item in items if item.get("asset_id")])
        return {
            "version": RAG_CONTEXT_VERSION,
            "query": query_text,
            "top_k": requested_top_k,
            "ranker": _ranker_name(items),
            "requested_backend": requested_backend,
            "retrieval_backend": actual_backend,
            "backend_attempts": backend_attempts,
            "project_id": scope.get("project_id", ""),
            "workspace_path": scope.get("workspace_path", ""),
            "source_asset_id": input_asset.id,
            "source_asset_type": input_asset.type,
            "source_asset_path": source_path,
            "source_asset_ids": source_asset_ids,
            "source_paths": _dedupe([str(item["path"]) for item in items if item.get("path")]),
            "items": items,
            "buckets": buckets,
        }

    def _ranked_candidates(self, query: str, limit: int, backend: str) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []
        if backend in {"auto", "qdrant"}:
            health = embedding_provider_health(require_semantic=True)
            if health.get("ok"):
                try:
                    settings = self.settings or IndustrialSettings.from_env(root=self.storage.root)
                    results = qdrant_search_assets(self.storage, settings, query=query, limit=limit)
                    attempts.append({"backend": "qdrant", "ok": True, "result_count": len(results)})
                    return results, "qdrant", attempts
                except Exception as exc:
                    attempts.append({"backend": "qdrant", "ok": False, "error": str(exc)})
                    if backend == "qdrant":
                        raise
            else:
                attempts.append({"backend": "qdrant", "ok": False, "error": health.get("error") or health.get("message") or "embedding provider unavailable"})
                if backend == "qdrant":
                    raise RuntimeError(str(attempts[-1]["error"]))
        try:
            results = vector_search_assets(self.storage, query=query, limit=limit)
            attempts.append({"backend": "local", "ok": True, "result_count": len(results)})
            return results, "local", attempts
        except Exception as exc:
            attempts.append({"backend": "local", "ok": False, "error": str(exc)})
            return [], "scan", attempts

    def _select_items(
        self,
        ranked: list[dict[str, Any]],
        input_asset: BaseAsset,
        source_path: str,
        scope: dict[str, str],
        top_k: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in ranked:
            path_text = str(result.get("path", "")).strip()
            if not path_text:
                continue
            path = self.storage.root / path_text
            item = self._item_from_path(path, result, input_asset, source_path, scope)
            if not item:
                continue
            key = str(item["path"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
            if len(items) >= top_k:
                break
        return items

    def _fill_from_project_scan(
        self,
        items: list[dict[str, Any]],
        input_asset: BaseAsset,
        source_path: str,
        scope: dict[str, str],
        top_k: int,
    ) -> list[dict[str, Any]]:
        seen = {str(item["path"]) for item in items}
        for category in DATA_DIRS:
            for path in reversed(self.storage.list_json(category)):
                result = {"path": _relative_path(self.storage, path), "score": 0.0, "ranker": "project-scoped-asset-priority"}
                item = self._item_from_path(path, result, input_asset, source_path, scope)
                if not item or str(item["path"]) in seen:
                    continue
                seen.add(str(item["path"]))
                items.append(item)
                if len(items) >= top_k:
                    return items
        return items

    def _item_from_path(
        self,
        path: Path,
        result: dict[str, Any],
        input_asset: BaseAsset,
        source_path: str,
        scope: dict[str, str],
    ) -> dict[str, Any] | None:
        try:
            data = self.storage.read_json(path)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        relative = _relative_path(self.storage, path)
        if data.get("id") == input_asset.id or relative == source_path:
            return None
        if not _matches_project_scope(self.storage, data, relative, scope):
            return None
        categories = _categories_for_asset(data)
        if not categories:
            return None
        asset_scope = _project_scope_for_asset(self.storage, data, relative)
        return {
            "asset_id": str(data.get("id", "")),
            "path": relative,
            "type": str(data.get("type", "")),
            "title": str(data.get("title") or data.get("name") or ""),
            "categories": categories,
            "score": round(float(result.get("score", 0.0)), 6),
            "ranker": str(result.get("ranker") or "project-scoped-asset-priority"),
            "project_id": asset_scope.get("project_id", ""),
            "workspace_path": asset_scope.get("workspace_path", ""),
            "summary": _asset_context_summary(data),
        }


def build_rag_context(
    storage: LocalStorage,
    input_asset: BaseAsset,
    input_path: str | Path | None = None,
    query: str | None = None,
    top_k: int = DEFAULT_RAG_TOP_K,
    backend: str = "auto",
    settings: IndustrialSettings | None = None,
) -> dict[str, Any]:
    return RagContextBuilder(storage, backend=backend, settings=settings).build(input_asset, input_path=input_path, query=query, top_k=top_k)


def retrieval_metadata(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "retrieved_context": context,
        "retrieval_query": context.get("query", ""),
        "retrieval_top_k": context.get("top_k", 0),
        "retrieval_ranker": context.get("ranker", ""),
        "retrieval_backend": context.get("retrieval_backend", ""),
        "retrieval_requested_backend": context.get("requested_backend", ""),
        "retrieval_backend_attempts": context.get("backend_attempts", []),
        "retrieval_source_asset_ids": context.get("source_asset_ids", []),
    }


def retrieval_reference_ids(input_asset_id: str, context: dict[str, Any]) -> list[str]:
    return _dedupe([input_asset_id, *[str(item) for item in context.get("source_asset_ids", []) if str(item).strip()]])


def _default_query(asset: BaseAsset) -> str:
    payload = {
        "type": asset.type,
        "title": asset.title,
        "tags": asset.tags,
        "source": asset.source,
        "content": asset.content,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _categories_for_asset(data: dict[str, Any]) -> list[str]:
    buckets = list(TYPE_BUCKETS.get(str(data.get("type", "")), []))
    searchable = json.dumps(
        {
            "title": data.get("title", ""),
            "tags": data.get("tags", []),
            "content": data.get("content", {}),
            "metadata": data.get("metadata", {}),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).lower()
    if any(term.lower() in searchable for term in FORESHADOWING_TERMS):
        buckets.append("foreshadowing")
    return _dedupe([bucket for bucket in buckets if bucket in RAG_BUCKETS])


def _asset_context_summary(data: dict[str, Any]) -> str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    summary_fields = []
    for key in [
        "summary",
        "setting",
        "rules",
        "role",
        "external_goal",
        "internal_need",
        "motivation_chain",
        "principles",
        "usable_patterns",
        "do_not_copy",
        "chapter_states",
        "continuity_threads",
        "open_issues",
        "hook",
        "beats",
        "text",
    ]:
        if key in content:
            summary_fields.append({key: content[key]})
    payload = summary_fields if summary_fields else content
    return _compact_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), limit=500)


def _project_scope_for_asset(storage: LocalStorage, data: dict[str, Any], path: str = "") -> dict[str, str]:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if data.get("type") == "project_workspace_state":
        return {
            "project_id": str(content.get("project_id") or data.get("id") or metadata.get("project_id", "")),
            "workspace_id": str(metadata.get("workspace_id") or data.get("id") or ""),
            "workspace_path": path or str(metadata.get("workspace_path", "")),
        }
    scope = {
        "project_id": str(metadata.get("project_id") or content.get("project_id") or ""),
        "workspace_id": str(metadata.get("workspace_id") or content.get("workspace_id") or ""),
        "workspace_path": str(metadata.get("workspace_path") or content.get("workspace_path") or ""),
    }
    if scope["project_id"] or scope["workspace_path"]:
        return scope
    for reference in data.get("references", []) if isinstance(data.get("references", []), list) else []:
        referenced = _read_reference(storage, str(reference))
        if referenced:
            ref_path, ref_data = referenced
            ref_scope = _project_scope_for_asset(storage, ref_data, ref_path)
            if ref_scope.get("project_id") or ref_scope.get("workspace_path"):
                return ref_scope
    return scope


def _matches_project_scope(storage: LocalStorage, data: dict[str, Any], path: str, scope: dict[str, str]) -> bool:
    project_id = scope.get("project_id", "")
    workspace_path = scope.get("workspace_path", "")
    if not project_id and not workspace_path:
        return True
    candidate = _project_scope_for_asset(storage, data, path)
    return bool(
        (project_id and candidate.get("project_id") == project_id)
        or (workspace_path and candidate.get("workspace_path") == workspace_path)
        or (data.get("type") == "project_workspace_state" and path == workspace_path)
    )


def _read_reference(storage: LocalStorage, reference: str) -> tuple[str, dict[str, Any]] | None:
    if not reference:
        return None
    candidate = storage.root / reference
    if candidate.exists() and candidate.is_file():
        try:
            data = storage.read_json(candidate)
        except Exception:
            return None
        return (_relative_path(storage, candidate), data) if isinstance(data, dict) else None
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if reference in {str(data.get("id", "")), _relative_path(storage, path)}:
                return _relative_path(storage, path), data
    return None


def _ranker_name(items: list[dict[str, Any]]) -> str:
    rankers = _dedupe([str(item.get("ranker", "")) for item in items if str(item.get("ranker", "")).strip()])
    return "+".join(rankers) if rankers else "project-scoped-asset-priority"


def _normalize_backend(value: str) -> str:
    backend = str(value or "auto").strip().lower()
    if backend not in RAG_BACKENDS:
        raise ValueError(f"RAG backend must be one of: {', '.join(sorted(RAG_BACKENDS))}")
    return backend


def _relative_path(storage: LocalStorage, path: str | Path | None) -> str:
    if path is None:
        return ""
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = storage.root / resolved
    try:
        return str(resolved.resolve().relative_to(storage.root))
    except ValueError:
        return str(resolved)


def _compact_text(text: str, limit: int) -> str:
    compact = " ".join(str(text).split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
