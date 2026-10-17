from __future__ import annotations

from .capacity_continuation import effective_context_content

from .contracts import ChapterHandlerRequest, ChapterInputAsset
from .receipt_recovery import _require_current_receipt_family
from .realization_composition import (
    compile_realization_contract, integrate_realization,
    resolve_accepted_realization_sources,
)
from .chapter_plan_views import build_draft_style_view
from .craft_execution import require_craft_delivery
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash


def require_current_completed_draft(source, output, *, asset_reader):
    _require_current_receipt_family(source)
    assets = []
    for frozen in source["input_asset_snapshot"]:
        asset = asset_reader.require(project_id=source["project_id"], asset_version_id=frozen["asset_version_id"])
        if (asset.project_id != source["project_id"] or asset.content_hash != frozen["content_hash"]
                or asset.content_hash != snapshot_hash(asset.content)
                or asset.lifecycle not in {"ACTIVE", "SUPERSEDED"}
                or asset.eligibility != "ELIGIBLE" or asset.governance != "CLEAR"):
            raise KernelError("RETAINED_GRAPH_DRAFT_INPUT_DRIFT", "Current Draft requires its exact frozen governed inputs")
        assets.append(ChapterInputAsset(asset.asset_version_id, asset.asset_type, asset.content_hash, asset.content))
    request = ChapterHandlerRequest(source["operation_id"], source["project_id"], source["workspace_id"],
        source["trace_id"], source["correlation_id"], source["command_payload"], tuple(assets), definition_version="3.10.0")
    from .capacity_continuation import bind_retained_capacity_context
    request = bind_retained_capacity_context(request, asset_reader=asset_reader)
    plan = request.require_input("chapter_plan").content
    context = request.require_input("context_bundle")
    require_craft_delivery(plan=plan, intent=request.require_input("chapter_execution_intent").content,
        memo=request.require_input("chapter_memo").content, context=effective_context_content(request, context))
    accepted = resolve_accepted_realization_sources(request, asset_reader=asset_reader, verify_content_hash=True)
    contract = compile_realization_contract(plan, build_draft_style_view(effective_context_content(request, context), work_requirements=True),
        core_policy="continuous-scene.v1", information_policy="actor-source-scope.v1", accepted_sources=accepted,
        world_preparation=effective_context_content(request, context).get("chapter_execution_expectations", {}).get("world_preparation", {}))
    if (not contract["slots"] or output.get("context_bundle_id") != context.asset_version_id
            or output.get("chapter") != plan["chapter"]
            or snapshot_hash(output.get("realization_contract")) != snapshot_hash(contract)):
        raise KernelError("RETAINED_GRAPH_DRAFT_CONTRACT_DRIFT", "Completed Draft must bind the full current contract and original accepted sources")
    proof = integrate_realization(contract=contract, artifacts=output.get("scene_artifacts"),
        text=output.get("text", ""), separators=output.get("scene_separators"))
    if any(snapshot_hash(output.get(key)) != snapshot_hash(value) for key, value in proof.items()):
        raise KernelError("RETAINED_GRAPH_DRAFT_PROOF_DRIFT", "Recompute actor scopes, composition and voice evidence without modifying the original output")
