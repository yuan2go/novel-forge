from __future__ import annotations

import csv
import json
import re
import zipfile
from html import unescape
from xml.etree import ElementTree
from pathlib import Path
from typing import Any

from .file_type_detector import detect_file_type


def read_source_file(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    file_type = detect_file_type(file_path)
    warnings: list[str] = []
    metadata: dict[str, Any] = {"file_type": file_type, "parser_adapter": f"{file_type}_adapter"}
    sections: list[dict[str, Any]] = []
    toc: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    parser_quality = "basic_text"
    try:
        if file_type in {"plain_text", "classical_text", "parallel_text", "markdown"}:
            text = file_path.read_text(encoding="utf-8")
            sections = _sectionize_plain_text(text, default_title=file_path.stem)
            toc = _toc_from_sections(sections)
        elif file_type == "json":
            text = _read_json_text(file_path)
            sections = _sectionize_plain_text(text, default_title=file_path.stem)
            toc = _toc_from_sections(sections)
        elif file_type == "csv":
            text = _read_csv_text(file_path)
            sections = _sectionize_plain_text(text, default_title=file_path.stem)
            toc = _toc_from_sections(sections)
        elif file_type == "html":
            text = _strip_markup(file_path.read_text(encoding="utf-8", errors="ignore"))
            sections = _sectionize_html(file_path.read_text(encoding="utf-8", errors="ignore"))
            toc = _toc_from_sections(sections)
        elif file_type == "docx":
            structured = _read_docx_structured(file_path)
            text = structured["text"]
            warnings.extend(structured["warnings"])
            sections = structured["sections"]
            toc = structured["toc"]
            parser_quality = structured["parser_quality"]
        elif file_type == "epub":
            structured = _read_epub_structured(file_path)
            text = structured["text"]
            warnings.extend(structured["warnings"])
            sections = structured["sections"]
            toc = structured["toc"]
            parser_quality = structured["parser_quality"]
        elif file_type == "pdf":
            structured = _read_pdf_structured(file_path)
            text = structured["text"]
            warnings.extend(structured["warnings"])
            sections = structured["sections"]
            toc = structured["toc"]
            pages = structured["pages"]
            parser_quality = structured["parser_quality"]
        else:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            warnings.append(f"unknown extension parsed as text: {file_path.suffix}")
            sections = _sectionize_plain_text(text, default_title=file_path.stem)
            toc = _toc_from_sections(sections)
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        warnings.append("file required utf-8 error tolerant decoding")
        sections = _sectionize_plain_text(text, default_title=file_path.stem)
        toc = _toc_from_sections(sections)
    if not sections and text.strip():
        sections = _sectionize_plain_text(text, default_title=file_path.stem)
    if not toc:
        toc = _toc_from_sections(sections)
    metadata.update(
        {
            "parser_quality": parser_quality,
            "section_count": len(sections),
            "toc_count": len(toc),
            "page_count": len(pages),
            "structure_preserved": bool(toc or len(sections) > 1 or pages),
        }
    )
    return {
        "path": str(file_path),
        "file_type": file_type,
        "supported": file_type != "unknown",
        "text": text,
        "sections": sections,
        "toc": toc,
        "pages": pages,
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


def _read_docx_structured(path: Path) -> dict[str, Any]:
    try:
        from docx import Document  # type: ignore

        document = Document(str(path))
        paragraphs: list[dict[str, Any]] = []
        for index, paragraph in enumerate(document.paragraphs):
            text = paragraph.text.strip()
            if not text:
                continue
            style = paragraph.style.name if paragraph.style else ""
            level = _heading_level_from_style(style)
            paragraphs.append({"index": index, "text": text, "style": style, "heading_level": level})
        sections = _sections_from_paragraphs(paragraphs, default_title=path.stem)
        return {
            "text": "\n\n".join(section["text"] for section in sections),
            "sections": sections,
            "toc": _toc_from_sections(sections),
            "warnings": [],
            "parser_quality": "python_docx_structured",
        }
    except Exception as exc:
        warnings = [f"python-docx unavailable or failed; using xml fallback: {exc}"]
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    paragraphs = _docx_paragraphs_from_xml(xml)
    sections = _sections_from_paragraphs(paragraphs, default_title=path.stem)
    return {
        "text": "\n\n".join(section["text"] for section in sections),
        "sections": sections,
        "toc": _toc_from_sections(sections),
        "warnings": warnings,
        "parser_quality": "docx_xml_structured_fallback",
    }


def _read_epub_structured(path: Path) -> dict[str, Any]:
    try:
        import ebooklib  # type: ignore
        from ebooklib import epub  # type: ignore

        book = epub.read_epub(str(path))
        toc = _ebooklib_toc(book.toc)
        sections = []
        for index, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT)):
            html = item.get_content().decode("utf-8", errors="ignore")
            text = _strip_markup(html)
            if text:
                sections.append(_section(index, item.get_name(), text, level=1, source_file=item.get_name()))
        return {
            "text": "\n\n".join(section["text"] for section in sections),
            "sections": sections,
            "toc": toc or _toc_from_sections(sections),
            "warnings": [],
            "parser_quality": "ebooklib_structured",
        }
    except Exception as exc:
        warnings = [f"ebooklib unavailable or failed; using zip fallback: {exc}"]
    fragments: list[dict[str, Any]] = []
    toc = []
    with zipfile.ZipFile(path) as archive:
        toc = _epub_toc_from_zip(archive)
        for name in sorted(archive.namelist()):
            lower = name.lower()
            if lower.endswith((".xhtml", ".html", ".htm", ".txt")):
                text = _strip_markup(archive.read(name).decode("utf-8", errors="ignore"))
                if text:
                    fragments.append(_section(len(fragments), Path(name).stem, text, level=1, source_file=name))
    return {
        "text": "\n\n".join(fragment["text"] for fragment in fragments),
        "sections": fragments,
        "toc": toc or _toc_from_sections(fragments),
        "warnings": warnings,
        "parser_quality": "epub_zip_structured_fallback",
    }


def _read_pdf_structured(path: Path) -> dict[str, Any]:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages = []
        for index, page in enumerate(reader.pages):
            text = str(page.extract_text() or "").strip()
            pages.append({"page_number": index + 1, "text": text, "char_count": len(text), "source_isolation": {"raw_text_allowed_for_prose": False}})
        outlines = _pypdf_outline(reader)
        sections = _sections_from_pdf_pages(pages, outlines, default_title=path.stem)
        return {
            "text": "\n\n".join(page["text"] for page in pages if page["text"]),
            "pages": pages,
            "sections": sections,
            "toc": outlines or _toc_from_sections(sections),
            "warnings": [],
            "parser_quality": "pypdf_structured",
        }
    except Exception as exc:
        warnings = [f"pypdf unavailable or failed; using dependency-free fallback: {exc}"]
    raw = path.read_bytes()
    decoded = raw.decode("utf-8", errors="ignore") or raw.decode("latin-1", errors="ignore")
    candidates = re.findall(r"\(([^()]{2,})\)", decoded)
    text = "\n".join(candidates) if candidates else decoded
    text = re.sub(r"\s+", " ", text).strip()
    pages = [{"page_number": 1, "text": text, "char_count": len(text), "source_isolation": {"raw_text_allowed_for_prose": False}}] if text else []
    sections = _sectionize_plain_text(text, default_title=path.stem)
    warnings.append("pdf adapter fallback cannot guarantee complex layout fidelity")
    return {
        "text": text,
        "pages": pages,
        "sections": sections,
        "toc": _toc_from_sections(sections),
        "warnings": warnings,
        "parser_quality": "pdf_dependency_free_fallback",
    }


def _strip_markup(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _sectionize_plain_text(text: str, *, default_title: str) -> list[dict[str, Any]]:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    sections: list[dict[str, Any]] = []
    current_title = default_title
    current_level = 1
    buffer: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _looks_like_heading(stripped):
            if buffer:
                sections.append(_section(len(sections), current_title, "\n".join(buffer).strip(), level=current_level))
                buffer = []
            current_title = stripped.lstrip("#").strip()
            current_level = _heading_level(stripped)
        elif stripped:
            buffer.append(stripped)
    if buffer or not sections:
        sections.append(_section(len(sections), current_title, "\n".join(buffer).strip() or str(text or "").strip(), level=current_level))
    return sections


def _sectionize_html(html: str) -> list[dict[str, Any]]:
    parts = re.split(r"(<h[1-6][^>]*>.*?</h[1-6]>)", html, flags=re.IGNORECASE | re.DOTALL)
    sections: list[dict[str, Any]] = []
    title = "document"
    level = 1
    buffer: list[str] = []
    for part in parts:
        if re.match(r"<h[1-6]", part or "", flags=re.IGNORECASE):
            if buffer:
                sections.append(_section(len(sections), title, _strip_markup(" ".join(buffer)), level=level))
                buffer = []
            level_match = re.match(r"<h([1-6])", part, flags=re.IGNORECASE)
            level = int(level_match.group(1)) if level_match else 1
            title = _strip_markup(part) or title
        else:
            buffer.append(part)
    if buffer:
        text = _strip_markup(" ".join(buffer))
        if text:
            sections.append(_section(len(sections), title, text, level=level))
    return sections or _sectionize_plain_text(_strip_markup(html), default_title="document")


def _sections_from_paragraphs(paragraphs: list[dict[str, Any]], *, default_title: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    title = default_title
    level = 1
    buffer: list[str] = []
    start_index = 0
    for paragraph in paragraphs:
        text = str(paragraph.get("text") or "").strip()
        if not text:
            continue
        heading_level = int(paragraph.get("heading_level") or 0)
        if heading_level:
            if buffer:
                sections.append(_section(len(sections), title, "\n\n".join(buffer), level=level, paragraph_start=start_index, paragraph_end=int(paragraph.get("index", 0)) - 1))
                buffer = []
            title = text
            level = heading_level
            start_index = int(paragraph.get("index", 0)) + 1
        else:
            buffer.append(text)
    if buffer or not sections:
        sections.append(_section(len(sections), title, "\n\n".join(buffer), level=level, paragraph_start=start_index, paragraph_end=max(start_index, len(paragraphs) - 1)))
    return sections


def _docx_paragraphs_from_xml(xml: str) -> list[dict[str, Any]]:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        root = ElementTree.fromstring(xml.encode("utf-8"))
    except ElementTree.ParseError:
        # Some lightweight test DOCX fixtures omit namespace declarations. Keep
        # this fallback dependency-free while still preserving heading markers.
        paragraphs: list[dict[str, Any]] = []
        for index, match in enumerate(re.finditer(r"<w:p[\s\S]*?</w:p>|<p[\s\S]*?</p>", xml, flags=re.IGNORECASE)):
            block = match.group(0)
            text = "".join(first or second for first, second in re.findall(r"<(?:w:)?t[^>]*>(.*?)</(?:w:)?t>|<t[^>]*>(.*?)</t>", block, flags=re.IGNORECASE | re.DOTALL))
            text = _strip_markup(text).strip()
            if not text:
                continue
            style_match = re.search(r"<(?:w:)?pStyle[^>]*(?:w:)?val=[\"']([^\"']+)[\"']", block, flags=re.IGNORECASE)
            style = style_match.group(1) if style_match else ""
            paragraphs.append({"index": index, "text": text, "style": style, "heading_level": _heading_level_from_style(style)})
        return paragraphs
    paragraphs: list[dict[str, Any]] = []
    for index, paragraph in enumerate(root.findall(".//w:p", ns)):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
        text = "".join(texts).strip()
        if not text:
            continue
        style = ""
        style_node = paragraph.find(".//w:pStyle", ns)
        if style_node is not None:
            style = str(style_node.attrib.get(f"{{{ns['w']}}}val") or "")
        paragraphs.append({"index": index, "text": text, "style": style, "heading_level": _heading_level_from_style(style)})
    return paragraphs


def _heading_level_from_style(style: str) -> int:
    normalized = str(style or "").lower().replace(" ", "")
    if "heading" in normalized:
        match = re.search(r"(\d+)", normalized)
        return max(1, min(6, int(match.group(1)))) if match else 1
    if normalized.startswith("标题"):
        match = re.search(r"(\d+)", normalized)
        return max(1, min(6, int(match.group(1)))) if match else 1
    return 0


def _heading_level(text: str) -> int:
    if text.startswith("#"):
        return max(1, min(6, len(text) - len(text.lstrip("#"))))
    match = re.match(r"^(第[一二三四五六七八九十百千万0-9]+[章节卷部篇]|Chapter\s+\d+)", text, flags=re.IGNORECASE)
    return 1 if match else 0


def _looks_like_heading(text: str) -> bool:
    if not text:
        return False
    return text.startswith("#") or bool(re.match(r"^(第[一二三四五六七八九十百千万0-9]+[章节卷部篇]|Chapter\s+\d+|Part\s+\d+)(?:\b|$)", text, flags=re.IGNORECASE))


def _section(index: int, title: str, text: str, *, level: int = 1, source_file: str = "", paragraph_start: int | None = None, paragraph_end: int | None = None) -> dict[str, Any]:
    return {
        "section_index": index,
        "title": str(title or f"section-{index + 1}"),
        "level": level,
        "text": str(text or ""),
        "char_count": len(str(text or "")),
        "source_file": source_file,
        "paragraph_start": paragraph_start,
        "paragraph_end": paragraph_end,
        "source_isolation": {"raw_text_allowed_for_prose": False},
    }


def _toc_from_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "title": str(section.get("title") or ""),
            "level": int(section.get("level") or 1),
            "section_index": int(section.get("section_index") or index),
            "char_count": int(section.get("char_count") or 0),
        }
        for index, section in enumerate(sections)
    ]


def _ebooklib_toc(toc: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(items: Any, level: int) -> None:
        for item in items or []:
            if isinstance(item, tuple):
                walk(item[1], level + 1)
                item = item[0]
            title = str(getattr(item, "title", "") or "").strip()
            href = str(getattr(item, "href", "") or "").strip()
            if title:
                rows.append({"title": title, "href": href, "level": level, "section_index": len(rows)})

    walk(toc, 1)
    return rows


def _epub_toc_from_zip(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in archive.namelist():
        lower = name.lower()
        if lower.endswith("toc.ncx") or lower.endswith("nav.xhtml") or lower.endswith("nav.html"):
            text = archive.read(name).decode("utf-8", errors="ignore")
            titles = re.findall(r"<text[^>]*>(.*?)</text>|<a[^>]*>(.*?)</a>", text, flags=re.IGNORECASE | re.DOTALL)
            for match in titles:
                title = _strip_markup(match[0] or match[1])
                if title:
                    rows.append({"title": title, "level": 1, "section_index": len(rows), "source_file": name})
            if rows:
                break
    return rows


def _pypdf_outline(reader: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(items: Any, level: int) -> None:
        for item in items or []:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            title = str(getattr(item, "title", "") or "").strip()
            if title:
                page_number = None
                try:
                    page_number = reader.get_destination_page_number(item) + 1
                except Exception:
                    page_number = None
                rows.append({"title": title, "level": level, "page_start": page_number, "section_index": len(rows)})

    try:
        walk(getattr(reader, "outline", []), 1)
    except Exception:
        return []
    return rows


def _sections_from_pdf_pages(pages: list[dict[str, Any]], toc: list[dict[str, Any]], *, default_title: str) -> list[dict[str, Any]]:
    if not pages:
        return []
    if not toc:
        return [
            _section(
                index,
                f"{default_title} p{page['page_number']}",
                str(page.get("text") or ""),
                level=1,
                paragraph_start=int(page.get("page_number") or 1),
                paragraph_end=int(page.get("page_number") or 1),
            )
            for index, page in enumerate(pages)
            if str(page.get("text") or "").strip()
        ]
    sections: list[dict[str, Any]] = []
    sorted_toc = sorted(toc, key=lambda row: int(row.get("page_start") or 1))
    for index, row in enumerate(sorted_toc):
        start = max(1, int(row.get("page_start") or 1))
        end = int(sorted_toc[index + 1].get("page_start") or len(pages) + 1) - 1 if index + 1 < len(sorted_toc) else len(pages)
        text = "\n\n".join(str(page.get("text") or "") for page in pages if start <= int(page.get("page_number") or 0) <= end)
        sections.append(_section(index, str(row.get("title") or f"{default_title} {index + 1}"), text, level=int(row.get("level") or 1), paragraph_start=start, paragraph_end=end))
    return sections
