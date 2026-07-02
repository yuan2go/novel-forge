from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.model_adapters import (
    GuardedModelAdapter,
    ModelAdapter,
    ModelOutputValidationError,
    model_from_env,
    parse_json_object,
    validate_model_output,
)
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.mkaos import build_knowledge_pack, record_pack_usage_for_artifact
from novel_forge.modules.planning_context import build_planning_context, planning_context_metadata
from novel_forge.modules.production_chain import create_chapter_plan_version
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage

PROMPT_VERSION = "chapter-plan-v2-project-context"


def generate_chapter_plan(
    storage: LocalStorage,
    input_path: str | None = None,
    model: ModelAdapter | None = None,
    *,
    workspace_path: str | None = None,
    chapter: int | None = None,
    carry_forward: dict[str, Any] | None = None,
) -> Path:
    model = model or model_from_env("chapter_plan")
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
        flow="chapter_outline",
        project_id=project_id,
        workspace_path=workspace,
        genre=str(project_config.get("genre") or ""),
        platform=str(project_config.get("target_platform") or ""),
        chapter_id=str(target_chapter),
        current_goal=f"chapter {target_chapter} plan",
    )
    carry = carry_forward or {}
    with AgentExecutionContext(
        storage,
        agent_key="chapter_plan",
        operation="generate-chapter-plan",
        input_assets=_dedupe([outline_ref, *planning_context.get("references", []), str(carry.get("previous_draft_path", "")), str(carry.get("previous_plan_path", ""))]),
        output_types=["chapter_plan", "chapter_plan_version"],
        model_provider=getattr(model, "name", "local"),
        model_name=getattr(model, "name", "local"),
        prompt_version=PROMPT_VERSION,
        token_budget=2600,
        sla_seconds=600,
        workspace_path=workspace,
    ) as run:
        run.guard("read_asset")
        guarded_model = GuardedModelAdapter(model, storage, run.path)
        generated = validate_model_output(
            "generate",
            guarded_model.generate(
                "Generate a chapter plan for the target chapter. Return JSON only.",
                {
                    "required_output": {
                        "chapter": target_chapter,
                        "objective": "string",
                        "beats": ["string"],
                        "hook": "string",
                        "word_budget": {"target": 2500, "min": 1800, "max": 3200},
                        "conflict": "string",
                        "information_points": ["string"],
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
                    "mkaos_knowledge_pack": _pack_content(mkaos_pack),
                    "copyright_boundary": "Use references as abstract constraints only. Do not copy protected scenes, names, settings, or prose.",
                },
            ),
        )
        packet = _chapter_plan_packet(
            generated,
            outline.to_dict(),
            planning_context,
            target_chapter=target_chapter,
            carry_forward=carry,
            model_name=getattr(model, "name", ""),
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
                "information_points": packet.get("information_points", []),
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
                "mkaos_knowledge_pack": _pack_content(mkaos_pack),
                "mkaos_knowledge_pack_path": mkaos_pack.get("path", ""),
                "mkaos_knowledge_pack_warning": mkaos_pack.get("warning", ""),
                "model_output": generated,
                "agent_run_path": run.path,
                "copyright_boundary": generated.get("copyright_boundary")
                or "chapter plan generated from project profiles and abstract references; no protected expression copied",
            },
            metadata={
                "model": getattr(model, "name", "local"),
                "provider": str(generated.get("provider", getattr(model, "name", "local"))),
                "agent_run_path": run.path,
                "prompt_version": PROMPT_VERSION,
                "source_asset_path": outline_ref,
                "chapter": target_chapter,
                "mkaos_knowledge_pack_id": mkaos_pack.get("asset", {}).get("id", ""),
                "mkaos_knowledge_pack_path": mkaos_pack.get("path", ""),
                "mkaos_warning": mkaos_pack.get("warning", ""),
                **planning_context_metadata(planning_context),
                "run_metadata": run_metadata(
                    "generate-chapter-plan",
                    outline,
                    provider=str(generated.get("provider", getattr(model, "name", "local"))),
                    model=str(generated.get("model", getattr(model, "name", "local"))),
                    prompt_version=PROMPT_VERSION,
                ),
            },
            references=filter_project_safe_references(
                storage,
                project_id,
                _dedupe([outline.id, outline_ref, workspace, mkaos_pack.get("path", ""), mkaos_pack.get("asset", {}).get("id", ""), str(carry.get("previous_draft_id", "")), str(carry.get("previous_draft_path", "")), *planning_context.get("references", [])]),
            ),
        )
        run.guard("write_chapter_plan", "chapter_plan")
        path = storage.write_asset("chapter_plans", asset)
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
    continuity_checks = _strings(packet.get("continuity_checks")) or planning_context.get("continuity", {}).get("constraints", [])
    feedback_constraints = _strings(packet.get("feedback_constraints")) or planning_context.get("feedback", {}).get("constraints", [])
    risk_controls = _dedupe(
        [
            *_strings(packet.get("risk_controls")),
            *[f"creative strategy: {item}" for item in strategy_constraints[:8]],
        ]
    )
    return {
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
        "pleasure_beats": _strings(packet.get("pleasure_beats")) or _strings(strategy_content.get("pleasure_rhythm")),
        "long_hook_progress": _strings(packet.get("long_hook_progress")) or _strings(strategy_content.get("long_hooks")),
        "platform_pacing": _strings(packet.get("platform_pacing")) or _strings(strategy_content.get("platform_pacing")),
        "creative_strategy_constraints": _dedupe([str(item) for item in strategy_constraints if str(item).strip()]),
        "continuity_checks": _dedupe([str(item) for item in continuity_checks if str(item).strip()]),
        "feedback_constraints": _dedupe([str(item) for item in feedback_constraints if str(item).strip()]),
        "risk_controls": risk_controls,
        "tags": _strings(packet.get("tags")),
    }


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
    return {
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
        "pleasure_beats": _strings(strategy_content.get("pleasure_rhythm")) or [
            "open pressure",
            "visible choice",
            "cost disclosure",
            "partial payoff",
            "next hook",
        ],
        "long_hook_progress": _strings(strategy_content.get("long_hooks")) or ["seed or advance one long hook without premature payoff"],
        "platform_pacing": _strings(strategy_content.get("platform_pacing")) or ["keep chapter objective and hook visible"],
        "creative_strategy_constraints": _dedupe([str(item) for item in strategy_constraints if str(item).strip()]),
        "continuity_checks": continuity_checks,
        "feedback_constraints": feedback_constraints,
        "risk_controls": [
            "do not copy protected source expression",
            "do not bypass project quality standard",
            "do not contradict continuity bible",
            *[f"creative strategy: {item}" for item in strategy_constraints[:8]],
        ],
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
    platform = planning_context.get("profiles", {}).get("platform_profile", {}) if isinstance(planning_context.get("profiles", {}), dict) else {}
    content = platform.get("content", {}) if isinstance(platform.get("content", {}), dict) else {}
    chapter_length = content.get("chapter_length") if isinstance(content.get("chapter_length"), dict) else {}
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
    flow: str,
    project_id: str,
    workspace_path: str,
    genre: str,
    platform: str,
    chapter_id: str,
    current_goal: str,
) -> dict[str, Any]:
    try:
        return build_knowledge_pack(
            storage,
            {
                "flow": flow,
                "task_id": f"{flow}-{project_id or 'local'}-{chapter_id}",
                "project_id": project_id or "local-system",
                "workspace_path": workspace_path,
                "genre": genre,
                "platform": platform,
                "chapter_id": chapter_id,
                "current_goal": current_goal,
            },
        )
    except Exception as exc:
        return {"path": "", "asset": {"content": {}}, "warning": str(exc)}


def _pack_content(pack: dict[str, Any]) -> dict[str, Any]:
    asset = pack.get("asset", {}) if isinstance(pack.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return content


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
