from __future__ import annotations

from pathlib import Path

from novel_forge.modules.common import read_previous
from novel_forge.schemas import MaterialCard
from novel_forge.storage.local import LocalStorage


def build_materials(storage: LocalStorage, input_path: str | None = None) -> Path:
    knowledge = read_previous(storage, "knowledge", input_path)
    asset = MaterialCard(
        title="Suspense production material card",
        source=knowledge.id,
        tags=[
            "material",
            "suspense",
            "reusable",
            "hook",
            "conflict",
            "reader-retention",
            "chapter-ending",
        ],
        content={
            "usable_patterns": knowledge.content.get("principles", []),
            "prompt_fragments": [
                "Design a clue that changes the protagonist's available choices.",
                "End the chapter with a new obligation, not just a question.",
            ],
            "do_not_copy": ["names", "sentences", "unique settings", "plot sequence combinations"],
        },
        metadata={
            "copyright_boundary": "reusable abstract production material only",
            "tag_facets": {
                "genre": ["suspense"],
                "function": ["hook", "conflict", "reader-retention", "chapter-ending"],
                "source_type": ["knowledge_card"],
            },
        },
        references=[knowledge.id],
    )
    return storage.write_asset("materials", asset)
