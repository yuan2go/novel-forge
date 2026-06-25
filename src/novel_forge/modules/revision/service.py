from __future__ import annotations

from pathlib import Path

from novel_forge.model_adapters import ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.common import read_previous
from novel_forge.schemas import RevisionPlan
from novel_forge.storage.local import LocalStorage


def revise(storage: LocalStorage, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    model = model or model_from_env("revise")
    review_asset = read_previous(storage, "reviews", input_path)
    result = validate_model_output("revise", model.revise("", review_asset.to_dict()))
    target_score = result.get("target_score")
    if target_score is None:
        target_score = max(80, int(review_asset.score) + 8 if hasattr(review_asset, "score") else 80)
    asset = RevisionPlan(
        title=f"Revision plan for {review_asset.title}",
        source=review_asset.id,
        tags=["revision", "plan"],
        content={
            "steps": result["plan"],
            "target_score": target_score,
            "must_preserve": result.get("must_preserve") or ["original premise", "copyright boundary", "chapter hook"],
            "model_output": result,
        },
        metadata={"model": model.name, "provider": result.get("provider", model.name)},
        references=[review_asset.id],
    )
    return storage.write_asset("reviews", asset)
