from __future__ import annotations

from pathlib import Path

from novel_forge.agents import agent_runtime_profile, enforce_agent_action
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous, run_metadata
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import KnowledgeCard
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import build_rag_context, retrieval_metadata, retrieval_reference_ids


def extract_knowledge(storage: LocalStorage, input_path: str | None = None) -> Path:
    agent_profile = agent_runtime_profile("knowledge")
    report = read_previous(storage, "decompositions", input_path)
    report_path = input_path or str(storage.root / "data" / "decompositions" / f"{report.id}.json")
    project = project_scope_from_asset(storage, report, input_path=report_path)
    retrieved_context = build_rag_context(
        storage,
        report,
        input_path=input_path,
        query=f"extract knowledge {report.title} {report.content.get('summary', '')}",
    )
    with AgentExecutionContext(
        storage,
        agent_key="knowledge",
        operation="extract-knowledge",
        input_assets=[report_path],
        output_types=["knowledge_card"],
        model_provider="local-rules",
        model_name="knowledge-transform-v1",
        prompt_version="prompt-v1",
        sla_seconds=600,
        workspace_path=str(project.get("workspace_path", "")),
    ) as agent_run:
        agent_run.guard("read_asset")
        agent_run.guard("write_knowledge_card", "knowledge_card")
        asset = KnowledgeCard(
            title=f"Knowledge from {report.title}",
            source=report.id,
            tags=["knowledge", "suspense", "structure"],
            content={
                "principles": [
                    "open with a concrete question before exposition",
                    "attach each clue to a cost or relationship pressure",
                    "turn chapter endings into decision pressure rather than mere mystery",
                ],
                "derived_from": report.content,
                "retrieved_context": retrieved_context,
                "agent_run_path": agent_run.path,
            },
            metadata={
                "copyright_boundary": "abstracted writing principles derived from structure",
                "agent_runtime": agent_profile,
                "agent_run_path": agent_run.path,
                "project_id": project.get("project_id", ""),
                "workspace_path": project.get("workspace_path", ""),
                **retrieval_metadata(retrieved_context),
                "run_metadata": run_metadata("extract-knowledge", report, provider="local-rules", model="knowledge-transform-v1"),
            },
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), retrieval_reference_ids(report.id, retrieved_context)),
        )
        enforce_agent_action(agent_profile, "write_knowledge_card", "knowledge_card")
        path = storage.write_asset("knowledge", asset)
        agent_run.succeed(output_assets=[path], token_used=len(str(asset.content)))
        return path
