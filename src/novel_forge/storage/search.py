from __future__ import annotations

import json
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.retrieval_index import search_retrieval_index


def search_assets(
    storage: LocalStorage,
    category: str | None = None,
    asset_type: str | None = None,
    tags: list[str] | None = None,
    keyword: str | None = None,
    limit: int = 50,
    use_index: bool = True,
    rebuild_index: bool = False,
    rank: str = "path",
) -> list[dict[str, Any]]:
    if use_index:
        return search_retrieval_index(
            storage,
            category=category,
            asset_type=asset_type,
            tags=tags,
            keyword=keyword,
            limit=limit,
            force_rebuild=rebuild_index,
            rank=rank,
        )
    if rank != "path":
        raise ValueError("ranked search requires the retrieval index")
    return scan_assets(storage, category=category, asset_type=asset_type, tags=tags, keyword=keyword, limit=limit)


def scan_assets(
    storage: LocalStorage,
    category: str | None = None,
    asset_type: str | None = None,
    tags: list[str] | None = None,
    keyword: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    categories = _resolve_categories(category)
    required_tags = {tag.lower() for tag in tags or [] if tag}
    keyword_lower = keyword.lower() if keyword else ""
    results: list[dict[str, Any]] = []

    for item_category in categories:
        for path in storage.list_json(item_category):
            data = storage.read_json(path)
            if not isinstance(data, dict):
                continue
            asset_tags = [str(tag) for tag in data.get("tags", [])]
            if asset_type and data.get("type") != asset_type:
                continue
            if required_tags and not required_tags.issubset({tag.lower() for tag in asset_tags}):
                continue
            if keyword_lower and keyword_lower not in _search_text(data):
                continue
            results.append(
                {
                    "path": str(path.relative_to(storage.root)),
                    "category": item_category,
                    "type": data.get("type", ""),
                    "title": data.get("title") or data.get("name", ""),
                    "tags": asset_tags,
                    "source": data.get("source", ""),
                }
            )

    return sorted(results, key=lambda item: item["path"])[:limit]


def _resolve_categories(category: str | None) -> list[str]:
    if category is None:
        return list(DATA_DIRS)
    if category not in DATA_DIRS:
        raise ValueError(f"unknown data category: {category}")
    return [category]


def _search_text(data: dict[str, Any]) -> str:
    payload = {
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title", ""),
        "name": data.get("name", ""),
        "source": data.get("source", ""),
        "tags": data.get("tags", []),
        "content": data.get("content", {}),
        "metadata": data.get("metadata", {}),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
