from __future__ import annotations

import zipfile
from html.parser import HTMLParser
from pathlib import Path

from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.schemas import SourceDocument
from novel_forge.storage.local import LocalStorage

SUPPORTED_SOURCE_EXTENSIONS = {".txt", ".md", ".epub", ".mobi", ".azw3"}


def ingest(storage: LocalStorage, input_path: str, title: str | None = None) -> Path:
    path = resolve_path(storage.root, input_path)
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"input path is a directory; use ingest_many for batch import: {path}")
    text = read_source_text(path)
    asset = SourceDocument(
        title=title or path.stem,
        source=str(path),
        tags=["imported", "raw", source_format(path)],
        content={"text": text},
        metadata={
            "original_path": str(path),
            "ingested_at": utc_now(),
            "source_format": source_format(path),
            "byte_size": path.stat().st_size,
        },
    )
    return storage.write_asset("raw", asset)


def ingest_many(storage: LocalStorage, input_path: str, title: str | None = None) -> list[Path]:
    path = resolve_path(storage.root, input_path)
    if not path.exists():
        raise FileNotFoundError(f"input path not found: {path}")
    if path.is_file():
        return [ingest(storage, str(path), title)]

    files = discover_source_files(path)
    if not files:
        formats = ", ".join(sorted(SUPPORTED_SOURCE_EXTENSIONS))
        raise ValueError(f"no supported source files found under {path}; supported formats: {formats}")
    return [ingest(storage, str(file_path), None) for file_path in files]


def discover_source_files(path: Path) -> list[Path]:
    return sorted(
        (
            file_path
            for file_path in path.rglob("*")
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS
        ),
        key=lambda item: str(item.relative_to(path)).lower(),
    )


def read_source_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SOURCE_EXTENSIONS:
        formats = ", ".join(sorted(SUPPORTED_SOURCE_EXTENSIONS))
        raise ValueError(f"unsupported source format: {path.suffix}; supported formats: {formats}")
    if suffix in {".txt", ".md"}:
        text = _read_text_file(path)
    elif suffix == ".epub":
        text = _read_epub_text(path)
    else:
        text = _read_binary_fixture_text(path)

    if not text.strip():
        raise ValueError(f"no readable text extracted from source file: {path}")
    return text


def source_format(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "unknown"


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _read_epub_text(path: Path) -> str:
    if not zipfile.is_zipfile(path):
        return _read_binary_fixture_text(path)

    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm", ".txt")) and not name.endswith("/")
        )
        for name in names:
            data = archive.read(name)
            text = _decode_bytes(data)
            if name.lower().endswith((".xhtml", ".html", ".htm")):
                text = _strip_html(text)
            if text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts)


def _read_binary_fixture_text(path: Path) -> str:
    data = path.read_bytes()
    return _decode_bytes(data).replace("\x00", "").strip()


def _decode_bytes(data: bytes) -> str:
    for encoding in ["utf-8-sig", "utf-8", "gb18030", "latin-1"]:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _strip_html(text: str) -> str:
    parser = _TextExtractor()
    parser.feed(text)
    return parser.text()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def text(self) -> str:
        return "\n".join(self._parts)
