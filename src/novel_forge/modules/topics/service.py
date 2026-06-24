from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.common import read_previous
from novel_forge.schemas import TopicSeed
from novel_forge.storage.local import LocalStorage


def develop_topic(storage: LocalStorage, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    model = model or MockModelAdapter()
    material = read_previous(storage, "materials", input_path)
    generated = model.generate("develop a differentiated suspense topic", {"material": material.content})
    material_tags = _string_list(material.tags)
    asset = TopicSeed(
        title="钟楼回声调查",
        source=material.id,
        tags=_dedupe(["topic", "topic-development", "suspense", "original", *material_tags]),
        content={
            "logline": "A novice investigator tracks a sequence of public signals that expose a hidden civic bargain.",
            "reader_attraction": "mystery clock signal, escalating public stakes, ethical choice pressure",
            "differentiation": "focus on civic memory systems instead of copying any existing detective plot",
            "market_positioning": {
                "target_reader": "urban suspense readers who want clear hooks and moral pressure",
                "platform_fit": "chapter-driven mystery with repeatable public-signal hooks",
                "commercial_hooks": ["visible countdown", "public clue trail", "ethical tradeoff"],
            },
            "trope_variation": {
                "base_mechanism": "low-status investigator + public signal mystery + escalating civic cost",
                "variation": "the clue system is a public archive mechanism, not a copied case or setting",
            },
            "source_material_tags": material_tags,
            "model_output": generated,
        },
        metadata={
            "workflow": "topic-development",
            "skill": "topic-development",
            "originality_boundary": "new premise generated from abstract materials; do not copy source expression",
        },
        references=[material.id],
    )
    return storage.write_asset("topics", asset)


def generate_topic(storage: LocalStorage, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    return develop_topic(storage, input_path, model)


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str) and value.strip()]


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
