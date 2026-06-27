from __future__ import annotations

from pathlib import Path

from novel_forge.agents import agent_runtime_profile, enforce_agent_action
from novel_forge.model_adapters import GuardedModelAdapter, ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle
from novel_forge.modules.continuity_graph import create_chapter_stability_preflight_report
from novel_forge.modules.production_chain import create_draft_version, create_generation_run
from novel_forge.modules.production_context import build_production_context, filter_project_safe_references
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import retrieval_metadata, retrieval_reference_ids


def draft(
    storage: LocalStorage,
    input_path: str | None = None,
    model: ModelAdapter | None = None,
    *,
    context_bundle_path: str | Path | None = None,
    stability_preflight_path: str | Path | None = None,
    workspace_path: str | None = None,
) -> Path:
    agent_profile = agent_runtime_profile("draft")
    model = model or model_from_env("draft")
    plan_path = _resolve_chapter_plan_path(storage, input_path)
    plan = storage.read_asset(plan_path)
    plan_ref = _display_path(storage.root, plan_path)
    production_context = build_production_context(storage, plan, input_path=plan_path, workspace_path=workspace_path)
    stability_preflight = _load_or_create_stability_preflight(
        storage,
        plan_path,
        stability_preflight_path=stability_preflight_path,
        workspace_path=workspace_path or str(production_context["project"].get("workspace_path", "")),
    )
    if context_bundle_path:
        bundle_file = resolve_path(storage.root, context_bundle_path)
        bundle_asset = storage.read_asset(bundle_file)
        if bundle_asset.type != "context_bundle":
            raise ValueError("context_bundle_path must point to a context_bundle asset")
        context_bundle = {"path": _display_path(storage.root, bundle_file), "asset": bundle_asset.to_dict()}
        context_plan_path = str(bundle_asset.content.get("build_plan_path", ""))
        context_plan_asset = (
            storage.read_asset(resolve_path(storage.root, context_plan_path)).to_dict()
            if context_plan_path
            else {"id": "", "content": {}}
        )
        context_plan_ref = context_plan_path
    else:
        context_plan = create_context_build_plan(
            storage,
            plan_path,
            query=f"draft chapter {plan.title} {plan.content.get('objective', '')} {plan.content.get('hook', '')}",
            top_k=8,
            token_budget=4000,
            backend="auto",
            workspace_path=workspace_path,
        )
        context_bundle = create_context_bundle(storage, context_plan["path"])
        context_plan_asset = context_plan["asset"]
        context_plan_ref = str(context_plan["path"])
    context_bundle_asset = context_bundle["asset"]
    retrieved_context = context_bundle_asset.get("content", {}).get("retrieved_context", {})
    with AgentExecutionContext(
        storage,
        agent_key="draft",
        operation="draft",
        input_assets=[plan_path, stability_preflight["path"], context_plan_asset.get("path", "") or context_plan_asset.get("id", ""), context_bundle.get("path", "")],
        output_types=["draft_chapter", "draft_version", "generation_run"],
        model_provider=getattr(model, "name", "local"),
        model_name=getattr(model, "name", "local"),
        prompt_version="prompt-v1",
        token_budget=6000,
        sla_seconds=1200,
        workspace_path=str(production_context["project"].get("workspace_path", "")),
    ) as agent_run:
        agent_run.guard("read_asset")
        guarded_model = GuardedModelAdapter(model, storage, agent_run.path)
        generated = validate_model_output(
            "generate",
            guarded_model.generate("Draft an original Chinese web-novel chapter from the chapter plan.", {
                "plan": plan.content,
                "source_asset_id": plan.id,
                "retrieved_context": retrieved_context,
                "stability_preflight": stability_preflight["content"],
                "context_build_plan": context_plan_asset.get("content", {}),
                "context_bundle": context_bundle_asset.get("content", {}),
                "actual_context": context_bundle_asset.get("content", {}).get("actual_context", ""),
                "production_context": production_context,
            }),
        )
        enforce_agent_action(agent_profile, "write_draft_chapter", "draft_chapter")
        agent_run.guard("write_draft_chapter", "draft_chapter")
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
                "stability_preflight": stability_preflight["content"],
                "stability_preflight_path": stability_preflight["path"],
                "stability_preflight_id": stability_preflight["id"],
                "context_build_plan_id": context_plan_asset.get("id", ""),
                "context_build_plan_path": context_plan_ref,
                "context_bundle_id": context_bundle_asset.get("id", ""),
                "context_bundle_path": context_bundle.get("path", ""),
                "actual_context": context_bundle_asset.get("content", {}).get("actual_context", ""),
                "production_context": production_context,
                "agent_run_path": agent_run.path,
                "copyright_boundary": generated.get("copyright_boundary")
                or "original draft generated from chapter plan; no reference expression copied",
            },
            metadata={
                "model": model.name,
                "provider": generated.get("provider", model.name),
                "agent_runtime": agent_profile,
                "agent_run_path": agent_run.path,
                "project_id": production_context["project"].get("project_id", ""),
                "workspace_path": production_context["project"].get("workspace_path", ""),
                "platform_profile_id": _profile_id(production_context, "platform_profile"),
                "genre_market_profile_id": _profile_id(production_context, "genre_market_profile"),
                "quality_standard_profile_id": _profile_id(production_context, "quality_standard_profile"),
                "style_profile_id": _profile_id(production_context, "style_profile"),
                "style_blend_preset_id": _profile_id(production_context, "style_blend_preset"),
                "continuity_bible_id": _profile_id(production_context, "continuity_bible"),
                "stability_preflight_id": stability_preflight["id"],
                "stability_preflight_path": stability_preflight["path"],
                "stability_preflight_recommendation": stability_preflight["recommendation"],
                "stability_preflight_gate_status": stability_preflight["gate_status"],
                "context_build_plan_id": context_plan_asset.get("id", ""),
                "context_build_plan_path": context_plan_ref,
                "context_bundle_id": context_bundle_asset.get("id", ""),
                "context_bundle_path": context_bundle.get("path", ""),
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
                _dedupe([
                    *retrieval_reference_ids(plan.id, retrieved_context),
                    plan_ref,
                    stability_preflight["id"],
                    stability_preflight["path"],
                    str(context_plan_asset.get("id", "")),
                    context_plan_ref,
                    str(context_bundle_asset.get("id", "")),
                    str(context_bundle.get("path", "")),
                    *production_context.get("profile_references", []),
                ]),
            ),
        )
        path = storage.write_asset("drafts", asset)
        agent_run.guard("write_draft_version", "draft_version")
        draft_version = create_draft_version(storage, path)
        agent_run.guard("write_generation_run", "generation_run")
        generation_run = create_generation_run(
            storage,
            plan_path,
            str(context_bundle.get("path", "")),
            output_path=path,
            provider=str(generated.get("provider", model.name)),
            model=str(generated.get("model", model.name)),
            prompt_version="prompt-v1",
            status="succeeded",
        )
        data = storage.read_json(path)
        if isinstance(data, dict):
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            metadata["draft_version_path"] = draft_version.get("path", "")
            metadata["draft_version_id"] = draft_version.get("asset", {}).get("id", "")
            metadata["generation_run_path"] = generation_run.get("path", "")
            metadata["generation_run_id"] = generation_run.get("asset", {}).get("id", "")
            data["metadata"] = metadata
            storage.write_json(path, data)
        agent_run.succeed(output_assets=[path, draft_version.get("path", ""), generation_run.get("path", "")], token_used=len(draft_text))
        return path


def _checked_model_generate(agent_profile: dict, model: ModelAdapter, prompt: str, context: dict) -> dict:
    enforce_agent_action(agent_profile, "call_model_adapter")
    return model.generate(prompt, context)


def _resolve_chapter_plan_path(storage: LocalStorage, input_path: str | Path | None) -> Path:
    if input_path:
        path = resolve_path(storage.root, input_path)
        asset = storage.read_asset(path)
        if asset.type != "chapter_plan":
            raise ValueError("draft requires a chapter_plan asset")
        return path
    for path in reversed(storage.list_json("chapter_plans")):
        try:
            asset = storage.read_asset(path)
        except Exception:
            continue
        if asset.type == "chapter_plan":
            return path
    raise FileNotFoundError("no chapter_plan assets found in data/chapter_plans")


def _load_or_create_stability_preflight(
    storage: LocalStorage,
    plan_path: Path,
    *,
    stability_preflight_path: str | Path | None = None,
    workspace_path: str | None = None,
) -> dict[str, str | dict]:
    if stability_preflight_path:
        report_file = resolve_path(storage.root, stability_preflight_path)
    else:
        report = create_chapter_stability_preflight_report(storage, plan_path, workspace_path=workspace_path)
        report_file = resolve_path(storage.root, report["path"])
    report_asset = storage.read_asset(report_file)
    if report_asset.type != "chapter_continuity_report":
        raise ValueError("stability_preflight_path must point to a chapter_continuity_report asset")
    content = report_asset.content
    if content.get("gate") != "long_form_stability_preflight":
        raise ValueError("stability_preflight_path must be a long_form_stability_preflight report")
    recommendation = str(content.get("recommendation", "pass"))
    if recommendation == "block":
        blocking = content.get("blocking_violations", []) if isinstance(content.get("blocking_violations", []), list) else []
        raise ValueError(f"draft generation blocked by long-form stability preflight: {len(blocking)} blocking violation(s)")
    return {
        "id": report_asset.id,
        "path": _display_path(storage.root, report_file),
        "content": content,
        "recommendation": recommendation,
        "gate_status": str(content.get("gate_status", "")),
    }


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


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
