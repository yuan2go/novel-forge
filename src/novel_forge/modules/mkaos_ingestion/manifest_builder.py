from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .file_type_detector import detect_corpus_type, detect_file_type


def build_repository_manifest(root: str | Path, *, repository_id: str = "") -> dict[str, Any]:
    root_path = Path(root)
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root_path.rglob("*") if item.is_file()):
        relative = str(path.relative_to(root_path))
        file_type = detect_file_type(path)
        files.append(
            {
                "path": relative,
                "file_type": file_type,
                "book_name": infer_book_name(root_path, path),
                "chapter_path": infer_chapter_path(root_path, path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
                "import_status": "pending",
            }
        )
    return {
        "repository_id": repository_id,
        "root_path": str(root_path),
        "files": files,
        "detected_structure": detect_corpus_type(root_path),
        "stats": {
            "file_count": len(files),
            "book_count": len({item["book_name"] for item in files if item["book_name"]}),
            "parallel_file_count": len([item for item in files if item["file_type"] == "parallel_text"]),
        },
    }


def infer_book_name(root: Path, path: Path) -> str:
    parts = path.relative_to(root).parts
    if len(parts) >= 2 and parts[0] in {"古文原文", "双语数据"}:
        return parts[1]
    if len(parts) >= 2:
        return parts[-2]
    return path.stem


def infer_chapter_path(root: Path, path: Path) -> list[str]:
    parts = path.relative_to(root).parts
    if len(parts) <= 2:
        return [path.stem]
    if parts[0] in {"古文原文", "双语数据"}:
        return [part for part in parts[2:-1]] or [path.stem]
    return [part for part in parts[1:-1]] or [path.stem]
