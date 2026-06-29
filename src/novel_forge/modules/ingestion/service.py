from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.schemas import SourceDocument
from novel_forge.storage.local import LocalStorage

SUPPORTED_SOURCE_EXTENSIONS = {".txt", ".md", ".epub", ".mobi", ".azw3"}


@dataclass(frozen=True)
class ExtractedSource:
    text: str
    metadata: dict = field(default_factory=dict)


def ingest(
    storage: LocalStorage,
    input_path: str,
    title: str | None = None,
    rights_authorization: str = "unknown",
    license_name: str = "",
    copyright_note: str = "",
    source_url: str = "",
    allow_downstream_generation: bool = False,
) -> Path:
    path = resolve_path(storage.root, input_path)
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"input path is a directory; use ingest_many for batch import: {path}")
    extracted = extract_source(path)
    asset = SourceDocument(
        title=title or path.stem,
        source=str(path),
        tags=["imported", "raw", source_format(path)],
        content={"text": extracted.text},
        metadata={
            "original_path": str(path),
            "ingested_at": utc_now(),
            "source_format": source_format(path),
            "byte_size": path.stat().st_size,
            "rights": {
                "authorization": rights_authorization,
                "license": license_name,
                "copyright_boundary": copyright_note or "recorded source; do not copy protected expression",
                "source_url": source_url,
                "allow_downstream_generation": allow_downstream_generation,
            },
            **extracted.metadata,
        },
    )
    return storage.write_asset("raw", asset)


def ingest_many(
    storage: LocalStorage,
    input_path: str,
    title: str | None = None,
    rights_authorization: str = "unknown",
    license_name: str = "",
    copyright_note: str = "",
    source_url: str = "",
    allow_downstream_generation: bool = False,
) -> list[Path]:
    path = resolve_path(storage.root, input_path)
    if not path.exists():
        raise FileNotFoundError(f"input path not found: {path}")
    if path.is_file():
        return [
            ingest(
                storage,
                str(path),
                title,
                rights_authorization,
                license_name,
                copyright_note,
                source_url,
                allow_downstream_generation,
            )
        ]

    files = discover_source_files(path)
    if not files:
        formats = ", ".join(sorted(SUPPORTED_SOURCE_EXTENSIONS))
        raise ValueError(f"no supported source files found under {path}; supported formats: {formats}")
    return [
        ingest(
            storage,
            str(file_path),
            None,
            rights_authorization,
            license_name,
            copyright_note,
            source_url,
            allow_downstream_generation,
        )
        for file_path in files
    ]


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
    return extract_source(path).text


def extract_source(path: Path) -> ExtractedSource:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SOURCE_EXTENSIONS:
        formats = ", ".join(sorted(SUPPORTED_SOURCE_EXTENSIONS))
        raise ValueError(f"unsupported source format: {path.suffix}; supported formats: {formats}")
    if suffix in {".txt", ".md"}:
        extracted = _read_text_file(path)
    elif suffix == ".epub":
        extracted = _read_epub_source(path)
    else:
        extracted = _read_binary_fixture_source(path)

    if not extracted.text.strip():
        raise ValueError(f"no readable text extracted from source file: {path}")
    return extracted


def source_format(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "unknown"


def _read_text_file(path: Path) -> ExtractedSource:
    data = path.read_bytes()
    decoded = _decode_text_bytes(data)
    return ExtractedSource(
        decoded["text"],
        {
            "extraction_method": "text-decode",
            "detected_encoding": decoded["encoding"],
            "encoding_confidence": decoded["confidence"],
            "encoding_candidates": decoded["candidates"],
            "encoding_warnings": decoded["warnings"],
        },
    )


def _read_epub_source(path: Path) -> ExtractedSource:
    if not zipfile.is_zipfile(path):
        fallback = _read_binary_fixture_source(path)
        return ExtractedSource(
            fallback.text,
            {
                **fallback.metadata,
                "extraction_method": "epub-binary-fallback",
                "extraction_warnings": ["epub file is not a valid zip archive; used binary text fallback"],
            },
        )

    parts: list[str] = []
    warnings: list[str] = []
    with zipfile.ZipFile(path) as archive:
        opf_path = _epub_opf_path(archive)
        epub_metadata: dict[str, str] = {}
        if opf_path:
            names, epub_metadata = _epub_spine_names(archive, opf_path)
            extraction_method = "epub-opf-spine"
        else:
            names = []
            extraction_method = "epub-file-scan"
            warnings.append("OPF package document not found; fell back to sorted content files")
        if not names:
            names = _epub_content_names(archive)
            extraction_method = "epub-file-scan"
            warnings.append("EPUB spine is empty or unreadable; fell back to sorted content files")
        for name in names:
            data = archive.read(name)
            text = _decode_bytes(data)
            if name.lower().endswith((".xhtml", ".html", ".htm")):
                text = _strip_html(text)
            if text.strip():
                parts.append(text.strip())
    return ExtractedSource(
        "\n\n".join(parts),
        {
            "extraction_method": extraction_method,
            "epub_spine_items": names,
            "epub_metadata": epub_metadata,
            "extraction_warnings": warnings,
        },
    )


def _read_binary_fixture_source(path: Path) -> ExtractedSource:
    data = path.read_bytes()
    decoded = _decode_bytes(data).replace("\x00", "")
    text = _readable_text(decoded)
    suffix = path.suffix.lower().lstrip(".")
    warnings = []
    if suffix in {"mobi", "azw3"}:
        warnings.append(f"{suffix} proprietary parsing is limited without external ebook dependencies")
    return ExtractedSource(
        text,
        {
            "extraction_method": "binary-readable-text",
            "extraction_warnings": warnings,
            "decoded_character_count": len(decoded),
        },
    )


def _decode_bytes(data: bytes) -> str:
    return _decode_text_bytes(data)["text"]


def _decode_text_bytes(data: bytes) -> dict:
    candidates: list[dict] = []
    for encoding in ["utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1"]:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            candidates.append({"encoding": encoding, "status": "decode_error", "score": 0})
            continue
        score = _decode_quality_score(text)
        candidates.append({"encoding": encoding, "status": "decoded", "score": score})
    decoded_candidates = [item for item in candidates if item["status"] == "decoded"]
    if decoded_candidates:
        best = sorted(decoded_candidates, key=lambda item: (-float(item["score"]), str(item["encoding"])))[0]
        text = data.decode(str(best["encoding"]))
        warnings = []
        if str(best["encoding"]) not in {"utf-8-sig", "utf-8"}:
            warnings.append(f"source decoded with non-utf8 encoding: {best['encoding']}")
        return {
            "text": text,
            "encoding": best["encoding"],
            "confidence": _decode_confidence(best, decoded_candidates),
            "candidates": candidates,
            "warnings": warnings,
        }
    text = data.decode("utf-8", errors="replace")
    return {
        "text": text,
        "encoding": "utf-8-replace",
        "confidence": "low",
        "candidates": candidates,
        "warnings": ["all strict decoders failed; used utf-8 replacement decode"],
    }


def _decode_quality_score(text: str) -> float:
    if not text:
        return 0.0
    length = max(len(text), 1)
    replacement_penalty = text.count("�") * 8
    control_penalty = sum(1 for char in text if not (char.isprintable() or char in "\n\r\t")) * 4
    cjk_ratio = sum(1 for char in text if "\u4e00" <= char <= "\u9fff") / length
    mojibake_hits = sum(text.count(marker) for marker in ["Ã", "Â", "¤", "¥", "Ð", "Ñ"])
    punctuation_signal = sum(text.count(marker) for marker in ["。", "，", "！", "？", "“", "”", "第", "章"])
    return (cjk_ratio * 100.0) + min(30.0, punctuation_signal / max(length / 1000.0, 1.0)) - replacement_penalty - control_penalty - mojibake_hits * 3


def _decode_confidence(best: dict, decoded: list[dict]) -> str:
    if not decoded:
        return "low"
    scores = sorted([float(item.get("score", 0.0)) for item in decoded], reverse=True)
    best_score = float(best.get("score", 0.0))
    gap = best_score - (scores[1] if len(scores) > 1 else 0.0)
    if best_score >= 20 and gap >= 5:
        return "high"
    if best_score >= 10:
        return "medium"
    return "low"


def _strip_html(text: str) -> str:
    parser = _TextExtractor()
    parser.feed(text)
    return parser.text()


def _epub_opf_path(archive: zipfile.ZipFile) -> str | None:
    try:
        container = archive.read("META-INF/container.xml")
    except KeyError:
        candidates = [name for name in archive.namelist() if name.lower().endswith(".opf")]
        return sorted(candidates)[0] if candidates else None
    try:
        root = ET.fromstring(container)
    except ET.ParseError:
        return None
    for element in root.iter():
        if _local_name(element.tag) == "rootfile":
            full_path = element.attrib.get("full-path")
            if full_path:
                return full_path
    return None


def _epub_spine_names(archive: zipfile.ZipFile, opf_path: str) -> tuple[list[str], dict[str, str]]:
    try:
        root = ET.fromstring(archive.read(opf_path))
    except (KeyError, ET.ParseError):
        return [], {}
    base = Path(opf_path).parent
    manifest: dict[str, str] = {}
    spine_ids: list[str] = []
    metadata: dict[str, str] = {}
    for element in root.iter():
        name = _local_name(element.tag)
        if name == "item" and element.attrib.get("id") and element.attrib.get("href"):
            href = str((base / element.attrib["href"]).as_posix()) if str(base) != "." else element.attrib["href"]
            manifest[element.attrib["id"]] = href
        elif name == "itemref" and element.attrib.get("idref"):
            spine_ids.append(element.attrib["idref"])
        elif name in {"title", "creator", "language"} and element.text and element.text.strip():
            metadata[name] = element.text.strip()
    names = [manifest[item_id] for item_id in spine_ids if manifest.get(item_id)]
    names = [name for name in names if name in archive.namelist() and _is_epub_content_name(name)]
    return names, metadata


def _epub_content_names(archive: zipfile.ZipFile) -> list[str]:
    return sorted(name for name in archive.namelist() if _is_epub_content_name(name))


def _is_epub_content_name(name: str) -> bool:
    return name.lower().endswith((".xhtml", ".html", ".htm", ".txt")) and not name.endswith("/")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _readable_text(text: str) -> str:
    lines = []
    for line in text.splitlines() or [text]:
        cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in line)
        cleaned = " ".join(cleaned.split())
        if len(cleaned) >= 3:
            lines.append(cleaned)
    if lines:
        return "\n".join(lines).strip()
    return " ".join(text.split()).strip()


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
