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
from novel_forge.modules.production_chain import create_chapter_plan_version
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.production_execution import (
    CandidateKind,
    DomainExecutionPort,
    execute_domain_candidate,
    execution_model_name,
)
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage

PROMPT_VERSION = "chapter-plan-v2-project-context"
CHAPTER_BLUEPRINT_CONTRACT_VERSION = "chapter-blueprint-contract-v1"


def generate_chapter_plan(
    storage: LocalStorage,
    input_path: str | None = None,
    model: object | None = None,
    *,
    execution_port: DomainExecutionPort | None = None,
    workspace_path: str | None = None,
    chapter: int | None = None,
    carry_forward: dict[str, Any] | None = None,
    environment: str = "",
    os_envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
    provider_runtime_gate: dict[str, Any] | None = None,
) -> Path:
    model_name = execution_model_name(
        execution_port, model, legacy_model_role="chapter_plan"
    )
    outline_path = resolve_path(storage.root, input_path) if input_path else storage.latest("outlines")
    outline = storage.read_asset(outline_path)
    outline_ref = _display_path(storage.root, outline_path)
    target_chapter = _positive_chapter(chapter or _next_chapter_number(storage, outline.id))
    planning_context = build_planning_context(storage, outline, input_path=outline_path, workspace_path=workspace_path, chapter=target_chapter)
    production_context = planning_context["production_context"]
    project_id = str(production_context.get("project", {}).get("project_id", ""))
    workspace = str(production_context.get("project", {}).get("workspace_path", ""))
    project_config = production_context.get("project_config", {}) if isinstance(production_context.get("project_config", {}), dict) else {}
    mkaos_pack = _build_mkaos_pack(
        storage,
        target_path=outline_path,
        flow="chapter_outline",
        project_id=project_id,
        workspace_path=workspace,
        genre=str(project_config.get("genre") or ""),
        platform=str(project_config.get("target_platform") or ""),
        chapter_id=str(target_chapter),
        current_goal=f"chapter {target_chapter} plan",
        environment=environment,
        os_envelope=os_envelope,
        source_policy=source_policy,
    )
    knowledge_contract = knowledge_context_contract_from_pack(mkaos_pack)
    content_intelligence = content_intelligence_preflight_gate(
        storage,
        target_asset_id=outline.id,
        target_asset_path=outline_path,
        project_id=project_id,
        workspace_path=workspace,
        required=is_production_environment(environment or (os_envelope or {}).get("environment")),
    )
    preflight = enforce_model_operation_preflight(
        storage,
        operation="generate-chapter-plan",
        environment=environment,
        target_asset_id=outline.id,
        target_asset_path=outline_path,
        project_id=project_id,
        workspace_path=workspace,
        asset_type="chapter_plan",
        task_type="generate-chapter-plan",
        os_envelope=os_envelope,
        source_policy=source_policy,
        provider_runtime_gate=provider_runtime_gate,
        context_bundle_path=str(mkaos_pack.get("context_bundle_path") or ""),
        require_context_bundle=True,
        extra_gate_statuses={"content_intelligence": content_intelligence},
        extra_required_gates=["content_intelligence"],
    )
    carry = carry_forward or {}
    with AgentExecutionContext(
        storage,
        agent_key="chapter_plan",
        operation="generate-chapter-plan",
        input_assets=_dedupe([outline_ref, *planning_context.get("references", []), str(carry.get("previous_draft_path", "")), str(carry.get("previous_plan_path", ""))]),
        output_types=["chapter_plan", "chapter_plan_version"],
        model_provider=model_name,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
        token_budget=2600,
        sla_seconds=600,
        workspace_path=workspace,
        knowledge_context_contract=knowledge_contract,
    ) as run:
        run.guard("read_asset")
        candidate = execute_domain_candidate(
            capability="planning.chapter.generate",
            operation="generate",
            candidate_kind=CandidateKind.GENERATION,
            prompt="Generate a chapter plan for the target chapter. Return JSON only.",
            context={
                    "required_output": {
                        "chapter": target_chapter,
                        "objective": "string",
                        "beats": ["string"],
                        "hook": "string",
                        "word_budget": {"target": 2500, "min": 1800, "max": 3200},
                        "conflict": "string",
                        "scene_beats": [
                            {
                                "scene_goal": "string",
                                "protagonist_action": "string",
                                "conflict_pressure": "string",
                                "turn": "string",
                                "payoff": "string",
                                "exit_hook": "string",
                            }
                        ],
                        "conflict_beats": [
                            {
                                "pressure": "string",
                                "choice": "string",
                                "cost": "string",
                                "reversal": "string",
                            }
                        ],
                        "information_points": ["string"],
                        "info_release_points": [
                            {
                                "point": "string",
                                "timing": "opening|middle|late|ending",
                                "purpose": "string",
                                "withheld": "string",
                            }
                        ],
                        "hook_plan": {
                            "opening_hook": "string",
                            "closing_hook": "string",
                            "long_hook_link": "string",
                            "next_chapter_question": "string",
                        },
                        "emotion_curve": [{"position": "opening|build|turn|ending", "target_emotion": "string", "pressure_level": 1}],
                        "payoff_target": {"local_payoff": "string", "promise_payoff": "string", "withheld_question": "string"},
                        "quality_targets": ["string"],
                        "reader_promise": "string",
                        "volume_goal": "string",
                        "pleasure_beats": ["string"],
                        "long_hook_progress": ["string"],
                        "platform_pacing": ["string"],
                        "creative_strategy_constraints": ["string"],
                        "continuity_checks": ["string"],
                        "feedback_constraints": ["string"],
                        "risk_controls": ["string"],
                    },
                    "outline": outline.to_dict(),
                    "target_chapter": target_chapter,
                    "carry_forward": carry,
                    "planning_context": planning_context,
                    "context_bundle": _context_bundle_content(mkaos_pack),
                    "mkaos_knowledge_pack": _pack_content(mkaos_pack),
                    "copyright_boundary": "Use references as abstract constraints only. Do not copy protected scenes, names, settings, or prose.",
            },
            execution_port=execution_port,
            legacy_model=model,
            legacy_model_role="chapter_plan",
            environment=environment,
            storage=storage,
            agent_run_path=run.path,
        )
        generated = dict(candidate.raw_output)
        model_name = candidate.evidence.model_id or model_name
        packet = _chapter_plan_packet(
            generated,
            outline.to_dict(),
            planning_context,
            target_chapter=target_chapter,
            carry_forward=carry,
            model_name=model_name,
        )
        asset = ChapterPlan(
            title=str(packet.get("title") or f"Chapter {target_chapter} plan"),
            source=outline.id,
            tags=_dedupe(["chapter-plan", f"chapter-{target_chapter}", "model-driven", "project-context", *packet.get("tags", [])]),
            content={
                "chapter": target_chapter,
                "objective": packet["objective"],
                "beats": packet["beats"],
                "hook": packet["hook"],
                "word_budget": packet["word_budget"],
                "conflict": packet.get("conflict", ""),
                "scene_beats": packet.get("scene_beats", []),
                "conflict_beats": packet.get("conflict_beats", []),
                "information_points": packet.get("information_points", []),
                "info_release_points": packet.get("info_release_points", []),
                "hook_plan": packet.get("hook_plan", {}),
                "emotion_curve": packet.get("emotion_curve", []),
                "payoff_target": packet.get("payoff_target", {}),
                "chapter_blueprint_contract": packet.get("chapter_blueprint_contract", {}),
                "blueprint_quality_gate": packet.get("blueprint_quality_gate", {}),
                "quality_targets": packet.get("quality_targets", []),
                "reader_promise": packet.get("reader_promise", ""),
                "volume_goal": packet.get("volume_goal", ""),
                "pleasure_beats": packet.get("pleasure_beats", []),
                "long_hook_progress": packet.get("long_hook_progress", []),
                "platform_pacing": packet.get("platform_pacing", []),
                "creative_strategy_constraints": packet.get("creative_strategy_constraints", []),
                "continuity_checks": packet.get("continuity_checks", []),
                "feedback_constraints": packet.get("feedback_constraints", []),
                "risk_controls": packet.get("risk_controls", []),
                "carry_forward": carry,
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
                or "chapter plan generated from project profiles and abstract references; no protected expression copied",
            },
            metadata={
                "project_id": project_id,
                "workspace_path": workspace,
                "model": model_name,
                "provider": str(generated.get("provider", model_name)),
                "agent_run_path": run.path,
                "prompt_version": PROMPT_VERSION,
                "source_asset_path": outline_ref,
                "chapter": target_chapter,
                "chapter_blueprint_contract_version": CHAPTER_BLUEPRINT_CONTRACT_VERSION,
                "chapter_blueprint_gate_status": packet.get("blueprint_quality_gate", {}).get("status", ""),
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
                    "generate-chapter-plan",
                    outline,
                    provider=str(generated.get("provider", model_name)),
                    model=str(generated.get("model", model_name)),
                    prompt_version=PROMPT_VERSION,
                ),
            },
            references=filter_project_safe_references(
                storage,
                project_id,
                _dedupe([outline.id, outline_ref, workspace, mkaos_pack.get("path", ""), mkaos_pack.get("asset", {}).get("id", ""), mkaos_pack.get("context_bundle_path", ""), mkaos_pack.get("context_bundle", {}).get("asset", {}).get("id", ""), str(carry.get("previous_draft_id", "")), str(carry.get("previous_draft_path", "")), *planning_context.get("references", [])]),
            ),
        )
        run.guard("write_chapter_plan", "chapter_plan")
        path = storage.write_asset("chapter_plans", asset)
        final_governance = record_model_operation_final_governance(
            storage,
            operation="generate-chapter-plan",
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
        _record_mkaos_usage(storage, mkaos_pack, flow="chapter_outline", target_asset_id=asset.id, chapter_id=str(target_chapter), agent_name="ChapterOutlineAgent")
        run.guard("write_chapter_plan_version", "chapter_plan_version")
        version = create_chapter_plan_version(storage, path, change_summary="model-driven chapter plan from project planning context")
        run.succeed(output_assets=[_display_path(storage.root, path), version["path"]], token_used=len(json.dumps(packet, ensure_ascii=False)))
        return path


def _chapter_plan_packet(
    generated: dict[str, Any],
    outline: dict[str, Any],
    planning_context: dict[str, Any],
    *,
    target_chapter: int,
    carry_forward: dict[str, Any],
    model_name: str,
) -> dict[str, Any]:
    text = str(generated.get("text", "")).strip()
    if model_name != "mock-model":
        packet = _parse_json_payload(text)
        return _normalize_chapter_plan_packet(packet, planning_context, target_chapter=target_chapter)
    try:
        return _normalize_chapter_plan_packet(_parse_json_payload(text), planning_context, target_chapter=target_chapter)
    except ModelOutputValidationError:
        return _fallback_chapter_plan_packet(outline, planning_context, target_chapter=target_chapter, carry_forward=carry_forward)


def _normalize_chapter_plan_packet(packet: dict[str, Any], planning_context: dict[str, Any], *, target_chapter: int) -> dict[str, Any]:
    beats = _strings(packet.get("beats"))
    if not beats:
        raise ModelOutputValidationError("chapter plan JSON must contain non-empty beats")
    objective = str(packet.get("objective") or "").strip()
    hook = str(packet.get("hook") or "").strip()
    if not objective or not hook:
        raise ModelOutputValidationError("chapter plan JSON must contain objective and hook")
    quality_targets = _strings(packet.get("quality_targets")) or planning_context.get("quality_standard", {}).get("dimensions", [])
    creative_strategy = planning_context.get("creative_strategy", {}) if isinstance(planning_context.get("creative_strategy", {}), dict) else {}
    strategy_content = creative_strategy.get("content", {}) if isinstance(creative_strategy.get("content", {}), dict) else {}
    strategy_constraints = creative_strategy.get("constraints", []) if isinstance(creative_strategy.get("constraints", []), list) else []
    platform_strategy = planning_context.get("platform_strategy", {}).get("content", {}) if isinstance(planning_context.get("platform_strategy", {}), dict) else {}
    chapter_strategy = platform_strategy.get("chapter_strategy", {}) if isinstance(platform_strategy.get("chapter_strategy", {}), dict) else {}
    validation_policy = platform_strategy.get("validation_policy", {}) if isinstance(platform_strategy.get("validation_policy", {}), dict) else {}
    platform_constraints = _dedupe([*_strings(chapter_strategy.get("required_beats")), *_strings(validation_policy.get("blocking_if_missing"))])
    continuity_checks = _strings(packet.get("continuity_checks")) or planning_context.get("continuity", {}).get("constraints", [])
    feedback_constraints = _strings(packet.get("feedback_constraints")) or planning_context.get("feedback", {}).get("constraints", [])
    risk_controls = _dedupe(
        [
            *_strings(packet.get("risk_controls")),
            *[f"creative strategy: {item}" for item in strategy_constraints[:8]],
            *[f"platform strategy: {item}" for item in platform_constraints[:8]],
        ]
    )
    normalized = {
        "title": str(packet.get("title") or f"Chapter {target_chapter} plan").strip(),
        "objective": objective,
        "beats": beats,
        "hook": hook,
        "word_budget": _word_budget(packet.get("word_budget"), planning_context),
        "conflict": str(packet.get("conflict") or "").strip(),
        "information_points": _strings(packet.get("information_points")),
        "quality_targets": _dedupe([str(item) for item in quality_targets if str(item).strip()]),
        "reader_promise": str(packet.get("reader_promise") or strategy_content.get("reader_promise") or "").strip(),
        "volume_goal": str(packet.get("volume_goal") or _first_strategy_value(strategy_content.get("volume_goals")) or "").strip(),
        "pleasure_beats": _strings(packet.get("pleasure_beats")) or _strings(strategy_content.get("pleasure_rhythm")) or _strings(chapter_strategy.get("required_beats")),
        "long_hook_progress": _strings(packet.get("long_hook_progress")) or _strings(strategy_content.get("long_hooks")),
        "platform_pacing": _strings(packet.get("platform_pacing")) or _strings(strategy_content.get("platform_pacing")) or _strings(chapter_strategy.get("beat_cadence")),
        "creative_strategy_constraints": _dedupe([str(item) for item in strategy_constraints if str(item).strip()]),
        "continuity_checks": _dedupe([str(item) for item in continuity_checks if str(item).strip()]),
        "feedback_constraints": _dedupe([str(item) for item in feedback_constraints if str(item).strip()]),
        "risk_controls": risk_controls,
        "tags": _strings(packet.get("tags")),
    }
    normalized.update(_chapter_blueprint_payload(packet, normalized, planning_context, target_chapter=target_chapter))
    return normalized


def _fallback_chapter_plan_packet(
    outline: dict[str, Any],
    planning_context: dict[str, Any],
    *,
    target_chapter: int,
    carry_forward: dict[str, Any],
) -> dict[str, Any]:
    quality_targets = planning_context.get("quality_standard", {}).get("dimensions", []) or [
        "causal_chain",
        "chapter_hook",
        "originality_boundary",
    ]
    continuity_checks = planning_context.get("continuity", {}).get("constraints", [])
    feedback_constraints = planning_context.get("feedback", {}).get("constraints", [])
    creative_strategy = planning_context.get("creative_strategy", {}) if isinstance(planning_context.get("creative_strategy", {}), dict) else {}
    strategy_content = creative_strategy.get("content", {}) if isinstance(creative_strategy.get("content", {}), dict) else {}
    strategy_constraints = creative_strategy.get("constraints", []) if isinstance(creative_strategy.get("constraints", []), list) else []
    platform_strategy = planning_context.get("platform_strategy", {}).get("content", {}) if isinstance(planning_context.get("platform_strategy", {}), dict) else {}
    chapter_strategy = platform_strategy.get("chapter_strategy", {}) if isinstance(platform_strategy.get("chapter_strategy", {}), dict) else {}
    validation_policy = platform_strategy.get("validation_policy", {}) if isinstance(platform_strategy.get("validation_policy", {}), dict) else {}
    platform_constraints = _dedupe([*_strings(chapter_strategy.get("required_beats")), *_strings(validation_policy.get("blocking_if_missing"))])
    act = _act_for_chapter(outline, target_chapter)
    carry_hook = str(carry_forward.get("previous_hook", "") or "").strip()
    reader_promise = str(strategy_content.get("reader_promise") or "deliver a clear genre promise with visible pressure, payoff, and next-hook momentum")
    volume_goal = _first_strategy_value(strategy_content.get("volume_goals")) or "advance the current volume promise without losing long-form continuity"
    objective = (
        f"advance chapter {target_chapter} from the outline goal: {act.get('goal') or 'maintain forward momentum'}"
        if target_chapter == 1
        else f"resolve the previous chapter consequence and advance chapter {target_chapter} toward: {act.get('goal') or 'the next obligation'}"
    )
    beats = [
        carry_hook or "open with a concrete pressure point connected to the outline promise",
        "make the protagonist choose between two visible costs",
        "pay off one small setup while planting one higher-order question",
        "close on a hook that changes the next chapter's immediate objective",
    ]
    normalized = {
        "title": f"Chapter {target_chapter} plan",
        "objective": objective,
        "beats": beats,
        "hook": carry_hook or str(act.get("turn") or "a new consequence makes the next action unavoidable"),
        "word_budget": _word_budget(None, planning_context),
        "conflict": "the protagonist's safest option becomes more expensive than action",
        "information_points": _dedupe([
            "preserve project continuity",
            "avoid repeating prior chapter prose",
            "make the causal chain explicit",
            f"reader promise: {reader_promise}",
            f"volume goal: {volume_goal}",
            *continuity_checks[:3],
        ]),
        "quality_targets": quality_targets,
        "reader_promise": reader_promise,
        "volume_goal": volume_goal,
        "pleasure_beats": _strings(strategy_content.get("pleasure_rhythm")) or _strings(chapter_strategy.get("required_beats")) or [
            "open pressure",
            "visible choice",
            "cost disclosure",
            "partial payoff",
            "next hook",
        ],
        "long_hook_progress": _strings(strategy_content.get("long_hooks")) or ["seed or advance one long hook without premature payoff"],
        "platform_pacing": _strings(strategy_content.get("platform_pacing")) or _strings(chapter_strategy.get("beat_cadence")) or ["keep chapter objective and hook visible"],
        "creative_strategy_constraints": _dedupe([str(item) for item in [*strategy_constraints, *[f"platform strategy: {item}" for item in platform_constraints[:8]]] if str(item).strip()]),
        "continuity_checks": continuity_checks,
        "feedback_constraints": feedback_constraints,
        "risk_controls": [
            "do not copy protected source expression",
            "do not bypass project quality standard",
            "do not contradict continuity bible",
            *[f"creative strategy: {item}" for item in strategy_constraints[:8]],
            *[f"platform strategy: {item}" for item in platform_constraints[:8]],
        ],
        "tags": ["deterministic-fallback"],
    }
    normalized.update(_chapter_blueprint_payload({}, normalized, planning_context, target_chapter=target_chapter))
    return normalized


def _chapter_blueprint_payload(
    packet: dict[str, Any],
    normalized: dict[str, Any],
    planning_context: dict[str, Any],
    *,
    target_chapter: int,
) -> dict[str, Any]:
    objective = str(normalized.get("objective", "")).strip()
    beats = _strings(normalized.get("beats"))
    conflict = str(normalized.get("conflict", "") or "the protagonist must act under visible pressure").strip()
    hook = str(normalized.get("hook", "") or "the next action becomes unavoidable").strip()
    information_points = _strings(normalized.get("information_points"))
    reader_promise = str(normalized.get("reader_promise", "") or "deliver a clear chapter promise").strip()
    pleasure_beats = _strings(normalized.get("pleasure_beats"))
    long_hook_progress = _strings(normalized.get("long_hook_progress"))
    scene_beats = _normalize_scene_beats(packet.get("scene_beats"), beats, objective=objective, conflict=conflict, hook=hook, information_points=information_points)
    conflict_beats = _normalize_conflict_beats(packet.get("conflict_beats"), scene_beats, conflict=conflict)
    info_release_points = _normalize_info_release_points(packet.get("info_release_points"), information_points)
    hook_plan = _normalize_hook_plan(
        packet.get("hook_plan"),
        objective=objective,
        hook=hook,
        reader_promise=reader_promise,
        long_hook_progress=long_hook_progress,
        carry_context=planning_context,
    )
    emotion_curve = _normalize_emotion_curve(packet.get("emotion_curve"), scene_beats, conflict=conflict)
    payoff_target = _normalize_payoff_target(packet.get("payoff_target"), reader_promise=reader_promise, pleasure_beats=pleasure_beats, hook_plan=hook_plan)
    quality_gate = _blueprint_quality_gate(
        scene_beats=scene_beats,
        conflict_beats=conflict_beats,
        info_release_points=info_release_points,
        hook_plan=hook_plan,
        emotion_curve=emotion_curve,
        payoff_target=payoff_target,
    )
    contract = {
        "contract_version": CHAPTER_BLUEPRINT_CONTRACT_VERSION,
        "chapter": target_chapter,
        "required_fields": [
            "scene_beats",
            "conflict_beats",
            "info_release_points",
            "hook_plan",
            "emotion_curve",
            "payoff_target",
        ],
        "present_fields": [field for field in ["scene_beats", "conflict_beats", "info_release_points", "hook_plan", "emotion_curve", "payoff_target"] if quality_gate["field_status"].get(field) == "present"],
        "status": quality_gate["status"],
        "risk_controls": normalized.get("risk_controls", []),
        "drafting_contract": "drafting must treat this as scene execution guidance, not as final prose",
    }
    return {
        "scene_beats": scene_beats,
        "conflict_beats": conflict_beats,
        "info_release_points": info_release_points,
        "hook_plan": hook_plan,
        "emotion_curve": emotion_curve,
        "payoff_target": payoff_target,
        "chapter_blueprint_contract": contract,
        "blueprint_quality_gate": quality_gate,
    }


def _normalize_scene_beats(value: Any, beats: list[str], *, objective: str, conflict: str, hook: str, information_points: list[str]) -> list[dict[str, Any]]:
    rows = _dict_rows(value)
    if not rows:
        seed_beats = beats or [objective, conflict, hook]
        rows = []
        for index, beat in enumerate(seed_beats[:5], start=1):
            info = information_points[min(index - 1, len(information_points) - 1)] if information_points else ""
            rows.append(
                {
                    "scene_goal": str(beat),
                    "protagonist_action": _derive_action(str(beat), objective),
                    "conflict_pressure": conflict if index == 1 else f"{conflict}; complication {index}",
                    "turn": _derive_turn(str(beat), index),
                    "payoff": info or f"beat {index} changes the immediate objective",
                    "exit_hook": hook if index == len(seed_beats[:5]) else f"new cost after beat {index}",
                }
            )
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:6], start=1):
        scene_goal = str(row.get("scene_goal") or row.get("goal") or row.get("beat") or (beats[index - 1] if index - 1 < len(beats) else objective)).strip()
        normalized.append(
            {
                "beat_id": str(row.get("beat_id") or f"scene-{index}"),
                "order": index,
                "scene_goal": scene_goal,
                "protagonist_action": str(row.get("protagonist_action") or row.get("action") or _derive_action(scene_goal, objective)).strip(),
                "conflict_pressure": str(row.get("conflict_pressure") or row.get("pressure") or conflict).strip(),
                "turn": str(row.get("turn") or _derive_turn(scene_goal, index)).strip(),
                "payoff": str(row.get("payoff") or row.get("result") or "the scene changes what the protagonist can do next").strip(),
                "exit_hook": str(row.get("exit_hook") or row.get("hook") or hook).strip(),
                "required_context": _strings(row.get("required_context"))[:6],
            }
        )
    return normalized


def _normalize_conflict_beats(value: Any, scene_beats: list[dict[str, Any]], *, conflict: str) -> list[dict[str, Any]]:
    rows = _dict_rows(value)
    if not rows:
        rows = [
            {
                "pressure": scene.get("conflict_pressure", conflict),
                "choice": scene.get("protagonist_action", ""),
                "cost": scene.get("turn", ""),
                "reversal": scene.get("exit_hook", ""),
            }
            for scene in scene_beats[:4]
        ]
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:6], start=1):
        normalized.append(
            {
                "beat_id": str(row.get("beat_id") or f"conflict-{index}"),
                "pressure": str(row.get("pressure") or conflict).strip(),
                "choice": str(row.get("choice") or row.get("decision") or "protagonist must choose an irreversible action").strip(),
                "cost": str(row.get("cost") or "the safe option becomes more expensive").strip(),
                "reversal": str(row.get("reversal") or row.get("turn") or "new information changes the route").strip(),
            }
        )
    return normalized


def _normalize_info_release_points(value: Any, information_points: list[str]) -> list[dict[str, Any]]:
    rows = _dict_rows(value)
    if not rows:
        timings = ["opening", "middle", "late", "ending"]
        rows = [{"point": item, "timing": timings[index % len(timings)], "purpose": "change a decision", "withheld": "full implication"} for index, item in enumerate(information_points[:5])]
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:6], start=1):
        normalized.append(
            {
                "point_id": str(row.get("point_id") or f"info-{index}"),
                "point": str(row.get("point") or row.get("information") or row.get("fact") or "").strip(),
                "timing": str(row.get("timing") or "middle").strip(),
                "purpose": str(row.get("purpose") or "change a character decision or reader expectation").strip(),
                "withheld": str(row.get("withheld") or row.get("withhold") or "the larger implication remains open").strip(),
            }
        )
    return [row for row in normalized if row["point"]]


def _normalize_hook_plan(value: Any, *, objective: str, hook: str, reader_promise: str, long_hook_progress: list[str], carry_context: dict[str, Any]) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    previous = carry_context.get("previous", {}) if isinstance(carry_context.get("previous", {}), dict) else {}
    return {
        "opening_hook": str(row.get("opening_hook") or previous.get("hook") or f"open with pressure tied to: {objective}").strip(),
        "midpoint_turn": str(row.get("midpoint_turn") or row.get("middle_hook") or "new evidence changes the cost of the objective").strip(),
        "closing_hook": str(row.get("closing_hook") or row.get("ending_hook") or hook).strip(),
        "long_hook_link": str(row.get("long_hook_link") or (long_hook_progress[0] if long_hook_progress else reader_promise)).strip(),
        "promise_advanced": str(row.get("promise_advanced") or reader_promise).strip(),
        "next_chapter_question": str(row.get("next_chapter_question") or f"what must change after: {hook}").strip(),
    }


def _normalize_emotion_curve(value: Any, scene_beats: list[dict[str, Any]], *, conflict: str) -> list[dict[str, Any]]:
    rows = _dict_rows(value)
    if not rows:
        defaults = [
            ("opening", "curiosity under pressure", 2),
            ("build", "concern and forward pull", 3),
            ("turn", "shock or narrowed options", 4),
            ("ending", "urgent anticipation", 5),
        ]
        rows = [{"position": position, "target_emotion": emotion, "pressure_level": level} for position, emotion, level in defaults]
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:6], start=1):
        normalized.append(
            {
                "position": str(row.get("position") or f"beat-{index}").strip(),
                "target_emotion": str(row.get("target_emotion") or row.get("emotion") or "focused tension").strip(),
                "pressure_level": _bounded_int(row.get("pressure_level") or row.get("intensity") or min(index + 1, 5), minimum=1, maximum=5),
                "cause": str(row.get("cause") or (scene_beats[index - 1].get("conflict_pressure", conflict) if index - 1 < len(scene_beats) else conflict)).strip(),
                "release": str(row.get("release") or "partial payoff before renewed pressure").strip(),
            }
        )
    return normalized


def _normalize_payoff_target(value: Any, *, reader_promise: str, pleasure_beats: list[str], hook_plan: dict[str, Any]) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "local_payoff": str(row.get("local_payoff") or row.get("payoff") or (pleasure_beats[-1] if pleasure_beats else "pay off one visible setup")).strip(),
        "promise_payoff": str(row.get("promise_payoff") or reader_promise).strip(),
        "withheld_question": str(row.get("withheld_question") or hook_plan.get("next_chapter_question") or "larger cause remains unresolved").strip(),
        "evidence_required": _strings(row.get("evidence_required")) or ["reader can identify what changed by the end of the chapter"],
    }


def _blueprint_quality_gate(
    *,
    scene_beats: list[dict[str, Any]],
    conflict_beats: list[dict[str, Any]],
    info_release_points: list[dict[str, Any]],
    hook_plan: dict[str, Any],
    emotion_curve: list[dict[str, Any]],
    payoff_target: dict[str, Any],
) -> dict[str, Any]:
    field_status = {
        "scene_beats": "present" if len(scene_beats) >= 3 else "weak" if scene_beats else "missing",
        "conflict_beats": "present" if conflict_beats else "missing",
        "info_release_points": "present" if info_release_points else "weak",
        "hook_plan": "present" if hook_plan.get("opening_hook") and hook_plan.get("closing_hook") else "missing",
        "emotion_curve": "present" if len(emotion_curve) >= 3 else "weak" if emotion_curve else "missing",
        "payoff_target": "present" if payoff_target.get("local_payoff") and payoff_target.get("withheld_question") else "missing",
    }
    blocking = [field for field, status in field_status.items() if status == "missing"]
    weak = [field for field, status in field_status.items() if status == "weak"]
    score = max(0, 100 - len(blocking) * 30 - len(weak) * 10)
    return {
        "gate_id": "chapter-blueprint-quality-v1",
        "status": "failed" if blocking else "warning" if weak else "passed",
        "score": score,
        "field_status": field_status,
        "blocking_issues": [f"missing {field}" for field in blocking],
        "warnings": [f"weak {field}" for field in weak],
        "recommendations": _dedupe([
            "ensure every scene beat changes character options",
            "make opening and closing hooks visible",
            "tie information release to decisions rather than exposition",
        ] if blocking or weak else ["chapter blueprint is ready for drafting"]),
    }


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                rows.append(dict(item))
            elif str(item).strip():
                rows.append({"beat": str(item).strip(), "point": str(item).strip()})
        return rows
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, str) and value.strip():
        return [{"beat": value.strip(), "point": value.strip()}]
    return []


def _derive_action(beat: str, objective: str) -> str:
    text = beat.strip() or objective.strip()
    if not text:
        return "take a visible action that changes the scene"
    return f"act on: {text[:120]}"


def _derive_turn(beat: str, index: int) -> str:
    text = beat.strip()
    if not text:
        return f"beat {index} reveals a new cost"
    return f"because of {text[:90]}, the next option becomes narrower"


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = minimum
    return min(max(number, minimum), maximum)


def _parse_json_payload(text: str) -> dict[str, Any]:
    try:
        return parse_json_object(text)
    except ModelOutputValidationError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return parse_json_object(text[start : end + 1])
        raise


def _act_for_chapter(outline: dict[str, Any], chapter: int) -> dict[str, Any]:
    content = outline.get("content", {}) if isinstance(outline.get("content", {}), dict) else {}
    acts = content.get("acts", []) if isinstance(content.get("acts", []), list) else []
    for act in acts:
        if not isinstance(act, dict):
            continue
        chapters = act.get("chapters", []) if isinstance(act.get("chapters", []), list) else []
        if any(isinstance(row, dict) and _positive_chapter(row.get("chapter")) == chapter for row in chapters):
            return act
    if acts:
        index = min(max(chapter - 1, 0), len(acts) - 1)
        return acts[index] if isinstance(acts[index], dict) else {}
    return {}


def _word_budget(value: Any, planning_context: dict[str, Any]) -> dict[str, int]:
    if isinstance(value, dict):
        return {
            "target": _positive_chapter(value.get("target") or 2500),
            "min": _positive_chapter(value.get("min") or 1800),
            "max": _positive_chapter(value.get("max") or 3200),
        }
    platform_strategy = planning_context.get("platform_strategy", {}).get("content", {}) if isinstance(planning_context.get("platform_strategy", {}), dict) else {}
    chapter_strategy = platform_strategy.get("chapter_strategy", {}) if isinstance(platform_strategy.get("chapter_strategy", {}), dict) else {}
    strategy_budget = chapter_strategy.get("word_budget", {}) if isinstance(chapter_strategy.get("word_budget", {}), dict) else {}
    if strategy_budget:
        target = _positive_chapter(strategy_budget.get("ideal") or strategy_budget.get("target") or 2500)
        return {
            "target": target,
            "min": _positive_chapter(strategy_budget.get("min") or int(target * 0.72)),
            "max": _positive_chapter(strategy_budget.get("max") or int(target * 1.28)),
        }
    platform = planning_context.get("profiles", {}).get("platform_profile", {}) if isinstance(planning_context.get("profiles", {}), dict) else {}
    content = platform.get("content", {}) if isinstance(platform.get("content", {}), dict) else {}
    chapter_length = content.get("chapter_length") if isinstance(content.get("chapter_length"), dict) else content.get("chapter_length_range") if isinstance(content.get("chapter_length_range"), dict) else {}
    target = _positive_chapter(chapter_length.get("target") or chapter_length.get("recommended") or 2500)
    return {
        "target": target,
        "min": _positive_chapter(chapter_length.get("min") or int(target * 0.72)),
        "max": _positive_chapter(chapter_length.get("max") or int(target * 1.28)),
    }


def _next_chapter_number(storage: LocalStorage, outline_id: str) -> int:
    chapters: list[int] = []
    for path in storage.list_json("chapter_plans"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "chapter_plan":
            continue
        if str(data.get("source", "")) != outline_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        chapters.append(_positive_chapter(content.get("chapter", 1)))
    return max(chapters, default=0) + 1


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        rows: list[str] = []
        for item in value:
            if isinstance(item, dict):
                rows.extend(_strings(item))
            elif str(item).strip():
                rows.append(str(item).strip())
        return rows
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items() if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _first_strategy_value(value: Any) -> str:
    if isinstance(value, dict):
        for item in value.values():
            text = str(item or "").strip()
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                text = " ".join(str(part or "").strip() for part in item.values() if str(part or "").strip())
            else:
                text = str(item or "").strip()
            if text:
                return text
    return str(value or "").strip()


def _positive_chapter(value: Any) -> int:
    try:
        number = int(value)
    except Exception:
        number = 1
    return max(number, 1)


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
    chapter_id: str,
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
                chapter_id=chapter_id,
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


def _record_mkaos_usage(storage: LocalStorage, pack: dict[str, Any], *, flow: str, target_asset_id: str, chapter_id: str, agent_name: str) -> None:
    try:
        record_pack_usage_for_artifact(
            storage,
            pack,
            flow=flow,
            target_artifact_id=target_asset_id,
            chapter_id=chapter_id,
            agent_name=agent_name,
            used_as="chapter_plan_constraint",
        )
    except Exception:
        return
