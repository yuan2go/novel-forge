from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority import ApproveKnowledgeCandidateCommand, MkaosAuthorityApplication
from novel_forge.modules.mkaos_authority.craft import core_catalog, craft_candidate
from novel_forge.modules.source_import import SourceIntelligencePolicy
from novel_forge.modules.source_import.craft_discovery import CRAFT_DISCOVERY_POLICY, CRAFT_DISCOVERY_ROUTING
from novel_forge.modules.source_import.execution_contracts import MKAOS_STAGE, content_intelligence_fixture_response
from tests.integration import test_source_import_runtime_postgres as source_support
from tests.integration.authority_postgres_support import DATABASE_URL, transaction


def test_source_craft_discovery_uses_native_effect_observation_governance_and_exact_replay():
    source_support.SourceImportRuntimePostgresTests.setUpClass()
    fixture = source_support.SourceImportRuntimePostgresTests()
    fixture.setUp()
    observed_inputs = []
    discovered_by_observation = {}

    def fixture_response(stage, inputs):
        result = content_intelligence_fixture_response(stage, inputs)
        if stage != MKAOS_STAGE or not inputs.get("craft_discovery_contract"):
            return result
        observed_inputs.append(dict(inputs))
        observation_id = inputs["observation_asset_version_id"]
        if observation_id not in discovered_by_observation:
            mechanism = core_catalog()[len(discovered_by_observation)]
            mechanism["mechanism_id"] = "fixture-discovered-" + mechanism["mechanism_id"]
            mechanism["provenance"] = {
                "origin": "SOURCE_ABSTRACTION", "attribution": "Scripted discovery output; no semantic or reader-quality claim",
                "abstraction_policy_version": CRAFT_DISCOVERY_POLICY,
                "source_observation_asset_version_ids": [observation_id],
                "confidence": "HYPOTHESIS", "supersedes_card_asset_version_id": "",
            }
            discovered_by_observation[observation_id] = craft_candidate(mechanism)
        candidate = discovered_by_observation[observation_id]
        return {**candidate, **{key: result[key] for key in (
            "preconditions", "exceptions", "misuse_risks", "epistemic_status", "source_finding_codes") if key in result}}

    try:
        policy = SourceIntelligencePolicy(routing_policy_version=CRAFT_DISCOVERY_ROUTING)
        with patch("novel_forge.api.authority_dependencies.content_intelligence_fixture_response", side_effect=fixture_response):
            imported = fixture._create_import("craft-discovery", fixture.commit_a, intelligence_policy=policy)
            fixture.scheduler.run_or_recover(operation_id=imported["operation_id"], project_id=fixture.project_id)
            fixture._run_ready_source_operations()
            candidates = fixture.mkaos_query.list_candidates(project_id=fixture.project_id)
            assert candidates, fixture.query.downstream_status(project_id=fixture.project_id, import_job_id=imported["import_job_id"])
            assert len(candidates) == len(discovered_by_observation) == len(observed_inputs)
            assert all(item["candidate_status"] == "NEEDS_REVIEW" for item in candidates)
            assert not fixture.mkaos_query.list_cards(project_id=fixture.project_id)
            assert "A question creates forward pressure." not in json.dumps(observed_inputs)
            assert all(item["abstraction_policy_version"] == CRAFT_DISCOVERY_POLICY for item in observed_inputs)
            assert all(item["craft_discovery_contract"]["schema_version"] == "narrative-craft-discovery.v1" for item in observed_inputs)
            for candidate in candidates:
                content = candidate["content"]
                mechanism = content["candidate"]["craft_mechanism"]
                assert mechanism["provenance"]["source_observation_asset_version_ids"] == content["observation_asset_version_ids"]
                assert content["lineage_mode"] == "OBSERVATION_ABSTRACTION"
                assert content["execution_evidence"]["proof"]["fixture_protocol_only"]
                assert content["execution_evidence"]["proof"]["real_provider_proven"] is False
                assert mechanism["effect_evidence"] == []
                assert mechanism["validation_evidence"] == []
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """SELECT version.content->'contract' FROM authority_asset_version version
                       JOIN authority_asset asset ON asset.asset_id=version.asset_id
                       WHERE asset.project_id=%s AND version.content #>> '{contract,schema_version}'='source-capability-materialization.v1'
                         AND version.content #>> '{contract,stage}'=%s""", [fixture.project_id, MKAOS_STAGE])
                materials = [row[0] for row in cursor.fetchall()]
                assert materials
                for material in materials:
                    schema = material["output_schema"]["content"]
                    assert "craft_mechanism" in schema["required"]
                    provenance_schema = schema["properties"]["craft_mechanism"]["properties"]["provenance"]["properties"]
                    assert provenance_schema["origin"]["const"] == "SOURCE_ABSTRACTION"
                    assert provenance_schema["confidence"]["const"] == "HYPOTHESIS"
                    assert provenance_schema["source_observation_asset_version_ids"]["const"][0] in discovered_by_observation
                cursor.execute(
                    """SELECT external_effect_id,request_payload,status FROM authority_external_effect
                       WHERE project_id=%s AND request_payload ? '_source_intelligence' ORDER BY external_effect_id""",
                    [fixture.project_id])
                effects_before = cursor.fetchall()
                assert effects_before and all(row[2] == "SUCCEEDED" for row in effects_before)
            replay = fixture._create_import("craft-discovery", fixture.commit_a, intelligence_policy=policy)
            assert replay["operation_id"] == imported["operation_id"]
            fixture._run_ready_source_operations()
            assert len(observed_inputs) == len(candidates)
            target = next(row for row in effects_before if row[1]["_source_intelligence"]["kind"] == "mkaos")
            replayed_effect = fixture.execution_port._replay_succeeded_effect(
                worker=SimpleNamespace(project_id=fixture.project_id),
                cache_key=target[1]["_source_intelligence"]["cache_key"])
            assert replayed_effect["provider_execution_reused"]
            assert replayed_effect["result"]["craft_mechanism"]["provenance"]["origin"] == "SOURCE_ABSTRACTION"
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """SELECT external_effect_id,request_payload,status FROM authority_external_effect
                       WHERE project_id=%s AND request_payload ? '_source_intelligence' ORDER BY external_effect_id""",
                    [fixture.project_id])
                assert cursor.fetchall() == effects_before
        candidate = candidates[0]
        approval = ApproveKnowledgeCandidateCommand(project_id=fixture.project_id, workspace_id=fixture.workspace_id,
            candidate_asset_version_id=candidate["asset_version_id"], policy_version="craft-discovery-governance.fixture.v1",
            rationale="Explicit isolated fixture approval proves protocol only; semantic quality and actual reader effect remain unproven.",
            actor_id=fixture.principal.principal_id, idempotency_key="discovery-fixture-approval",
            trace_id="trace:discovery-approval", correlation_id=fixture.project_id)
        guarded = MkaosAuthorityApplication(DATABASE_URL, application_build_id="craft-discovery-test", commit_sha="e"*40)
        with pytest.raises(KernelError, match="fixture execution"):
            guarded.execute_approval(approval, principal=fixture.principal)
        approved = fixture.mkaos_application.execute_approval(approval, principal=fixture.principal)
        assert approved["status"] == "SUCCEEDED"
        card = fixture.mkaos_query.list_cards(project_id=fixture.project_id)[0]["content"]
        assert card["source_policy"]["fixture_protocol_only"]
        assert card["abstract_content"]["craft_mechanism"]["provenance"]["confidence"] == "HYPOTHESIS"
        assert "A question creates forward pressure." not in json.dumps(card)
        assert fixture.mkaos_application.execute_approval(replace(approval, idempotency_key="approval-replay"), principal=fixture.principal)["replayed"]
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("violation", ["unrelated_observation", "raw_source_expression"])
def test_source_discovery_output_cannot_claim_unrelated_lineage_or_publish_raw_expression(violation):
    source_support.SourceImportRuntimePostgresTests.setUpClass()
    fixture = source_support.SourceImportRuntimePostgresTests()
    fixture.setUp()
    attempted = []

    def invalid_fixture_response(stage, inputs):
        result = content_intelligence_fixture_response(stage, inputs)
        if stage != MKAOS_STAGE or not inputs.get("craft_discovery_contract"):
            return result
        attempted.append(inputs["observation_asset_version_id"])
        mechanism = core_catalog()[0]
        mechanism["mechanism_id"] = "fixture-invalid-discovery"
        mechanism["provenance"].update({"origin": "SOURCE_ABSTRACTION", "abstraction_policy_version": CRAFT_DISCOVERY_POLICY,
            "source_observation_asset_version_ids": ["unrelated-observation:v1" if violation == "unrelated_observation" else inputs["observation_asset_version_id"]]})
        candidate = craft_candidate(mechanism)
        if violation == "raw_source_expression":
            candidate["source_text"] = "A question creates forward pressure."
        return {**candidate, **{key: result[key] for key in (
            "preconditions", "exceptions", "misuse_risks", "epistemic_status", "source_finding_codes") if key in result}}

    try:
        policy = SourceIntelligencePolicy(routing_policy_version=CRAFT_DISCOVERY_ROUTING)
        with patch("novel_forge.api.authority_dependencies.content_intelligence_fixture_response", side_effect=invalid_fixture_response):
            imported = fixture._create_import("invalid-craft-discovery", fixture.commit_a, intelligence_policy=policy)
            fixture.scheduler.run_or_recover(operation_id=imported["operation_id"], project_id=fixture.project_id)
            with pytest.raises(KernelError) as rejected:
                fixture._run_ready_source_operations()
            assert rejected.value.code == "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"
            assert ("source_observation_asset_version_ids" if violation == "unrelated_observation" else "source_text") in str(rejected.value)
        assert attempted
        assert not fixture.mkaos_query.list_candidates(project_id=fixture.project_id)
        assert not fixture.mkaos_query.list_cards(project_id=fixture.project_id)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT effect.status FROM authority_external_effect effect
                   WHERE project_id=%s AND request_payload #>> '{_source_intelligence,kind}'='mkaos'""",
                [fixture.project_id])
            statuses = [row[0] for row in cursor.fetchall()]
            assert statuses
            cursor.execute("SELECT status FROM authority_operation WHERE project_id=%s AND definition_name LIKE 'source.import.%%mkaos%%'", [fixture.project_id])
            operation_statuses = [row[0] for row in cursor.fetchall()]
            assert operation_statuses and "SUCCEEDED" not in operation_statuses
            assert any(status.startswith("FAILED") for status in operation_statuses)
    finally:
        fixture.tearDown()
