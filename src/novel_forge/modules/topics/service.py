from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous, resolve_path
from novel_forge.modules.content_intelligence_governance import content_intelligence_preflight_gate
from novel_forge.modules.model_operation_governance import (
    attach_model_operation_governance,
    enforce_model_operation_preflight,
    record_model_operation_final_governance,
)
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_execution import (
    CandidateKind,
    DomainExecutionPort,
    execute_domain_candidate,
    execution_model_name,
)
from novel_forge.schemas import TopicSeed
from novel_forge.storage.local import LocalStorage


def develop_topic(
    storage: LocalStorage,
    input_path: str | None = None,
    model: object | None = None,
    *,
    execution_port: DomainExecutionPort | None = None,
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
    provider_runtime_gate: dict[str, Any] | None = None,
) -> Path:
    material = read_previous(storage, "materials", input_path)
    material_path = resolve_path(storage.root, input_path) if input_path else storage.latest("materials")
    project_id = str(material.metadata.get("project_id") or "")
    workspace_path = str(material.metadata.get("workspace_path") or "")
    model_name = execution_model_name(
        execution_port, model, legacy_model_role="topic"
    )
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
        model_provider=model_name,
        model_name=model_name,
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        candidate = execute_domain_candidate(
            capability="creative.topic.generate",
            operation="generate",
            candidate_kind=CandidateKind.GENERATION,
            prompt="Develop a differentiated suspense topic seed.",
            context={
                "material": material.content,
                "runtime_operation": "develop_topic",
                "copyright_boundary": "Use materials as abstract reusable mechanisms only. Do not copy protected expression, scenes, names, or plot combinations.",
            },
            execution_port=execution_port,
            legacy_model=model,
            legacy_model_role="topic",
            environment=environment,
            storage=storage,
            agent_run_path=run.path,
        )
        generated = dict(candidate.raw_output)
        model_name = candidate.evidence.model_id or model_name
        run.guard("write_topic_seed", "topic_seed")
        path = _write_topic(
            storage,
            material,
            generated,
            model_name=model_name,
            execution_evidence=candidate.evidence.to_dict(),
        )
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


def _write_topic(
    storage: LocalStorage,
    material: Any,
    generated: dict[str, Any],
    *,
    model_name: str,
    execution_evidence: dict[str, Any],
) -> Path:
    material_tags = _string_list(material.tags)
    material_content = material.content if isinstance(material.content, dict) else {}
    patterns = _string_list(material_content.get("usable_patterns"))
    primary_pattern = patterns[0] if patterns else (material_tags[0] if material_tags else "核心冲突")
    project_id = str(material.metadata.get("project_id") or "")
    workspace_path = str(material.metadata.get("workspace_path") or "")
    title = f"{material.title}：原创叙事方案"
    asset = TopicSeed(
        title=title,
        source=material.id,
        tags=_dedupe(["topic", "topic-development", "original", *material_tags]),
        content={
            "logline": f"一名主角必须在“{primary_pattern}”造成的持续压力中行动，并承担每次选择带来的升级代价。",
            "reader_attraction": f"以{primary_pattern}建立清晰钩子、冲突升级和章节兑现。",
            "differentiation": f"从“{material.title}”的抽象机制发展原创题材，不复制任何既有故事表达。",
            "market_positioning": {
                "target_reader": "偏好明确冲突、选择代价和连续钩子的连载读者",
                "platform_fit": "以章节目标、转折和钩子推进的长篇连载",
                "commercial_hooks": [primary_pattern, "选择代价", "章节反转"],
            },
            "trope_variation": {
                "base_mechanism": primary_pattern,
                "variation": "把抽象机制转为原创人物目标、对手压力和世界规则，不复用来源的场景或情节组合。",
            },
            "source_material_tags": material_tags,
            "model_output": generated,
        },
        metadata={
            "workflow": "topic-development",
            "skill": "topic-development",
            "model": model_name,
            "provider": generated.get("provider", model_name),
            "production_execution": execution_evidence,
            "project_id": project_id,
            "workspace_path": workspace_path,
            "originality_boundary": "new premise generated from abstract materials; do not copy source expression",
        },
        references=[material.id],
    )
    return storage.write_asset("topics", asset)


def generate_topic(
    storage: LocalStorage,
    input_path: str | None = None,
    model: object | None = None,
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
