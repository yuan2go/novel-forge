from __future__ import annotations

from pathlib import Path

from novel_forge.modules.common import read_previous
from novel_forge.modules.production_chain import create_chapter_plan_version
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage


def generate_chapter_plan(storage: LocalStorage, input_path: str | None = None) -> Path:
    outline = read_previous(storage, "outlines", input_path)
    asset = ChapterPlan(
        title="Chapter 1 plan",
        source=outline.id,
        tags=["chapter-plan", "chapter-1"],
        content={
            "chapter": 1,
            "objective": "introduce the impossible clock signal and protagonist pressure",
            "beats": [
                "rainy public square signal",
                "protagonist notices archive mismatch",
                "supervisor orders silence",
                "anonymous note predicts next bell",
            ],
            "hook": "the next bell rings from a dismantled tower",
            "quality_targets": ["causal chain", "chapter hook", "originality boundary"],
        },
        references=[outline.id],
    )
    path = storage.write_asset("chapter_plans", asset)
    create_chapter_plan_version(storage, path)
    return path
