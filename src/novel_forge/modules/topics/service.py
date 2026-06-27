from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.model_adapters import ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous
from novel_forge.schemas import TopicSeed
from novel_forge.storage.local import LocalStorage


def develop_topic(storage: LocalStorage, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    material = read_previous(storage, "materials", input_path)
    model = model or model_from_env("topic")
    with AgentExecutionContext(
        storage,
        agent_key="topic",
        operation="develop-topic",
        input_assets=[input_path or material.id],
        output_types=["topic_seed"],
        model_provider=model.name,
        model_name=model.name,
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        run.guard("call_model_adapter")
        generated = validate_model_output(
            "generate",
            model.generate("Develop a differentiated suspense topic seed.", {"material": material.content}),
        )
        run.guard("write_topic_seed", "topic_seed")
        path = _write_topic(storage, material, generated, model)
        run.succeed(output_assets=[str(path.relative_to(storage.root)) if path.is_absolute() and path.is_relative_to(storage.root) else str(path)])
        return path


def _write_topic(storage: LocalStorage, material: Any, generated: dict[str, Any], model: ModelAdapter) -> Path:
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
            "model": model.name,
            "provider": generated.get("provider", model.name),
            "originality_boundary": "new premise generated from abstract materials; do not copy source expression",
        },
        references=[material.id],
    )
    return storage.write_asset("topics", asset)


def generate_topic(storage: LocalStorage, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
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
