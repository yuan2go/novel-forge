from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.model_adapters import GuardedModelAdapter, ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous, resolve_path
from novel_forge.modules.content_intelligence_governance import content_intelligence_preflight_gate
from novel_forge.modules.model_operation_governance import (
    attach_model_operation_governance,
    enforce_model_operation_preflight,
    record_model_operation_final_governance,
)
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.schemas import TopicSeed
from novel_forge.storage.local import LocalStorage


def develop_topic(
    storage: LocalStorage,
    input_path: str | None = None,
    model: ModelAdapter | None = None,
    *,
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
    provider_runtime_gate: dict[str, Any] | None = None,
) -> Path:
    material = read_previous(storage, "materials", input_path)
    material_path = resolve_path(storage.root, input_path) if input_path else storage.latest("materials")
    project_id = str(material.metadata.get("project_id") or "")
    workspace_path = str(material.metadata.get("workspace_path") or "")
    model = model or model_from_env("topic")
    content_intelligence = content_intelligence_preflight_gate(
        storage,
        target_asset_id=material.id,
        target_asset_path=material_path,
        project_id=project_id,
        workspace_path=workspace_path,
        required=is_production_environment(environment or (os_envelope or {}).get("environment")),
    )
    preflight = enforce_model_operation_preflight(
        storage,
        operation="develop-topic",
        environment=environment,
        target_asset_id=material.id,
        target_asset_path=material_path,
        project_id=project_id,
        workspace_path=workspace_path,
        asset_type="topic_seed",
        task_type="develop-topic",
        os_envelope=os_envelope,
        source_policy=source_policy,
        provider_runtime_gate=provider_runtime_gate,
        extra_gate_statuses={"content_intelligence": content_intelligence},
        extra_required_gates=["content_intelligence"],
    )
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
        guarded_model = GuardedModelAdapter(model, storage, run.path)
        generated = validate_model_output(
            "generate",
            guarded_model.generate(
                "Develop a differentiated suspense topic seed.",
                {
                    "material": material.content,
                    "runtime_operation": "develop_topic",
                    "copyright_boundary": "Use materials as abstract reusable mechanisms only. Do not copy protected expression, scenes, names, or plot combinations.",
                },
            ),
        )
        run.guard("write_topic_seed", "topic_seed")
        path = _write_topic(storage, material, generated, model)
        final_governance = record_model_operation_final_governance(
            storage,
            operation="develop-topic",
            environment=environment,
            output_asset_id=storage.read_json(path).get("id", ""),
            output_asset_path=path,
            project_id=project_id,
            workspace_path=workspace_path,
            source_policy=source_policy,
            os_envelope=os_envelope,
            provider_runtime_gate=provider_runtime_gate,
            preflight_governance=preflight,
            extra_gate_statuses={"content_intelligence": content_intelligence},
            extra_required_gates=["content_intelligence"],
        )
        attach_model_operation_governance(storage, path, final_governance)
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


def generate_topic(
    storage: LocalStorage,
    input_path: str | None = None,
    model: ModelAdapter | None = None,
    **kwargs: Any,
) -> Path:
    return develop_topic(storage, input_path, model, **kwargs)


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
