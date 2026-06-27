from __future__ import annotations

from novel_forge.model_adapters import GuardedModelAdapter, ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import RevisionPlan
from novel_forge.storage.local import LocalStorage


def revise(storage: LocalStorage, input_path: str | None = None, model: ModelAdapter | None = None) -> Path:
    model = model or model_from_env("revise")
    review_asset = read_previous(storage, "reviews", input_path)
    review_path = input_path or str(storage.root / "data" / "reviews" / f"{review_asset.id}.json")
    project = project_scope_from_asset(storage, review_asset, input_path=review_path)
    with AgentExecutionContext(
        storage,
        agent_key="review",
        operation="revise",
        input_assets=[review_path],
        output_types=["revision_plan"],
        model_provider=getattr(model, "name", "local"),
        model_name=getattr(model, "name", "local"),
        prompt_version="prompt-v1",
        token_budget=1500,
        sla_seconds=600,
        workspace_path=str(project.get("workspace_path", "")),
    ) as agent_run:
        agent_run.guard("read_asset")
        guarded_model = GuardedModelAdapter(model, storage, agent_run.path)
        result = validate_model_output("revise", guarded_model.revise("", review_asset.to_dict()))
        target_score = result.get("target_score")
        if target_score is None:
            target_score = max(80, int(review_asset.score) + 8 if hasattr(review_asset, "score") else 80)
        agent_run.guard("write_revision_plan", "revision_plan")
        asset = RevisionPlan(
            title=f"Revision plan for {review_asset.title}",
            source=review_asset.id,
            tags=["revision", "plan"],
            content={
                "steps": result["plan"],
                "target_score": target_score,
                "must_preserve": result.get("must_preserve") or ["original premise", "copyright boundary", "chapter hook"],
                "agent_run_path": agent_run.path,
                "model_output": result,
            },
            metadata={
                "model": model.name,
                "provider": result.get("provider", model.name),
                "agent_run_path": agent_run.path,
                "project_id": project.get("project_id", ""),
                "workspace_path": project.get("workspace_path", ""),
            },
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [review_asset.id]),
        )
        path = storage.write_asset("reviews", asset)
        agent_run.succeed(output_assets=[path], token_used=len(str(result)))
        return path
