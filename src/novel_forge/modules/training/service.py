from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.common import read_previous
from novel_forge.schemas import TrainingExercise
from novel_forge.storage.local import LocalStorage


def generate_training_exercise(storage: LocalStorage, input_path: str | None = None) -> Path:
    source_asset = read_previous(storage, "topics", input_path)
    logline = _string_value(source_asset.content.get("logline"), "Use the current topic seed as the writing premise.")
    attraction = _string_value(source_asset.content.get("reader_attraction"), "clear hook and visible conflict")
    differentiation = _string_value(source_asset.content.get("differentiation"), "abstract mechanism, not copied expression")

    asset = TrainingExercise(
        title="Topic-to-chapter hook training exercise",
        source=source_asset.id,
        tags=_dedupe(["training", "training-exercise", "topic-development", *source_asset.tags]),
        content={
            "objective": "Practice turning a schema-backed TopicSeed into an original chapter hook and conflict beat.",
            "prompt": (
                "Based on the topic logline, design one original opening scene beat. "
                f"Logline: {logline} "
                f"Reader attraction: {attraction} "
                f"Differentiation boundary: {differentiation}"
            ),
            "rubric": {
                "causal_conflict": "The scene creates a choice, obstacle, and consequence.",
                "reader_retention": "The ending creates a concrete next-chapter obligation or unanswered risk.",
                "originality_boundary": "The answer uses abstract mechanisms only and copies no protected plot expression.",
                "schema_completeness": "The answer includes premise, conflict, hook, and self-check notes.",
            },
            "expected_output": {
                "premise": "one sentence",
                "scene_goal": "one concrete objective",
                "conflict_beat": "one obstacle with pressure",
                "chapter_hook": "one end beat that forces continuation",
                "self_check": ["originality", "causality", "reader retention"],
            },
            "constraints": [
                "Do not reuse names, settings, sentences, or plot sequence combinations from source materials.",
                "Keep the output as training material, not final canon for a live novel project.",
                "Prefer conflict and hook mechanics over descriptive lore.",
            ],
        },
        metadata={
            "workflow": "training-exercise",
            "skill": "training-exercise",
            "source_asset_type": source_asset.type,
            "copyright_boundary": "training exercise derived from abstract topic mechanics only",
        },
        references=[source_asset.id],
    )
    return storage.write_asset("training", asset)


def _string_value(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
