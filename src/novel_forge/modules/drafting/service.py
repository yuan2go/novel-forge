from __future__ import annotations

from pathlib import Path

from novel_forge.agents import agent_runtime_profile, enforce_agent_action
from novel_forge.model_adapters import ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.common import read_previous, run_metadata
from novel_forge.modules.production_context import build_production_context, filter_project_safe_references
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import build_rag_context, retrieval_metadata, retrieval_reference_ids


def draft(storage: LocalStorage, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    agent_profile = agent_runtime_profile("draft")
    model = model or model_from_env("draft")
    plan = read_previous(storage, "chapter_plans", input_path)
    production_context = build_production_context(storage, plan, input_path=input_path)
    retrieved_context = build_rag_context(
        storage,
        plan,
        input_path=input_path,
        query=f"draft chapter {plan.title} {plan.content.get('objective', '')} {plan.content.get('hook', '')}",
    )
    generated = validate_model_output(
        "generate",
        _checked_model_generate(agent_profile, model, "Draft an original Chinese web-novel chapter from the chapter plan.", {
            "plan": plan.content,
            "source_asset_id": plan.id,
            "retrieved_context": retrieved_context,
            "production_context": production_context,
        }),
    )
    enforce_agent_action(agent_profile, "write_draft_chapter", "draft_chapter")
    draft_text = (
        generated["text"]
        if model.name != "mock-model"
        else (
            "雨水把广场的钟声压得很低。林乔抬头时，停用三年的钟楼忽然响了一下。"
            "档案表显示维护员早已离职，但新登记的巡检号正贴在门缝里。"
            "她把纸条塞进口袋，听见第二声钟从城市另一端传来。"
        )
    )
    asset = DraftChapter(
        title="Chapter 1 draft v0",
        source=plan.id,
        tags=["draft", "v0", model.name],
        content={
            "chapter": 1,
            "text": draft_text,
            "model_output": generated,
            "retrieved_context": retrieved_context,
            "production_context": production_context,
            "copyright_boundary": generated.get("copyright_boundary")
            or "original draft generated from chapter plan; no reference expression copied",
        },
        metadata={
            "model": model.name,
            "provider": generated.get("provider", model.name),
            "agent_runtime": agent_profile,
            "project_id": production_context["project"].get("project_id", ""),
            "workspace_path": production_context["project"].get("workspace_path", ""),
            "platform_profile_id": _profile_id(production_context, "platform_profile"),
            "genre_market_profile_id": _profile_id(production_context, "genre_market_profile"),
            "quality_standard_profile_id": _profile_id(production_context, "quality_standard_profile"),
            "style_profile_id": _profile_id(production_context, "style_profile"),
            "style_blend_preset_id": _profile_id(production_context, "style_blend_preset"),
            "continuity_bible_id": _profile_id(production_context, "continuity_bible"),
            "preflight_ready": production_context["preflight"].get("ready", False),
            "preflight_warnings": production_context["preflight"].get("warnings", []),
            **retrieval_metadata(retrieved_context),
            "run_metadata": run_metadata(
                "draft",
                plan,
                provider=generated.get("provider", model.name),
                model=generated.get("model", model.name),
            ),
        },
        references=filter_project_safe_references(
            storage,
            str(production_context["project"].get("project_id", "")),
            _dedupe([*retrieval_reference_ids(plan.id, retrieved_context), *production_context.get("profile_references", [])]),
        ),
    )
    return storage.write_asset("drafts", asset)


def _checked_model_generate(agent_profile: dict, model: ModelAdapter, prompt: str, context: dict) -> dict:
    enforce_agent_action(agent_profile, "call_model_adapter")
    return model.generate(prompt, context)


def _profile_id(context: dict, asset_type: str) -> str:
    profiles = context.get("profiles", {}) if isinstance(context.get("profiles", {}), dict) else {}
    profile = profiles.get(asset_type)
    return str(profile.get("id", "")) if isinstance(profile, dict) else ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
