from __future__ import annotations

from pathlib import Path
from typing import Any

from .bilingual_pair_parser import parse_bitext_text, parse_parallel_pair_files
from .file_type_detector import detect_corpus_type, detect_file_type


def scan_classical_modern_repository(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    structure = detect_corpus_type(root_path)
    original_files = [path for path in root_path.rglob("text.txt") if "古文原文" in path.parts]
    bitext_files = [path for path in root_path.rglob("bitext.txt")]
    source_files = [path for path in root_path.rglob("source.txt")]
    pair_previews: list[dict[str, Any]] = []
    for bitext in bitext_files[:20]:
        pair_previews.extend(parse_bitext_text(bitext.read_text(encoding="utf-8", errors="ignore"), source_file=str(bitext))[:3])
    for source in source_files[:20]:
        target = source.with_name("target.txt")
        if target.exists():
            pair_previews.extend(parse_parallel_pair_files(source, target)[:3])
    return {
        "root_path": str(root_path),
        "detected_structure": structure,
        "original_file_count": len(original_files),
        "parallel_file_count": len(bitext_files) + len(source_files),
        "sample_files": [
            {
                "path": str(path.relative_to(root_path)),
                "file_type": detect_file_type(path),
                "book_name": _book_name(root_path, path),
            }
            for path in [*original_files[:10], *bitext_files[:10], *source_files[:10]]
        ],
        "pair_preview": pair_previews[:10],
    }


def _book_name(root: Path, path: Path) -> str:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return path.stem
    if len(parts) >= 2 and parts[0] in {"古文原文", "双语数据"}:
        return parts[1]
    return parts[0] if parts else path.stem
