from __future__ import annotations

import csv
import json
import re
import zipfile
from html import unescape
from pathlib import Path
from typing import Any

from .file_type_detector import detect_file_type


def read_source_file(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    file_type = detect_file_type(file_path)
    warnings: list[str] = []
    metadata: dict[str, Any] = {"file_type": file_type, "parser_adapter": f"{file_type}_adapter"}
    try:
        if file_type in {"plain_text", "classical_text", "parallel_text", "markdown"}:
            text = file_path.read_text(encoding="utf-8")
        elif file_type == "json":
            text = _read_json_text(file_path)
        elif file_type == "csv":
            text = _read_csv_text(file_path)
        elif file_type == "html":
            text = _strip_markup(file_path.read_text(encoding="utf-8", errors="ignore"))
        elif file_type == "docx":
            text = _read_docx_text(file_path)
        elif file_type == "epub":
            text = _read_epub_text(file_path)
        elif file_type == "pdf":
            text = _read_pdf_text(file_path)
            warnings.append("pdf adapter uses dependency-free best-effort text extraction")
        else:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            warnings.append(f"unknown extension parsed as text: {file_path.suffix}")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        warnings.append("file required utf-8 error tolerant decoding")
    return {
        "path": str(file_path),
        "file_type": file_type,
        "supported": file_type != "unknown",
        "text": text,
        "warnings": warnings,
        "metadata": metadata,
    }


def _read_json_text(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        rows = [json.dumps(item, ensure_ascii=False, sort_keys=True) if not isinstance(item, str) else item for item in data]
        return "\n".join(rows)
    if isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)
    return str(data)


def _read_csv_text(path: Path) -> str:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for row in reader:
            rows.append(" | ".join(cell.strip() for cell in row if cell.strip()))
    return "\n".join(row for row in rows if row)


def _read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return unescape(xml)


def _read_epub_text(path: Path) -> str:
    fragments: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            lower = name.lower()
            if lower.endswith((".xhtml", ".html", ".htm", ".txt")):
                fragments.append(_strip_markup(archive.read(name).decode("utf-8", errors="ignore")))
    return "\n\n".join(fragment for fragment in fragments if fragment.strip())


def _read_pdf_text(path: Path) -> str:
    raw = path.read_bytes()
    decoded = raw.decode("utf-8", errors="ignore") or raw.decode("latin-1", errors="ignore")
    candidates = re.findall(r"\(([^()]{2,})\)", decoded)
    text = "\n".join(candidates) if candidates else decoded
    return re.sub(r"\s+", " ", text).strip()


def _strip_markup(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()
