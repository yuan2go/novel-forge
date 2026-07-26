from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.model_adapters import (
    ModelOutputValidationError,
    parse_json_object,
)
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.content_intelligence_governance import content_intelligence_preflight_gate
from novel_forge.modules.context_builder import build_flow_context_bundle, knowledge_context_contract_from_pack, knowledge_context_contract_metadata
from novel_forge.modules.mkaos import build_mkaos_flow_context_with_policy, mkaos_pack_metadata, record_pack_usage_for_artifact
from novel_forge.modules.model_operation_governance import (
    attach_model_operation_governance,
    enforce_model_operation_preflight,
    record_model_operation_final_governance,
)
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.planning_context import build_planning_context, planning_context_metadata
from novel_forge.modules.production_chain import create_outline_version
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.production_execution import (
    CandidateKind,
    DomainExecutionPort,
    execute_domain_candidate,
    execution_model_name,
)
from novel_forge.schemas import Outline
from novel_forge.storage.local import LocalStorage

PROMPT_VERSION = "outline-v2-project-context"


def generate_outline(
    storage: LocalStorage,
    input_path: str | None = None,
    model: object | None = None,
    *,
    execution_port: DomainExecutionPort | None = None,
    workspace_path: str | None = None,
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
    provider_runtime_gate: dict[str, Any] | None = None,
) -> Path:
    model_name = execution_model_name(
        execution_port, model, legacy_model_role="outline"
    )
    source_path = resolve_path(storage.root, input_path) if input_path else storage.latest("characters")
    character = storage.read_asset(source_path)
    source_ref = _display_path(storage.root, source_path)
    planning_context = build_planning_context(storage, character, input_path=source_path, workspace_path=workspace_path)
    production_context = planning_context["production_context"]
    project_id = str(production_context.get("project", {}).get("project_id", ""))
    workspace = str(production_context.get("project", {}).get("workspace_path", ""))
    project_config = production_context.get("project_config", {}) if isinstance(production_context.get("project_config", {}), dict) else {}
    mkaos_pack = _build_mkaos_pack(
        storage,
        target_path=source_path,
        flow="outline",
        project_id=project_id,
        workspace_path=workspace,
        genre=str(project_config.get("genre") or ""),
        platform=str(project_config.get("target_platform") or ""),
        current_goal=f"outline for {character.title or character.id}",
        environment=environment,
        os_envelope=os_envelope,
        source_policy=source_policy,
    )
    knowledge_contract = knowledge_context_contract_from_pack(mkaos_pack)
    content_intelligence = content_intelligence_preflight_gate(
        storage,
        target_asset_id=character.id,
        target_asset_path=source_path,
        project_id=project_id,
        workspace_path=workspace,
        required=is_production_environment(environment or (os_envelope or {}).get("environment")),
    )
    preflight = enforce_model_operation_preflight(
        storage,
        operation="generate-outline",
        environment=environment,
        target_asset_id=character.id,
        target_asset_path=source_path,
        project_id=project_id,
        workspace_path=workspace,
        asset_type="outline",
        task_type="generate-outline",
        os_envelope=os_envelope,
        source_policy=source_policy,
        provider_runtime_gate=provider_runtime_gate,
        context_bundle_path=str(mkaos_pack.get("context_bundle_path") or ""),
        require_context_bundle=True,
        extra_gate_statuses={"content_intelligence": content_intelligence},
        extra_required_gates=["content_intelligence"],
    )
    with AgentExecutionContext(
        storage,
        agent_key="outline",
        operation="generate-outline",
        input_assets=_dedupe([source_ref, *planning_context.get("references", [])]),
        output_types=["outline", "outline_version"],
        model_provider=model_name,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
        token_budget=3500,
        sla_seconds=600,
        workspace_path=workspace,
        knowledge_context_contract=knowledge_contract,
    ) as run:
        run.guard("read_asset")
        candidate = execute_domain_candidate(
            capability="planning.book.generate",
            operation="generate",
            candidate_kind=CandidateKind.GENERATION,
            prompt="Generate a project-specific long-form novel outline. Return JSON only.",
            context={
                    "required_output": {
                        "title": "string",
                        "reader_promise": "string",
                        "conflict_engine": "string",
                        "acts": [
                            {
                                "act": 1,
                                "goal": "string",
                                "turn": "string",
                                "chapters": [{"chapter": 1, "promise": "string", "hook": "string"}],
                            }
                        ],
                        "quality_targets": ["string"],
                        "creative_strategy_constraints": ["string"],
                        "volume_goals": ["string"],
                        "pleasure_rhythm": ["string"],
                        "long_hooks": ["string"],
                        "platform_pacing": ["string"],
                        "continuity_constraints": ["string"],
                        "feedback_constraints": ["string"],
                    },
                    "source_character": character.to_dict(),
                    "planning_context": planning_context,
                    "context_bundle": _context_bundle_content(mkaos_pack),
                    "mkaos_knowledge_pack": _pack_content(mkaos_pack),
                    "copyright_boundary": "Use reference assets for abstract structure only. Do not copy protected scenes, names, settings, or prose.",
            },
            execution_port=execution_port,
            legacy_model=model,
            legacy_model_role="outline",
            environment=environment,
            storage=storage,
            agent_run_path=run.path,
        )
        generated = dict(candidate.raw_output)
        model_name = candidate.evidence.model_id or model_name
        packet = _outline_packet(
            generated,
            character.to_dict(),
            planning_context,
            model_name=model_name,
        )
        asset = Outline(
            title=str(packet.get("title") or f"{character.title or 'Project'} outline"),
            source=character.id,
            tags=_dedupe(["outline", "model-driven", "project-context", *[str(item) for item in packet.get("tags", []) if str(item).strip()]]),
            content={
                "acts": packet["acts"],
                "reader_promise": packet.get("reader_promise", ""),
                "conflict_engine": packet.get("conflict_engine", ""),
                "quality_targets": packet.get("quality_targets", []),
                "creative_strategy_constraints": packet.get("creative_strategy_constraints", []),
                "volume_goals": packet.get("volume_goals", []),
                "pleasure_rhythm": packet.get("pleasure_rhythm", []),
                "long_hooks": packet.get("long_hooks", []),
                "platform_pacing": packet.get("platform_pacing", []),
                "continuity_constraints": packet.get("continuity_constraints", []),
                "feedback_constraints": packet.get("feedback_constraints", []),
                "planning_context": planning_context,
                "context_bundle": _context_bundle_content(mkaos_pack),
                "context_bundle_id": mkaos_pack.get("context_bundle", {}).get("asset", {}).get("id", ""),
                "context_bundle_path": mkaos_pack.get("context_bundle_path", ""),
                "knowledge_context_contract": knowledge_contract,
                "mkaos_knowledge_pack": _pack_content(mkaos_pack),
                "mkaos_knowledge_pack_path": mkaos_pack.get("path", ""),
                "mkaos_knowledge_pack_warning": mkaos_pack.get("warning", ""),
                "mkaos_pack_policy": mkaos_pack_metadata(mkaos_pack)["mkaos_pack_policy"],
                "mkaos_runtime_policy_warning_path": mkaos_pack_metadata(mkaos_pack)["mkaos_runtime_policy_warning_path"],
                "model_output": generated,
                "production_execution": candidate.evidence.to_dict(),
                "agent_run_path": run.path,
                "copyright_boundary": generated.get("copyright_boundary")
                or "outline generated from project profiles and abstract references; no protected expression copied",
            },
            metadata={
                "model": model_name,
                "provider": str(generated.get("provider", model_name)),
                "agent_run_path": run.path,
                "prompt_version": PROMPT_VERSION,
                "source_asset_path": source_ref,
                "context_bundle_id": mkaos_pack.get("context_bundle", {}).get("asset", {}).get("id", ""),
                "context_bundle_path": mkaos_pack.get("context_bundle_path", ""),
                **knowledge_context_contract_metadata(knowledge_contract),
                "context_builder_unified": bool(mkaos_pack.get("context_bundle_path", "")),
                "mkaos_knowledge_pack_id": mkaos_pack.get("asset", {}).get("id", ""),
                "mkaos_knowledge_pack_path": mkaos_pack.get("path", ""),
                "mkaos_warning": mkaos_pack.get("warning", ""),
                **mkaos_pack_metadata(mkaos_pack),
                **planning_context_metadata(planning_context),
                "run_metadata": run_metadata(
                    "generate-outline",
                    character,
                    provider=str(generated.get("provider", model_name)),
                    model=str(generated.get("model", model_name)),
                    prompt_version=PROMPT_VERSION,
                ),
            },
            references=filter_project_safe_references(
                storage,
                project_id,
                _dedupe([character.id, source_ref, workspace, mkaos_pack.get("path", ""), mkaos_pack.get("asset", {}).get("id", ""), mkaos_pack.get("context_bundle_path", ""), mkaos_pack.get("context_bundle", {}).get("asset", {}).get("id", ""), *planning_context.get("references", [])]),
            ),
        )
        run.guard("write_outline", "outline")
        path = storage.write_asset("outlines", asset)
        final_governance = record_model_operation_final_governance(
            storage,
            operation="generate-outline",
            environment=environment,
            output_asset_id=asset.id,
            output_asset_path=path,
            project_id=project_id,
            workspace_path=workspace,
            source_policy=source_policy,
            os_envelope=os_envelope,
            provider_runtime_gate=provider_runtime_gate,
            preflight_governance=preflight,
            context_bundle_path=str(mkaos_pack.get("context_bundle_path") or ""),
            require_context_bundle=True,
            extra_gate_statuses={"content_intelligence": content_intelligence},
            extra_required_gates=["content_intelligence"],
        )
        attach_model_operation_governance(storage, path, final_governance)
        _record_mkaos_usage(storage, mkaos_pack, flow="outline", target_asset_id=asset.id, agent_name="OutlineAgent")
        run.guard("write_outline_version", "outline_version")
        version = create_outline_version(storage, path, change_summary="model-driven outline from project planning context")
        run.succeed(output_assets=[_display_path(storage.root, path), version["path"]], token_used=len(json.dumps(packet, ensure_ascii=False)))
        return path


def _outline_packet(
    generated: dict[str, Any],
    source_asset: dict[str, Any],
    planning_context: dict[str, Any],
    *,
    model_name: str,
) -> dict[str, Any]:
    text = str(generated.get("text", "")).strip()
    if model_name != "mock-model":
        packet = _parse_json_payload(text)
        return _normalize_outline_packet(packet, planning_context)
    try:
        return _normalize_outline_packet(_parse_json_payload(text), planning_context)
    except ModelOutputValidationError:
        return _fallback_outline_packet(source_asset, planning_context)


def _normalize_outline_packet(packet: dict[str, Any], planning_context: dict[str, Any]) -> dict[str, Any]:
    acts = packet.get("acts")
    if not isinstance(acts, list) or not acts:
        raise ModelOutputValidationError("outline JSON must contain a non-empty acts list")
    normalized_acts = []
    for index, item in enumerate(acts, start=1):
        if not isinstance(item, dict):
            raise ModelOutputValidationError(f"outline acts[{index - 1}] must be an object")
        chapters = item.get("chapters", [])
        normalized_acts.append(
            {
                "act": _int(item.get("act"), index),
                "goal": _required_text(item, "goal", f"act {index} goal"),
                "turn": _required_text(item, "turn", f"act {index} turn"),
                "chapters": _chapter_rows(chapters),
            }
        )
    quality_targets = _strings(packet.get("quality_targets")) or planning_context.get("quality_standard", {}).get("dimensions", [])
    creative_strategy = planning_context.get("creative_strategy", {}) if isinstance(planning_context.get("creative_strategy", {}), dict) else {}
    strategy_content = creative_strategy.get("content", {}) if isinstance(creative_strategy.get("content", {}), dict) else {}
    platform_strategy = planning_context.get("platform_strategy", {}).get("content", {}) if isinstance(planning_context.get("platform_strategy", {}), dict) else {}
    outline_strategy = platform_strategy.get("outline_strategy", {}) if isinstance(platform_strategy.get("outline_strategy", {}), dict) else {}
    chapter_strategy = platform_strategy.get("chapter_strategy", {}) if isinstance(platform_strategy.get("chapter_strategy", {}), dict) else {}
    platform_constraints = _dedupe([*_strings(outline_strategy.get("opening_requirements")), *_strings(outline_strategy.get("risk_controls"))])
    return {
        "title": str(packet.get("title") or "Project outline").strip(),
        "reader_promise": str(packet.get("reader_promise") or "").strip(),
        "conflict_engine": str(packet.get("conflict_engine") or "").strip(),
        "acts": normalized_acts,
        "quality_targets": _dedupe([str(item) for item in quality_targets if str(item).strip()]),
        "creative_strategy_constraints": _strings(packet.get("creative_strategy_constraints")) or _dedupe([*creative_strategy.get("constraints", []), *[f"platform strategy: {item}" for item in platform_constraints[:8]]]),
        "volume_goals": _strings(packet.get("volume_goals")) or _strings(strategy_content.get("volume_goals")) or _strings(outline_strategy.get("volume_goals")),
        "pleasure_rhythm": _strings(packet.get("pleasure_rhythm")) or _strings(strategy_content.get("pleasure_rhythm")) or _strings(chapter_strategy.get("required_beats")),
        "long_hooks": _strings(packet.get("long_hooks")) or _strings(strategy_content.get("long_hooks")),
        "platform_pacing": _strings(packet.get("platform_pacing")) or _strings(strategy_content.get("platform_pacing")) or _strings(outline_strategy.get("pacing")) or _strings(chapter_strategy.get("beat_cadence")),
        "continuity_constraints": _strings(packet.get("continuity_constraints")) or planning_context.get("continuity", {}).get("constraints", []),
        "feedback_constraints": _strings(packet.get("feedback_constraints")) or planning_context.get("feedback", {}).get("constraints", []),
        "tags": _strings(packet.get("tags")),
    }


def _fallback_outline_packet(source_asset: dict[str, Any], planning_context: dict[str, Any]) -> dict[str, Any]:
    project = planning_context.get("project", {}) if isinstance(planning_context.get("project", {}), dict) else {}
    config = planning_context.get("project_config", {}) if isinstance(planning_context.get("project_config", {}), dict) else {}
    title = str(project.get("title") or source_asset.get("title") or "Project").strip()
    genre = str(config.get("genre") or "long-form fiction").strip()
    platform = str(config.get("target_platform") or "local publishing").strip()
    quality_targets = planning_context.get("quality_standard", {}).get("dimensions", []) or [
        "causal_chain",
        "chapter_hook",
        "originality_boundary",
    ]
    continuity_constraints = planning_context.get("continuity", {}).get("constraints", [])
    feedback_constraints = planning_context.get("feedback", {}).get("constraints", [])
    creative_strategy = planning_context.get("creative_strategy", {}) if isinstance(planning_context.get("creative_strategy", {}), dict) else {}
    strategy_content = creative_strategy.get("content", {}) if isinstance(creative_strategy.get("content", {}), dict) else {}
    strategy_constraints = creative_strategy.get("constraints", []) if isinstance(creative_strategy.get("constraints", []), list) else []
    platform_strategy = planning_context.get("platform_strategy", {}).get("content", {}) if isinstance(planning_context.get("platform_strategy", {}), dict) else {}
    outline_strategy = platform_strategy.get("outline_strategy", {}) if isinstance(platform_strategy.get("outline_strategy", {}), dict) else {}
    chapter_strategy = platform_strategy.get("chapter_strategy", {}) if isinstance(platform_strategy.get("chapter_strategy", {}), dict) else {}
    platform_constraints = _dedupe([*_strings(outline_strategy.get("opening_requirements")), *_strings(outline_strategy.get("risk_controls"))])
    return {
        "title": f"{title} long-form outline",
        "reader_promise": f"A {genre} story tuned for {platform}, driven by escalating choices and clear payoffs.",
        "conflict_engine": "Each major decision spends an existing resource, reveals a hidden cost, and opens the next obligation.",
        "acts": [
            {
                "act": 1,
                "goal": "establish the project promise, protagonist pressure, and the first irreversible choice",
                "turn": "the opening mystery becomes a concrete obligation with social or survival cost",
                "chapters": [
                    {"chapter": 1, "promise": "open the core hook with a visible pressure point", "hook": "the first clue points to a larger system"},
                    {"chapter": 2, "promise": "convert curiosity into personal stakes", "hook": "the protagonist's safe option closes"},
                ],
            },
            {
                "act": 2,
                "goal": "expand allies, rivals, rules, and escalating costs without breaking continuity",
                "turn": "the protagonist wins a tactical result but exposes a deeper structural threat",
                "chapters": [
                    {"chapter": 3, "promise": "test the first rule under pressure", "hook": "a previous assumption is inverted"},
                    {"chapter": 4, "promise": "raise the cost through relationship and resource pressure", "hook": "a hidden stakeholder acts"},
                ],
            },
            {
                "act": 3,
                "goal": "force payoffs, resolve the central obligation, and seed the next volume-level question",
                "turn": "the final choice preserves the core promise while changing the project status quo",
                "chapters": [
                    {"chapter": 5, "promise": "pay off a planted clue through action", "hook": "the final confrontation demands sacrifice"},
                    {"chapter": 6, "promise": "close the arc with consequences", "hook": "one unresolved thread points forward"},
                ],
            },
        ],
        "quality_targets": quality_targets,
        "creative_strategy_constraints": _dedupe([*strategy_constraints, *[f"platform strategy: {item}" for item in platform_constraints[:8]]]),
        "volume_goals": _strings(strategy_content.get("volume_goals")) or _strings(outline_strategy.get("volume_goals")) or ["establish the first volume promise and payoff ladder"],
        "pleasure_rhythm": _strings(strategy_content.get("pleasure_rhythm")) or _strings(chapter_strategy.get("required_beats")) or ["hook -> pressure -> choice -> cost -> payoff -> next hook"],
        "long_hooks": _strings(strategy_content.get("long_hooks")) or ["seed one long hook and one relationship pressure"],
        "platform_pacing": _strings(strategy_content.get("platform_pacing")) or _strings(outline_strategy.get("pacing")) or _strings(chapter_strategy.get("beat_cadence")) or ["front-load conflict in first 3 chapters"],
        "continuity_constraints": continuity_constraints,
        "feedback_constraints": feedback_constraints,
        "tags": ["deterministic-fallback"],
    }


def _parse_json_payload(text: str) -> dict[str, Any]:
    try:
        return parse_json_object(text)
    except ModelOutputValidationError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return parse_json_object(text[start : end + 1])
        raise


def _chapter_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "chapter": _int(item.get("chapter"), index),
                "promise": str(item.get("promise") or item.get("objective") or "").strip(),
                "hook": str(item.get("hook") or "").strip(),
            }
        )
    return rows


def _required_text(item: dict[str, Any], key: str, fallback: str) -> str:
    value = str(item.get(key) or "").strip()
    return value or fallback


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _build_mkaos_pack(
    storage: LocalStorage,
    *,
    target_path: str | Path,
    flow: str,
    project_id: str,
    workspace_path: str,
    genre: str,
    platform: str,
    current_goal: str,
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_mkaos_flow_context_with_policy(
        storage,
        flow=flow,
        project_id=project_id or "local-system",
        workspace_path=workspace_path,
        target_path=target_path,
        environment=environment,
        builder=lambda: _pack_from_flow_context(
            build_flow_context_bundle(
                storage,
                target_path,
                flow=flow,
                project_id=project_id or "local-system",
                workspace_path=workspace_path,
                genre=genre,
                platform=platform,
                current_goal=current_goal,
                query=current_goal,
                token_budget=5000,
                source_policy=source_policy,
                environment=environment,
                os_envelope=os_envelope,
            )
        ),
    )


def _pack_from_flow_context(flow_context: dict[str, Any]) -> dict[str, Any]:
    pack = flow_context["mkaos_pack"]
    return {**pack, "context_bundle": flow_context["context_bundle"], "context_bundle_path": flow_context["path"], "context_plan": flow_context["context_plan"]}


def _pack_content(pack: dict[str, Any]) -> dict[str, Any]:
    asset = pack.get("asset", {}) if isinstance(pack.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return content


def _context_bundle_content(pack: dict[str, Any]) -> dict[str, Any]:
    bundle = pack.get("context_bundle", {}) if isinstance(pack.get("context_bundle", {}), dict) else {}
    asset = bundle.get("asset", {}) if isinstance(bundle.get("asset", {}), dict) else {}
    return asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}


def _record_mkaos_usage(storage: LocalStorage, pack: dict[str, Any], *, flow: str, target_asset_id: str, agent_name: str) -> None:
    try:
        record_pack_usage_for_artifact(storage, pack, flow=flow, target_artifact_id=target_asset_id, agent_name=agent_name, used_as="planning_constraint")
    except Exception:
        return
