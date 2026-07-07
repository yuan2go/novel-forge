from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous, run_metadata
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.schemas import MaterialCard
from novel_forge.storage.local import LocalStorage


def build_materials(storage: LocalStorage, input_path: str | None = None, *, environment: str = "") -> Path:
    knowledge = read_previous(storage, "knowledge", input_path)
    source_eligibility = knowledge.content.get("source_eligibility", {}) if isinstance(knowledge.content, dict) and isinstance(knowledge.content.get("source_eligibility", {}), dict) else {}
    source_chunk_ids = [str(item) for item in knowledge.content.get("source_chunk_ids", []) if str(item).strip()] if isinstance(knowledge.content, dict) else []
    _enforce_material_source_eligibility(source_eligibility, source_chunk_ids=source_chunk_ids, environment=environment)
    with AgentExecutionContext(
        storage,
        agent_key="material",
        operation="build-materials",
        input_assets=[input_path or knowledge.id],
        output_types=["material_card"],
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
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
                "source_eligibility": source_eligibility or {"status": "not_required", "caller": "materials.build_materials"},
                "source_boundary": {
                    "raw_text_included": False,
                    "clean_text_included": False,
                    "inherits_knowledge_source_eligibility": bool(source_eligibility),
                },
            },
            metadata={
                "copyright_boundary": "reusable abstract production material only",
                "source_eligibility_status": source_eligibility.get("status", "not_required") if source_eligibility else "not_required",
                "source_policy_refs": source_eligibility.get("source_policy_refs", []) if source_eligibility else [],
                "source_risk_report_refs": source_eligibility.get("source_risk_report_refs", []) if source_eligibility else [],
                "use_in_generation_rag": bool(source_eligibility.get("generation_context_allowed")) and not bool(source_eligibility.get("evidence_only")) if source_eligibility else False,
                "tag_facets": {
                    "genre": ["suspense"],
                    "function": ["hook", "conflict", "reader-retention", "chapter-ending"],
                    "source_type": ["knowledge_card"],
                },
                "run_metadata": run_metadata("build-materials", knowledge, provider="local-rules", model="material-transform-v1"),
            },
            references=[knowledge.id],
        )
        run.guard("write_material_card", "material_card")
        path = storage.write_asset("materials", asset)
        run.succeed(output_assets=[str(path.relative_to(storage.root))])
        return path


def _enforce_material_source_eligibility(source_eligibility: dict[str, Any], *, source_chunk_ids: list[str], environment: str) -> None:
    if not is_production_environment(environment):
        return
    if not source_eligibility and source_chunk_ids:
        raise ValueError("Material source eligibility blocks production material card: missing")
    if not source_eligibility or source_eligibility.get("status") in {"not_required", "passed"}:
        return
    raise ValueError(f"Material source eligibility blocks production material card: {source_eligibility.get('status') or 'missing'}")
