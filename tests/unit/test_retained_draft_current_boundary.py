from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.chapter_authority.retained_draft_validation import require_current_completed_draft
from novel_forge.modules.chapter_authority.realization_composition import compile_realization_contract, integrate_realization
from novel_forge.modules.chapter_authority.chapter_plan_views import build_draft_style_view
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash


def fixture():
    plan = {"chapter": 2, "scene_plan": [{"scene_id": "scene", "participants": ["actor"], "beats": [],
        "accessible_knowledge": [], "information_gain": []}],
        "character_participation": [{"character_id": "actor", "known_fact_ids": []}]}
    snapshot = {"contract_version": "story-state-snapshot-v2", "accepted_state_only": True, "project_id": "project", "book_id": "book", "accepted_through_chapter": 1, "current_state": {}}
    state_hash = snapshot_hash(snapshot)
    context = {"context_segments": [{"asset_type": "style_policy", "asset_version_id": "style", "structured_facts": []}],
        "context_manifest": {"accepted_boundary": {"story_state_snapshot_version": "state", "accepted_through_chapter": 1},
            "selected_inputs": [{"asset_version_id": "state", "allowed_use": "generation", "content_digest": state_hash}]},
        "production_input_manifest": {"style_policy_version_id": "style", "selected_asset_versions": [
            {"asset_version_id": "state", "asset_type": "story_state_snapshot", "content_hash": state_hash}]}}
    bodies = {"plan": ("chapter_plan", plan), "context": ("context_bundle", context),
        "intent": ("chapter_execution_intent", {}), "memo": ("chapter_memo", {}), "state": ("story_state_snapshot", snapshot)}
    assets = {key: SimpleNamespace(project_id="project", asset_version_id=key, asset_type=kind, content=body,
        content_hash=snapshot_hash(body), lifecycle="ACTIVE", eligibility="ELIGIBLE", governance="CLEAR") for key, (kind, body) in bodies.items()}
    source = {"definition_name": "chapter.draft.generate", "definition_version": "3.10.0", "status": "SUCCEEDED",
        "definition_snapshot": {"policy": {"scene_core_projection": "continuous-scene.v1", "scene_information_flow": "actor-source-scope.v1"}},
        "project_id": "project", "workspace_id": "workspace", "actor_id": "owner", "operation_id": "draft", "trace_id": "trace", "correlation_id": "correlation",
        "command_payload": {"book_id": "book"}, "input_asset_snapshot": [{"asset_version_id": key, "content_hash": assets[key].content_hash} for key in ("plan", "context", "intent", "memo")]}
    accepted = {"asset_version_id": "state", "content_hash": state_hash, "accepted_through_chapter": 1, "facts": [], "authority": "EXACT_ACCEPTED_SOURCE_PROJECTION"}
    contract = compile_realization_contract(plan, build_draft_style_view(context, work_requirements=True),
        core_policy="continuous-scene.v1", information_policy="actor-source-scope.v1", accepted_sources=accepted)
    artifacts = [{"slot_id": contract["slots"][0]["slot_id"], "text": "完整的场景。", "used_fact_ids": [], "character_source_uses": []}]
    output = {"text": artifacts[0]["text"], "chapter": 2, "context_bundle_id": "context", **integrate_realization(contract=contract, artifacts=artifacts, text=artifacts[0]["text"])}
    reader = SimpleNamespace(require=lambda *, project_id, asset_version_id: assets[asset_version_id])
    return source, output, reader, assets


def test_current_completed_draft_rebuilds_native_frozen_proof_without_provider_or_mutation():
    source, output, reader, _ = fixture()
    before = deepcopy((source, output))
    require_current_completed_draft(source, output, asset_reader=reader)
    assert (source, output) == before


@pytest.mark.parametrize("change", ["old_version", "same_version_old_policy", "contract_tag", "accepted_hash", "missing_actor_uses", "foreign_actor", "composition_digest", "input_hash", "snapshot_book", "snapshot_permission"])
def test_completed_draft_cannot_claim_current_qualification_from_incomplete_or_foreign_evidence(change):
    source, output, reader, assets = fixture()
    if change == "old_version":
        source["definition_version"] = "3.9.1"
    elif change == "same_version_old_policy":
        source["definition_snapshot"]["policy"].pop("scene_information_flow")
    elif change == "contract_tag":
        output["realization_contract"]["contract_version"] = "scene-realization-composition.v2"
    elif change == "accepted_hash":
        output["realization_contract"]["accepted_sources"]["content_hash"] = "wrong"
    elif change == "missing_actor_uses":
        output["scene_artifacts"][0].pop("character_source_uses")
    elif change == "foreign_actor":
        output["scene_artifacts"][0]["character_source_uses"] = [{"character_id": "other", "used_fact_ids": []}]
    elif change == "composition_digest":
        output["composition_digest"] = "wrong"
    elif change == "input_hash":
        assets["plan"].content_hash = "wrong"
    elif change == "snapshot_book":
        assets["state"].content["book_id"] = "other"
    else:
        assets["context"].content["context_manifest"]["selected_inputs"][0]["allowed_use"] = "analysis"
    with pytest.raises(KernelError):
        require_current_completed_draft(source, output, asset_reader=reader)


def test_old_completed_prefix_is_rejected_before_any_graph_mutation():
    from novel_forge.modules.command_kernel.retained_graph import continue_graph_in_uow
    uow = Mock()
    source = {"root": {}, "steps": [{"operation": {"definition_name": "chapter.draft.generate", "definition_version": "3.9.1"}}]}
    with pytest.raises(KernelError, match="KNOWN_RECEIPT_HISTORICAL_CONTRACT_BLOCKED"):
        continue_graph_in_uow(uow, source=source, request=Mock(), context=Mock())
    uow.cursor.execute.assert_not_called()
    uow.commit.assert_not_called()


def test_quote_recovery_cannot_bypass_current_completed_draft_reader(monkeypatch):
    from novel_forge.modules.command_kernel.retained_graph import source_graph
    from novel_forge.modules.chapter_authority import current_quote_recovery
    cursor = Mock()
    root = {"definition_name": "chapter.slice.run", "root_operation_id": "root", "operation_id": "root", "actor_id": "owner", "definition_version": "3.9.0", "status": "FAILED_FINAL"}
    saga = {"project_id": "project", "status": "MANUAL_INTERVENTION"}
    cursor.fetchone.side_effect = [(root,), (saga,), (True,)]
    graph = {"root": root, "steps": [{"operation": {"definition_name": "chapter.draft.generate", "definition_version": "3.9.1"}}]}
    monkeypatch.setattr(current_quote_recovery, "source_graph", lambda *a, **k: graph)
    with pytest.raises(KernelError, match="KNOWN_RECEIPT_HISTORICAL_CONTRACT_BLOCKED"):
        source_graph(cursor, root_id="root", project_id="project", actor_id="owner")
    assert cursor.execute.call_count == 3
