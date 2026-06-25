from __future__ import annotations

from pathlib import Path

from novel_forge.model_adapters import ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.common import read_previous
from novel_forge.schemas import DecompositionReport
from novel_forge.storage.local import LocalStorage


def decompose(storage: LocalStorage, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    model = model or model_from_env("decompose")
    cleaned = read_previous(storage, "cleaned", input_path)
    text = cleaned.content.get("text", "")
    analysis = validate_model_output("analyze", model.analyze(text, {"source_asset_id": cleaned.id}))
    asset = DecompositionReport(
        title=f"{cleaned.title} decomposition",
        source=cleaned.id,
        tags=["decomposition", "abstracted", "commercial-patterns"],
        content={
            "summary": analysis["summary"],
            "commercial_patterns": analysis.get("commercial_patterns")
            or ["reader question raised before explanation", "visible consequence per scene"],
            "narrative_patterns": analysis.get("narrative_patterns") or analysis.get("patterns")
            or ["problem -> investigation -> obstacle -> cost -> hook"],
            "character_mechanisms": ["protagonist pressure increases through external deadline"],
            "conflict_patterns": ["truth-seeking vs institutional silence"],
            "emotion_curve": ["curiosity", "tension", "uncertainty", "anticipation"],
            "hook_patterns": ["unanswered clue at chapter end"],
            "word_count": analysis["word_count"],
            "model_output": analysis,
        },
        metadata={
            "model": model.name,
            "copyright_boundary": "abstract structure and mechanism only; no protected expression copied",
        },
        references=[cleaned.id],
    )
    return storage.write_asset("decompositions", asset)
