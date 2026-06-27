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
from novel_forge.modules.planning_context import build_planning_context, planning_context_metadata
from novel_forge.modules.production_chain import create_outline_version
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import Outline
from novel_forge.storage.local import LocalStorage

PROMPT_VERSION = "outline-v2-project-context"


def generate_outline(
    storage: LocalStorage,
    input_path: str | None = None,
    model: ModelAdapter | None = None,
    *,
    workspace_path: str | None = None,
) -> Path:
    model = model or model_from_env("outline")
    source_path = resolve_path(storage.root, input_path) if input_path else storage.latest("characters")
    character = storage.read_asset(source_path)
    source_ref = _display_path(storage.root, source_path)
    planning_context = build_planning_context(storage, character, input_path=source_path, workspace_path=workspace_path)
    production_context = planning_context["production_context"]
    project_id = str(production_context.get("project", {}).get("project_id", ""))
    workspace = str(production_context.get("project", {}).get("workspace_path", ""))
    with AgentExecutionContext(
        storage,
        agent_key="outline",
        operation="generate-outline",
        input_assets=_dedupe([source_ref, *planning_context.get("references", [])]),
        output_types=["outline", "outline_version"],
        model_provider=getattr(model, "name", "local"),
        model_name=getattr(model, "name", "local"),
        prompt_version=PROMPT_VERSION,
        token_budget=3500,
        sla_seconds=600,
        workspace_path=workspace,
    ) as run:
        run.guard("read_asset")
        guarded_model = GuardedModelAdapter(model, storage, run.path)
        generated = validate_model_output(
            "generate",
            guarded_model.generate(
                "Generate a project-specific long-form novel outline. Return JSON only.",
                {
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
                        "continuity_constraints": ["string"],
                        "feedback_constraints": ["string"],
                    },
                    "source_character": character.to_dict(),
                    "planning_context": planning_context,
                    "copyright_boundary": "Use reference assets for abstract structure only. Do not copy protected scenes, names, settings, or prose.",
                },
            ),
        )
        packet = _outline_packet(generated, character.to_dict(), planning_context, model_name=getattr(model, "name", ""))
        asset = Outline(
            title=str(packet.get("title") or f"{character.title or 'Project'} outline"),
            source=character.id,
            tags=_dedupe(["outline", "model-driven", "project-context", *[str(item) for item in packet.get("tags", []) if str(item).strip()]]),
            content={
                "acts": packet["acts"],
                "reader_promise": packet.get("reader_promise", ""),
                "conflict_engine": packet.get("conflict_engine", ""),
                "quality_targets": packet.get("quality_targets", []),
                "continuity_constraints": packet.get("continuity_constraints", []),
                "feedback_constraints": packet.get("feedback_constraints", []),
                "planning_context": planning_context,
                "model_output": generated,
                "agent_run_path": run.path,
                "copyright_boundary": generated.get("copyright_boundary")
                or "outline generated from project profiles and abstract references; no protected expression copied",
            },
            metadata={
                "model": getattr(model, "name", "local"),
                "provider": str(generated.get("provider", getattr(model, "name", "local"))),
                "agent_run_path": run.path,
                "prompt_version": PROMPT_VERSION,
                "source_asset_path": source_ref,
                **planning_context_metadata(planning_context),
                "run_metadata": run_metadata(
                    "generate-outline",
                    character,
                    provider=str(generated.get("provider", getattr(model, "name", "local"))),
                    model=str(generated.get("model", getattr(model, "name", "local"))),
                    prompt_version=PROMPT_VERSION,
                ),
            },
            references=filter_project_safe_references(
                storage,
                project_id,
                _dedupe([character.id, source_ref, workspace, *planning_context.get("references", [])]),
            ),
        )
        run.guard("write_outline", "outline")
        path = storage.write_asset("outlines", asset)
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
    return {
        "title": str(packet.get("title") or "Project outline").strip(),
        "reader_promise": str(packet.get("reader_promise") or "").strip(),
        "conflict_engine": str(packet.get("conflict_engine") or "").strip(),
        "acts": normalized_acts,
        "quality_targets": _dedupe([str(item) for item in quality_targets if str(item).strip()]),
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
