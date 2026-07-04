from __future__ import annotations

from pathlib import Path

from novel_forge.model_adapters import GuardedModelAdapter, ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous
from novel_forge.modules.context_builder import build_flow_context_bundle, knowledge_context_contract_from_result, knowledge_context_contract_metadata
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import DecompositionReport
from novel_forge.storage.local import LocalStorage


def decompose(
    storage: LocalStorage,
    input_path: str | None = None,
    model: ModelAdapter | None = None,
    *,
    environment: str = "",
    os_envelope: dict[str, object] | None = None,
) -> Path:
    model = model or model_from_env("decompose")
    cleaned = read_previous(storage, "cleaned", input_path)
    cleaned_path = input_path or str(storage.root / "data" / "cleaned" / f"{cleaned.id}.json")
    project = project_scope_from_asset(storage, cleaned, input_path=cleaned_path)
    context = build_flow_context_bundle(
        storage,
        cleaned_path,
        flow="decompose",
        project_id=str(project.get("project_id", "")),
        workspace_path=str(project.get("workspace_path", "")),
        current_goal="decompose source into abstract knowledge mechanisms",
        token_budget=2500,
        environment=environment,
        os_envelope=os_envelope,
    )
    knowledge_contract = knowledge_context_contract_from_result(context)
    text = cleaned.content.get("text", "")
    with AgentExecutionContext(
        storage,
        agent_key="knowledge",
        operation="decompose",
        input_assets=[cleaned_path],
        output_types=["decomposition_report"],
        model_provider=getattr(model, "name", "local"),
        model_name=getattr(model, "name", "local"),
        prompt_version="prompt-v1",
        token_budget=2500,
        sla_seconds=900,
        workspace_path=str(project.get("workspace_path", "")),
        knowledge_context_contract=knowledge_contract,
    ) as agent_run:
        agent_run.guard("read_asset")
        guarded_model = GuardedModelAdapter(model, storage, agent_run.path)
        analysis = validate_model_output("analyze", guarded_model.analyze(text, {"source_asset_id": cleaned.id}))
        agent_run.guard("write_decomposition_report", "decomposition_report")
        asset = DecompositionReport(
            title=f"{cleaned.title} decomposition",
            source=cleaned.id,
            tags=["decomposition", "abstracted", "commercial-patterns"],
            content={
                "summary": analysis["summary"],
                "commercial_patterns": analysis.get("commercial_patterns")
                or ["reader question raised before explanation", "visible consequence per scene"],
                "narrative_patterns": analysis.get("narrative_patterns") or analysis.get("patterns")
                or ["problem -> investigation -> obstacle -> cost -> hook"],
                "character_mechanisms": ["protagonist pressure increases through external deadline"],
                "conflict_patterns": ["truth-seeking vs institutional silence"],
                "emotion_curve": ["curiosity", "tension", "uncertainty", "anticipation"],
                "hook_patterns": ["unanswered clue at chapter end"],
                "word_count": analysis["word_count"],
                "knowledge_context_contract": knowledge_contract,
                "agent_run_path": agent_run.path,
                "model_output": analysis,
            },
            metadata={
                "model": model.name,
                "agent_run_path": agent_run.path,
                **knowledge_context_contract_metadata(knowledge_contract),
                "project_id": project.get("project_id", ""),
                "workspace_path": project.get("workspace_path", ""),
                "copyright_boundary": "abstract structure and mechanism only; no protected expression copied",
            },
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [cleaned.id]),
        )
        path = storage.write_asset("decompositions", asset)
        agent_run.succeed(output_assets=[path], token_used=int(analysis.get("word_count", 0)))
        return path
