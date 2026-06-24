from __future__ import annotations

from pathlib import Path

from novel_forge.modules.common import read_previous
from novel_forge.schemas import KnowledgeCard
from novel_forge.storage.local import LocalStorage


def extract_knowledge(storage: LocalStorage, input_path: str | None = None) -> Path:
    report = read_previous(storage, "decompositions", input_path)
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
        },
        metadata={"copyright_boundary": "abstracted writing principles derived from structure"},
        references=[report.id],
    )
    return storage.write_asset("knowledge", asset)
