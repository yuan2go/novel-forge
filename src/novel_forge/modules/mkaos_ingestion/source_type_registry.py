from __future__ import annotations

from typing import Any


SOURCE_TYPE_REGISTRY: dict[str, dict[str, Any]] = {
    "classical_text": {
        "label": "古典文本",
        "default_disciplines": ["classical_literature", "ethics", "political_order"],
        "recommended_flows": ["worldbuilding", "character_design", "outline", "chapter_outline", "review"],
        "extractor": "classical_text_extractor",
    },
    "webnovel_analysis": {
        "label": "网文拆解",
        "default_disciplines": ["commercial_narrative", "platform_rhythm"],
        "recommended_flows": ["outline", "chapter_outline", "prose", "review"],
        "extractor": "webnovel_extractor",
    },
    "professional_book": {
        "label": "专业书籍",
        "default_disciplines": ["professional_knowledge", "methodology"],
        "recommended_flows": ["outline", "chapter_outline", "review", "recap"],
        "extractor": "professional_book_extractor",
    },
    "mystery": {
        "label": "推理/悬疑文本",
        "default_disciplines": ["logic", "mystery_craft"],
        "recommended_flows": ["outline", "chapter_outline", "prose", "review"],
        "extractor": "mystery_extractor",
    },
}


def source_type_profile(source_type: str) -> dict[str, Any]:
    return dict(SOURCE_TYPE_REGISTRY.get(str(source_type or "").strip(), SOURCE_TYPE_REGISTRY["professional_book"]))
