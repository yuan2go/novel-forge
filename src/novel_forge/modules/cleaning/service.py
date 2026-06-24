from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novel_forge.modules.common import read_previous
from novel_forge.schemas import CleanedText
from novel_forge.storage.local import LocalStorage

ADVERTISEMENT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^\s*(本书首发|首发于|来源[:：]|转自|下载地址|最新网址|请收藏|求收藏|求推荐|加入书签).*$",
        r"^\s*(www\.|https?://|扫码|关注公众号|微信公众号|QQ群|扣扣群).*$",
        r".*(笔趣阁|起点中文网|晋江文学城|纵横中文网|番茄小说|书旗小说).*(首发|正版|阅读|下载)?.*",
        r"^\s*[-=_*]{4,}\s*$",
    ]
]

OCR_REPLACEMENTS = {
    "\ufeff": "",
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\xa0": " ",
    "�": "",
    "，,": "，",
    "。。": "。",
    "！！": "！",
    "？？": "？",
}

CHAPTER_PATTERNS = [
    re.compile(r"^\s*第[零〇一二三四五六七八九十百千万\d]+[章节卷集部].*$"),
    re.compile(r"^\s*Chapter\s+\d+\b.*$", re.IGNORECASE),
]


def clean(storage: LocalStorage, input_path: str | None = None) -> Path:
    source = read_previous(storage, "raw", input_path)
    text = source.content.get("text", "")
    result = clean_text(text)
    asset = CleanedText(
        title=f"{source.title} cleaned",
        source=source.id,
        tags=["cleaned"],
        content={
            "text": result["text"],
            "chapters": result["chapters"],
        },
        metadata={
            "steps": result["steps"],
            "removed_line_count": result["removed_line_count"],
            "chapter_count": len(result["chapters"]),
        },
        references=[source.id],
    )
    return storage.write_asset("cleaned", asset)


def clean_text(text: str) -> dict[str, Any]:
    normalized = _normalize_ocr_noise(text)
    lines = normalized.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned_lines: list[str] = []
    removed_line_count = 0
    previous_blank = False

    for line in lines:
        cleaned = _normalize_inline_spacing(line)
        if _is_advertisement_or_watermark(cleaned):
            removed_line_count += 1
            continue
        if not cleaned:
            if not previous_blank and cleaned_lines:
                cleaned_lines.append("")
            previous_blank = True
            continue
        cleaned_lines.append(cleaned)
        previous_blank = False

    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()

    final_text = "\n".join(cleaned_lines)
    chapters = _extract_chapters(cleaned_lines)
    return {
        "text": final_text,
        "chapters": chapters,
        "removed_line_count": removed_line_count,
        "steps": [
            "normalize_newlines",
            "normalize_ocr_noise",
            "remove_advertisement_watermark_lines",
            "collapse_repeated_blank_lines",
            "normalize_inline_spacing",
            "detect_chapter_headings",
        ],
    }


def _normalize_ocr_noise(text: str) -> str:
    normalized = text
    for source, target in OCR_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized


def _normalize_inline_spacing(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([，。！？；：、,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"([（《「『【])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([）》」』】])", r"\1", cleaned)
    return cleaned


def _is_advertisement_or_watermark(line: str) -> bool:
    if not line:
        return False
    return any(pattern.match(line) for pattern in ADVERTISEMENT_PATTERNS)


def _extract_chapters(lines: list[str]) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        if any(pattern.match(line) for pattern in CHAPTER_PATTERNS):
            chapters.append({"line": index, "title": line})
    return chapters
