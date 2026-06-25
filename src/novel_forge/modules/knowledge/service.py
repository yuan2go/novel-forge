from __future__ import annotations

from pathlib import Path

from novel_forge.agents import agent_runtime_profile, enforce_agent_action
from novel_forge.modules.common import read_previous, run_metadata
from novel_forge.schemas import KnowledgeCard
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import build_rag_context, retrieval_metadata, retrieval_reference_ids


def extract_knowledge(storage: LocalStorage, input_path: str | None = None) -> Path:
    agent_profile = agent_runtime_profile("knowledge")
    report = read_previous(storage, "decompositions", input_path)
    retrieved_context = build_rag_context(
        storage,
        report,
        input_path=input_path,
        query=f"extract knowledge {report.title} {report.content.get('summary', '')}",
    )
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
        },
        metadata={
            "copyright_boundary": "abstracted writing principles derived from structure",
            "agent_runtime": agent_profile,
            **retrieval_metadata(retrieved_context),
            "run_metadata": run_metadata("extract-knowledge", report, provider="local-rules", model="knowledge-transform-v1"),
        },
        references=retrieval_reference_ids(report.id, retrieved_context),
    )
    enforce_agent_action(agent_profile, "write_knowledge_card", "knowledge_card")
    return storage.write_asset("knowledge", asset)
