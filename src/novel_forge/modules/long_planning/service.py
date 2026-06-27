from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.planning_context import build_planning_context
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import LongFormMacroPlan, validate_common_fields
from novel_forge.storage.local import LocalStorage


def create_long_form_macro_plan(
    storage: LocalStorage,
    *,
    workspace_path: str | None = None,
    source_path: str | Path | None = None,
    target_word_count: int = 1_000_000,
    volume_count: int = 5,
    chapters_per_volume: int = 80,
) -> dict[str, Any]:
    storage.ensure_layout()
    source_asset = _source_asset(storage, source_path, workspace_path)
    project = project_scope_from_asset(storage, source_asset, input_path=source_path, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    planning_context = build_planning_context(storage, source_asset, input_path=source_path, workspace_path=workspace)
    target_word_count = max(int(target_word_count or 1_000_000), 100_000)
    volume_count = max(int(volume_count or 5), 1)
    chapters_per_volume = max(int(chapters_per_volume or 80), 10)
    with AgentExecutionContext(
        storage,
        agent_key="outline",
        operation="create-long-form-macro-plan",
        input_assets=[source_path or workspace],
        output_types=["long_form_macro_plan"],
        workspace_path=workspace,
        sla_seconds=600,
    ) as run:
        run.guard("read_asset")
        plan_id = make_id("long_form_macro_plan", project_id or source_asset.id)
        volume_plans = _volume_plans(volume_count, chapters_per_volume, target_word_count, planning_context)
        mainline = _mainline_matrix(volume_plans, planning_context)
        subplots = _subplot_matrix(volume_plans, planning_context)
        character_arcs = _character_arc_curves(volume_plans, planning_context)
        climax_ladder = _climax_ladder(volume_plans, planning_context)
        pacing = _commercial_pacing_table(volume_plans, planning_context)
        gates = _verification_gates(planning_context)
        asset = LongFormMacroPlan(
            title=f"{project.get('title') or source_asset.title or 'Project'} long-form macro plan",
            source=source_asset.id,
            tags=["long-form", "macro-plan", f"{volume_count}-volumes"],
            content={
                "plan_id": plan_id,
                "project_id": project_id or "global",
                "workspace_path": workspace,
                "target_word_count": target_word_count,
                "volume_count": volume_count,
                "chapters_per_volume": chapters_per_volume,
                "reader_promise": planning_context.get("creative_strategy", {}).get("content", {}).get("reader_promise", ""),
                "volume_plans": volume_plans,
                "mainline_matrix": mainline,
                "subplot_matrix": subplots,
                "character_arc_curves": character_arcs,
                "climax_ladder": climax_ladder,
                "commercial_pacing_table": pacing,
                "verification_gates": gates,
                "planning_context": planning_context,
                "created_at": utc_now(),
            },
            metadata={"project_id": project_id, "workspace_path": workspace, "target_word_count": target_word_count, "workflow": "long-form-macro-planning"},
            references=filter_project_safe_references(storage, project_id, [source_asset.id, workspace, *planning_context.get("references", [])]),
        )
        result = _write(storage, asset)
        run.guard("write_outline", "long_form_macro_plan")
        run.succeed(output_assets=[result["path"]], token_used=len(str(asset.content)))
        return result


def list_long_form_macro_plans(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("outlines")):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "long_form_macro_plan":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "title": data.get("title") or data.get("name", ""),
                "project_id": metadata.get("project_id", ""),
                "target_word_count": content.get("target_word_count", 0),
                "volume_count": content.get("volume_count", 0),
                "mainline_count": len(content.get("mainline_matrix", []) if isinstance(content.get("mainline_matrix", []), list) else []),
                "subplot_count": len(content.get("subplot_matrix", []) if isinstance(content.get("subplot_matrix", []), list) else []),
                "gate_count": len(content.get("verification_gates", []) if isinstance(content.get("verification_gates", []), list) else []),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _source_asset(storage: LocalStorage, source_path: str | Path | None, workspace_path: str | None) -> Any:
    if source_path:
        return storage.read_asset(_resolve(storage.root, source_path))
    if workspace_path:
        return storage.read_asset(_resolve(storage.root, workspace_path))
    for category in ["outlines", "workspaces", "characters", "worlds"]:
        paths = storage.list_json(category)
        if paths:
            return storage.read_asset(paths[-1])
    raise FileNotFoundError("no source asset found for long-form macro planning")


def _volume_plans(volume_count: int, chapters_per_volume: int, target_word_count: int, context: dict[str, Any]) -> list[dict[str, Any]]:
    words_per_volume = max(int(target_word_count / volume_count), 1)
    strategy = context.get("creative_strategy", {}).get("content", {}) if isinstance(context.get("creative_strategy", {}), dict) else {}
    hooks = strategy.get("long_hooks", []) if isinstance(strategy.get("long_hooks", []), list) else []
    return [
        {
            "volume": index,
            "word_budget": words_per_volume,
            "chapter_range": [((index - 1) * chapters_per_volume) + 1, index * chapters_per_volume],
            "volume_goal": _volume_goal(index, strategy),
            "reader_promise_focus": strategy.get("reader_promise", "clear genre promise"),
            "main_conflict": f"escalate the core conflict to tier {index}",
            "major_payoff": f"pay off volume {index} promise while opening volume {index + 1 if index < volume_count else 'final'} consequence",
            "long_hooks": hooks[: max(1, min(len(hooks), 3))],
            "risk_controls": ["no filler volume", "each volume must change status quo", "protect originality boundary"],
        }
        for index in range(1, volume_count + 1)
    ]


def _mainline_matrix(volume_plans: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "thread_id": f"mainline_v{volume['volume']}",
            "volume": volume["volume"],
            "setup": volume["volume_goal"],
            "pressure": volume["main_conflict"],
            "turning_point": f"mid-volume reversal for volume {volume['volume']}",
            "payoff": volume["major_payoff"],
            "verification": "outline/chapter_plan must show setup-pressure-payoff continuity",
        }
        for volume in volume_plans
    ]


def _subplot_matrix(volume_plans: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    feedback = context.get("feedback", {}).get("constraints", []) if isinstance(context.get("feedback", {}), dict) else []
    subplot_names = ["relationship_pressure", "resource_constraint", "identity_mystery", "world_rule_cost"]
    rows: list[dict[str, Any]] = []
    for volume in volume_plans:
        for index, name in enumerate(subplot_names, start=1):
            rows.append(
                {
                    "subplot_id": f"{name}_v{volume['volume']}",
                    "volume": volume["volume"],
                    "priority": index,
                    "function": name,
                    "setup_window": volume["chapter_range"][0],
                    "payoff_window": volume["chapter_range"][1],
                    "reader_feedback_constraints": feedback[:3],
                }
            )
    return rows


def _character_arc_curves(volume_plans: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    continuity_assets = context.get("continuity", {}).get("assets", []) if isinstance(context.get("continuity", {}), dict) else []
    names = [str(asset.get("title", "")).strip() for asset in continuity_assets if str(asset.get("title", "")).strip()][:4] or ["protagonist", "rival", "ally"]
    return [
        {
            "character": name,
            "arc_points": [
                {
                    "volume": volume["volume"],
                    "state": f"{name} state shifts through pressure tier {volume['volume']}",
                    "choice_cost": f"cost escalates in volume {volume['volume']}",
                    "verification": "canon graph must record state/location/power change before final draft is published",
                }
                for volume in volume_plans
            ],
        }
        for name in names
    ]


def _climax_ladder(volume_plans: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "volume": volume["volume"],
            "chapters": [max(volume["chapter_range"][0], volume["chapter_range"][1] - 8), volume["chapter_range"][1]],
            "climax_type": "status quo break" if volume["volume"] < len(volume_plans) else "series-level payoff",
            "required_payoffs": [volume["major_payoff"]],
            "next_hook_policy": "seed next volume hook" if volume["volume"] < len(volume_plans) else "close all mandatory long hooks",
        }
        for volume in volume_plans
    ]


def _commercial_pacing_table(volume_plans: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    pacing = context.get("creative_strategy", {}).get("content", {}).get("platform_pacing", {}) if isinstance(context.get("creative_strategy", {}), dict) else {}
    return [
        {
            "volume": volume["volume"],
            "opening_window": pacing.get("opening_window", "first_3_chapters"),
            "retention_window": pacing.get("retention_window", "first_10_chapters"),
            "hook_interval_chapters": 1,
            "payoff_interval_chapters": 2,
            "anti_fatigue_rule": "rotate conflict function every 3-5 chapters",
            "word_budget": volume["word_budget"],
        }
        for volume in volume_plans
    ]


def _verification_gates(context: dict[str, Any]) -> list[dict[str, Any]]:
    quality = context.get("quality_standard", {}).get("dimensions", []) if isinstance(context.get("quality_standard", {}), dict) else []
    return [
        {"gate": "volume_goal_visible", "required": True, "check": "each chapter_plan references current volume goal"},
        {"gate": "mainline_subplot_matrix", "required": True, "check": "chapter_plan references at least one mainline or subplot row"},
        {"gate": "canon_patch_after_final", "required": True, "check": "final_draft produces proposed canon_patch"},
        {"gate": "quality_dimensions", "required": bool(quality), "check": ", ".join(str(item) for item in quality[:8])},
    ]


def _volume_goal(index: int, strategy: dict[str, Any]) -> str:
    goals = strategy.get("volume_goals", {}) if isinstance(strategy.get("volume_goals", {}), dict) else {}
    return str(goals.get(f"volume_{index}") or goals.get("current_volume") or f"deliver volume {index} promise with escalating pressure")


def _write(storage: LocalStorage, asset: LongFormMacroPlan) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _resolve(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
