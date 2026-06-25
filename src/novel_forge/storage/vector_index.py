from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.model_adapters.embeddings import HashEmbeddingAdapter, cosine_similarity
from novel_forge.storage.local import LocalStorage

VECTOR_INDEX_VERSION = "0.2.0"
VECTOR_INDEX_RELATIVE_PATH = Path("data/indexes/vector-index.json")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", re.UNICODE)
CJK_PATTERN = re.compile(r"^[\u4e00-\u9fff]+$")


def vector_index_path(storage: LocalStorage) -> Path:
    return storage.root / VECTOR_INDEX_RELATIVE_PATH


def build_vector_index(storage: LocalStorage, adapter: HashEmbeddingAdapter | None = None) -> Path:
    storage.ensure_layout()
    adapter = adapter or HashEmbeddingAdapter()
    assets: list[dict[str, Any]] = []
    fingerprint = _asset_fingerprint(storage)
    document_frequency: Counter[str] = Counter()

    for category in DATA_DIRS:
        for path in storage.list_json(category):
            data = storage.read_json(path)
            if not isinstance(data, dict):
                continue
            search_text = _search_text(data)
            tokens = _tokenize(search_text)
            term_frequency = Counter(tokens)
            document_frequency.update(set(tokens))
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
                    "token_count": len(tokens),
                    "term_frequency": dict(term_frequency),
                    "embedding": adapter.embed_text(search_text),
                }
            )

    avg_token_count = round(sum(int(asset["token_count"]) for asset in assets) / len(assets), 4) if assets else 0.0
    index = {
        "version": VECTOR_INDEX_VERSION,
        "built_at": utc_now(),
        "categories": list(DATA_DIRS),
        "asset_count": len(assets),
        "fingerprint": fingerprint,
        "embedding": adapter.health_check(),
        "retrieval": {
            "ranker": "hybrid-hash-vector-bm25",
            "document_count": len(assets),
            "average_token_count": avg_token_count,
            "document_frequency": dict(document_frequency),
            "tokenizer": "ascii-token+cjk-unigram-bigram",
        },
        "assets": assets,
        "metadata": {
            "kind": "local_vector_index",
            "storage_root": str(storage.root),
            "index_path": str(VECTOR_INDEX_RELATIVE_PATH),
            "external_services": False,
            "semantic_model": False,
        },
    }
    return storage.write_json(VECTOR_INDEX_RELATIVE_PATH, index)


def load_vector_index(storage: LocalStorage, force_rebuild: bool = False, auto_rebuild: bool = True) -> dict[str, Any]:
    path = vector_index_path(storage)
    if not force_rebuild and path.exists():
        index = storage.read_json(path)
        if isinstance(index, dict) and is_vector_index_current(storage, index):
            return index
    if not auto_rebuild:
        raise FileNotFoundError(f"vector index missing or stale: {path}")
    build_vector_index(storage)
    index = storage.read_json(path)
    if not isinstance(index, dict):
        raise ValueError(f"vector index must be a JSON object: {path}")
    return index


def is_vector_index_current(storage: LocalStorage, index: dict[str, Any]) -> bool:
    if index.get("version") != VECTOR_INDEX_VERSION:
        return False
    if index.get("categories") != list(DATA_DIRS):
        return False
    return index.get("fingerprint") == _asset_fingerprint(storage)


def vector_search_assets(
    storage: LocalStorage,
    query: str,
    category: str | None = None,
    asset_type: str | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
    force_rebuild: bool = False,
    adapter: HashEmbeddingAdapter | None = None,
) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("query must not be empty")
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    adapter = adapter or HashEmbeddingAdapter()
    categories = _resolve_categories(category)
    required_tags = {tag.lower() for tag in tags or [] if tag}
    index = load_vector_index(storage, force_rebuild=force_rebuild)
    records = index.get("assets", [])
    if not isinstance(records, list):
        raise ValueError("vector index assets must be a list")

    query_embedding = adapter.embed_text(query)
    query_tokens = _tokenize(query)
    retrieval = index.get("retrieval", {})
    document_frequency = retrieval.get("document_frequency", {}) if isinstance(retrieval, dict) else {}
    document_count = int(retrieval.get("document_count", len(records))) if isinstance(retrieval, dict) else len(records)
    average_token_count = float(retrieval.get("average_token_count", 0.0)) if isinstance(retrieval, dict) else 0.0
    results: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        asset_tags = [str(tag) for tag in record.get("tags", [])]
        if record.get("category") not in categories:
            continue
        if asset_type and record.get("type") != asset_type:
            continue
        if required_tags and not required_tags.issubset({tag.lower() for tag in asset_tags}):
            continue
        embedding = record.get("embedding", [])
        if not isinstance(embedding, list):
            continue
        term_frequency = record.get("term_frequency", {})
        if not isinstance(term_frequency, dict):
            term_frequency = {}
        token_count = int(record.get("token_count", 0))
        search_text = str(record.get("search_text", "")).lower()
        token_boost = sum(1.0 for token in query_tokens if token in search_text)
        vector_score = cosine_similarity(query_embedding, [float(value) for value in embedding])
        lexical_score = _bm25_score(query_tokens, term_frequency, document_frequency, document_count, token_count, average_token_count)
        score = vector_score + lexical_score + (token_boost * 0.05)
        results.append(
            {
                "path": record.get("path", ""),
                "category": record.get("category", ""),
                "type": record.get("type", ""),
                "title": record.get("title", ""),
                "tags": asset_tags,
                "source": record.get("source", ""),
                "score": round(score, 6),
                "vector_score": round(vector_score, 6),
                "lexical_score": round(lexical_score, 6),
                "ranker": "hybrid-hash-vector-bm25",
            }
        )

    return sorted(results, key=lambda item: (-float(item["score"]), item["path"]))[:limit]


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
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(text):
        token = match.group(0).lower()
        tokens.append(token)
        if CJK_PATTERN.match(token):
            tokens.extend(_cjk_ngrams(token))
    return tokens


def _cjk_ngrams(token: str) -> list[str]:
    if len(token) <= 1:
        return []
    grams = list(token)
    grams.extend(token[index : index + 2] for index in range(len(token) - 1))
    return grams


def _bm25_score(
    query_tokens: list[str],
    term_frequency: dict[str, Any],
    document_frequency: dict[str, Any],
    document_count: int,
    token_count: int,
    average_token_count: float,
) -> float:
    if not query_tokens or document_count <= 0 or average_token_count <= 0:
        return 0.0
    k1 = 1.5
    b = 0.75
    score = 0.0
    for token in set(query_tokens):
        try:
            tf = float(term_frequency.get(token, 0))
            df = float(document_frequency.get(token, 0))
        except (TypeError, ValueError):
            continue
        if tf <= 0:
            continue
        idf = math.log(1 + ((document_count - df + 0.5) / (df + 0.5)))
        denominator = tf + k1 * (1 - b + b * (token_count / average_token_count))
        score += idf * ((tf * (k1 + 1)) / denominator)
    return score
