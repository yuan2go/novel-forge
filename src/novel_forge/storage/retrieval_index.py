from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.storage.local import LocalStorage

INDEX_VERSION = "0.1.0"
INDEX_RELATIVE_PATH = Path("data/indexes/retrieval-index.json")
TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def retrieval_index_path(storage: LocalStorage) -> Path:
    return storage.root / INDEX_RELATIVE_PATH


def build_retrieval_index(storage: LocalStorage) -> Path:
    storage.ensure_layout()
    assets: list[dict[str, Any]] = []
    token_index: dict[str, list[int]] = {}
    fingerprint = _asset_fingerprint(storage)

    for category in DATA_DIRS:
        for path in storage.list_json(category):
            data = storage.read_json(path)
            if not isinstance(data, dict):
                continue
            record_id = len(assets)
            search_text = _search_text(data)
            tokens = sorted(set(_tokenize(search_text)))
            assets.append(
                {
                    "path": str(path.relative_to(storage.root)),
                    "category": category,
                    "id": data.get("id", ""),
                    "type": data.get("type", ""),
                    "title": data.get("title") or data.get("name", ""),
                    "tags": [str(tag) for tag in data.get("tags", [])],
                    "source": data.get("source", ""),
                    "search_text": search_text,
                    "tokens": tokens,
                }
            )
            for token in tokens:
                token_index.setdefault(token, []).append(record_id)

    index = {
        "version": INDEX_VERSION,
        "built_at": utc_now(),
        "categories": list(DATA_DIRS),
        "asset_count": len(assets),
        "fingerprint": fingerprint,
        "assets": assets,
        "token_index": token_index,
        "metadata": {
            "kind": "local_retrieval_index",
            "storage_root": str(storage.root),
            "index_path": str(INDEX_RELATIVE_PATH),
            "external_services": False,
        },
    }
    return storage.write_json(INDEX_RELATIVE_PATH, index)


def load_retrieval_index(storage: LocalStorage, force_rebuild: bool = False, auto_rebuild: bool = True) -> dict[str, Any]:
    path = retrieval_index_path(storage)
    if not force_rebuild and path.exists():
        index = storage.read_json(path)
        if isinstance(index, dict) and is_retrieval_index_current(storage, index):
            return index
    if not auto_rebuild:
        raise FileNotFoundError(f"retrieval index missing or stale: {path}")
    build_retrieval_index(storage)
    index = storage.read_json(path)
    if not isinstance(index, dict):
        raise ValueError(f"retrieval index must be a JSON object: {path}")
    return index


def is_retrieval_index_current(storage: LocalStorage, index: dict[str, Any]) -> bool:
    if index.get("version") != INDEX_VERSION:
        return False
    if index.get("categories") != list(DATA_DIRS):
        return False
    return index.get("fingerprint") == _asset_fingerprint(storage)


def search_retrieval_index(
    storage: LocalStorage,
    category: str | None = None,
    asset_type: str | None = None,
    tags: list[str] | None = None,
    keyword: str | None = None,
    limit: int = 50,
    force_rebuild: bool = False,
    rank: str = "path",
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    if rank not in {"path", "relevance"}:
        raise ValueError("rank must be path or relevance")
    categories = _resolve_categories(category)
    required_tags = {tag.lower() for tag in tags or [] if tag}
    keyword_lower = keyword.lower() if keyword else ""
    query_tokens = _tokenize(keyword_lower)
    index = load_retrieval_index(storage, force_rebuild=force_rebuild)
    asset_records = index.get("assets", [])
    if not isinstance(asset_records, list):
        raise ValueError("retrieval index assets must be a list")

    candidates = _candidate_record_ids(index, keyword_lower)
    results: list[dict[str, Any]] = []
    for record_id in candidates:
        if record_id >= len(asset_records):
            continue
        record = asset_records[record_id]
        if not isinstance(record, dict):
            continue
        asset_tags = [str(tag) for tag in record.get("tags", [])]
        if record.get("category") not in categories:
            continue
        if asset_type and record.get("type") != asset_type:
            continue
        if required_tags and not required_tags.issubset({tag.lower() for tag in asset_tags}):
            continue
        search_text = str(record.get("search_text", "")).lower()
        if keyword_lower and rank == "path" and keyword_lower not in search_text:
            continue
        if keyword_lower and rank == "relevance" and not _matches_relevance_query(record, keyword_lower, query_tokens):
            continue
        row = {
            "path": record.get("path", ""),
            "category": record.get("category", ""),
            "type": record.get("type", ""),
            "title": record.get("title", ""),
            "tags": asset_tags,
            "source": record.get("source", ""),
        }
        if rank == "relevance":
            row["score"] = round(_relevance_score(record, keyword_lower, query_tokens, required_tags), 6)
            row["ranker"] = "field-weighted-token"
        results.append(row)

    if rank == "relevance":
        return sorted(results, key=lambda item: (-float(item.get("score", 0.0)), item["path"]))[:limit]
    return sorted(results, key=lambda item: item["path"])[:limit]


def _candidate_record_ids(index: dict[str, Any], keyword_lower: str) -> list[int]:
    assets = index.get("assets", [])
    if not isinstance(assets, list):
        return []
    if not keyword_lower:
        return list(range(len(assets)))

    token_index = index.get("token_index", {})
    if not isinstance(token_index, dict):
        return list(range(len(assets)))
    tokens = _tokenize(keyword_lower)
    if not tokens:
        return list(range(len(assets)))

    candidate_sets: list[set[int]] = []
    for token in tokens:
        values = token_index.get(token, [])
        if isinstance(values, list) and values:
            candidate_sets.append({int(value) for value in values if isinstance(value, int)})
    if not candidate_sets:
        return list(range(len(assets)))
    return sorted(set.intersection(*candidate_sets))


def _matches_relevance_query(record: dict[str, Any], keyword_lower: str, query_tokens: list[str]) -> bool:
    search_text = str(record.get("search_text", "")).lower()
    if keyword_lower in search_text:
        return True
    record_tokens = {str(token).lower() for token in record.get("tokens", []) if isinstance(token, str)}
    return any(token in record_tokens for token in query_tokens)


def _relevance_score(
    record: dict[str, Any],
    keyword_lower: str,
    query_tokens: list[str],
    required_tags: set[str],
) -> float:
    title = str(record.get("title", "")).lower()
    tags = {str(tag).lower() for tag in record.get("tags", [])}
    source = str(record.get("source", "")).lower()
    search_text = str(record.get("search_text", "")).lower()
    record_tokens = {str(token).lower() for token in record.get("tokens", []) if isinstance(token, str)}

    score = 0.0
    if keyword_lower:
        if keyword_lower in title:
            score += 8.0
        if keyword_lower in " ".join(sorted(tags)):
            score += 6.0
        if keyword_lower in source:
            score += 2.0
        if keyword_lower in search_text:
            score += 3.0

    for token in query_tokens:
        if token in title:
            score += 5.0
        if token in tags:
            score += 4.0
        if token in source:
            score += 1.5
        if token in record_tokens:
            score += 1.0
        if token and token in search_text:
            score += 0.5

    score += len(required_tags.intersection(tags)) * 2.0
    return score


def _asset_fingerprint(storage: LocalStorage) -> list[dict[str, Any]]:
    fingerprint: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            stat = path.stat()
            fingerprint.append(
                {
                    "path": str(path.relative_to(storage.root)),
                    "mtime_ns": stat.st_mtime_ns,
                    "size": stat.st_size,
                }
            )
    return fingerprint


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


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]
