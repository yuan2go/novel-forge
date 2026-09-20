from dataclasses import replace

import pytest
import psycopg

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.application import ApproveKnowledgeCandidateCommand, MkaosAuthorityApplication
from novel_forge.modules.mkaos_authority.craft import CRAFT_ORIGINAL_POLICY, core_catalog_hash, core_catalog, craft_candidate
from novel_forge.modules.mkaos_authority.craft_authoring import AuthorCoreCraftCommand, validate_craft_lineage
from novel_forge.modules.mkaos_authority.query import MkaosAuthorityQuery
from novel_forge.modules.project_authority import ProjectAuthorityApplication, ProjectAuthorityCommand
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, transaction


def setup_craft():
    ensure_migrated()
    project, workspace = identifier("craft-project"), identifier("craft-workspace")
    ProjectAuthorityApplication(DATABASE_URL, application_build_id="craft-engineering", commit_sha="f"*40).execute(
        ProjectAuthorityCommand(definition_name="project_lifecycle.create", project_id=project,
            workspace_id=workspace, actor_id="craft-operator", idempotency_key=f"project:{project}",
            trace_id=f"trace:{project}", correlation_id=f"correlation:{project}", payload={"title": "Craft original governance test"}))
    application = MkaosAuthorityApplication(DATABASE_URL, application_build_id="craft-engineering", commit_sha="f"*40)
    command = AuthorCoreCraftCommand(project, workspace, "subtext-pressure", core_catalog_hash(), "craft-operator",
        f"craft:{project}", f"trace:{project}", f"correlation:{project}")
    return application, command


def test_original_candidate_separate_exact_approval_query_and_replay():
    application, command = setup_craft()
    result = application.execute_core_craft(command)
    assert result["status"] == "SUCCEEDED"
    replay = application.execute_core_craft(command)
    assert replay["asset_version_id"] == result["asset_version_id"]
    assert replay["replayed"]
    query = MkaosAuthorityQuery(DATABASE_URL)
    assert not query.list_cards(project_id=command.project_id)
    approval = ApproveKnowledgeCandidateCommand(command.project_id, command.workspace_id,
        result["asset_version_id"], "unbound-policy", "Approve original mechanism hypothesis for controlled use; no creative-quality claim",
        command.actor_id, "approve:"+command.idempotency_key, command.trace_id, command.correlation_id)
    with pytest.raises(KernelError, match="exact catalog hash"):
        application.execute_approval(approval)
    approved = application.execute_approval(replace(approval, policy_version=CRAFT_ORIGINAL_POLICY+":"+core_catalog_hash()))
    assert approved["status"] == "SUCCEEDED"
    assert application.execute_approval(replace(approval, policy_version=CRAFT_ORIGINAL_POLICY+":"+core_catalog_hash()))["replayed"]
    cards = query.list_cards(project_id=command.project_id)
    assert len(cards) == 1
    with transaction() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT execution_asset_version_id, origin_kind, craft_mechanism_id FROM authority_mkaos_knowledge_candidate WHERE asset_version_id=%s", [result["asset_version_id"]])
        assert cursor.fetchone() == (None, "REPOSITORY_ORIGINAL", "subtext-pressure")
        cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s", [approved["asset_version_id"]])
        content = cursor.fetchone()[0]
        assert content["source_policy"]["production_context_eligible"]
        assert content["source_policy"]["review_class"] == "ORIGINAL_CATALOG_OPERATOR_APPROVAL"
        assert content["lineage"]["source_chunk_asset_version_ids"] == []
        cursor.execute("SELECT COUNT(*) FROM authority_external_effect WHERE operation_id IN (%s,%s)", [result["operation_id"], approved["operation_id"]])
        assert cursor.fetchone()[0] == 0


def test_source_null_execution_db_guard_and_original_masquerade_rejected():
    application, command = setup_craft()
    result = application.execute_core_craft(command)
    with transaction() as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.cursor().execute("UPDATE authority_mkaos_knowledge_candidate SET origin_kind='SOURCE_ABSTRACTION' WHERE asset_version_id=%s", [result["asset_version_id"]])
        connection.rollback()
    candidate = craft_candidate(core_catalog()[0])
    with transaction() as connection:
        with pytest.raises(KernelError, match="canonical authoring path"):
            validate_craft_lineage(connection.cursor(), command.project_id, candidate, ("unrelated-observation",))
        candidate["craft_mechanism"]["provenance"]["origin"] = "SOURCE_ABSTRACTION"
        candidate["craft_mechanism"]["provenance"]["source_observation_asset_version_ids"] = ["other-observation"]
        with pytest.raises(KernelError, match="canonical authoring path"):
            validate_craft_lineage(connection.cursor(), command.project_id, candidate, ("unrelated-observation",))


def test_mutated_same_version_and_unresolved_human_evidence_are_rejected():
    application, command = setup_craft()
    application.execute_core_craft(command)
    mechanism = next(item for item in core_catalog() if item["mechanism_id"] == command.mechanism_id)
    mechanism["abstract_mechanism"] = "changed mechanism under unchanged identity"
    with transaction() as connection:
        with pytest.raises(KernelError, match="immutable Craft"):
            validate_craft_lineage(connection.cursor(), command.project_id, craft_candidate(mechanism), (), original=True)
        mechanism = core_catalog()[0]
        mechanism["effect_evidence"] = [{"kind": "HUMAN_READER", "asset_version_id": "invented-reader-evidence", "claim": "Readers liked it"}]
        with pytest.raises(KernelError, match="same project"):
            validate_craft_lineage(connection.cursor(), command.project_id, craft_candidate(mechanism), (), original=True)


def test_all_core_mechanisms_can_be_governed_in_native_store_without_provider_claims():
    application, command = setup_craft()
    catalog = core_catalog()
    for mechanism in catalog:
        authored = application.execute_core_craft(replace(command, mechanism_id=mechanism["mechanism_id"],
            idempotency_key=command.idempotency_key+":"+mechanism["mechanism_id"]))
        approved = application.execute_approval(ApproveKnowledgeCandidateCommand(
            project_id=command.project_id, workspace_id=command.workspace_id,
            candidate_asset_version_id=authored["asset_version_id"],
            policy_version=CRAFT_ORIGINAL_POLICY+":"+command.catalog_hash,
            rationale="Engineering fixture invokes explicit operator governance; no independent reader or creative quality evidence.",
            actor_id=command.actor_id, idempotency_key="approve:"+mechanism["mechanism_id"],
            trace_id=command.trace_id, correlation_id=command.correlation_id))
        assert approved["status"] == "SUCCEEDED"
    cards = MkaosAuthorityQuery(DATABASE_URL).list_cards(project_id=command.project_id, limit=100)
    assert len(cards) == len(catalog)
    assert {card["content"]["abstract_content"]["craft_mechanism"]["mechanism_id"] for card in cards} == {item["mechanism_id"] for item in catalog}
    assert all(card["content"]["source_policy"]["review_class"] == "ORIGINAL_CATALOG_OPERATOR_APPROVAL" for card in cards)
