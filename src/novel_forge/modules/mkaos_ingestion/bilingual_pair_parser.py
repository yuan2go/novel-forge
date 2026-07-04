from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


PAIR_SEPARATORS = ("|||", "\t", " => ", " -> ")


def parse_bitext_text(
    text: str,
    *,
    book_id: str = "",
    chapter_id: str = "",
    source_file: str = "",
    source_language: str = "classical_chinese",
    target_language: str = "modern_chinese",
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        source_text = ""
        target_text = ""
        for separator in PAIR_SEPARATORS:
            if separator in line:
                left, right = line.split(separator, 1)
                source_text, target_text = left.strip(), right.strip()
                break
        if not source_text and not target_text:
            source_text, target_text = _split_classical_modern_line(line)
        if source_text and target_text:
            pairs.append(_pair_payload(source_text, target_text, len(pairs), book_id, chapter_id, source_file, source_language, target_language))
    return pairs


def parse_parallel_pair_files(
    source_path: str | Path,
    target_path: str | Path,
    *,
    book_id: str = "",
    chapter_id: str = "",
    source_language: str = "classical_chinese",
    target_language: str = "modern_chinese",
) -> list[dict[str, Any]]:
    source_lines = [line.strip() for line in Path(source_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    target_lines = [line.strip() for line in Path(target_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    count = min(len(source_lines), len(target_lines))
    return [
        _pair_payload(source_lines[index], target_lines[index], index, book_id, chapter_id, f"{source_path}|{target_path}", source_language, target_language)
        for index in range(count)
    ]


def _pair_payload(source_text: str, target_text: str, index: int, book_id: str, chapter_id: str, source_file: str, source_language: str, target_language: str) -> dict[str, Any]:
    content_hash = hashlib.sha256(f"{source_text}\n{target_text}".encode("utf-8")).hexdigest()
    return {
        "pair_id": f"parallel-pair-{content_hash[:16]}",
        "book_id": book_id,
        "chapter_id": chapter_id,
        "source_text": source_text,
        "target_text": target_text,
        "source_language": source_language,
        "target_language": target_language,
        "pair_index": index,
        "source_file": source_file,
        "raw_text_allowed_for_prose": False,
        "evidence_layer_only": True,
        "content_hash": content_hash,
    }


def _split_classical_modern_line(line: str) -> tuple[str, str]:
    match = re.match(r"^(.+?[。！？；;])\s*(.+)$", line)
    if not match:
        return "", ""
    left, right = match.group(1).strip(), match.group(2).strip()
    return left, right
