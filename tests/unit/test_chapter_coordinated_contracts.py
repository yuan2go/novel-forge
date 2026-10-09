from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterNode
from novel_forge.modules.chapter_authority.definitions import (
    chapter_operation_definitions, chapter_root_operation_definition,
)

IDENTITY = dict(application_build_id="test-build", commit_sha="a" * 40, model_effects_required=True)


def test_coordinated_contract_has_explicit_root_and_exact_node_versions():
    legacy = chapter_operation_definitions(**IDENTITY)
    current = chapter_operation_definitions(**IDENTITY, coordinated_contract=True)
    root = chapter_root_operation_definition(**IDENTITY, coordinated_contract=True)
    assert root["definition_version"] == "3.10.0"
    assert root["policy"]["node_definition_versions"] == {
        node.definition_name: "3.10.0"
        for node in ChapterNode
    }
    for old, new in zip(legacy, [d for d in current if d["definition_version"] == "3.10.0"], strict=True):
        if old["name"] == ChapterNode.PLAN.definition_name:
            assert new["definition_version"] == "3.10.0"
            assert new["policy"]["chapter_plan_book_scope"] == "host-book-plan.v1"
            assert old["definition_version"] == "3.9.16"
            assert new["completion_contract"] == old["completion_contract"]
        else:
            assert new["definition_version"] == "3.10.0"
            assert new["policy"]["coordinated_chapter_contract"] == "chapter-coordinated-production.v1"
            if old["name"] in {ChapterNode.REVISION.definition_name, ChapterNode.REREVIEW.definition_name}:
                assert "required_external_effects" not in new["completion_contract"]
                assert new["completion_contract"]["required_asset_selectors"][-1]["selector"] == "revision_execution_decision"
            else:
                assert new["completion_contract"] == old["completion_contract"]
    assert chapter_root_operation_definition(**IDENTITY)["definition_version"] == "3.9.0"
    assert chapter_operation_definitions(**IDENTITY) == legacy


def test_coordinated_author_input_retains_no_provider_gate():
    author = chapter_operation_definitions(**IDENTITY, coordinated_contract=True, author_input=True)[-1]
    assert author["definition_version"] == "3.10.0-author-input.v3"
    assert author["external_capabilities"] == []
    assert "required_external_effects" not in author["completion_contract"]


def test_coordinated_work_gate_does_not_enable_unknown_adjacent_contract():
    def request(version):
        return ChapterHandlerRequest(operation_id="operation", project_id="project", workspace_id="workspace",
            trace_id="trace", correlation_id="correlation", command={}, inputs=(), definition_version=version)
    assert request("3.10.0").work_requirements_enabled
    assert request("3.10.0-author-input.v3").work_requirements_enabled
    assert request("3.10.1").work_requirements_enabled
    assert not request("3.10.9").work_requirements_enabled


def test_published_main_definition_hashes_remain_exact():
    import json
    from pathlib import Path
    from novel_forge.modules.chapter_authority.definitions import chapter_provider_sample_definitions
    from novel_forge.storage.authority_repositories import definition_hash
    frozen = json.loads((Path(__file__).parents[1] / "fixtures/chapter_main_c621_definition_hashes.json").read_text())
    identity = dict(application_build_id="fixed-main-hash-comparison", commit_sha=frozen["source_sha"])
    rows = chapter_operation_definitions(**identity, model_effects_required=True, author_input=True)
    rows += (chapter_root_operation_definition(**identity, model_effects_required=True),)
    for reference in (False, True):
        rows += chapter_provider_sample_definitions(**identity, reference_samples=reference, definition_version="2.5.0" if reference else "2.4.0")
    assert {row["name"] + "@" + row["definition_version"]: definition_hash(row) for row in rows} == frozen["definitions"]


def test_receipt_draft_successor_preserves_current_contract_and_bounded_retry():
    rows = chapter_operation_definitions(**IDENTITY, coordinated_contract=True)
    base = next(d for d in rows if d["name"] == "chapter.draft.generate" and d["definition_version"] == "3.10.0")
    repair = next(d for d in rows if d["name"] == "chapter.draft.generate" and d["definition_version"] == "3.10.1")
    assert repair["completion_contract"] == base["completion_contract"]
    assert repair["retry_policy"] == base["retry_policy"]
    assert repair["policy"]["scene_core_projection"] == "continuous-scene.v1"
    assert repair["policy"]["scene_information_flow"] == "actor-source-scope.v1"
    assert repair["policy"]["scene_evidence_union_revalidation"] == "scene-evidence-union.v1"
