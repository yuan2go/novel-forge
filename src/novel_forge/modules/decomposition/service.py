from __future__ import annotations

from pathlib import Path

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.common import read_previous
from novel_forge.schemas import DecompositionReport
from novel_forge.storage.local import LocalStorage


def decompose(storage: LocalStorage, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    model = model or MockModelAdapter()
    cleaned = read_previous(storage, "cleaned", input_path)
    text = cleaned.content.get("text", "")
    analysis = model.analyze(text)
    asset = DecompositionReport(
        title=f"{cleaned.title} decomposition",
        source=cleaned.id,
        tags=["decomposition", "abstracted", "commercial-patterns"],
        content={
            "summary": analysis["summary"],
            "commercial_patterns": ["reader question raised before explanation", "visible consequence per scene"],
            "narrative_patterns": ["problem -> investigation -> obstacle -> cost -> hook"],
            "character_mechanisms": ["protagonist pressure increases through external deadline"],
            "conflict_patterns": ["truth-seeking vs institutional silence"],
            "emotion_curve": ["curiosity", "tension", "uncertainty", "anticipation"],
            "hook_patterns": ["unanswered clue at chapter end"],
            "word_count": analysis["word_count"],
        },
        metadata={
            "model": model.name,
            "copyright_boundary": "abstract structure and mechanism only; no protected expression copied",
        },
        references=[cleaned.id],
    )
    return storage.write_asset("decompositions", asset)
