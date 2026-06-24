from __future__ import annotations

from pathlib import Path

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.common import read_previous
from novel_forge.schemas import RevisionPlan
from novel_forge.storage.local import LocalStorage


def revise(storage: LocalStorage, input_path: str | None = None, model: MockModelAdapter | None = None) -> Path:
    model = model or MockModelAdapter()
    review_asset = read_previous(storage, "reviews", input_path)
    result = model.revise("", review_asset.to_dict())
    asset = RevisionPlan(
        title=f"Revision plan for {review_asset.title}",
        source=review_asset.id,
        tags=["revision", "plan"],
        content={
            "steps": result["plan"],
            "target_score": max(80, int(review_asset.score) + 8 if hasattr(review_asset, "score") else 80),
            "must_preserve": ["original premise", "copyright boundary", "chapter hook"],
        },
        references=[review_asset.id],
    )
    return storage.write_asset("reviews", asset)
