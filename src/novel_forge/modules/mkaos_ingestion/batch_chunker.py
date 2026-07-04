from __future__ import annotations

import hashlib
import re
from typing import Any


def chunk_text(text: str, *, max_chars: int = 1200) -> list[dict[str, Any]]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|(?<=。)\s+(?=\S)", str(text or "")) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
        else:
            if current:
                chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    if not chunks and str(text or "").strip():
        chunks = [str(text).strip()[:max_chars]]
    return [
        {
            "chunk_index": index,
            "text": chunk,
            "content_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
            "text_length": len(chunk),
        }
        for index, chunk in enumerate(chunks)
    ]


def dedupe_chunks(chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    duplicates = 0
    for chunk in chunks:
        content_hash = str(chunk.get("content_hash") or "")
        if content_hash in seen:
            duplicates += 1
            continue
        seen.add(content_hash)
        unique.append(chunk)
    return unique, duplicates
