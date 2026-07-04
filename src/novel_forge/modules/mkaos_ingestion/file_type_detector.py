from __future__ import annotations

from pathlib import Path


TEXT_EXTENSIONS = {".txt", ".text"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
JSON_EXTENSIONS = {".json", ".jsonl"}
CSV_EXTENSIONS = {".csv", ".tsv"}
HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
EPUB_EXTENSIONS = {".epub"}


def detect_file_type(path: str | Path) -> str:
    file_path = Path(path)
    name = file_path.name.lower()
    parts = {part.lower() for part in file_path.parts}
    suffix = file_path.suffix.lower()
    if name in {"source.txt", "target.txt", "bitext.txt"}:
        return "parallel_text"
    if "双语数据" in file_path.parts or "bilingual" in parts or "bitext" in parts:
        return "parallel_text"
    if "古文原文" in file_path.parts or "classical" in parts:
        return "classical_text"
    if suffix in TEXT_EXTENSIONS:
        return "plain_text"
    if suffix in MARKDOWN_EXTENSIONS:
        return "markdown"
    if suffix in JSON_EXTENSIONS:
        return "json"
    if suffix in CSV_EXTENSIONS:
        return "csv"
    if suffix in HTML_EXTENSIONS:
        return "html"
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    if suffix in DOCX_EXTENSIONS:
        return "docx"
    if suffix in EPUB_EXTENSIONS:
        return "epub"
    return "unknown"


def detect_corpus_type(root: str | Path) -> dict[str, object]:
    root_path = Path(root)
    has_classical_original = (root_path / "古文原文").exists() or any(part.name.lower() == "classical" for part in root_path.glob("*"))
    has_bilingual_data = (root_path / "双语数据").exists() or any(part.name.lower() in {"bilingual", "bitext"} for part in root_path.glob("*"))
    has_bitext = any(path.name.lower() == "bitext.txt" for path in root_path.rglob("*") if path.is_file())
    corpus_type = "classical_modern_parallel_corpus" if has_classical_original or has_bilingual_data or has_bitext else "local_text_repository"
    return {
        "corpus_type": corpus_type,
        "has_classical_original": has_classical_original,
        "has_bilingual_data": has_bilingual_data,
        "has_bitext": has_bitext,
    }
